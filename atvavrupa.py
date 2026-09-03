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
CHECK_INTERVAL = 10


def get_stream_url():
    result = subprocess.run(
        ["streamlink", "--stream-url",
         "https://www.atvavrupa.tv/canli-yayin", "best"],
        capture_output=True, text=True, timeout=60
    )
    url = result.stdout.strip()
    if not url:
        print("Yayın URL'si bulunamadı.")
        return None
    return url


def get_playlist(stream_url):
    response = requests.get(
        stream_url, headers=HEADERS, timeout=30
    )
    response.raise_for_status()

    lines = [x.strip() for x in response.text.splitlines() if x.strip()]
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
                duration = lines[i].split(":", 1)[1].split(",", 1)[0]
            except Exception:
                i += 1
                continue

            j = i + 1
            while j < len(lines):
                if not lines[j].startswith("#"):
                    url = urljoin(stream_url, lines[j])
                    segments.append({
                        "id": hashlib.sha1(
                            url.split("?", 1)[0].encode()
                        ).hexdigest(),
                        "duration": duration,
                        "url": url
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
            data = json.load(f)

        if not isinstance(data.get("seen_segments"), list):
            data["seen_segments"] = []

        if "last_local_sequence" not in data:
            data["last_local_sequence"] = -1

        return data

    except Exception:
        return default


def save_state(state):
    state["seen_segments"] = state["seen_segments"][-1500:]

    temp = STATE_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

    os.replace(temp, STATE_FILE)


def load_entries():
    entries = []

    if not os.path.exists(PLAYLIST_FILE):
        return entries

    try:
        with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
            lines = [x.strip() for x in f if x.strip()]

        duration = None

        for line in lines:
            if line.startswith("#EXTINF:"):
                duration = line.split(":", 1)[1].split(",", 1)[0]

            elif duration and not line.startswith("#"):
                filename = line.rsplit("/", 1)[-1]

                if filename.startswith("seg_") and filename.endswith(".ts"):
                    try:
                        seq = int(filename[4:-3])
                        if os.path.exists(
                            os.path.join(STREAM_DIR, filename)
                        ):
                            entries.append({
                                "sequence": seq,
                                "duration": duration,
                                "filename": filename
                            })
                    except ValueError:
                        pass

                duration = None

    except Exception as error:
        print(f"Eski liste okunamadı: {error}")

    return sorted(entries, key=lambda x: x["sequence"])


def download(item):
    filename, url = item
    path = os.path.join(STREAM_DIR, filename)

    if os.path.exists(path):
        return filename

    temp = path + ".tmp"

    try:
        response = requests.get(url, headers=HEADERS, timeout=45)
        response.raise_for_status()

        with open(temp, "wb") as f:
            f.write(response.content)

        os.replace(temp, path)
        return filename

    except Exception as error:
        print(f"İndirme hatası: {filename} -> {error}")
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
        f.write(f"#EXT-X-TARGETDURATION:{target_duration}\n")
        f.write(f"#EXT-X-MEDIA-SEQUENCE:{entries[0]['sequence']}\n")

        for entry in entries:
            f.write(f"#EXTINF:{entry['duration']},\n")
            f.write(f"{BASE_URL}{entry['filename']}\n")

    os.replace(temp, PLAYLIST_FILE)


def clean_files(entries):
    keep = {x["filename"] for x in entries}

    for filename in os.listdir(STREAM_DIR):
        if (
            filename.startswith("seg_")
            and filename.endswith(".ts")
            and filename not in keep
        ):
            try:
                os.remove(os.path.join(STREAM_DIR, filename))
            except OSError:
                pass


def update_once():
    stream_url = get_stream_url()
    if not stream_url:
        return False

    target_duration, source_segments = get_playlist(stream_url)

    state = load_state()
    entries = load_entries()
    seen = set(state["seen_segments"])

    last_local = state["last_local_sequence"]
    if entries:
        last_local = max(last_local, entries[-1]["sequence"])

    new_segments = [
        segment for segment in source_segments
        if segment["id"] not in seen
    ]

    if not new_segments:
        print("Yeni segment yok.")
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

        downloads.append((filename, segment["url"]))

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(download, downloads))

    successful = {x for x in results if x}

    new_entries = [
        x for x in pending
        if x["filename"] in successful
    ]

    if not new_entries:
        return False

    for entry in new_entries:
        seen.add(entry["id"])

    state["seen_segments"] = list(seen)
    state["last_local_sequence"] = max(
        x["sequence"] for x in new_entries
    )

    entries.extend([
        {
            "sequence": x["sequence"],
            "duration": x["duration"],
            "filename": x["filename"]
        }
        for x in new_entries
    ])

    entries = sorted(entries, key=lambda x: x["sequence"])[-MAX_SEGMENTS:]

    write_playlist(entries, target_duration)
    save_state(state)
    clean_files(entries)

    print(
        f"{len(new_entries)} yeni segment eklendi. "
        f"Toplam: {len(entries)}"
    )

    return True


def main():
    os.makedirs(STREAM_DIR, exist_ok=True)

    while True:
        try:
            print("Kontrol ediliyor...")
            update_once()
        except Exception as error:
            print(f"Genel hata: {error}")

        print(f"{CHECK_INTERVAL} saniye bekleniyor...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
