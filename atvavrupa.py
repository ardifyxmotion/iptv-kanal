import os
import time
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILENAME = os.path.join(STREAM_DIR, "atvavrupa_state.txt")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Cache-Control": "no-cache"
}

CHECK_INTERVAL = 2
STREAM_REFRESH_INTERVAL = 300
MAX_WORKERS = 10


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


def get_playlist(stream_url):
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
                media_sequence = int(
                    line.split(":", 1)[1]
                )

            elif line.startswith("#EXT-X-TARGETDURATION:"):
                target_duration = int(
                    line.split(":", 1)[1]
                )

        i = 0

        while i < len(lines):
            if lines[i].startswith("#EXTINF:"):
                duration = (
                    lines[i]
                    .split(":", 1)[1]
                    .split(",", 1)[0]
                )

                j = i + 1

                while j < len(lines):
                    if not lines[j].startswith("#"):
                        segments.append({
                            "duration": duration,
                            "url": urljoin(
                                stream_url,
                                lines[j]
                            )
                        })

                        i = j
                        break

                    j += 1

            i += 1

        return {
            "media_sequence": media_sequence,
            "target_duration": target_duration,
            "segments": segments
        }

    except Exception as error:
        print(f"M3U8 okuma hatası: {error}")
        return None


def load_state():
    state = {
        "last_source_sequence": None,
        "last_local_sequence": 0
    }

    if not os.path.exists(STATE_FILENAME):
        return state

    try:
        with open(
            STATE_FILENAME,
            "r",
            encoding="utf-8"
        ) as file:

            for line in file:
                line = line.strip()

                if line.startswith(
                    "last_source_sequence="
                ):
                    state[
                        "last_source_sequence"
                    ] = int(
                        line.split("=", 1)[1]
                    )

                elif line.startswith(
                    "last_local_sequence="
                ):
                    state[
                        "last_local_sequence"
                    ] = int(
                        line.split("=", 1)[1]
                    )

    except Exception as error:
        print(f"State okuma hatası: {error}")

    return state


def save_state(source_sequence, local_sequence):
    temp = STATE_FILENAME + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(
            f"last_source_sequence="
            f"{source_sequence}\n"
        )

        file.write(
            f"last_local_sequence="
            f"{local_sequence}\n"
        )

    os.replace(temp, STATE_FILENAME)


def load_existing_entries():
    entries = []

    if not os.path.exists(M3U8_FILENAME):
        return entries

    try:
        with open(
            M3U8_FILENAME,
            "r",
            encoding="utf-8"
        ) as file:

            lines = [
                line.strip()
                for line in file
                if line.strip()
            ]

        duration = None

        for line in lines:
            if line.startswith("#EXTINF:"):
                duration = (
                    line
                    .split(":", 1)[1]
                    .split(",", 1)[0]
                )

            elif (
                duration is not None
                and not line.startswith("#")
            ):
                filename = line.split("/")[-1]

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
        print(f"Eski liste okuma hatası: {error}")

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
            timeout=60
        )

        response.raise_for_status()

        if not response.content:
            raise ValueError("Boş segment indirildi.")

        with open(temp_path, "wb") as file:
            file.write(response.content)

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
            f"İndirme hatası "
            f"{filename}: {error}"
        )

        return None


def update_once(stream_url):
    playlist = get_playlist(stream_url)

    if not playlist:
        return False

    source_start = playlist["media_sequence"]
    target_duration = playlist["target_duration"]
    source_segments = playlist["segments"]

    if not source_segments:
        print("Segment bulunamadı.")
        return False

    state = load_state()
    existing_entries = load_existing_entries()

    last_source = state["last_source_sequence"]
    last_local = state["last_local_sequence"]

    if existing_entries:
        last_local = max(
            last_local,
            max(
                item["sequence"]
                for item in existing_entries
            )
        )

    new_source_entries = []

    for index, segment in enumerate(source_segments):
        source_sequence = source_start + index

        if (
            last_source is None
            or source_sequence > last_source
        ):
            new_source_entries.append({
                "source_sequence": source_sequence,
                "duration": segment["duration"],
                "url": segment["url"]
            })

    if not new_source_entries:
        return False

    files = []
    pending_entries = []

    for item in new_source_entries:
        last_local += 1

        filename = f"seg_{last_local}.ts"

        files.append((
            filename,
            item["url"]
        ))

        pending_entries.append({
            "sequence": last_local,
            "source_sequence": (
                item["source_sequence"]
            ),
            "duration": item["duration"],
            "filename": filename
        })

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:
        results = list(
            executor.map(
                download_segment,
                files
            )
        )

    successful = {
        filename
        for filename in results
        if filename is not None
    }

    new_entries = []

    for item in pending_entries:
        if item["filename"] not in successful:
            # Sıralamada boşluk oluşmaması için
            # başarısız segmentten sonrasını ekleme.
            break

        new_entries.append(item)

    if not new_entries:
        print(
            "Yeni parçalar indirilemedi. "
            "Eski yayın korunuyor."
        )
        return False

    all_entries = (
        existing_entries +
        [
            {
                "sequence": item["sequence"],
                "duration": item["duration"],
                "filename": item["filename"]
            }
            for item in new_entries
        ]
    )

    all_entries.sort(
        key=lambda item: item["sequence"]
    )

    temp_playlist = (
        M3U8_FILENAME + ".tmp"
    )

    with open(
        temp_playlist,
        "w",
        encoding="utf-8"
    ) as file:

        file.write("#EXTM3U\n")
        file.write("#EXT-X-VERSION:3\n")

        file.write(
            f"#EXT-X-TARGETDURATION:"
            f"{target_duration}\n"
        )

        file.write(
            f"#EXT-X-MEDIA-SEQUENCE:"
            f"{all_entries[0]['sequence']}\n"
        )

        for item in all_entries:
            file.write(
                f"#EXTINF:"
                f"{item['duration']},\n"
            )

            file.write(
                f"{BASE_URL}"
                f"{item['filename']}\n"
            )

    os.replace(
        temp_playlist,
        M3U8_FILENAME
    )

    save_state(
        new_entries[-1]["source_sequence"],
        new_entries[-1]["sequence"]
    )

    print(
        f"{len(new_entries)} yeni parça eklendi. "
        f"Toplam kayıt: {len(all_entries)}"
    )

    return True


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    stream_url = None
    last_refresh = 0

    while True:
        try:
            now = time.time()

            if (
                stream_url is None
                or now - last_refresh
                >= STREAM_REFRESH_INTERVAL
            ):
                new_url = get_stream_url()

                if not new_url:
                    print(
                        "Yayın URL'si alınamadı. "
                        "Tekrar denenecek."
                    )

                    time.sleep(5)
                    continue

                stream_url = new_url
                last_refresh = now

                print(
                    "Yayın URL'si güncellendi."
                )

            changed = update_once(stream_url)

            if changed:
                print(
                    "Yayın güncellendi."
                )

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("Program durduruldu.")
            break

        except Exception as error:
            print(
                f"Genel hata: {error}"
            )

            # URL geçersizleşmiş olabilir.
            stream_url = None
            last_refresh = 0

            time.sleep(3)


if __name__ == "__main__":
    main()
