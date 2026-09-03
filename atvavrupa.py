import os
import glob
import hashlib
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

BASE_URL = (
    "https://raw.githubusercontent.com/"
    "ardifyxmotion/iptv-kanal/main/streams/"
)

REMOTE_PLAYLIST_URL = BASE_URL + "atvavrupa.m3u8"

MAX_SEGMENTS = 5000
MAX_WORKERS = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_stream_url():
    """Streamlink ile gerçek canlı yayın adresini bulur."""

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


def create_filename(url, sequence):
    """Segment URL'sinden benzersiz dosya adı oluşturur."""

    url_hash = hashlib.md5(
        url.encode("utf-8")
    ).hexdigest()[:12]

    return f"seg_{sequence}_{url_hash}.ts"


def get_source_playlist(stream_url):
    """Kaynak M3U8 dosyasını okur."""

    try:
        response = requests.get(
            stream_url,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

    except Exception as error:
        print(f"Kaynak M3U8 okunamadı: {error}")
        return None

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

            except Exception:
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
    """GitHub üzerindeki eski DVR listesini okur."""

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
        sequence = 0

        for line in lines:

            if line.startswith(
                "#EXT-X-MEDIA-SEQUENCE:"
            ):

                try:
                    sequence = int(
                        line.split(":", 1)[1]
                    )
                except ValueError:
                    sequence = 0

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

                except Exception:

                    index += 1
                    continue

                next_index = index + 1

                while next_index < len(lines):

                    next_line = lines[next_index]

                    if not next_line.startswith("#"):

                        filename = (
                            urlparse(
                                next_line
                            )
                            .path
                            .rstrip("/")
                            .split("/")[-1]
                        )

                        if filename:

                            old_segments.append(
                                {
                                    "sequence": sequence,
                                    "duration": duration,
                                    "filename": filename
                                }
                            )

                            sequence += 1

                        index = next_index
                        break

                    next_index += 1

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
    """Tek segmenti indirir."""

    filename = item["filename"]
    url = item["url"]

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(filepath):

        size = os.path.getsize(filepath)

        if size > 0:
            return filename

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=60,
            stream=True
        )

        response.raise_for_status()

        temp_path = filepath + ".tmp"

        with open(
            temp_path,
            "wb"
        ) as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 256
            ):

                if chunk:
                    file.write(chunk)

        if (
            not os.path.exists(temp_path)
            or os.path.getsize(temp_path) == 0
        ):

            if os.path.exists(temp_path):
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

        try:

            if os.path.exists(
                filepath + ".tmp"
            ):
                os.remove(
                    filepath + ".tmp"
                )

        except OSError:
            pass

        return None


def clean_old_segments(current_files):
    """M3U8 içerisinde olmayan eski segmentleri siler."""

    existing_files = glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*"
        )
    )

    for filepath in existing_files:

        if filepath.endswith(".tmp"):
            continue

        filename = os.path.basename(
            filepath
        )

        if filename not in current_files:

            try:
                os.remove(filepath)

            except OSError:
                pass


def get_sort_value(segment):
    """Segment sıra numarasını döndürür."""

    try:

        filename = segment["filename"]

        if filename.startswith("seg_"):

            parts = filename.split("_")

            return int(parts[1])

    except Exception:
        pass

    return 0


def main():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    try:

        old_segments = get_old_playlist()

        segment_map = {}

        for segment in old_segments:

            filename = segment["filename"]

            filepath = os.path.join(
                STREAM_DIR,
                filename
            )

            if os.path.exists(filepath):

                if os.path.getsize(filepath) > 0:

                    segment_map[
                        filename
                    ] = segment

        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            f"Canlı yayın bulundu:\n"
            f"{stream_url}"
        )

        playlist = get_source_playlist(
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

        source_segments = (
            playlist["segments"]
        )

        print(
            f"Kaynak segment sayısı: "
            f"{len(source_segments)}"
        )

        files_to_download = []
        new_segments = []

        for index, segment in enumerate(
            source_segments
        ):

            sequence_number = (
                media_sequence + index
            )

            filename = create_filename(
                segment["url"],
                sequence_number
            )

            item = {
                "sequence": sequence_number,
                "duration": segment[
                    "duration"
                ],
                "filename": filename,
                "url": segment["url"]
            }

            files_to_download.append(item)
            new_segments.append(item)

        successful_files = set()

        with ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        ) as executor:

            futures = {

                executor.submit(
                    download_segment,
                    item
                ): item

                for item in files_to_download
            }

            for future in as_completed(
                futures
            ):

                try:

                    result = future.result()

                    if result:

                        successful_files.add(
                            result
                        )

                except Exception as error:

                    print(
                        f"İndirme görevi hatası: "
                        f"{error}"
                    )

        print(
            f"Başarılı segment sayısı: "
            f"{len(successful_files)}"
        )

        for segment in new_segments:

            filename = segment["filename"]

            filepath = os.path.join(
                STREAM_DIR,
                filename
            )

            if (
                filename in successful_files
                and os.path.exists(filepath)
                and os.path.getsize(filepath) > 0
            ):

                segment_map[filename] = {
                    "sequence": segment[
                        "sequence"
                    ],
                    "duration": segment[
                        "duration"
                    ],
                    "filename": filename
                }

        playlist_entries = sorted(
            segment_map.values(),
            key=get_sort_value
        )

        if len(playlist_entries) > MAX_SEGMENTS:

            playlist_entries = (
                playlist_entries[
                    -MAX_SEGMENTS:
                ]
            )

        if not playlist_entries:

            print(
                "M3U8 oluşturmak için segment yok."
            )

            return

        first_sequence = get_sort_value(
            playlist_entries[0]
        )

        with open(
            M3U8_FILENAME,
            "w",
            encoding="utf-8"
        ) as file:

            file.write("#EXTM3U\n")

            file.write(
                "#EXT-X-VERSION:3\n"
            )

            file.write(
                f"#EXT-X-TARGETDURATION:"
                f"{target_duration}\n"
            )

            file.write(
                f"#EXT-X-MEDIA-SEQUENCE:"
                f"{first_sequence}\n"
            )

            valid_count = 0

            for entry in playlist_entries:

                filename = entry[
                    "filename"
                ]

                filepath = os.path.join(
                    STREAM_DIR,
                    filename
                )

                if (
                    not os.path.exists(filepath)
                    or os.path.getsize(filepath) == 0
                ):
                    continue

                file.write(
                    f"#EXTINF:"
                    f"{entry['duration']},\n"
                )

                file.write(
                    f"{BASE_URL}"
                    f"{filename}\n"
                )

                valid_count += 1

        current_files = {

            entry["filename"]

            for entry in playlist_entries
        }

        clean_old_segments(
            current_files
        )

        print("\nDVR güncellendi.")

        print(
            f"Geçerli toplam segment: "
            f"{valid_count}"
        )

        print(
            f"İlk sequence: "
            f"{first_sequence}"
        )

    except Exception as error:

        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
