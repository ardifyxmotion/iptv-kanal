import os
import json
import hashlib
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
PLAYLIST_FILE = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILE = os.path.join(STREAM_DIR, "atvavrupa_state.json")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Çok fazla eski görüntünün tekrar listeye girmemesi için
# oynatma listesinde sınırlı bir geçmiş tutulur.
MAX_SEGMENTS = 300


def get_stream_url():
    try:
        result = subprocess.run(
            [
                "streamlink",
                "--stream-url",
                "https://www.atvavrupa.tv/canli-yayin",
                "best"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        url = result.stdout.strip()

        if not url:
            print("Canlı yayın adresi bulunamadı.")
            print(result.stderr)
            return None

        return url

    except Exception as error:
        print(f"Streamlink hatası: {error}")
        return None


def get_source_playlist(stream_url):
    try:
        response = requests.get(
            stream_url,
            headers=HEADERS,
            timeout=30
        )
        response.raise_for_status()

        lines = [
            line.strip()
            for line in response.text.splitlines()
            if line.strip()
        ]

        target_duration = 10
        segments = []

        for line in lines:
            if line.startswith("#EXT-X-TARGETDURATION:"):
                try:
                    target_duration = int(
                        line.split(":", 1)[1]
                    )
                except ValueError:
                    pass

        index = 0

        while index < len(lines):
            if lines[index].startswith("#EXTINF:"):
                try:
                    duration = lines[index].split(
                        ":", 1
                    )[1].split(",", 1)[0]
                except (IndexError, ValueError):
                    index += 1
                    continue

                next_index = index + 1

                while next_index < len(lines):
                    next_line = lines[next_index]

                    if not next_line.startswith("#"):
                        segment_url = urljoin(
                            stream_url,
                            next_line
                        )

                        segments.append({
                            "duration": duration,
                            "url": segment_url
                        })

                        index = next_index
                        break

                    next_index += 1

            index += 1

        if not segments:
            return None

        return {
            "target_duration": target_duration,
            "segments": segments
        }

    except Exception as error:
        print(f"Kaynak liste okunamadı: {error}")
        return None


def segment_id(url):
    """
    Geçici token ve benzeri değişiklikler URL'yi değiştirse bile
    mümkün olduğunca aynı segmenti tekrar eklememek için URL'nin
    yol kısmı temel alınır.
    """

    clean_url = url.split("?", 1)[0]

    return hashlib.sha1(
        clean_url.encode("utf-8")
    ).hexdigest()


def load_state():
    default_state = {
        "last_local_sequence": -1,
        "seen_segments": []
    }

    if not os.path.exists(STATE_FILE):
        return default_state

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            state = json.load(f)

        if not isinstance(
            state.get("seen_segments"),
            list
        ):
            state["seen_segments"] = []

        if "last_local_sequence" not in state:
            state["last_local_sequence"] = -1

        return state

    except Exception as error:
        print(f"State dosyası okunamadı: {error}")
        return default_state


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    # State dosyasının sınırsız büyümesini engelle.
    # Son segment geçmişini sakla.
    state["seen_segments"] = (
        state["seen_segments"][-1000:]
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False
        )

    os.replace(temp_file, STATE_FILE)


def load_existing_entries():
    entries = []

    if not os.path.exists(PLAYLIST_FILE):
        return entries

    try:
        with open(
            PLAYLIST_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            lines = [
                line.strip()
                for line in f
                if line.strip()
            ]

        duration = None

        for line in lines:
            if line.startswith("#EXTINF:"):
                duration = line.split(
                    ":", 1
                )[1].split(",", 1)[0]

            elif (
                duration is not None
                and not line.startswith("#")
            ):
                filename = line.rsplit(
                    "/",
                    1
                )[-1]

                if (
                    filename.startswith("seg_")
                    and filename.endswith(".ts")
                ):
                    try:
                        sequence = int(
                            filename[4:-3]
                        )

                        filepath = os.path.join(
                            STREAM_DIR,
                            filename
                        )

                        if os.path.exists(filepath):
                            entries.append({
                                "sequence": sequence,
                                "duration": duration,
                                "filename": filename
                            })

                    except ValueError:
                        pass

                duration = None

    except Exception as error:
        print(
            f"Mevcut liste okunamadı: {error}"
        )

    return sorted(
        entries,
        key=lambda item: item["sequence"]
    )


def download_segment(item):
    filename, url = item
    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(filepath):
        return filename

    temp_path = filepath + ".tmp"

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=45
        )

        response.raise_for_status()

        with open(
            temp_path,
            "wb"
        ) as f:
            f.write(response.content)

        os.replace(
            temp_path,
            filepath
        )

        return filename

    except Exception as error:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass

        print(
            f"Segment indirilemedi: "
            f"{filename} -> {error}"
        )

        return None


def write_playlist(entries, target_duration):
    if not entries:
        return False

    temp_file = PLAYLIST_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")

        f.write(
            f"#EXT-X-TARGETDURATION:"
            f"{target_duration}\n"
        )

        f.write(
            f"#EXT-X-MEDIA-SEQUENCE:"
            f"{entries[0]['sequence']}\n"
        )

        for entry in entries:
            f.write(
                f"#EXTINF:"
                f"{entry['duration']},\n"
            )

            f.write(
                f"{BASE_URL}"
                f"{entry['filename']}\n"
            )

    os.replace(
        temp_file,
        PLAYLIST_FILE
    )

    return True


def clean_old_files(entries):
    current_files = {
        entry["filename"]
        for entry in entries
    }

    for filename in os.listdir(STREAM_DIR):

        if (
            filename.startswith("seg_")
            and filename.endswith(".ts")
            and filename not in current_files
        ):
            try:
                os.remove(
                    os.path.join(
                        STREAM_DIR,
                        filename
                    )
                )
            except OSError:
                pass


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    stream_url = get_stream_url()

    if not stream_url:
        return

    playlist = get_source_playlist(
        stream_url
    )

    if not playlist:
        print(
            "Kaynak listede segment bulunamadı."
        )
        return

    state = load_state()

    existing_entries = (
        load_existing_entries()
    )

    last_local = state[
        "last_local_sequence"
    ]

    if existing_entries:
        last_local = max(
            last_local,
            existing_entries[-1]["sequence"]
        )

    # Daha önce görülen segmentlerin kümesi
    seen = set(
        state["seen_segments"]
    )

    new_source_segments = []

    for segment in playlist["segments"]:

        unique_id = segment_id(
            segment["url"]
        )

        if unique_id not in seen:

            new_source_segments.append({
                "id": unique_id,
                "duration": (
                    segment["duration"]
                ),
                "url": segment["url"]
            })

    if not new_source_segments:

        print(
            "Gerçekten yeni segment bulunamadı. "
            "Aynı sahneler tekrar eklenmiyor."
        )

        return

    print(
        f"{len(new_source_segments)} "
        f"yeni segment bulundu."
    )

    pending_entries = []
    download_list = []

    for segment in new_source_segments:

        last_local += 1

        filename = (
            f"seg_{last_local}.ts"
        )

        pending_entries.append({
            "sequence": last_local,
            "id": segment["id"],
            "duration": segment["duration"],
            "filename": filename
        })

        download_list.append((
            filename,
            segment["url"]
        ))

    with ThreadPoolExecutor(
        max_workers=6
    ) as executor:

        results = list(
            executor.map(
                download_segment,
                download_list
            )
        )

    successful = {
        filename
        for filename in results
        if filename is not None
    }

    successful_new_entries = [
        entry
        for entry in pending_entries
        if entry["filename"] in successful
    ]

    if not successful_new_entries:

        print(
            "Yeni segmentler indirilemedi. "
            "Mevcut liste korunuyor."
        )

        return

    # Yalnızca başarıyla indirilen segmentleri
    # 'görüldü' listesine ekle.
    for entry in successful_new_entries:
        seen.add(entry["id"])

    state["seen_segments"] = list(seen)

    # Yerel sıra numarasını başarıyla indirilen
    # son dosyaya göre güncelle.
    state["last_local_sequence"] = max(
        entry["sequence"]
        for entry in successful_new_entries
    )

    all_entries = (
        existing_entries +
        [
            {
                "sequence": entry["sequence"],
                "duration": entry["duration"],
                "filename": entry["filename"]
            }
            for entry in successful_new_entries
        ]
    )

    # Aynı dosya numarasını iki kez yazma
    unique_entries = {}

    for entry in all_entries:
        unique_entries[
            entry["sequence"]
        ] = entry

    all_entries = sorted(
        unique_entries.values(),
        key=lambda item: item["sequence"]
    )

    # Oynatma listesini sınırlı tut
    if len(all_entries) > MAX_SEGMENTS:
        all_entries = all_entries[
            -MAX_SEGMENTS:
        ]

    write_playlist(
        all_entries,
        playlist["target_duration"]
    )

    save_state(state)

    clean_old_files(all_entries)

    print(
        f"{len(successful_new_entries)} "
        f"yeni segment eklendi."
    )

    print(
        f"Toplam segment: "
        f"{len(all_entries)}"
    )


if __name__ == "__main__":
    main()
