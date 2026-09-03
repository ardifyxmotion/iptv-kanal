import os
import re
import glob
import math
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

# GitHub RAW segment adresi
BASE_URL = (
    "https://raw.githubusercontent.com/"
    "ardifyxmotion/iptv-kanal/main/streams/"
)

# GitHub'da tutulacak maksimum segment
MAX_SEGMENTS = 160

# HTTP ayarları
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def download_segment(seq, url):
    """Segmenti indirir ve başarılıysa True döndürür."""

    fname = f"seg_{seq}.ts"
    fpath = os.path.join(STREAM_DIR, fname)

    # Dosya daha önce başarıyla indirilmişse tekrar indirme
    if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
        return seq, True

    temp_path = fpath + ".tmp"

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=(5, 20)
        )

        response.raise_for_status()

        if not response.content:
            return seq, False

        # Önce geçici dosyaya yaz
        with open(temp_path, "wb") as f:
            f.write(response.content)

        # İndirme tamamen bittikten sonra gerçek isme çevir
        os.replace(temp_path, fpath)

        return seq, True

    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

        return seq, False


def get_stream_url():
    """Streamlink ile gerçek yayın adresini alır."""

    cmd = [
        "streamlink",
        "--stream-url",
        "https://www.atvavrupa.tv/canli-yayin",
        "best"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        stream_url = result.stdout.strip()

        if stream_url.startswith("http"):
            return stream_url

    except Exception:
        pass

    return None


def parse_m3u8(stream_url):
    """Kaynak M3U8 dosyasını gerçek sequence değerleriyle çözer."""

    response = requests.get(
        stream_url,
        headers=HEADERS,
        timeout=(5, 20)
    )

    response.raise_for_status()

    lines = response.text.splitlines()

    media_sequence = 0
    segments = []
    current_duration = 10.0

    for line in lines:

        line = line.strip()

        if not line:
            continue

        # Kaynak MEDIA-SEQUENCE
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(
                    line.split(":", 1)[1]
                )
            except Exception:
                media_sequence = 0

        # Segment süresi
        elif line.startswith("#EXTINF:"):
            try:
                value = line.split(":", 1)[1]
                current_duration = float(
                    value.split(",", 1)[0]
                )
            except Exception:
                current_duration = 10.0

        # Segment URL'si
        elif not line.startswith("#"):
            segments.append(
                (
                    current_duration,
                    urljoin(stream_url, line)
                )
            )

    result = []

    for index, (duration, url) in enumerate(segments):
        seq = media_sequence + index
        result.append((seq, duration, url))

    return result


def read_existing_segments():
    """Mevcut dosyaları bulur."""

    result = set()

    for path in glob.glob(
        os.path.join(STREAM_DIR, "seg_*.ts")
    ):

        filename = os.path.basename(path)

        match = re.match(
            r"seg_(\d+)\.ts$",
            filename
        )

        if match:
            try:
                result.add(int(match.group(1)))
            except Exception:
                pass

    return result


def cleanup_old_segments(valid_sequences):
    """
    Sadece M3U8 listesinde artık bulunmayan
    eski segmentleri temizler.
    """

    files = glob.glob(
        os.path.join(STREAM_DIR, "seg_*.ts")
    )

    for path in files:

        filename = os.path.basename(path)

        match = re.match(
            r"seg_(\d+)\.ts$",
            filename
        )

        if not match:
            continue

        seq = int(match.group(1))

        if seq not in valid_sequences:
            try:
                os.remove(path)
            except Exception:
                pass


def write_playlist(segments):
    """Sadece başarıyla indirilen segmentlerle M3U8 oluşturur."""

    if not segments:
        return

    # En fazla son MAX_SEGMENTS
    segments = sorted(
        segments,
        key=lambda x: x[0]
    )[-MAX_SEGMENTS:]

    # Sadece fiziksel olarak mevcut segmentleri kullan
    valid_segments = []

    for seq, duration, url in segments:

        fpath = os.path.join(
            STREAM_DIR,
            f"seg_{seq}.ts"
        )

        if (
            os.path.exists(fpath)
            and os.path.getsize(fpath) > 0
        ):
            valid_segments.append(
                (seq, duration)
            )

    if not valid_segments:
        return

    # Target duration en uzun segmentten küçük olamaz
    max_duration = max(
        duration
        for _, duration in valid_segments
    )

    target_duration = math.ceil(max_duration)

    # Playlist önce geçici dosyaya yazılır
    temp_playlist = M3U8_FILENAME + ".tmp"

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

        # İlk gerçek sequence numarası
        f.write(
            f"#EXT-X-MEDIA-SEQUENCE:"
            f"{valid_segments[0][0]}\n"
        )

        for seq, duration in valid_segments:

            f.write(
                f"#EXTINF:{duration:.3f},\n"
            )

            f.write(
                f"{BASE_URL}"
                f"seg_{seq}.ts\n"
            )

    # Atomik değişim
    os.replace(
        temp_playlist,
        M3U8_FILENAME
    )

    # M3U8'de olmayan dosyaları temizle
    valid_sequences = {
        seq
        for seq, _ in valid_segments
    }

    cleanup_old_segments(
        valid_sequences
    )


def main():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    # 1. Gerçek yayın URL'sini al
    stream_url = get_stream_url()

    if not stream_url:
        return

    # 2. Kaynak playlisti çöz
    try:
        source_segments = parse_m3u8(
            stream_url
        )
    except Exception:
        return

    if not source_segments:
        return

    # Son MAX_SEGMENTS kadar segment kullan
    source_segments = source_segments[
        -MAX_SEGMENTS:
    ]

    # 3. Eksik segmentleri indir
    existing = read_existing_segments()

    download_list = [
        (seq, url)
        for seq, duration, url
        in source_segments
        if seq not in existing
    ]

    if download_list:

        with ThreadPoolExecutor(
            max_workers=10
        ) as executor:

            futures = [
                executor.submit(
                    download_segment,
                    seq,
                    url
                )
                for seq, url
                in download_list
            ]

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass

    # 4. Başarıyla indirilen segmentlerle
    # yeni playlist oluştur
    write_playlist(
        source_segments
    )


if __name__ == "__main__":
    main()
