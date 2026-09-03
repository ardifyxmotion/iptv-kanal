import os
import json
import time
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

MAX_SEGMENTS = 300
CHECK_INTERVAL = 2
STREAM_REFRESH_INTERVAL = 300
MAX_RETRIES = 3


def get_stream_url():
    for attempt in range(1, MAX_RETRIES + 1):
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

            stream_url = result.stdout.strip()

            if stream_url:
                return stream_url

            error_text = result.stderr.strip()

            print(
                f"Streamlink URL döndürmedi "
                f"({attempt}/{MAX_RETRIES}): {error_text}"
            )

        except Exception as error:
            print(
                f"Streamlink hatası "
                f"({attempt}/{MAX_RETRIES}): {error}"
            )

        if attempt < MAX_RETRIES:
            time.sleep(3)

    return None


def get_playlist(stream_url):
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                stream_url,
                headers=HEADERS,
                timeout=20
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

                            clean_url = segment_url.split(
                                "?", 1
                            )[0]

                            segments.append({
                                "id": hashlib.sha1(
                                    clean_url.encode()
                                ).hexdigest(),
                                "duration": duration,
                                "url": segment_url
                            })

                            i = j
                            break

                        j += 1

                i += 1

            return target_duration, segments

        except Exception as error:
            last_error = error

            print(
                f"Playlist hatası "
                f"({attempt}/{MAX_RETRIES}): {error}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(2)

    raise last_error


def load_state():
    default = {
        "last_local_sequence": -1,
        "seen_segments": []
    }

    if not os.path.exists(STATE_FILE):
        return default

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            state = json.load(file)

        if not isinstance(
            state.get("seen_segments"),
            list
        ):
            state["seen_segments"] = []

        if not isinstance(
            state.get("last_local_sequence"),
            int
        ):
            state["last_local_sequence"] = -1

        return state

    except Exception as error:
        print(f"State dosyası okunamadı: {error}")
        return default


def save_state(state):
    state["seen_segments"] = state[
        "seen_segments"
    ][-2000:]

    temp = STATE_FILE + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False
        )

    os.replace(temp, STATE_FILE)


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

            elif duration and not line.startswith("#"):
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
        print(f"Liste hatası: {error}")

    return sorted(
        entries,
        key=lambda item: item["sequence"]
    )


def download(item):
    filename, url = item

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(filepath):
        return filename

    temp = filepath + ".tmp"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            response.raise_for_status()

            with open(temp, "wb") as file:
                file.write(response.content)

            if os.path.getsize(temp) == 0:
                raise ValueError(
                    "Boş segment indirildi"
                )

            os.replace(temp, filepath)

            return filename

        except Exception as error:
            print(
                f"Segment indirme hatası "
                f"{filename} "
                f"({attempt}/{MAX_RETRIES}): {error}"
            )

            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except OSError:
                pass

            if attempt < MAX_RETRIES:
                time.sleep(1)

    return None


def write_playlist(entries, target_duration):
    if not entries:
        return

    temp = PLAYLIST_FILE + ".tmp"

    with open(
        temp,
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

    os.replace(temp, PLAYLIST_FILE)


def clean_old_files(entries):
    keep = {
        entry["filename"]
        for entry in entries
    }

    try:
        filenames = os.listdir(STREAM_DIR)
    except OSError:
        return

    for filename in filenames:
        if (
            filename.startswith("seg_")
            and filename.endswith(".ts")
            and filename not in keep
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
    target_duration, source_segments = get_playlist(
        stream_url
    )

    if not source_segments:
        print("Playlist içinde segment bulunamadı.")
        return False

    state = load_state()
    entries = load_entries()

    seen_list = state["seen_segments"]
    seen = set(seen_list)

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
        if segment["id"] not in seen
    ]

    if not new_segments:
        return False

    pending = []
    downloads = []

    for segment in new_segments:
        last_local += 1

        filename = (
            f"seg_{last_local}.ts"
        )

        pending.append({
            "sequence": last_local,
            "id": segment["id"],
            "duration": segment["duration"],
            "filename": filename
        })

        downloads.append((
            filename,
            segment["url"]
        ))

    print(
        f"{len(downloads)} yeni segment "
        f"indiriliyor..."
    )

    with ThreadPoolExecutor(
        max_workers=6
    ) as executor:
        results = list(
            executor.map(
                download,
                downloads
            )
        )

    successful = {
        filename
        for filename in results
        if filename
    }

    new_entries = [
        entry
        for entry in pending
        if entry["filename"] in successful
    ]

    if not new_entries:
        print(
            "Yeni segmentlerin hiçbiri "
            "indirilemedi."
        )
        return False

    # Başarılı segmentleri görülenler listesine ekle.
    # Sıralamayı korumak için set doğrudan kaydedilmez.
    for entry in new_entries:
        if entry["id"] not in seen:
            seen_list.append(entry["id"])
            seen.add(entry["id"])

    state["seen_segments"] = seen_list[-2000:]

    state["last_local_sequence"] = max(
        entry["sequence"]
        for entry in new_entries
    )

    entries.extend([
        {
            "sequence": entry["sequence"],
            "duration": entry["duration"],
            "filename": entry["filename"]
        }
        for entry in new_entries
    ])

    # Aynı sıra numaralı kayıtları temizle.
    entries = sorted(
        {
            entry["sequence"]: entry
            for entry in entries
        }.values(),
        key=lambda item: item["sequence"]
    )

    # Son MAX_SEGMENTS segmenti tut.
    entries = entries[-MAX_SEGMENTS:]

    write_playlist(
        entries,
        target_duration
    )

    save_state(state)

    clean_old_files(entries)

    print(
        f"{len(new_entries)} yeni segment "
        f"başarıyla kaydedildi."
    )

    return True


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    stream_url = None
    last_stream_check = 0
    consecutive_errors = 0

    print(
        "ATV Avrupa yayın takip sistemi "
        "başlatıldı."
    )

    while True:
        try:
            current_time = time.time()

            # Stream URL'sini düzenli olarak yenile.
            if (
                stream_url is None
                or (
                    current_time
                    - last_stream_check
                    >= STREAM_REFRESH_INTERVAL
                )
            ):
                print(
                    "Yayın URL'si kontrol ediliyor..."
                )

                new_stream_url = get_stream_url()

                if new_stream_url:
                    stream_url = new_stream_url

                    last_stream_check = current_time

                    consecutive_errors = 0

                    print(
                        "Yayın URL'si başarıyla "
                        "alındı."
                    )
                else:
                    print(
                        "Yayın URL'si alınamadı. "
                        "Yeniden denenecek..."
                    )

                    stream_url = None

                    time.sleep(5)

                    continue

            # Yayını ve yeni segmentleri takip et.
            changed = update_once(stream_url)

            consecutive_errors = 0

            if changed:
                print("Yayın güncellendi.")

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print(
                "\nProgram kullanıcı tarafından "
                "durduruldu."
            )
            break

        except Exception as error:
            consecutive_errors += 1

            print(
                f"Genel hata "
                f"({consecutive_errors}): "
                f"{error}"
            )

            # Mevcut URL geçersiz olabilir.
            # Bir sonraki turda tekrar alınacak.
            stream_url = None
            last_stream_check = 0

            # Hata durumunda bekleme süresi
            # kademeli olarak artırılır.
            wait_time = min(
                consecutive_errors * 5,
                60
            )

            print(
                f"{wait_time} saniye sonra "
                f"yeniden bağlanılacak..."
            )

            time.sleep(wait_time)


if __name__ == "__main__":
    main()
