import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
SEQUENCE_FILE = os.path.join(STREAM_DIR, "sequence.txt")

MAX_SEGMENTS = 160
BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"


def download_segment(args):
    fname, url = args
    fpath = os.path.join(STREAM_DIR, fname)

    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )

        response.raise_for_status()

        # Her çalıştırmada dosyayı güncelle.
        with open(fpath, "wb") as f:
            f.write(response.content)

        return fname

    except Exception as e:
        print(f"İndirilemedi: {fname} - {e}")
        return None


def get_sequence():
    try:
        with open(SEQUENCE_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def save_sequence(sequence):
    with open(SEQUENCE_FILE, "w") as f:
        f.write(str(sequence))


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

    stream_url = result.stdout.strip()

    if not stream_url:
        print("Streamlink yayın URL'sini bulamadı.")
        print(result.stderr)
        return None

    return stream_url


def main():
    os.makedirs(STREAM_DIR, exist_ok=True)

    try:
        # 1. Canlı yayın M3U8 adresini al
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(f"Yayın bulundu: {stream_url}")

        # 2. M3U8 listesini indir
        response = requests.get(
            stream_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )

        response.raise_for_status()

        playlist_lines = response.text.splitlines()

        # Segment URL'lerini al
        segment_urls = []

        for line in playlist_lines:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            segment_urls.append(urljoin(stream_url, line))

        # Son MAX_SEGMENTS segmenti kullan
        segment_urls = segment_urls[-MAX_SEGMENTS:]

        if not segment_urls:
            print("M3U8 içerisinde segment bulunamadı.")
            return

        # Her GitHub Actions çalışmasında yeni ve benzersiz sıra numarası
        start_sequence = get_sequence()

        target_files = []

        for index, url in enumerate(segment_urls):
            sequence = start_sequence + index
            filename = f"seg_{sequence}.ts"
            target_files.append((filename, url))

        print(f"{len(target_files)} segment indiriliyor...")

        # 3. Segmentleri paralel indir
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(download_segment, target_files))

        # Başarılı indirilen segmentleri kullan
        downloaded_files = [
            fname for fname in results
            if fname is not None
        ]

        if not downloaded_files:
            print("Hiçbir segment indirilemedi.")
            return

        # 4. Yeni sequence numarasını kaydet
        next_sequence = start_sequence + len(segment_urls)
        save_sequence(next_sequence)

        # 5. Başarılı segmentler dışındaki eski dosyaları temizle
        current_files = set(downloaded_files)

        existing_files = glob.glob(
            os.path.join(STREAM_DIR, "seg_*.ts")
        )

        for filepath in existing_files:
            filename = os.path.basename(filepath)

            if filename not in current_files:
                try:
                    os.remove(filepath)
                except OSError:
                    pass

        # 6. M3U8 listesini oluştur
        # İlk gerçek segment numarasını MEDIA-SEQUENCE olarak kullan.
        first_sequence = int(
            downloaded_files[0]
            .replace("seg_", "")
            .replace(".ts", "")
        )

        with open(M3U8_FILENAME, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")
            f.write(f"#EXT-X-MEDIA-SEQUENCE:{first_sequence}\n")
            f.write("#EXT-X-TARGETDURATION:10\n")

            for filename in downloaded_files:
                f.write("#EXTINF:10.0,\n")
                f.write(f"{BASE_URL}{filename}\n")

        print(
            f"Tamamlandı: {len(downloaded_files)} segment "
            f"({first_sequence} - "
            f"{first_sequence + len(downloaded_files) - 1})"
        )

    except Exception as e:
        print(f"Hata: {e}")


if __name__ == "__main__":
    main()
