import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

# GitHub RAW dosya adresleri
BASE_URL = (
    "https://raw.githubusercontent.com/"
    "ardifyxmotion/iptv-kanal/main/streams/"
)

REMOTE_PLAYLIST_URL = (
    BASE_URL + "atvavrupa.m3u8"
)

# DVR'da tutulacak maksimum segment sayısı
# Segment süresine göre yaklaşık birkaç saatlik geçmiş sağlar.
MAX_SEGMENTS = 5000

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


def get_source_playlist(stream_url):
    """Kaynak M3U8 dosyasını okur."""

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
                duration = line.split(
                    ":",
                    1
                )[1].split(
                    ",",
                    1
                )[0]

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
        "media_sequence": media_sequence,
        "target_duration": target_duration,
        "segments": segments
    }


def get_old_playlist():
    """
    GitHub üzerindeki önceki M3U8 dosyasını okur.

    Böylece GitHub Actions her çalıştığında
    DVR geçmişi sıfırlanmaz.
    """

    old_segments = []

    try:

        response = requests.get(
            REMOTE_PLAYLIST_URL,
            headers=HEADERS,
            timeout=30
        )

        if response.status_code != 200:

            print(
                "Eski M3U8 bulunamadı. "
                "Yeni liste oluşturulacak."
            )

            return old_segments

        lines = [
            line.strip()
            for line in response.text.splitlines()
            if line.strip()
        ]

        index = 0

        while index < len(lines):

            line = lines[index]

            if line.startswith("#EXTINF:"):

                try:

                    duration = line.split(
                        ":",
                        1
                    )[1].split(
                        ",",
                        1
                    )[0]

                except (IndexError, ValueError):

                    index += 1
                    continue

                if index + 1 < len(lines):

                    segment_url = lines[index + 1]

                    if not segment_url.startswith("#"):

                        filename = (
                            segment_url
                            .split("?")[0]
                            .rstrip("/")
                            .split("/")[-1]
                        )

                        old_segments.append(
                            {
                                "duration": duration,
                                "filename": filename
                            }
                        )

                        index += 1

            index += 1

        print(
            f"Eski DVR geçmişi bulundu: "
            f"{len(old_segments)} segment"
        )

        return old_segments

    except Exception as error:

        print(
            f"Eski M3U8 okunamadı: {error}"
        )

        return old_segments


def download_segment(item):
    """Tek bir segmenti indirir."""

    filename, url = item

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    # Dosya zaten varsa tekrar indirme.
    if os.path.exists(filepath):

        return filename

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        temp_path = (
            filepath + ".tmp"
        )

        with open(
            temp_path,
            "wb"
        ) as f:

            f.write(
                response.content
            )

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


def clean_old_segments(current_files):
    """
    M3U8 içerisinde olmayan çok eski
    segmentleri siler.
    """

    existing_files = glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*.ts"
        )
    )

    for filepath in existing_files:

        filename = os.path.basename(
            filepath
        )

        if filename not in current_files:

            try:

                os.remove(
                    filepath
                )

            except OSError:

                pass


def main():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    try:

        # 1. Eski DVR geçmişini al
        old_segments = get_old_playlist()

        # Eski segmentleri sözlükte tut
        segment_map = {}

        for segment in old_segments:

            segment_map[
                segment["filename"]
            ] = segment

        # 2. Gerçek canlı yayın adresini bul
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            f"Canlı yayın bulundu:\n"
            f"{stream_url}"
        )

        # 3. Güncel kaynak M3U8'i al
        playlist = get_source_playlist(
            stream_url
        )

        if not playlist:

            print(
                "M3U8 içerisinde "
                "segment bulunamadı."
            )

            return

        media_sequence = (
            playlist["media_sequence"]
        )

        target_duration = (
            playlist["target_duration"]
        )

        source_segments = (
            playlist["segments"]
        )

        print(
            f"Yeni kaynak segmentleri: "
            f"{len(source_segments)}"
        )

        # 4. Yeni segmentlere sıra numarası ver
        files_to_download = []
        new_segment_info = []

        for index, segment in enumerate(
            source_segments
        ):

            sequence_number = (
                media_sequence + index
            )

            filename = (
                f"seg_{sequence_number}.ts"
            )

            files_to_download.append(
                (
                    filename,
                    segment["url"]
                )
            )

            new_segment_info.append(
                {
                    "sequence": sequence_number,
                    "duration": segment[
                        "duration"
                    ],
                    "filename": filename
                }
            )

        # 5. Segmentleri paralel indir
        with ThreadPoolExecutor(
            max_workers=10
        ) as executor:

            download_results = list(
                executor.map(
                    download_segment,
                    files_to_download
                )
            )

        successful_files = {

            filename

            for filename in download_results

            if filename is not None
        }

        print(
            f"Başarıyla indirilen/kontrol edilen: "
            f"{len(successful_files)}"
        )

        # 6. Başarılı yeni segmentleri
        # eski DVR listesine ekle
        for segment in new_segment_info:

            filename = segment[
                "filename"
            ]

            if filename in successful_files:

                segment_map[filename] = {
                    "duration": segment[
                        "duration"
                    ],
                    "filename": filename
                }

        # 7. Segmentleri sıra numarasına göre sırala
        def get_sequence(segment):

            try:

                filename = segment[
                    "filename"
                ]

                return int(
                    filename
                    .replace("seg_", "")
                    .replace(".ts", "")
                )

            except ValueError:

                return 0

        playlist_entries = sorted(
            segment_map.values(),
            key=get_sequence
        )

        # 8. Çok fazla segment varsa
        # sadece en yeni MAX_SEGMENTS kadarını tut
        if len(playlist_entries) > MAX_SEGMENTS:

            playlist_entries = (
                playlist_entries[
                    -MAX_SEGMENTS:
                ]
            )

        if not playlist_entries:

            print(
                "M3U8 için geçerli "
                "segment yok."
            )

            return

        # İlk segmentin gerçek sıra numarası
        first_sequence = get_sequence(
            playlist_entries[0]
        )

        # 9. Yeni DVR M3U8 oluştur
        with open(
            M3U8_FILENAME,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                "#EXTM3U\n"
            )

            f.write(
                "#EXT-X-VERSION:3\n"
            )

            f.write(
                f"#EXT-X-TARGETDURATION:"
                f"{target_duration}\n"
            )

            f.write(
                f"#EXT-X-MEDIA-SEQUENCE:"
                f"{first_sequence}\n"
            )

            for entry in playlist_entries:

                f.write(
                    f"#EXTINF:"
                    f"{entry['duration']},\n"
                )

                f.write(
                    f"{BASE_URL}"
                    f"{entry['filename']}\n"
                )

        # 10. Artık M3U8'de olmayan
        # çok eski segmentleri temizle
        current_files = {

            entry["filename"]

            for entry in playlist_entries
        }

        clean_old_segments(
            current_files
        )

        print(
            f"\nDVR başarıyla güncellendi."
        )

        print(
            f"Toplam segment: "
            f"{len(playlist_entries)}"
        )

        print(
            f"MEDIA-SEQUENCE: "
            f"{first_sequence}"
        )

    except Exception as error:

        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
