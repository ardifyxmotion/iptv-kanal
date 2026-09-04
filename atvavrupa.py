import os
import glob
import re
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
MAX_SEGMENTS = 160

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def download_segment(item):
    filename, url = item
    path = os.path.join(STREAM_DIR, filename)

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200 and response.content:
            with open(path, "wb") as f:
                f.write(response.content)
            return True
    except requests.RequestException:
        pass

    return False


def get_stream_url():
    cmd = [
        "streamlink",
        "--stream-url",
        "https://www.atvavrupa.tv/canli-yayin",
        "best"
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30
    )

    url = result.stdout.strip()

    if not url:
        raise RuntimeError("Streamlink yayın adresini bulamadı.")

    return url


def parse_playlist(stream_url):
    response = requests.get(
        stream_url,
        headers=HEADERS,
        timeout=15
    )
    response.raise_for_status()

    lines = response.text.splitlines()

    # Master playlist gelirse en yüksek bant genişliğine sahip varyantı bul.
    variants = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
            bandwidth = 0
            match = re.search(r"BANDWIDTH=(\d+)", line)
            if match:
                bandwidth = int(match.group(1))

            variants.append((bandwidth, lines[i + 1].strip()))

    if variants:
        variants.sort(reverse=True)
        variant = variants[0][1]

        if not variant.startswith("http"):
            variant = stream_url.rsplit("/", 1)[0] + "/" + variant

        return parse_playlist(variant)

    media_sequence = 0
    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(line.split(":", 1)[1])
            except ValueError:
                pass

    segments = []
    current_duration = 10.0
    pending_duration = None
    base = stream_url.rsplit("/", 1)[0] + "/"

    for line in lines:
        line = line.strip()

        if line.startswith("#EXTINF:"):
            try:
                pending_duration = float(
                    line.split(":", 1)[1].split(",", 1)[0]
                )
            except ValueError:
                pending_duration = 10.0

        elif line and not line.startswith("#"):
            url = line if line.startswith("http") else base + line
            duration = pending_duration or current_duration
            segments.append((duration, url))
            pending_duration = None

    return media_sequence, segments


def main():
    os.makedirs(STREAM_DIR, exist_ok=True)

    stream_url = get_stream_url()
    media_sequence, segments = parse_playlist(stream_url)

    if not segments:
        raise RuntimeError("Yayın listesinde segment bulunamadı.")

    # Kaynak playlistten son MAX_SEGMENTS segmenti al.
    segments = segments[-MAX_SEGMENTS:]

    items = []

    for index, (duration, url) in enumerate(segments):
        sequence = media_sequence + index
        filename = f"seg_{sequence}.ts"
        items.append((sequence, filename, duration, url))

    # Segmentleri paralel indir.
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(
            executor.map(
                download_segment,
                [(filename, url) for _, filename, _, url in items]
            )
        )

    # Sadece gerçekten indirilen veya disk üzerinde bulunan segmentleri listeye koy.
    valid_items = []

    for item, downloaded in zip(items, results):
        sequence, filename, duration, url = item
        path = os.path.join(STREAM_DIR, filename)

        if downloaded or os.path.exists(path):
            valid_items.append(item)

    if not valid_items:
        raise RuntimeError("Hiçbir segment indirilemedi.")

    # En eski segment numarasını playlist başlangıcı yap.
    valid_items.sort(key=lambda x: x[0])
    first_sequence = valid_items[0][0]

    max_duration = max(item[2] for item in valid_items)
    target_duration = max(1, int(max_duration + 0.999))

    # Artık kullanılmayan segmentleri temizle.
    keep_files = {item[1] for item in valid_items}

    for path in glob.glob(os.path.join(STREAM_DIR, "seg_*.ts")):
        if os.path.basename(path) not in keep_files:
            try:
                os.remove(path)
            except OSError:
                pass

    # M3U8 dosyasını kaynak segment sıralamasıyla oluştur.
    with open(M3U8_FILENAME, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write(f"#EXT-X-TARGETDURATION:{target_duration}\n")
        f.write(f"#EXT-X-MEDIA-SEQUENCE:{first_sequence}\n")

        for sequence, filename, duration, url in valid_items:
            f.write(f"#EXTINF:{duration:.3f},\n")
            f.write(f"{BASE_URL}{filename}\n")


if __name__ == "__main__":
    try:
        main()
        print("ATV Avrupa playlist başarıyla güncellendi.")
    except Exception as e:
        print(f"HATA: {e}")
        raise
