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
    "User-Agent": "Mozilla/5.0",
    "Cache-Control": "no-cache"
}

CHECK_INTERVAL = 1
STREAM_REFRESH_INTERVAL = 300
REQUEST_TIMEOUT = 20
DOWNLOAD_RETRIES = 5

# 0 = segmentleri silme. Böylece 50 dakika gibi
# sabit bir sınır oluşmaz.
MAX_SEGMENTS = 0


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
                f"({attempt}/5): "
                f"{result.stderr.strip()}"
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
    media_sequence = None
    discontinuity_sequence = 0

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

        elif line.startswith("#EXT-X-DISCONTINUITY-SEQUENCE:"):
            try:
                discontinuity_sequence = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

    segments = []
    segment_index = 0
    i = 0
    discontinuity_count = 0

    while i < len(lines):
        if lines[i] == "#EXT-X-DISCONTINUITY":
            discontinuity_count += 1
            i += 1
            continue

        if not lines[i].startswith("#EXTINF:"):
            i += 1
            continue

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
            if lines[j] == "#EXT-X-DISCONTINUITY":
                discontinuity_count += 1
                j += 1
                continue

            if not lines[j].startswith("#"):
                segment_url = urljoin(
                    stream_url,
                    lines[j]
                )

                if media_sequence is not None:
                    source_sequence = (
                        media_sequence
                        + segment_index
                    )
                else:
                    source_sequence = segment_index

                segment_id = (
                    f"{discontinuity_sequence}:"
                    f"{discontinuity_count}:"
                    f"{source_sequence}"
                )

                segments.append({
                    "id": segment_id,
                    "source_sequence": source_sequence,
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
        ) as file:
            state = json.load(file)

        if not isinstance(
            state.get("last_local_sequence"),
            int
        ):
            state["last_local_sequence"] = -1

        if not isinstance(
            state.get("seen_segments"),
            list
        ):
            state["seen_segments"] = []

        return state

    except Exception as error:
        print(
            f"State dosyası okunamadı: {error}"
        )

        return default_state


def save_state(state):
    state["seen_segments"] = (
        state["seen_segments"][-20000:]
    )

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

    if not os.path.exists(PLAYLIST_FILE):
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
            f"Playlist okunamadı: {error}"
        )

    return sorted(
        entries,
        key=lambda item: item["sequence"]
    )


def download_segment(filename, url):
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

            if len(content) < 100:
                raise ValueError(
                    "Segment boş veya çok küçük"
                )

            with open(
                temp_file,
                "wb"
            ) as file:
                file.write(content)

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
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except OSError:
                pass

            time.sleep(1)

    return False


def write_playlist(entries, target_duration):
    if not entries:
        return

    temp_file = PLAYLIST_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:
        file.write("#EXTM3U\n")
        file.write("#EXT-X-VERSION:3\n")
        file.write(
            "#EXT-X-INDEPENDENT-SEGMENTS\n"
        )

        file.write(
            f"#EXT-X-TARGETDURATION:"
            f"{target_duration}\n"
        )

        file.write(
            f"#EXT-X-MEDIA-SEQUENCE:"
            f"{entries[0]['sequence']}\n"
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

        # EXT-X-ENDLIST yazılmıyor.
        # Playlist canlı yayın olarak devam eder.

    os.replace(
        temp_file,
        PLAYLIST_FILE
    )


def clean_old_files(entries):
    if MAX_SEGMENTS <= 0:
        return

    keep_files = {
        entry["filename"]
        for entry in entries
    }

    try:
        files = os.listdir(STREAM_DIR)
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
        get_playlist(stream_url)
    )

    if not source_segments:
        print(
            "Playlist içinde segment bulunamadı."
        )
        return False

    state = load_state()
    entries = load_entries()

    seen_list = state["seen_segments"]
    seen = set(seen_list)

    last_local = state[
        "last_local_sequence"
    ]

    if entries:
        last_local = max(
            last_local,
            entries[-1]["sequence"]
        )

    new_segments = [
        segment
        for segment in source_segments
        if segment["id"] not in seen
    ]

    if not new_segments:
        return False

    successful_entries = []

    for segment in new_segments:
        local_sequence = last_local + 1

        filename = (
            f"seg_{local_sequence}.ts"
        )

        success = download_segment(
            filename,
            segment["url"]
        )

        if not success:
            print(
                "Segment başarısız oldu. "
                "Sonraki kontrolde tekrar denenecek."
            )
            break

        successful_entries.append({
            "sequence": local_sequence,
            "duration": segment["duration"],
            "filename": filename
        })

        seen_list.append(segment["id"])
        seen.add(segment["id"])

        last_local = local_sequence

    if not successful_entries:
        return False

    entries.extend(successful_entries)

    entries = sorted(
        {
            entry["sequence"]: entry
            for entry in entries
        }.values(),
        key=lambda item: item["sequence"]
    )

    if MAX_SEGMENTS > 0:
        entries = entries[-MAX_SEGMENTS:]

    write_playlist(
        entries,
        target_duration
    )

    state[
        "last_local_sequence"
    ] = last_local

    state["seen_segments"] = seen_list

    save_state(state)

    clean_old_files(entries)

    print(
        f"{len(successful_entries)} yeni "
        f"segment kaydedildi. "
        f"Toplam: {len(entries)}"
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
        "ATV Avrupa sürekli yayın takibi başladı."
    )

    while True:
        try:
            current_time = time.time()

            if (
                stream_url is None
                or current_time
                - last_stream_refresh
                >= STREAM_REFRESH_INTERVAL
            ):
                print(
                    "Yayın URL'si yenileniyor..."
                )

                new_url = get_stream_url()

                if new_url:
                    stream_url = new_url
                    last_stream_refresh = current_time
                else:
                    print(
                        "Yayın URL'si alınamadı."
                    )

                    time.sleep(5)
                    continue

            update_once(stream_url)

            error_count = 0

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print(
                "\nProgram durduruldu."
            )
            break

        except Exception as error:
            error_count += 1

            print(
                f"Genel hata "
                f"({error_count}): {error}"
            )

            stream_url = None
            last_stream_refresh = 0

            wait_time = min(
                2 * error_count,
                20
            )

            time.sleep(wait_time)


if __name__ == "__main__":
    main()
