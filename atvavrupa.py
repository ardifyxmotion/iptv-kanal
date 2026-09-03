import os
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
PLAYLIST_FILE = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILE = os.path.join(STREAM_DIR, "atvavrupa_state.txt")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Oynatıcı için yeterli geçmiş bırakılır.
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

        media_sequence = 0
        target_duration = 10
        segments = []

        for line in lines:
            if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                media_sequence = int(line.split(":", 1)[1])

            elif line.startswith("#EXT-X-TARGETDURATION:"):
                target_duration = int(line.split(":", 1)[1])

        index = 0

        while index < len(lines):
            if lines[index].startswith("#EXTINF:"):
                duration = lines[index].split(
                    ":", 1
                )[1].split(",", 1)[0]

                next_index = index + 1

                while next_index < len(lines):
                    next_line = lines[next_index]

                    if not next_line.startswith("#"):
                        segments.append({
                            "duration": duration,
                            "url": urljoin(
                                stream_url,
                                next_line
                            )
                        })

                        index = next_index
                        break

                    next_index += 1

            index += 1

        if not segments:
            return None

        return {
            "media_sequence": media_sequence,
            "target_duration": target_duration,
            "segments": segments
        }

    except Exception as error:
        print(f"Kaynak M3U8 hatası: {error}")
        return None


def load_state():
    state = {
        "last_source_sequence": None,
        "last_local_sequence": -1
    }

    if not os.path.exists(STATE_FILE):
        return state

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                key, separator, value = line.strip().partition("=")

                if not separator:
                    continue

                if key == "last_source_sequence":
                    state["last_source_sequence"] = int(value)

                elif key == "last_local_sequence":
                    state["last_local_sequence"] = int(value)

    except Exception as error:
        print(f"State okuma hatası: {error}")

    return state


def save_state(last_source, last_local):
    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(f"last_source_sequence={last_source}\n")
        f.write(f"last_local_sequence={last_local}\n")

    os.replace(temp_file, STATE_FILE)


def load_existing_entries():
    entries = []

    if not os.path.exists(PLAYLIST_FILE):
        return entries

    try:
        with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        duration = None

        for line in lines:
            if line.startswith("#EXTINF:"):
                duration = line.split(
                    ":", 1
                )[1].split(",", 1)[0]

            elif duration is not None and not line.startswith("#"):
                filename = line.rsplit("/", 1)[-1]

                if (
                    filename.startswith("seg_")
                    and filename.endswith(".ts")
                ):
                    try:
                        sequence = int(filename[4:-3])
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
        print(f"Eski liste okunamadı: {error}")

    return sorted(
        entries,
        key=lambda item: item["sequence"]
    )


def download_segment(item):
    filename, url = item
    filepath = os.path.join(STREAM_DIR, filename)

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

        with open(temp_path, "wb") as f:
            f.write(response.content)

        os.replace(temp_path, filepath)

        return filename

    except Exception as error:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass

        print(f"Segment indirilemedi: {filename} -> {error}")
        return None


def write_playlist(entries, target_duration):
    if not entries:
        return False

    temp_file = PLAYLIST_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write(
            f"#EXT-X-TARGETDURATION:{target_duration}\n"
        )
        f.write(
            f"#EXT-X-MEDIA-SEQUENCE:"
            f"{entries[0]['sequence']}\n"
        )

        for entry in entries:
            f.write(
                f"#EXTINF:{entry['duration']},\n"
            )
            f.write(
                f"{BASE_URL}{entry['filename']}\n"
            )

    os.replace(temp_file, PLAYLIST_FILE)
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
    os.makedirs(STREAM_DIR, exist_ok=True)

    stream_url = get_stream_url()

    if not stream_url:
        return

    playlist = get_source_playlist(stream_url)

    if not playlist:
        return

    state = load_state()
    existing_entries = load_existing_entries()

    last_source = state["last_source_sequence"]
    last_local = state["last_local_sequence"]

    if existing_entries:
        last_local = max(
            last_local,
            existing_entries[-1]["sequence"]
        )

    source_start = playlist["media_sequence"]
    source_segments = playlist["segments"]

    new_segments = []

    for index, segment in enumerate(source_segments):
        source_sequence = source_start + index

        if (
            last_source is None
            or source_sequence > last_source
        ):
            new_segments.append({
                "source_sequence": source_sequence,
                "duration": segment["duration"],
                "url": segment["url"]
            })

    if not new_segments:
        print("Yeni segment yok. Mevcut liste korunuyor.")
        return

    pending_entries = []
    download_list = []

    for segment in new_segments:
        last_local += 1
        filename = f"seg_{last_local}.ts"

        pending_entries.append({
            "sequence": last_local,
            "source_sequence": segment["source_sequence"],
            "duration": segment["duration"],
            "filename": filename
        })

        download_list.append((
            filename,
            segment["url"]
        ))

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(
            executor.map(
                download_segment,
                download_list
            )
        )

    successful = {
        filename
        for filename in results
        if filename
    }

    new_entries = [
        entry
        for entry in pending_entries
        if entry["filename"] in successful
    ]

    if not new_entries:
        print("Yeni segmentler indirilemedi. Eski liste korunuyor.")
        return

    # Eksik bir indirme olduğunda kaynak sırasını ileri taşıma.
    # Böylece bir sonraki kontrolde kaçan segment tekrar denenir.
    if len(new_entries) != len(pending_entries):
        print("Bazı segmentler indirilemedi; sonraki kontrolde tekrar denenecek.")

    all_entries = existing_entries + [
        {
            "sequence": entry["sequence"],
            "duration": entry["duration"],
            "filename": entry["filename"]
        }
        for entry in new_entries
    ]

    unique_entries = {}

    for entry in all_entries:
        unique_entries[entry["sequence"]] = entry

    all_entries = sorted(
        unique_entries.values(),
        key=lambda item: item["sequence"]
    )

    # Listeyi kontrollü biçimde küçült.
    if len(all_entries) > MAX_SEGMENTS:
        all_entries = all_entries[-MAX_SEGMENTS:]

    write_playlist(
        all_entries,
        playlist["target_duration"]
    )

    # Sadece aralıksız başarıyla indirilen son kaynak segmenti kaydet.
    successful_source_sequences = {
        entry["source_sequence"]
        for entry in new_entries
    }

    next_source = last_source + 1 if last_source is not None else source_start

    while next_source in successful_source_sequences:
        next_source += 1

    confirmed_last_source = next_source - 1

    if last_source is None and confirmed_last_source < source_start:
        confirmed_last_source = None

    confirmed_local = (
        max(entry["sequence"] for entry in new_entries)
    )

    if confirmed_last_source is not None:
        save_state(
            confirmed_last_source,
            confirmed_local
        )

    clean_old_files(all_entries)

    print(
        f"{len(new_entries)} yeni segment eklendi. "
        f"Toplam: {len(all_entries)}"
    )


if __name__ == "__main__":
    main()
