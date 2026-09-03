import os
import json
import time
import subprocess
import requests
from urllib.parse import urljoin

STREAM_DIR = "streams"
PLAYLIST_FILE = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILE = os.path.join(STREAM_DIR, "atvavrupa_state.json")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

MAX_SEGMENTS = 300
CHECK_INTERVAL = 1
STREAM_REFRESH_INTERVAL = 300
REQUEST_TIMEOUT = 20
DOWNLOAD_RETRIES = 5


def get_stream_url():
    for attempt in range(1, 6):
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

            if url:
                print("Yayın URL'si alındı.")
                return url

            print(
                f"Streamlink URL vermedi "
                f"({attempt}/5)."
            )

        except Exception as error:
            print(
                f"Streamlink hatası "
                f"({attempt}/5): {error}"
            )

        time.sleep(3)

    return None


def get_playlist(stream_url):
    response = requests.get(
        stream_url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    lines = [
        line.strip()
        for line in response.text.splitlines()
        if line.strip()
    ]

    target_duration = 10
    media_sequence = 0
    segments = []

    for line in lines:
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

        elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

    segment_index = 0
    i = 0

    while i < len(lines):
        if lines[i].startswith("#EXTINF:"):
            try:
                duration = (
                    lines[i]
                    .split(":", 1)[1]
                    .split(",", 1)[0]
                )
            except Exception:
                i += 1
                continue

            j = i + 1

            while j < len(lines):
                if not lines[j].startswith("#"):
                    segment_url = urljoin(
                        stream_url,
                        lines[j]
                    )

                    sequence = (
                        media_sequence
                        + segment_index
                    )

                    segments.append({
                        "sequence": sequence,
                        "duration": duration,
                        "url": segment_url
                    })

                    segment_index += 1
                    i = j
                    break

                j += 1

        i += 1

    return target_duration, segments


def load_state():
    default_state = {
        "last_source_sequence": -1,
        "last_local_sequence": -1
    }

    if not os.path.exists(STATE_FILE):
        return default_state

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            state = json.load(file)

        if (
            not isinstance(
                state.get(
                    "last_source_sequence"
                ),
                int
            )
        ):
            state[
                "last_source_sequence"
            ] = -1

        if (
            not isinstance(
                state.get(
                    "last_local_sequence"
                ),
                int
            )
        ):
            state[
                "last_local_sequence"
            ] = -1

        return state

    except Exception as error:
        print(
            f"State dosyası okunamadı: "
            f"{error}"
        )

        return default_state


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False
        )

    os.replace(
        temp_file,
        STATE_FILE
    )


