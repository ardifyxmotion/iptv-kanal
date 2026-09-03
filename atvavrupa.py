import os
import re
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILENAME = os.path.join(STREAM_DIR, "atvavrupa_state.txt")
HISTORY_FILENAME = os.path.join(STREAM_DIR, "atvavrupa_urls.txt")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

# Tutulacak maksimum segment sayısı
MAX_SEGMENTS = 1000

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
    """Kaynak M3U8 listesini URL ve EXTINF bilgileriyle okur."""

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

    target_duration = 10
    segments = []
    current_duration = None

    for line in lines:

        if line.startswith("#EXT-X-TARGETDURATION:"):

            try:
                target_duration = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

        elif line.startswith("#EXTINF:"):

            try:
                current_duration = (
                    line
                    .split(":", 1)[1]
                    .split(",", 1)[0]
                )
            except (IndexError, ValueError):
                current_duration = None

        elif (
            current_duration is not None
            and not line.startswith("#")
        ):

            segment_url = urljoin(
                stream_url,
                line
            )

            segments.append(
                {
                    "duration": current_duration,
                    "url": segment_url
                }
            )

            current_duration = None

    if not segments:
        return None

    return {
        "target_duration": target_duration,
        "segments": segments
    }


def read_old_playlist():
    """Mevcut M3U8 geçmişini okur."""

    if not os.path.exists(M3U8_FILENAME):
        return []

    entries = []
    current_duration = None

    try:

        with open(
            M3U8_FILENAME,
            "r",
            encoding="utf-8"
        ) as f:

            for raw_line in f:

                line = raw_line.strip()

                if not line:
                    continue

                if line.startswith("#EXTINF:"):

                    try:
                        current_duration = (
                            line
                            .split(":", 1)[1]
                            .split(",", 1)[0]
                        )
                    except (IndexError, ValueError):
                        current_duration = None

                elif (
                    current_duration is not None
                    and not line.startswith("#")
                ):

                    filename = line.split("/")[-1]

                    match = re.match(
                        r"seg_(\d+)\.ts$",
                        filename
                    )

                    if match:

                        filepath = os.path.join(
                            STREAM_DIR,
                            filename
                        )

                        if os.path.exists(filepath):

                            entries.append(
                                {
                                    "sequence": int(
                                        match.group(1)
                                    ),
                                    "duration": current_duration,
                                    "filename": filename
                                }
                            )

                    current_duration = None

    except Exception as error:

        print(
            f"Eski playlist okunamadı: "
            f"{error}"
        )

        return []

    return sorted(
        entries,
        key=lambda x: x["sequence"]
    )


def read_downloaded_urls():
    """Daha önce indirilen kaynak segment URL'lerini okur."""

    if not os.path.exists(HISTORY_FILENAME):
        return set()

    try:

        with open(
            HISTORY_FILENAME,
            "r",
            encoding="utf-8"
        ) as f:

            return {
                line.strip()
                for line in f
                if line.strip()
            }

    except Exception as error:

        print(
            f"URL geçmişi okunamadı: "
            f"{error}"
        )

        return set()


def save_downloaded_urls(urls):
    """URL geçmişini kaydeder."""

    temp_file = (
        HISTORY_FILENAME + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        for url in urls:
            f.write(f"{url}\n")

    os.replace(
        temp_file,
        HISTORY_FILENAME
    )


def get_highest_sequence(entries):
    """Mevcut en büyük yerel segment numarasını bulur."""

    highest = 0

    for entry in entries:

        highest = max(
            highest,
            entry["sequence"]
        )

    for filepath in glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*.ts"
        )
    ):

        filename = os.path.basename(
            filepath
        )

        match = re.match(
            r"seg_(\d+)\.ts$",
            filename
        )

        if match:

            highest = max(
                highest,
                int(match.group(1))
            )

    return highest


def download_segment(item):
    """Tek bir segmenti indirir."""

    filename, url = item

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(filepath):
        return filename

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        if not response.content:
            return None

        temp_path = (
            filepath + ".tmp"
        )

        with open(
            temp_path,
            "wb"
        ) as f:

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


