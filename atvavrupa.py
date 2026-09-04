import os
import glob
import re
import time
import subprocess
import requests
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

STREAM_DIR = "streams"
PLAYLIST_FILE = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

# GitHub repository RAW adresi
BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

# Oynatıcıda tutulacak yaklaşık segment sayısı
MAX_SEGMENTS = 160

# GitHub Actions tek çalışmada yaklaşık 5 dakika takip eder.
RUN_SECONDS = 300
POLL_SECONDS = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_stream_url():
    """Streamlink ile güncel HLS adresini bulur."""
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

    url = result.stdout.strip()

    if not url:
        raise RuntimeError(
            "Streamlink yayın adresini bulamadı: "
            + result.stderr.strip()
        )

    return url


def load_playlist(url):
    """Master playlist varsa medya playlistine iner."""
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=15
    )
    response.raise_for_status()

    lines = [
        line.strip()
        for line in response.text.splitlines()
        if line.strip()
    ]

    variants = []

    for index, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF") and index + 1 < len(lines):
            bandwidth = 0

            match = re.search(
                r"BANDWIDTH=(\d+)",
                line
            )

            if match:
                bandwidth = int(match.group(1))

            variants.append(
                (
                    bandwidth,
                    urljoin(url, lines[index + 1])
                )
            )

    if variants:
        variants.sort(
            key=lambda item: item[0],
            reverse=True
        )

        return load_playlist(variants[0][1])

    media_sequence = 0

    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

    segments = []
    pending_duration = None

    for line in lines:
        if line.startswith("#EXTINF:"):
            try:
                pending_duration = float(
                    line.split(
                        ":",
                        1
                    )[1].split(",", 1)[0]
                )
            except ValueError:
                pending_duration = 10.0

            continue

        if line.startswith("#"):
            continue

        segments.append(
            (
                pending_duration or 10.0,
                urljoin(url, line)
            )
        )

        pending_duration = None

    return media_sequence, segments


def segment_filename(sequence):
    return f"seg_{sequence}.ts"


def download_segment(sequence, url):
    filename = segment_filename(sequence)
    path = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(path) and os.path.getsize(path) > 0:
        return sequence, filename, True

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        if (
            response.status_code == 200
            and response.content
        ):
            temp_path = path + ".tmp"

            with open(
                temp_path,
                "wb"
            ) as file:
                file.write(response.content)

            # Dosya tamamen indikten sonra yeniden adlandır.
            # Böylece yarım segment playlist'e girmez.
            os.replace(
                temp_path,
                path
            )

            return sequence, filename, True

    except requests.RequestException:
        pass

    return sequence, filename, False


def write_playlist(segment_data):
    """Yalnızca tamamen indirilmiş segmentleri M3U8'e yazar."""

    valid_segments = [
        item
        for item in segment_data
        if os.path.exists(
            os.path.join(
                STREAM_DIR,
                segment_filename(item[0])
            )
        )
        and os.path.getsize(
            os.path.join(
                STREAM_DIR,
                segment_filename(item[0])
            )
        ) > 0
    ]

    valid_segments.sort(
        key=lambda item: item[0]
    )

    if not valid_segments:
        return

    valid_segments = valid_segments[
        -MAX_SEGMENTS:
    ]

    first_sequence = valid_segments[0][0]

    max_duration = max(
        item[1]
        for item in valid_segments
    )

    target_duration = max(
        1,
        int(max_duration + 0.999)
    )

    temp_playlist = PLAYLIST_FILE + ".tmp"

    with open(
        temp_playlist,
        "w",
        encoding="utf-8"
    ) as file:

        file.write("#EXTM3U\n")
        file.write("#EXT-X-VERSION:3\n")
        file.write(
            f"#EXT-X-TARGETDURATION:{target_duration}\n"
        )
        file.write(
            f"#EXT-X-MEDIA-SEQUENCE:{first_sequence}\n"
        )

        for sequence, duration in valid_segments:
            filename = segment_filename(sequence)

            file.write(
                f"#EXTINF:{duration:.3f},\n"
            )

            file.write(
                f"{BASE_URL}{filename}\n"
            )

    # Playlist dosyasını atomik olarak değiştir.
    os.replace(
        temp_playlist,
        PLAYLIST_FILE
    )

    # Kullanılmayan eski segmentleri sil.
    keep_files = {
        segment_filename(sequence)
        for sequence, duration in valid_segments
    }

    for path in glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*.ts"
        )
    ):
        if os.path.basename(path) not in keep_files:
            try:
                os.remove(path)
            except OSError:
                pass


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    print("ATV Avrupa canlı yayın takipçisi başladı.")

    known_segments = {}
    stream_url = None

    started_at = time.time()
    last_stream_refresh = 0

    while time.time() - started_at < RUN_SECONDS:

        try:
            # Her 60 saniyede Streamlink adresini yenile.
            if (
                stream_url is None
                or time.time() - last_stream_refresh > 60
            ):
                stream_url = get_stream_url()
                last_stream_refresh = time.time()

                print(
                    "Yeni yayın adresi alındı."
                )

            media_sequence, segments = load_playlist(
                stream_url
            )

            new_downloads = []

            for index, (
                duration,
                url
            ) in enumerate(segments):

                sequence = (
                    media_sequence
                    + index
                )

                known_segments[
                    sequence
                ] = duration

                path = os.path.join(
                    STREAM_DIR,
                    segment_filename(sequence)
                )

                if not os.path.exists(path):
                    new_downloads.append(
                        (
                            sequence,
                            url
                        )
                    )

            # Yeni segmentleri paralel indir.
            if new_downloads:

                print(
                    f"{len(new_downloads)} yeni segment bulundu."
                )

                with ThreadPoolExecutor(
                    max_workers=8
                ) as executor:

                    futures = [
                        executor.submit(
                            download_segment,
                            sequence,
                            url
                        )
                        for sequence, url
                        in new_downloads
                    ]

                    for future in as_completed(
                        futures
                    ):
                        sequence, filename, success = (
                            future.result()
                        )

                        if success:
                            print(
                                f"İndirildi: {filename}"
                            )

            # Diskte bulunmayan veya çok eski kayıtları temizle.
            if known_segments:
                newest = max(
                    known_segments.keys()
                )

                min_keep = (
                    newest
                    - MAX_SEGMENTS
                    - 20
                )

                known_segments = {
                    sequence: duration
                    for sequence, duration
                    in known_segments.items()
                    if sequence >= min_keep
                }

            # Her kontrolde güncel playlist yaz.
            write_playlist(
                list(
                    known_segments.items()
                )
            )

        except Exception as error:

            print(
                f"Kontrol hatası: {error}"
            )

            # Hata durumunda bir sonraki turda
            # Streamlink adresini yeniden al.
            stream_url = None

        time.sleep(POLL_SECONDS)

    print(
        "Bu çalışma tamamlandı."
    )


if __name__ == "__main__":
    main()
