import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

BASE_URL = (
    "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"
)

MAX_SEGMENTS = 500

# 4K çıktı çözünürlüğü
OUTPUT_WIDTH = 3840
OUTPUT_HEIGHT = 2160

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_stream_url():
    """Kaynağın sunduğu en yüksek yayın kalitesini bulur."""

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


def get_playlist(stream_url):
    """Kaynak M3U8 listesini ve segment bilgilerini alır."""

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
                duration = (
                    line.split(":", 1)[1]
                    .split(",", 1)[0]
                )
            except IndexError:
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

    if not segments:
        return None

    if len(segments) > MAX_SEGMENTS:

        removed = (
            len(segments) - MAX_SEGMENTS
        )

        segments = segments[-MAX_SEGMENTS:]
        media_sequence += removed

    return {
        "media_sequence": media_sequence,
        "target_duration": target_duration,
        "segments": segments
    }


def upscale_segment(item):
    """
    Segmenti indirir ve FFmpeg ile 4K çözünürlüğe
    upscale ederek yeniden kodlar.

    Lanczos ölçekleme ve hafif keskinleştirme kullanılır.
    """

    filename, url = item

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(filepath):
        return filename

    source_path = filepath + ".source.ts"
    temp_path = filepath + ".tmp.ts"

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        with open(source_path, "wb") as f:
            f.write(response.content)

        # Önce GPU destekli NVIDIA kodlama denenir.
        ffmpeg_command = [
            "ffmpeg",
            "-y",
            "-i", source_path,

            "-vf",
            (
                f"scale={OUTPUT_WIDTH}:"
                f"{OUTPUT_HEIGHT}:"
                "flags=lanczos,"
                "unsharp=5:5:0.7:5:5:0"
            ),

            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",

            "-c:a", "aac",
            "-b:a", "192k",

            "-f", "mpegts",
            temp_path
        ]

        result = subprocess.run(
            ffmpeg_command,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:

            print(
                f"FFmpeg hatası ({filename}):"
            )

            print(result.stderr[-1000:])

            if os.path.exists(temp_path):
                os.remove(temp_path)

            return None

        os.replace(
            temp_path,
            filepath
        )

        if os.path.exists(source_path):
            os.remove(source_path)

        print(
            f"4K işlendi: {filename}"
        )

        return filename

    except Exception as error:

        print(
            f"Segment işlenemedi: "
            f"{filename} -> {error}"
        )

        return None

    finally:

        if os.path.exists(source_path):
            try:
                os.remove(source_path)
            except OSError:
                pass

        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def clean_old_segments(current_files):
    """Eski ve kullanılmayan segmentleri temizler."""

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

        # 1. En yüksek mevcut kaynak kalitesini bul
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            "Kaynak yayın bulundu:"
        )

        print(stream_url)

        # 2. M3U8 listesini al
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
            f"İşlenecek segment: "
            f"{len(segments)}"
        )

        # 3. Segment isimlerini oluştur
        files_to_process = []

        for index, segment in enumerate(
            segments
        ):

            sequence_number = (
                media_sequence + index
            )

            filename = (
                f"seg_{sequence_number}.ts"
            )

            files_to_process.append(
                (
                    filename,
                    segment["url"]
                )
            )

        # 4. Segmentleri paralel olarak 4K işle
        #
        # 4K yeniden kodlama çok fazla CPU kullandığı için
        # aynı anda 2 işlem kullanılır.
        with ThreadPoolExecutor(
            max_workers=2
        ) as executor:

            results = list(
                executor.map(
                    upscale_segment,
                    files_to_process
                )
            )

        successful_files = {
            filename
            for filename in results
            if filename is not None
        }

        if not successful_files:

            print(
                "Hiçbir segment "
                "işlenemedi."
            )

            return

        # 5. Başarılı segmentleri M3U8 listesine ekle
        playlist_entries = []

        for index, segment in enumerate(
            segments
        ):

            sequence_number = (
                media_sequence + index
            )

            filename = (
                f"seg_{sequence_number}.ts"
            )

            if filename in successful_files:

                playlist_entries.append(
                    {
                        "sequence":
                            sequence_number,

                        "duration":
                            segment["duration"],

                        "filename":
                            filename
                    }
                )

        if not playlist_entries:

            print(
                "Geçerli segment yok."
            )

            return

        first_sequence = (
            playlist_entries[0]["sequence"]
        )

        # 6. Yeni M3U8 dosyasını oluştur
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

        # 7. Eski segmentleri temizle
        current_files = {
            entry["filename"]
            for entry in playlist_entries
        }

        clean_old_segments(
            current_files
        )

        print(
            f"\nTamamlandı!"
        )

        print(
            f"4K olarak işlenen "
            f"segment sayısı: "
            f"{len(playlist_entries)}"
        )

        print(
            f"Çözünürlük: "
            f"{OUTPUT_WIDTH}x"
            f"{OUTPUT_HEIGHT}"
        )

    except Exception as error:

        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
