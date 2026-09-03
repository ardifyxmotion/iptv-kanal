import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

# GitHub RAW segment adresi
BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

# Maksimum saklanacak segment sayısı
MAX_SEGMENTS = 2000

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_stream_url():
    """Streamlink ile gerçek canlı yayın M3U8 adresini bulur."""
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

        if not stream_url:
            print("Yayın URL'si bulunamadı.")
            print(result.stderr)
            return None

        return stream_url

    except Exception as error:
        print(f"Streamlink hatası: {error}")
        return None


def get_playlist(stream_url):
    """Kaynak M3U8 listesindeki segmentleri okur."""
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
                media_sequence = int(line.split(":", 1)[1])
            except ValueError:
                pass

        elif line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = int(line.split(":", 1)[1])
            except ValueError:
                pass

    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("#EXTINF:"):
            try:
                duration = line.split(":", 1)[1].split(",", 1)[0]
            except (IndexError, ValueError):
                index += 1
                continue

            next_index = index + 1

            while next_index < len(lines):
                next_line = lines[next_index]

                if not next_line.startswith("#"):
                    segment_url = urljoin(
                        stream_url,
                        next_line
                    )

                    segments.append(
                        {
                            "sequence": media_sequence + len(segments),
                            "duration": duration,
                            "url": segment_url
                        }
                    )

                    index = next_index
                    break

                next_index += 1

        index += 1

    if not segments:
        return None

    return {
        "target_duration": target_duration,
        "segments": segments
    }


def read_existing_playlist():
    """
    Eski oluşturulan M3U8 listesini okur.
    Böylece önceki GitHub Actions çalıştırmalarındaki
    segmentler korunur.
    """
    entries = []

    if not os.path.exists(M3U8_FILENAME):
        return entries

    try:
        with open(
            M3U8_FILENAME,
            "r",
            encoding="utf-8"
        ) as f:
            lines = [
                line.strip()
                for line in f
                if line.strip()
            ]

        index = 0

        while index < len(lines):
            line = lines[index]

            if line.startswith("#EXTINF:"):
                try:
                    duration = line.split(
                        ":", 1
                    )[1].split(",", 1)[0]

                    if index + 1 < len(lines):
                        url = lines[index + 1]

                        filename = url.rsplit(
                            "/",
                            1
                        )[-1]

                        if filename.startswith("seg_"):
                            try:
                                sequence = int(
                                    filename.replace(
                                        "seg_",
                                        ""
                                    ).replace(
                                        ".ts",
                                        ""
                                    )
                                )

                                entries.append(
                                    {
                                        "sequence": sequence,
                                        "duration": duration,
                                        "filename": filename
                                    }
                                )

                            except ValueError:
                                pass

                        index += 1

                except (IndexError, ValueError):
                    pass

            index += 1

    except Exception as error:
        print(
            f"Eski M3U8 okunamadı: {error}"
        )

    return entries


def download_segment(item):
    """Segmenti yalnızca gerekli olduğunda indirir."""

    filename, url = item
    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    # Dosya zaten mevcutsa tekrar indirme
    if os.path.exists(filepath):
        return filename

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=60
        )

        response.raise_for_status()

        # Çok küçük veya boş dosyaları kabul etme
        if len(response.content) < 100:
            print(
                f"Geçersiz segment: {filename}"
            )
            return None

        temp_path = filepath + ".tmp"

        with open(temp_path, "wb") as f:
            f.write(response.content)

        os.replace(
            temp_path,
            filepath
        )

        return filename

    except Exception as error:
        print(
            f"Segment indirilemedi: "
            f"{filename} -> {error}"
        )

        return None


