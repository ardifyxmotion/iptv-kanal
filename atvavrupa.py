import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

BASE_URL = (
    "https://raw.githubusercontent.com/"
    "ardifyxmotion/iptv-kanal/main/streams/"
)

MAX_SEGMENTS = 500

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_stream_url():
    """
    Streamlink ile mevcut en yüksek kaliteli
    canlı yayın M3U8 adresini bulur.
    """

    try:
        quality_result = subprocess.run(
            [
                "streamlink",
                "https://www.atvavrupa.tv/canli-yayin"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        print("Bulunan yayın kaliteleri:")
        print(
            quality_result.stdout
            or quality_result.stderr
        )

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


def get_playlist(stream_url):
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
                duration = (
                    line
                    .split(":", 1)[1]
                    .split(",", 1)[0]
                )
            except IndexError:
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

    if len(segments) > MAX_SEGMENTS:

        removed_segments = (
            len(segments)
            - MAX_SEGMENTS
        )

        segments = segments[-MAX_SEGMENTS:]

        media_sequence += removed_segments

    return {
        "media_sequence": media_sequence,
        "target_duration": target_duration,
        "segments": segments
    }


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

        temp_path = filepath + ".tmp"

        with open(temp_path, "wb") as f:
            f.write(response.content)

        os.replace(temp_path, filepath)

        return filename

    except Exception as error:

        print(
            f"Segment indirilemedi: "
            f"{filename} -> {error}"
        )

        return None


def clean_old_segments(current_files):
    """M3U8 listesinde olmayan eski segmentleri siler."""

    existing_files = glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*"
        )
    )

    for filepath in existing_files:

        filename = os.path.basename(filepath)

        if (
            filename.endswith(".ts")
            and filename not in current_files
        ):

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

        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            f"\nSeçilen en yüksek kalite "
            f"yayın adresi:\n{stream_url}"
        )

        playlist = get_playlist(stream_url)

        if not playlist:

            print(
                "M3U8 içerisinde "
                "segment bulunamadı."
            )

            return

        media_sequence = playlist["media_sequence"]
        target_duration = playlist["target_duration"]
        segments = playlist["segments"]

        print(
            f"Segment sayısı: "
            f"{len(segments)} | "
            f"MEDIA-SEQUENCE: "
            f"{media_sequence}"
        )

        files_to_download = []

        for index, segment in enumerate(segments):

            sequence_number = media_sequence + index

            filename = (
                f"seg_{sequence_number}.ts"
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

        if not successful_files:

            print(
                "Hiçbir segment "
                "indirilemedi."
            )

            return

        playlist_entries = []

        for index, segment in enumerate(segments):

            sequence_number = media_sequence + index

            filename = (
                f"seg_{sequence_number}.ts"
            )

            if filename in successful_files:

                playlist_entries.append(
                    {
                        "sequence": sequence_number,
                        "duration": segment["duration"],
                        "filename": filename
                    }
                )

        if not playlist_entries:

            print(
                "M3U8 için geçerli "
                "segment yok."
            )

            return

        first_sequence = (
            playlist_entries[0]["sequence"]
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

            for entry in playlist_entries:

                f.write(
                    f"#EXTINF:"
                    f"{entry['duration']},\n"
                )

                f.write(
                    f"{BASE_URL}"
                    f"{entry['filename']}\n"
                )

        current_files = {
            entry["filename"]
            for entry in playlist_entries
        }

        clean_old_segments(current_files)

        print(
            f"\nBaşarılı: "
            f"{len(playlist_entries)} "
            f"segment yazıldı."
        )

        print(
            f"MEDIA-SEQUENCE: "
            f"{first_sequence}"
        )

        print(
            "\nKullanılan kalite: "
            "Kaynağın sunduğu en yüksek kalite"
        )

    except Exception as error:

        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
