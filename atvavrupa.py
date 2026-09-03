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

# Kaç saniyelik yayın geçmişi tutulacak?
# 24 saat = 86400 saniye
MAX_HISTORY_SECONDS = 86400

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
    """Kaynak M3U8 dosyasını okur."""

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
                    line.split(
                        ":",
                        1
                    )[1].split(
                        ",",
                        1
                    )[0]
                )

            except (ValueError, IndexError):

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


def read_existing_playlist():
    """Önceki çalıştırmadan kalan M3U8 dosyasını okur."""

    if not os.path.exists(M3U8_FILENAME):
        return []

    try:

        with open(
            M3U8_FILENAME,
            "r",
            encoding="utf-8"
        ) as f:

            lines = [
                line.strip()
                for line in f.readlines()
                if line.strip()
            ]

        entries = []

        index = 0

        while index < len(lines):

            line = lines[index]

            if line.startswith("#EXTINF:"):

                try:

                    duration = float(
                        line.split(
                            ":",
                            1
                        )[1].split(
                            ",",
                            1
                        )[0]
                    )

                except (ValueError, IndexError):

                    index += 1
                    continue

                if index + 1 < len(lines):

                    segment_url = lines[index + 1]

                    filename = os.path.basename(
                        segment_url.split("?")[0]
                    )

                    if filename:

                        entries.append(
                            {
                                "duration": duration,
                                "filename": filename
                            }
                        )

                    index += 1

            index += 1

        return entries

    except Exception as error:

        print(
            f"Eski M3U8 okunamadı: {error}"
        )

        return []


def download_segment(item):
    """Tek bir segmenti indirir."""

    filename, url = item

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    # Dosya zaten varsa tekrar indirme
    if os.path.exists(filepath):
        return filename

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=60
        )

        response.raise_for_status()

        temp_path = filepath + ".tmp"

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


def keep_last_24_hours(entries):
    """Toplam segment süresi 24 saati geçerse en eskileri siler."""

    total_duration = sum(
        entry["duration"]
        for entry in entries
    )

    while (
        entries
        and total_duration > MAX_HISTORY_SECONDS
    ):

        old_entry = entries.pop(0)

        total_duration -= (
            old_entry["duration"]
        )

        old_filepath = os.path.join(
            STREAM_DIR,
            old_entry["filename"]
        )

        try:

            if os.path.exists(old_filepath):

                os.remove(
                    old_filepath
                )

        except OSError:
            pass

    return entries


def clean_unused_segments(entries):
    """M3U8 listesinde olmayan gereksiz segmentleri siler."""

    current_files = {
        entry["filename"]
        for entry in entries
    }

    existing_files = glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*"
        )
    )

    for filepath in existing_files:

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

        old_entries = read_existing_playlist()

        print(
            f"Önceki kayıtlı segment: "
            f"{len(old_entries)}"
        )

        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            f"Canlı yayın bulundu:\n"
            f"{stream_url}"
        )

        playlist = get_playlist(
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

        segments = (
            playlist["segments"]
        )

        print(
            f"Yeni segment sayısı: "
            f"{len(segments)}"
        )

        files_to_download = []
        new_entries = []

        for index, segment in enumerate(segments):

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

            new_entries.append(
                {
                    "duration": segment[
                        "duration"
                    ],
                    "filename": filename,
                    "sequence": sequence_number
                }
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

        combined_entries = []
        existing_filenames = set()

        for entry in old_entries:

            filename = entry["filename"]

            filepath = os.path.join(
                STREAM_DIR,
                filename
            )

            if (
                filename not in existing_filenames
                and os.path.exists(filepath)
            ):

                combined_entries.append(
                    entry
                )

                existing_filenames.add(
                    filename
                )

        for entry in new_entries:

            filename = entry["filename"]

            if (
                filename in successful_files
                and filename not in existing_filenames
            ):

                combined_entries.append(
                    {
                        "duration": entry[
                            "duration"
                        ],
                        "filename": filename
                    }
                )

                existing_filenames.add(
                    filename
                )

        if not combined_entries:

            print(
                "Geçerli segment bulunamadı."
            )

            return

        combined_entries = (
            keep_last_24_hours(
                combined_entries
            )
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

            first_sequence = 0

            if combined_entries:

                try:

                    first_filename = (
                        combined_entries[0]
                        ["filename"]
                    )

                    first_sequence = int(
                        first_filename
                        .replace(
                            "seg_",
                            ""
                        )
                        .replace(
                            ".ts",
                            ""
                        )
                    )

                except ValueError:
                    pass

            f.write(
                f"#EXT-X-MEDIA-SEQUENCE:"
                f"{first_sequence}\n"
            )

            for entry in combined_entries:

                f.write(
                    f"#EXTINF:"
                    f"{entry['duration']:.3f},\n"
                )

                f.write(
                    f"{BASE_URL}{entry['filename']}\n"
                )

        clean_unused_segments(
            combined_entries
        )

        total_seconds = sum(
            entry["duration"]
            for entry in combined_entries
        )

        total_hours = (
            total_seconds / 3600
        )

        print("\nBaşarılı!")

        print(
            f"Toplam segment: "
            f"{len(combined_entries)}"
        )

        print(
            f"Yayın geçmişi: "
            f"{total_hours:.2f} saat"
        )

    except Exception as error:

        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