def clean_old_segments(valid_files):
    """
    M3U8 listesinden çıkarılan çok eski segmentleri siler.
    Sadece maksimum segment sınırı aşıldığında çalışır.
    """
    existing_files = glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*.ts"
        )
    )

    for filepath in existing_files:
        filename = os.path.basename(filepath)

        if filename not in valid_files:
            try:
                os.remove(filepath)
            except OSError:
                pass


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    try:
        # 1. Önce eski playlist geçmişini oku
        old_entries = read_existing_playlist()

        print(
            f"Eski segment sayısı: "
            f"{len(old_entries)}"
        )

        # 2. Gerçek canlı yayın URL'sini bul
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            f"Canlı yayın bulundu:\n"
            f"{stream_url}"
        )

        # 3. Güncel kaynak playlist'i oku
        playlist = get_playlist(
            stream_url
        )

        if not playlist:
            print(
                "M3U8 içerisinde "
                "segment bulunamadı."
            )
            return

        target_duration = playlist[
            "target_duration"
        ]

        new_segments = playlist[
            "segments"
        ]

        print(
            f"Kaynak segment sayısı: "
            f"{len(new_segments)}"
        )

        # 4. Yeni segmentleri indir
        files_to_download = []

        for segment in new_segments:
            filename = (
                f"seg_{segment['sequence']}.ts"
            )

            files_to_download.append(
                (
                    filename,
                    segment["url"]
                )
            )

        with ThreadPoolExecutor(
            max_workers=10
        ) as executor:

            results = list(
                executor.map(
                    download_segment,
                    files_to_download
                )
            )

        successful_files = {
            filename
            for filename in results
            if filename is not None
        }

        # 5. Eski ve yeni segmentleri birleştir
        entry_map = {}

        # Önce eski segmentler
        for entry in old_entries:
            filepath = os.path.join(
                STREAM_DIR,
                entry["filename"]
            )

            # Dosya gerçekten varsa koru
            if os.path.exists(filepath):
                entry_map[
                    entry["sequence"]
                ] = entry

        # Yeni başarıyla indirilen segmentler
        for segment in new_segments:
            sequence = segment["sequence"]

            filename = (
                f"seg_{sequence}.ts"
            )

            if filename in successful_files:
                entry_map[sequence] = {
                    "sequence": sequence,
                    "duration": segment[
                        "duration"
                    ],
                    "filename": filename
                }

        # Sıralı hale getir
        all_entries = sorted(
            entry_map.values(),
            key=lambda item: item[
                "sequence"
            ]
        )

        # 6. Maksimum segment sınırı
        if len(all_entries) > MAX_SEGMENTS:
            all_entries = all_entries[
                -MAX_SEGMENTS:
            ]

        if not all_entries:
            print(
                "M3U8 için geçerli "
                "segment bulunamadı."
            )
            return

        # 7. Yeni M3U8 dosyasını oluştur
        first_sequence = all_entries[0][
            "sequence"
        ]

        temp_playlist = (
            M3U8_FILENAME + ".tmp"
        )

        with open(
            temp_playlist,
            "w",
            encoding="utf-8"
        ) as f:

            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")

            f.write(
                "#EXT-X-TARGETDURATION:"
                f"{target_duration}\n"
            )

            f.write(
                "#EXT-X-MEDIA-SEQUENCE:"
                f"{first_sequence}\n"
            )

            for entry in all_entries:
                f.write(
                    "#EXTINF:"
                    f"{entry['duration']},\n"
                )

                f.write(
                    f"{BASE_URL}"
                    f"{entry['filename']}\n"
                )

        # Geçici M3U8 başarılı şekilde yazıldıysa değiştir
        os.replace(
            temp_playlist,
            M3U8_FILENAME
        )

        # 8. Artık kullanılmayan segmentleri sil
        valid_files = {
            entry["filename"]
            for entry in all_entries
        }

        clean_old_segments(
            valid_files
        )

        print(
            f"Başarılı: "
            f"{len(all_entries)} "
            f"segment saklanıyor."
        )

        print(
            f"İlk MEDIA-SEQUENCE: "
            f"{first_sequence}"
        )

        print(
            f"Yeni indirilen segment: "
            f"{len(successful_files)}"
        )

    except Exception as error:
        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
