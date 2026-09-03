import os
import json
import time
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
INDEX_FILE = os.path.join(STREAM_DIR, "segments.json")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

# 23 saat = 82.800 saniye
MAX_ARCHIVE_SECONDS = 23 * 60 * 60

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def load_index():
    """Daha önce kaydedilen segment bilgilerini yükler."""

    if not os.path.exists(INDEX_FILE):
        return []

    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception as error:
        print(f"Segment kaydı okunamadı: {error}")

    return []


def save_index(segments):
    """Segment kayıtlarını kaydeder."""

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(
            segments,
            f,
            ensure_ascii=False,
            indent=2
        )


def get_stream_url():
    """Streamlink ile gerçek canlı yayın URL'sini alır."""

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
            print("Yayın URL'si bulunamadı.")
            print(result.stderr)
            return None

        return stream_url

    except Exception as error:
        print(f"Streamlink hatası: {error}")
        return None


def parse_playlist(stream_url):
    """
    Kaynak M3U8 listesini okur ve:
    - MEDIA-SEQUENCE
    - TARGETDURATION
    - gerçek EXTINF süreleri
    - segment URL'leri
    bilgilerini döndürür.
    """

    response = requests.get(
        stream_url,
        headers=HEADERS,
        timeout=30
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

    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("#EXTINF:"):
            try:
                duration = float(
                    line.split(":", 1)[1]
                    .split(",", 1)[0]
                )
            except (IndexError, ValueError):
                index += 1
                continue

            next_index = index + 1

            while next_index < len(lines):
                next_line = lines[next_index]

                if not next_line.startswith("#"):
                    segments.append(
                        {
                            "duration": duration,
                            "url": urljoin(
                                stream_url,
                                next_line
                            )
                        }
                    )

                    index = next_index
                    break

                next_index += 1

        index += 1

    # Her segmente kaynak sıra numarasını ekle
    for index, segment in enumerate(segments):
        segment["sequence"] = (
            media_sequence + index
        )

    return target_duration, segments


def download_segment(segment):
    """Yeni segmenti indirir."""

    filename = (
        f"seg_{segment['sequence']}.ts"
    )

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    # Aynı segment daha önce indirildiyse tekrar indirme
    if os.path.exists(filepath):
        return {
            "filename": filename,
            "sequence": segment["sequence"],
            "duration": segment["duration"],
            "saved_at": time.time()
        }

    try:
        response = requests.get(
            segment["url"],
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        temp_path = filepath + ".tmp"

        with open(temp_path, "wb") as f:
            f.write(response.content)

        os.replace(
            temp_path,
            filepath
        )

        print(f"İndirildi: {filename}")

        return {
            "filename": filename,
            "sequence": segment["sequence"],
            "duration": segment["duration"],
            "saved_at": time.time()
        }

    except Exception as error:
        print(
            f"Segment indirilemedi "
            f"({filename}): {error}"
        )

        return None


def remove_old_segments(archive):
    """
    Toplam segment süresi 23 saati aşarsa
    en eski segmentleri siler.
    """

    # Sıralamayı sıra numarasına göre yap
    archive.sort(
        key=lambda item: item["sequence"]
    )

    total_duration = sum(
        item["duration"]
        for item in archive
    )

    while (
        archive
        and total_duration > MAX_ARCHIVE_SECONDS
    ):
        oldest = archive.pop(0)

        filepath = os.path.join(
            STREAM_DIR,
            oldest["filename"]
        )

        try:
            if os.path.exists(filepath):
                os.remove(filepath)

                print(
                    f"Eski segment silindi: "
                    f"{oldest['filename']}"
                )

        except OSError:
            pass

        total_duration -= oldest["duration"]

    return archive


def write_playlist(
    archive,
    target_duration
):
    """23 saatlik kayan M3U8 listesini oluşturur."""

    if not archive:
        return

    archive.sort(
        key=lambda item: item["sequence"]
    )

    first_sequence = (
        archive[0]["sequence"]
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

        for segment in archive:
            f.write(
                f"#EXTINF:"
                f"{segment['duration']:.3f},\n"
            )

            f.write(
                f"{BASE_URL}"
                f"{segment['filename']}\n"
            )


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    try:
        # 1. Eski 23 saatlik arşivi yükle
        archive = load_index()

        # Aynı sequence numarasının tekrar eklenmesini engelle
        known_sequences = {
            item["sequence"]
            for item in archive
        }

        # 2. Canlı yayın URL'sini al
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            f"Canlı yayın bulundu:\n"
            f"{stream_url}"
        )

        # 3. Kaynak M3U8 listesini oku
        (
            target_duration,
            source_segments
        ) = parse_playlist(stream_url)

        if not source_segments:
            print(
                "Kaynak listede segment bulunamadı."
            )
            return

        # 4. Sadece daha önce kaydedilmemiş segmentleri bul
        new_segments = [
            segment
            for segment in source_segments
            if segment["sequence"]
            not in known_sequences
        ]

        print(
            f"Kaynak segment: "
            f"{len(source_segments)}"
        )

        print(
            f"Yeni segment: "
            f"{len(new_segments)}"
        )

        # 5. Yeni segmentleri paralel indir
        if new_segments:
            with ThreadPoolExecutor(
                max_workers=10
            ) as executor:

                results = list(
                    executor.map(
                        download_segment,
                        new_segments
                    )
                )

            for result in results:
                if result is not None:
                    archive.append(result)

        # 6. Arşivi 23 saatle sınırla
        archive = remove_old_segments(
            archive
        )

        # 7. Arşiv kaydını güncelle
        save_index(archive)

        # 8. Yeni M3U8 dosyasını oluştur
        write_playlist(
            archive,
            target_duration
        )

        total_seconds = sum(
            item["duration"]
            for item in archive
        )

        print(
            f"\nToplam segment: "
            f"{len(archive)}"
        )

        print(
            f"Toplam yayın süresi: "
            f"{total_seconds / 3600:.2f} saat"
        )

    except Exception as error:
        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
