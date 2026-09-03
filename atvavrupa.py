import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

MAX_SEGMENTS = 2500

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
                duration = line.split(
                    ":", 1
                )[1].split(",", 1)[0]
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


def download_segment(item):
    """Eksik segmenti indirir."""

    filename, url = item

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(filepath):

        if os.path.getsize(filepath) > 0:
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

            f.write(response.content)

        if os.path.getsize(temp_path) == 0:

            os.remove(temp_path)

            return None

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


def read_existing_playlist():
    """
    Mevcut M3U8 dosyasındaki segmentleri okur.
    Böylece geçmiş her çalıştırmada kaybolmaz.
    """

    entries = []

    if not os.path.exists(
        M3U8_FILENAME
    ):
        return entries

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

        duration = None

        for line in lines:

            if line.startswith("#EXTINF:"):

                try:
                    duration = line.split(
                        ":",
                        1
                    )[1].split(
                        ",",
                        1
                    )[0]

                except Exception:
                    duration = None

            elif (
                line.startswith(BASE_URL)
                and duration is not None
            ):

                filename = line.replace(
                    BASE_URL,
                    ""
                ).strip()

                if (
                    filename.startswith("seg_")
                    and filename.endswith(".ts")
                ):

                    try:

                        sequence = int(
                            filename
                            .replace("seg_", "")
                            .replace(".ts", "")
                        )

                        filepath = os.path.join(
                            STREAM_DIR,
                            filename
                        )

                        if (
                            os.path.exists(filepath)
                            and os.path.getsize(filepath) > 0
                        ):

                            entries.append(
                                {
                                    "sequence": sequence,
                                    "duration": duration,
                                    "filename": filename
                                }
                            )

                    except ValueError:
                        pass

                duration = None

    except Exception as error:

        print(
            f"Eski M3U8 okunamadı: "
            f"{error}"
        )

    return entries


def clean_old_segments(current_files):
    """
    Sadece MAX_SEGMENTS sınırını aşan
    gerçekten eski segmentleri siler.
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

                os.remove(filepath)

            except OSError:
                pass


def write_playlist(
    playlist_entries,
    target_duration
):
    """Yeni M3U8 dosyasını güvenli şekilde oluşturur."""

    if not playlist_entries:
        return

    playlist_entries.sort(
        key=lambda x: x["sequence"]
    )

    first_sequence = (
        playlist_entries[0]["sequence"]
    )

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
        f.write("#EXT-X-ALLOW-CACHE:YES\n")

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

    os.replace(
        temp_playlist,
        M3U8_FILENAME
    )


def main():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    try:

        print(
            "ATV Avrupa yayını aranıyor..."
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
                "M3U8 içerisinde segment bulunamadı."
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
            f"Yeni kaynak segment sayısı: "
            f"{len(segments)}"
        )

        old_entries = (
            read_existing_playlist()
        )

        print(
            f"Mevcut geçmiş segment sayısı: "
            f"{len(old_entries)}"
        )

        entries_by_sequence = {}

        for entry in old_entries:

            entries_by_sequence[
                entry["sequence"]
            ] = entry

        files_to_download = []
        new_entries = []

        for index, segment in enumerate(
            segments
        ):

            sequence_number = (
                media_sequence + index
            )

            filename = (
                f"seg_{sequence_number}.ts"
            )

            filepath = os.path.join(
                STREAM_DIR,
                filename
            )

            new_entries.append(
                {
                    "sequence": sequence_number,
                    "duration": segment["duration"],
                    "filename": filename
                }
            )

            if (
                not os.path.exists(filepath)
                or os.path.getsize(filepath) == 0
            ):

                files_to_download.append(
                    (
                        filename,
                        segment["url"]
                    )
                )

        if files_to_download:

            print(
                f"İndirilecek yeni segment: "
                f"{len(files_to_download)}"
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

        else:

            print(
                "Yeni indirilecek segment yok."
            )

        for entry in new_entries:

            filepath = os.path.join(
                STREAM_DIR,
                entry["filename"]
            )

            if (
                os.path.exists(filepath)
                and os.path.getsize(filepath) > 0
            ):

                entries_by_sequence[
                    entry["sequence"]
                ] = entry

        final_entries = sorted(
            entries_by_sequence.values(),
            key=lambda x: x["sequence"]
        )

        if len(final_entries) > MAX_SEGMENTS:

            final_entries = (
                final_entries[-MAX_SEGMENTS:]
            )

        if not final_entries:

            print(
                "M3U8 için geçerli segment yok."
            )

            return

        write_playlist(
            final_entries,
            target_duration
        )

        current_files = {
            entry["filename"]
            for entry in final_entries
        }

        clean_old_segments(
            current_files
        )

        print(
            f"Başarılı: "
            f"{len(final_entries)} segment "
            f"korunuyor."
        )

        print(
            f"İlk MEDIA-SEQUENCE: "
            f"{final_entries[0]['sequence']}"
        )

        print(
            f"Son MEDIA-SEQUENCE: "
            f"{final_entries[-1]['sequence']}"
        )

    except Exception as error:

        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
