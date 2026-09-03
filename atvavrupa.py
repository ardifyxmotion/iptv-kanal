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


def get_stream_url():
    try:
        result = subprocess.run(
            ["streamlink", "--stream-url",
             "https://www.atvavrupa.tv/canli-yayin", "best"],
            capture_output=True,
            text=True,
            timeout=60
        )

        return result.stdout.strip() or None

    except Exception as error:
        print(f"Streamlink hatası: {error}")
        return None


def get_playlist(stream_url):
    response = requests.get(
        stream_url,
        headers=HEADERS,
        timeout=15
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
                target_duration = int(line.split(":", 1)[1])
            except ValueError:
                pass

    i = 0

    while i < len(lines):
        if lines[i].startswith("#EXTINF:"):
            try:
                duration = lines[i].split(
                    ":", 1
                )[1].split(",", 1)[0]
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


def load_state():
    default = {
        "last_local_sequence": -1,
        "seen_segments": []
    }

    if not os.path.exists(STATE_FILE):
        return default

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if not isinstance(state.get("seen_segments"), list):
            state["seen_segments"] = []

        return state

    except Exception:
        return default


def save_state(state):
    state["seen_segments"] = state[
        "seen_segments"
    ][-2000:]

    temp = STATE_FILE + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(state, f)

    os.replace(temp, STATE_FILE)


def load_entries():
    entries = []

    if not os.path.exists(PLAYLIST_FILE):
        return entries

    try:
        with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
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

            elif duration and not line.startswith("#"):
                filename = line.rsplit("/", 1)[-1]

                if (
                    filename.startswith("seg_")
                    and filename.endswith(".ts")
                ):
                    try:
                        sequence = int(filename[4:-3])

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

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )
        response.raise_for_status()

        with open(temp, "wb") as f:
            f.write(response.content)

        os.replace(temp, filepath)

        return filename

    except Exception as error:
        print(f"İndirme hatası: {error}")

        try:
            os.remove(temp)
        except OSError:
            pass

        return None


def write_playlist(entries, target_duration):
    if not entries:
        return

    temp = PLAYLIST_FILE + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
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
                f"#EXTINF:{entry['duration']},\n"
            )
            f.write(
                f"{BASE_URL}{entry['filename']}\n"
            )

    os.replace(temp, PLAYLIST_FILE)


def clean_old_files(entries):
    keep = {
        entry["filename"]
        for entry in entries
    }

    for filename in os.listdir(STREAM_DIR):
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

    state = load_state()
    entries = load_entries()

    seen = set(state["seen_segments"])

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

        filename = f"seg_{last_local}.ts"

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

    with ThreadPoolExecutor(
        max_workers=6
    ) as executor:
        results = list(
            executor.map(download, downloads)
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
        return False

    for entry in new_entries:
        seen.add(entry["id"])

    state["seen_segments"] = list(seen)
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

    entries = sorted(
        {entry["sequence"]: entry
         for entry in entries}.values(),
        key=lambda item: item["sequence"]
    )[-MAX_SEGMENTS:]

    write_playlist(entries, target_duration)
    save_state(state)
    clean_old_files(entries)

    print(
        f"{len(new_entries)} yeni segment bulundu."
    )

    return True


def main():
    os.makedirs(STREAM_DIR, exist_ok=True)

    stream_url = None
    last_stream_check = 0

    while True:
        try:
            # Stream URL'sini her 5 dakikada bir yenile.
            if (
                stream_url is None
                or time.time() - last_stream_check > 300
            ):
                stream_url = get_stream_url()
                last_stream_check = time.time()

            if stream_url:
                changed = update_once(stream_url)

                if changed:
                    print("Yayın güncellendi.")
            else:
                print("Yayın URL'si alınamadı.")

        except Exception as error:
            print(f"Hata: {error}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
