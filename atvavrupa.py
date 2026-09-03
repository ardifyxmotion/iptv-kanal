import os
import json
import time
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
from datetime import datetime
from zoneinfo import ZoneInfo

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
INDEX_FILE = os.path.join(STREAM_DIR, "segments.json")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"
TIMEZONE = ZoneInfo("Europe/Istanbul")
HEADERS = {"User-Agent": "Mozilla/5.0"}


def load_archive():
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_archive(archive):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False)


def get_stream_url():
    result = subprocess.run(
        ["streamlink", "--stream-url",
         "https://www.atvavrupa.tv/canli-yayin", "best"],
        capture_output=True, text=True, timeout=30
    )
    url = result.stdout.strip()
    if not url:
        print("Yayın URL'si bulunamadı.")
        print(result.stderr)
        return None
    return url


def get_source_segments(stream_url):
    response = requests.get(stream_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    lines = [x.strip() for x in response.text.splitlines() if x.strip()]
    media_sequence = 0
    target_duration = 10

    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            media_sequence = int(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            target_duration = int(line.split(":", 1)[1])

    segments = []
    i = 0

    while i < len(lines):
        if lines[i].startswith("#EXTINF:"):
            try:
                duration = float(lines[i].split(":", 1)[1].split(",", 1)[0])
            except ValueError:
                i += 1
                continue

            j = i + 1
            while j < len(lines) and lines[j].startswith("#"):
                j += 1

            if j < len(lines):
                segments.append({
                    "duration": duration,
                    "url": urljoin(stream_url, lines[j]),
                    "sequence": media_sequence + len(segments)
                })
                i = j
        i += 1

    return target_duration, segments


def download_segment(segment):
    filename = f"seg_{segment['sequence']}.ts"
    path = os.path.join(STREAM_DIR, filename)

    if not os.path.exists(path):
        try:
            response = requests.get(
                segment["url"], headers=HEADERS, timeout=30
            )
            response.raise_for_status()

            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(response.content)
            os.replace(tmp, path)

        except Exception as error:
            print(f"İndirilemedi {filename}: {error}")
            return None

    return {
        "filename": filename,
        "sequence": segment["sequence"],
        "duration": segment["duration"],
        "date": datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    }


def clean_previous_day(archive, today):
    """Yeni gün başladığında önceki günün segmentlerini sil."""
    kept = []

    for item in archive:
        if item.get("date") == today:
            kept.append(item)
        else:
            path = os.path.join(STREAM_DIR, item["filename"])
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    return kept


def write_playlist(archive, target_duration):
    if not archive:
        return

    archive.sort(key=lambda x: x["sequence"])

    with open(M3U8_FILENAME, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write(f"#EXT-X-TARGETDURATION:{target_duration}\n")
        f.write(f"#EXT-X-MEDIA-SEQUENCE:{archive[0]['sequence']}\n")

        for item in archive:
            f.write(f"#EXTINF:{item['duration']:.3f},\n")
            f.write(f"{BASE_URL}{item['filename']}\n")


def main():
    os.makedirs(STREAM_DIR, exist_ok=True)

    now = datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")

    print(f"Tarih: {today}")
    print(f"Günün yayın konumu: {now.strftime('%H:%M:%S')}")

    archive = clean_previous_day(load_archive(), today)

    # Aynı kaynak sequence değerini tekrar ekleme
    known_sequences = {x["sequence"] for x in archive}

    stream_url = get_stream_url()
    if not stream_url:
        return

    target_duration, source_segments = get_source_segments(stream_url)

    new_segments = [
        segment for segment in source_segments
        if segment["sequence"] not in known_sequences
    ]

    print(f"Kaynak segment: {len(source_segments)}")
    print(f"Yeni segment: {len(new_segments)}")

    if new_segments:
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(download_segment, new_segments))

        archive.extend(x for x in results if x is not None)

    # Sequence değerine göre sırala ve dosyası olmayan kayıtları çıkar
    archive = [
        x for x in archive
        if os.path.exists(os.path.join(STREAM_DIR, x["filename"]))
    ]

    archive.sort(key=lambda x: x["sequence"])

    save_archive(archive)
    write_playlist(archive, target_duration)

    total_duration = sum(x["duration"] for x in archive)

    print(f"Arşiv segmenti: {len(archive)}")
    print(
        f"Biriken gerçek süre: "
        f"{int(total_duration // 3600):02d}:"
        f"{int((total_duration % 3600) // 60):02d}:"
        f"{int(total_duration % 60):02d}"
    )


if __name__ == "__main__":
    main()
