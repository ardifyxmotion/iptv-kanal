import os
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILENAME = os.path.join(STREAM_DIR, "atvavrupa_state.txt")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


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
                media_sequence = int(line.split(":", 1)[1])

            elif line.startswith("#EXT-X-TARGETDURATION:"):
                target_duration = int(line.split(":", 1)[1])

        i = 0

        while i < len(lines):
            if lines[i].startswith("#EXTINF:"):
                duration = lines[i].split(
                    ":", 1
                )[1].split(",", 1)[0]

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
        ) as f:

            for line in f:
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
    ) as f:
        f.write(
            f"last_source_sequence="
            f"{source_sequence}\n"
        )
        f.write(
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
                filename = line.split("/")[-1]

                if (
                    filename.startswith("seg_")
                    and filename.endswith(".ts")
                ):
                    try:
                        sequence = int(
                            filename[4:-3]
                        )

                        if os.path.exists(
                            os.path.join(
                                STREAM_DIR,
                                filename
                            )
                        ):
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

    return entries


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

        with open(temp_path, "wb") as f:
            f.write(response.content)

        os.replace(
            temp_path,
            filepath
        )

        return filename

    except Exception as error:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

        print(
            f"İndirme hatası "
            f"{filename}: {error}"
        )

        return None


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    stream_url = get_stream_url()

    if not stream_url:
        return

    playlist = get_playlist(stream_url)

    if not playlist:
        return

    source_start = playlist[
        "media_sequence"
    ]

    target_duration = playlist[
        "target_duration"
    ]

    source_segments = playlist[
        "segments"
    ]

    if not source_segments:
        print("Segment bulunamadı.")
        return

    state = load_state()

    existing_entries = (
        load_existing_entries()
    )

    last_source = state[
        "last_source_sequence"
    ]

    last_local = state[
        "last_local_sequence"
    ]

    if existing_entries:
        last_local = max(
            last_local,
            max(
                item["sequence"]
                for item in existing_entries
            )
        )

    new_source_entries = []

    for index, segment in enumerate(
        source_segments
    ):
        source_sequence = (
            source_start + index
        )

        if (
            last_source is None
            or source_sequence > last_source
        ):
            new_source_entries.append({
                "source_sequence": (
                    source_sequence
                ),
                "duration": (
                    segment["duration"]
                ),
                "url": segment["url"]
            })

    # Yeni yayın parçası yoksa mevcut listeyi ASLA değiştirme.
    if not new_source_entries:
        print(
            "Yeni yayın parçası henüz yok. "
            "Mevcut yayın korunuyor."
        )
        return

    files = []
    pending_entries = []

    for item in new_source_entries:
        last_local += 1

        filename = (
            f"seg_{last_local}.ts"
        )

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
        max_workers=10
    ) as executor:
        results = list(
            executor.map(
                download_segment,
                files
            )
        )

    successful = set(
        item
        for item in results
        if item is not None
    )

    new_entries = [
        item
        for item in pending_entries
        if item["filename"] in successful
    ]

    if not new_entries:
        print(
            "Yeni parçalar indirilemedi. "
            "Eski yayın korunuyor."
        )
        return

    # ÖNEMLİ:
    # Burada eski segmentler SİLİNMİYOR.
    # 29:46 civarında yaşanan kesilmenin nedeni
    # eski kodun 500 segment sınırına ulaşmasıydı.
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
        key=lambda x: x["sequence"]
    )

    temp_playlist = (
        M3U8_FILENAME + ".tmp"
    )

    with open(
        temp_playlist,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write(
            f"#EXT-X-TARGETDURATION:"
            f"{target_duration}\n"
        )

        if all_entries:
            f.write(
                f"#EXT-X-MEDIA-SEQUENCE:"
                f"{all_entries[0]['sequence']}\n"
            )

        for item in all_entries:
            f.write(
                f"#EXTINF:"
                f"{item['duration']},\n"
            )
            f.write(
                f"{BASE_URL}"
                f"{item['filename']}\n"
            )

    os.replace(
        temp_playlist,
        M3U8_FILENAME
    )

    save_state(
        new_entries[-1][
            "source_sequence"
        ],
        new_entries[-1][
            "sequence"
        ]
    )

    print(
        f"{len(new_entries)} yeni parça eklendi."
    )

    print(
        f"Toplam kayıt: "
        f"{len(all_entries)}"
    )

    print(
        "Yayın kaldığı yerden "
        "devam edecek."
    )


if __name__ == "__main__":
    main()