def clean_old_segments(current_files):
    """Playlist dışında kalan eski segmentleri siler."""

    for filepath in glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*.ts"
        )
    ):

        filename = os.path.basename(
            filepath
        )

        if filename not in current_files:

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

        # Mevcut geçmişi koru
        old_entries = read_old_playlist()

        print(
            f"Mevcut geçmiş: "
            f"{len(old_entries)} segment"
        )

        # En son yerel segment numarasını bul
        last_local_sequence = (
            get_highest_sequence(
                old_entries
            )
        )

        print(
            f"Son yerel segment: "
            f"{last_local_sequence}"
        )

        # Daha önce indirilen URL'leri al
        downloaded_urls = (
            read_downloaded_urls()
        )

        # Canlı yayın adresini bul
        stream_url = get_stream_url()

        if not stream_url:
            return

        # Kaynak playlist'i oku
        playlist = get_playlist(
            stream_url
        )

        if not playlist:

            print(
                "Kaynakta segment bulunamadı."
            )

            return

        source_segments = playlist[
            "segments"
        ]

        target_duration = playlist[
            "target_duration"
        ]

        print(
            f"Kaynakta görünen segment: "
            f"{len(source_segments)}"
        )

        # Sadece daha önce görülmeyen URL'leri seç
        new_source_segments = [

            segment

            for segment in source_segments

            if segment["url"]
            not in downloaded_urls

        ]

        if not new_source_segments:

            print(
                "Yeni segment bulunamadı. "
                "Mevcut yayın korunuyor."
            )

            return

        print(
            f"Yeni segment sayısı: "
            f"{len(new_source_segments)}"
        )

        files_to_download = []
        pending_entries = []

        # Yeni segmentleri 181, 182, 183...
        # şeklinde sürekli devam ettir
        for segment in new_source_segments:

            last_local_sequence += 1

            filename = (
                f"seg_{last_local_sequence}.ts"
            )

            files_to_download.append(
                (
                    filename,
                    segment["url"]
                )
            )

            pending_entries.append(
                {
                    "sequence": (
                        last_local_sequence
                    ),
                    "duration": (
                        segment["duration"]
                    ),
                    "filename": filename,
                    "url": segment["url"]
                }
            )

        # Segmentleri indir
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

        successful_entries = [

            entry

            for entry in pending_entries

            if entry["filename"]
            in successful_files

        ]

        if not successful_entries:

            print(
                "Hiçbir yeni segment "
                "indirilemedi."
            )

            return

        # Eski geçmişe yeni segmentleri ekle
        playlist_entries = (
            old_entries +
            successful_entries
        )

        # Sıralamayı koru
        playlist_entries = sorted(
            playlist_entries,
            key=lambda x: x["sequence"]
        )

        # Maksimum segment sınırı
        if len(playlist_entries) > MAX_SEGMENTS:

            playlist_entries = (
                playlist_entries[-MAX_SEGMENTS:]
            )

        # M3U8'i geçici dosyada oluştur
        temp_m3u8 = (
            M3U8_FILENAME + ".tmp"
        )

        first_sequence = (
            playlist_entries[0]["sequence"]
        )

        with open(
            temp_m3u8,
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

            for entry in playlist_entries:

                f.write(
                    f"#EXTINF:"
                    f"{entry['duration']},\n"
                )

                f.write(
                    f"{BASE_URL}"
                    f"{entry['filename']}\n"
                )

        # Tamamlandıktan sonra gerçek M3U8 ile değiştir
        os.replace(
            temp_m3u8,
            M3U8_FILENAME
        )

        # Başarıyla indirilen URL'leri geçmişe ekle
        for entry in successful_entries:

            downloaded_urls.add(
                entry["url"]
            )

        # Geçmişi sınırsız büyütmemek için
        # son 5000 URL'yi tut
        if len(downloaded_urls) > 5000:

            downloaded_urls = set(
                list(downloaded_urls)[-5000:]
            )

        save_downloaded_urls(
            downloaded_urls
        )

        # Playlist dışında kalan segmentleri temizle
        current_files = {

            entry["filename"]
            for entry in playlist_entries

        }

        clean_old_segments(
            current_files
        )

        print(
            f"Toplam segment: "
            f"{len(playlist_entries)}"
        )

        print(
            f"Son segment: "
            f"seg_{playlist_entries[-1]['sequence']}.ts"
        )

    except Exception as error:

        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