def load_entries():
    entries = []

    if not os.path.exists(
        PLAYLIST_FILE
    ):
        return entries

    try:
        with open(
            PLAYLIST_FILE,
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
                filename = (
                    line
                    .rsplit("/", 1)[-1]
                )

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

                        if os.path.exists(
                            filepath
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
        print(
            f"Playlist okunamadı: "
            f"{error}"
        )

    return sorted(
        entries,
        key=lambda item: item["sequence"]
    )


def download_segment(
    filename,
    url
):
    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(filepath):
        return True

    temp_file = filepath + ".tmp"

    for attempt in range(
        1,
        DOWNLOAD_RETRIES + 1
    ):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            content = response.content

            if not content:
                raise ValueError(
                    "Boş segment"
                )

            with open(
                temp_file,
                "wb"
            ) as file:
                file.write(content)

            if (
                os.path.getsize(
                    temp_file
                )
                < 100
            ):
                raise ValueError(
                    "Geçersiz segment boyutu"
                )

            os.replace(
                temp_file,
                filepath
            )

            return True

        except Exception as error:
            print(
                f"{filename} indirilemedi "
                f"({attempt}/{DOWNLOAD_RETRIES}): "
                f"{error}"
            )

            try:
                if os.path.exists(
                    temp_file
                ):
                    os.remove(
                        temp_file
                    )
            except OSError:
                pass

            time.sleep(1)

    return False


def write_playlist(
    entries,
    target_duration
):
    if not entries:
        return

    temp_file = PLAYLIST_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:
        file.write("#EXTM3U\n")
        file.write(
            "#EXT-X-VERSION:3\n"
        )

        file.write(
            f"#EXT-X-TARGETDURATION:"
            f"{target_duration}\n"
        )

        file.write(
            f"#EXT-X-MEDIA-SEQUENCE:"
            f"{entries[0]['sequence']}"
            f"\n"
        )

        for entry in entries:
            file.write(
                f"#EXTINF:"
                f"{entry['duration']},\n"
            )

            file.write(
                f"{BASE_URL}"
                f"{entry['filename']}\n"
            )

    os.replace(
        temp_file,
        PLAYLIST_FILE
    )


def clean_old_files(entries):
    keep_files = {
        entry["filename"]
        for entry in entries
    }

    try:
        files = os.listdir(
            STREAM_DIR
        )
    except OSError:
        return

    for filename in files:
        if (
            filename.startswith("seg_")
            and filename.endswith(".ts")
            and filename not in keep_files
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


def update_once(stream_url):
    target_duration, source_segments = (
        get_playlist(
            stream_url
        )
    )

    if not source_segments:
        return False

    state = load_state()
    entries = load_entries()

    last_source = state.get(
        "last_source_sequence",
        -1
    )

    last_local = state.get(
        "last_local_sequence",
        -1
    )

    if entries:
        last_local = max(
            last_local,
            entries[-1]["sequence"]
        )

    new_segments = [
        segment
        for segment in source_segments
        if (
            segment["sequence"]
            > last_source
        )
    ]

    if not new_segments:
        return False

    new_segments.sort(
        key=lambda item: item["sequence"]
    )

    successful_entries = []

    for segment in new_segments:
        local_sequence = (
            last_local + 1
        )

        filename = (
            f"seg_{local_sequence}.ts"
        )

        print(
            f"Segment indiriliyor: "
            f"Kaynak={segment['sequence']} "
            f"Yerel={local_sequence}"
        )

        success = download_segment(
            filename,
            segment["url"]
        )

        if not success:
            print(
                "Segment indirilemedi. "
                "Bu segment atlanmayacak."
            )

            # Başarısız segmentten sonra
            # kaynak sırasını ilerletme.
            break

        successful_entries.append({
            "sequence": local_sequence,
            "duration": segment["duration"],
            "filename": filename
        })

        # Sadece başarılı indirme sonrası
        # sıra numaralarını güncelle.
        last_local = local_sequence
        last_source = segment[
            "sequence"
        ]

    if not successful_entries:
        return False

    entries.extend(
        successful_entries
    )

    entries = sorted(
        {
            entry["sequence"]: entry
            for entry in entries
        }.values(),
        key=lambda item: item["sequence"]
    )

    entries = entries[
        -MAX_SEGMENTS:
    ]

    write_playlist(
        entries,
        target_duration
    )

    state[
        "last_source_sequence"
    ] = last_source

    state[
        "last_local_sequence"
    ] = last_local

    save_state(state)

    clean_old_files(
        entries
    )

    print(
        f"{len(successful_entries)} "
        f"yeni segment kaydedildi."
    )

    return True


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    stream_url = None
    last_stream_refresh = 0
    error_count = 0

    print(
        "Yayın sürekli takip ediliyor..."
    )

    while True:
        try:
            current_time = time.time()

            if (
                stream_url is None
                or (
                    current_time
                    - last_stream_refresh
                    >= STREAM_REFRESH_INTERVAL
                )
            ):
                new_url = get_stream_url()

                if not new_url:
                    print(
                        "Yayın URL'si alınamadı. "
                        "Tekrar deneniyor..."
                    )

                    time.sleep(3)
                    continue

                stream_url = new_url
                last_stream_refresh = (
                    current_time
                )

            update_once(
                stream_url
            )

            error_count = 0

            time.sleep(
                CHECK_INTERVAL
            )

        except KeyboardInterrupt:
            print(
                "\nProgram durduruldu."
            )
            break

        except Exception as error:
            error_count += 1

            print(
                f"Genel hata: {error}"
            )

            # Hata alan URL geçersiz kabul edilir.
            # Sonraki turda yeniden alınır.
            stream_url = None
            last_stream_refresh = 0

            wait_time = min(
                error_count * 2,
                15
            )

            print(
                f"{wait_time} saniye sonra "
                f"yeniden deneniyor..."
            )

            time.sleep(
                wait_time
            )


if __name__ == "__main__":
    main()
