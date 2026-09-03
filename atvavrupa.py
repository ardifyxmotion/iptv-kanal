import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

# GitHub Raw adresin
BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

# Kaynak listeden tutulacak maksimum segment
MAX_SEGMENTS = 160

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def download_segment(item):
    """
    Segmenti indirir.
    item = (dosya_adi, segment_url)
    """
    filename, url = item
    filepath = os.path.join(STREAM_DIR, filename)

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )
        response.raise_for_status()

        with open(filepath, "wb") as f:
            f.write(response.content)

        return filename

    except Exception as error:
        print(f"Segment indirilemedi: {url} -> {error}")
        return None


def get_stream_url():
    """Streamlink ile gerçek yayın adresini bulur."""

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
            timeout=30
        )

        stream_url = result.stdout.strip()

        if not stream_url:
            print("Streamlink yayın URL'sini bulamadı.")
            print(result.stderr)
            return None

        return stream_url

    except Exception as error:
        print(f"Streamlink hatası: {error}")
        return None


def parse_playlist(stream_url):
    """
    Kaynak M3U8 listesini okur.
    Gerçek segment sürelerini ve MEDIA-SEQUENCE değerini korur.
    """

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

    media_sequence = 0
    target_duration = 10
    segments = []

    # Kaynak MEDIA-SEQUENCE değerini bul
    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

        elif line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

    # EXTINF + segment URL çiftlerini bul
    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("#EXTINF:"):
            duration = line.split(":", 1)[1].split(",", 1)[0]

            # Bir sonraki gerçek URL satırını bul
            next_index = index + 1

            while (
                next_index < len(lines)
                and lines[next_index].startswith("#")
            ):
                next_index += 1

            if next_index < len(lines):
                segment_url = urljoin(
                    stream_url,
                    lines[next_index]
                )

                segments.append(
                    (duration, segment_url)
                )

                index = next_index

        index += 1

    # Son MAX_SEGMENTS segmenti kullan
    if len(segments) > MAX_SEGMENTS:
        segments = segments[-MAX_SEGMENTS:]

        # MEDIA-SEQUENCE'i kesilen segment sayısına göre düzelt
        media_sequence += (
            len(lines) - len(segments)
        )

    return media_sequence, target_duration, segments


def main():
    os.makedirs(STREAM_DIR, exist_ok=True)

    try:
        # 1. Gerçek canlı yayın URL'sini bul
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(f"Yayın URL'si bulundu:\n{stream_url}")

        # 2. Kaynak M3U8 listesini oku
        (
            media_sequence,
            target_duration,
            segments
        ) = parse_playlist(stream_url)

        if not segments:
            print("Kaynak M3U8 içerisinde segment bulunamadı.")
            return

        print(
            f"{len(segments)} segment bulundu. "
            f"MEDIA-SEQUENCE: {media_sequence}"
        )

        # 3. Segmentlere benzersiz dosya adı ver
        files_to_download = []

        for index, (_, segment_url) in enumerate(segments):
            sequence_number = media_sequence + index

            filename = f"seg_{sequence_number}.ts"

            files_to_download.append(
                (filename, segment_url)
            )

        # 4. Segmentleri paralel indir
        with ThreadPoolExecutor(max_workers=10) as executor:
            downloaded_results = list(
                executor.map(
                    download_segment,
                    files_to_download
                )
            )

        # Başarıyla indirilenleri bul
        downloaded_files = set(
            filename
            for filename in downloaded_results
            if filename is not None
        )

        if not downloaded_files:
            print("Hiçbir segment indirilemedi.")
            return

        # 5. Eski segmentleri temizle
        existing_files = glob.glob(
            os.path.join(STREAM_DIR, "seg_*.ts")
        )

        for filepath in existing_files:
            filename = os.path.basename(filepath)

            if filename not in downloaded_files:
                try:
                    os.remove(filepath)
                except OSError:
                    pass

        # 6. Yeni M3U8 listesini oluştur
        # Sadece gerçekten indirilen segmentleri listeye ekle
        playlist_entries = []

        for index, (duration, _) in enumerate(segments):
            sequence_number = media_sequence + index
            filename = f"seg_{sequence_number}.ts"

            if filename in downloaded_files:
                playlist_entries.append(
                    (duration, filename)
                )

        if not playlist_entries:
            print("M3U8 için kullanılabilecek segment yok.")
            return

        # İlk segmentin gerçek MEDIA-SEQUENCE numarası
        first_filename = playlist_entries[0][1]

        first_sequence = int(
            first_filename
            .replace("seg_", "")
            .replace(".ts", "")
        )

        with open(
            M3U8_FILENAME,
            "w",
            encoding="utf-8"
        ) as f:

            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")
            f.write(
                f"#EXT-X-TARGETDURATION:"
                f"{target_duration}\n"
            )
            f.write(
                f"#EXT-X-MEDIA-SEQUENCE:"
                f"{first_sequence}\n"
            )

            for duration, filename in playlist_entries:
                f.write(
                    f"#EXTINF:{duration},\n"
                )
                f.write(
                    f"{BASE_URL}{filename}\n"
                )

        print(
            f"Başarılı: "
            f"{len(playlist_entries)} segment "
            f"M3U8 dosyasına yazıldı."
        )

    except Exception as error:
        print(f"Genel hata: {error}")


if __name__ == "__main__":
    main()
