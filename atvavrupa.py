import os
import json
import re
import subprocess
import requests
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

STREAM_DIR = "streams"
PLAYLIST_FILE = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILE = os.path.join(STREAM_DIR, "stream_state.json")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanall/main/streams/"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        return {
            "next_output_sequence": int(
                state.get("next_output_sequence", 0)
            ),
            "last_source_sequence": state.get(
                "last_source_sequence"
            )
        }
    except (OSError, ValueError, TypeError):
        return {
            "next_output_sequence": 0,
            "last_source_sequence": None
        }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def get_stream_url():
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

    url = result.stdout.strip()

    if not url:
        raise RuntimeError(
            "Streamlink yayın adresini bulamadı.\n"
            + result.stderr.strip()
        )

    return url


def parse_playlist(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()

    lines = [
        line.strip()
        for line in response.text.splitlines()
        if line.strip()
    ]

    variants = []

    for index, line in enumerate(lines):
        if (
            line.startswith("#EXT-X-STREAM-INF")
            and index + 1 < len(lines)
        ):
            match = re.search(
                r"BANDWIDTH=(\d+)",
                line
            )

            bandwidth = (
                int(match.group(1))
                if match
                else 0
            )

            variants.append(
                (
                    bandwidth,
                    urljoin(
                        url,
                        lines[index + 1]
                    )
                )
            )

    if variants:
        variants.sort(
            key=lambda item: item[0],
            reverse=True
        )

        return parse_playlist(
            variants[0][1]
        )

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


def read_existing_items():
    items = []

    if not os.path.exists(PLAYLIST_FILE):
        return items

    try:
        with open(
            PLAYLIST_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            lines = [
                line.strip()
                for line in f
                if line.strip()
            ]

        duration = None

        for line in lines:

            if line.startswith("#EXTINF:"):
                try:
                    duration = float(
                        line.split(
                            ":",
                            1
                        )[1].split(",", 1)[0]
                    )
                except ValueError:
                    duration = 10.0

                continue

            if line.startswith("#"):
                continue

            match = re.search(
                r"seg_(\d+)\.ts",
                line
            )

            if match:
                sequence = int(
                    match.group(1)
                )

                filename = f"seg_{sequence}.ts"

                path = os.path.join(
                    STREAM_DIR,
                    filename
                )

                if (
                    os.path.exists(path)
                    and os.path.getsize(path) > 100
                ):
                    items.append(
                        (
                            sequence,
                            duration or 10.0
                        )
                    )

            duration = None

    except OSError:
        pass

    return items


def download_segment(item):
    output_sequence, url = item

    filename = f"seg_{output_sequence}.ts"

    path = os.path.join(
        STREAM_DIR,
        filename
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        if (
            response.status_code == 200
            and len(response.content) > 100
        ):
            temporary_path = path + ".tmp"

            with open(
                temporary_path,
                "wb"
            ) as f:
                f.write(response.content)

            os.replace(
                temporary_path,
                path
            )

            return output_sequence, True

    except requests.RequestException:
        pass

    return output_sequence, False


def write_playlist(items):
    """
    ÖNEMLİ:
    Eski segmentler silinmez.
    Playlist her zaman seg_0.ts ile başlar.
    Böylece oynatma süresi 00:00'dan itibaren ilerler.
    """

    items.sort(
        key=lambda item: item[0]
    )

    if not items:
        raise RuntimeError(
            "Playlist için segment bulunamadı."
        )

    temporary_path = PLAYLIST_FILE + ".tmp"

    target_duration = max(
        1,
        int(
            max(
                duration
                for _, duration in items
            ) + 0.999
        )
    )

    with open(
        temporary_path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write(
            f"#EXT-X-TARGETDURATION:{target_duration}\n"
        )

        # HER ZAMAN SIFIRDAN BAŞLAYAN OYNATMA LİSTESİ
        f.write("#EXT-X-MEDIA-SEQUENCE:0\n")

        # İlk segmentten oynatılmasını iste.
        f.write("#EXT-X-START:TIME-OFFSET=0\n")

        for sequence, duration in items:

            filename = f"seg_{sequence}.ts"

            f.write(
                f"#EXTINF:{duration:.3f},\n"
            )

            f.write(
                f"{BASE_URL}{filename}?v={sequence}\n"
            )

    os.replace(
        temporary_path,
        PLAYLIST_FILE
    )


def main():
    os.makedirs(STREAM_DIR, exist_ok=True)

    state = load_state()

    existing_items = read_existing_items()

    # İlk çalışma tamamen 0'dan başlar.
    if existing_items:
        next_output_sequence = max(
            sequence
            for sequence, _
            in existing_items
        ) + 1
    else:
        next_output_sequence = 0

    stream_url = get_stream_url()

    source_media_sequence, source_segments = (
        parse_playlist(stream_url)
    )

    if not source_segments:
        raise RuntimeError(
            "Kaynak playlist boş."
        )

    last_source_sequence = state.get(
        "last_source_sequence"
    )

    # İlk çalışmada kaynakta bulunan segmentlerin
    # tamamı 0'dan itibaren kaydedilir.
    if last_source_sequence is None:
        new_source_items = list(
            enumerate(
                source_segments,
                start=source_media_sequence
            )
        )
    else:
        new_source_items = [
            (
                source_sequence,
                segment
            )
            for source_sequence, segment
            in enumerate(
                source_segments,
                start=source_media_sequence
            )
            if source_sequence > last_source_sequence
        ]

    if not new_source_items:
        print(
            "Yeni kaynak segment henüz bulunamadı."
        )
        return

    download_items = []
    new_metadata = []

    for index, (
        source_sequence,
        (duration, url)
    ) in enumerate(new_source_items):

        output_sequence = (
            next_output_sequence
            + index
        )

        download_items.append(
            (
                output_sequence,
                url
            )
        )

        new_metadata.append(
            (
                source_sequence,
                output_sequence,
                duration
            )
        )

    print(
        f"{len(download_items)} yeni segment indiriliyor..."
    )

    with ThreadPoolExecutor(
        max_workers=16
    ) as executor:

        results = list(
            executor.map(
                download_segment,
                download_items
            )
        )

    successful_items = []
    highest_source_sequence = last_source_sequence

    for (
        output_sequence,
        success
    ), (
        source_sequence,
        expected_output_sequence,
        duration
    ) in zip(
        results,
        new_metadata
    ):

        if (
            success
            and output_sequence
            == expected_output_sequence
        ):
            successful_items.append(
                (
                    output_sequence,
                    duration
                )
            )

            highest_source_sequence = (
                source_sequence
            )

    if not successful_items:
        raise RuntimeError(
            "Hiçbir yeni segment indirilemedi."
        )

    combined = {
        sequence: duration
        for sequence, duration
        in existing_items
    }

    for sequence, duration in successful_items:
        combined[sequence] = duration

    final_items = sorted(
        combined.items(),
        key=lambda item: item[0]
    )

    # DİKKAT: MAX_SEGMENTS kesmesi ve eski segment silme yok.
    # Sayaç 00:00'dan başlayıp ilerlemeye devam eder.
    write_playlist(final_items)

    save_state(
        {
            "next_output_sequence": (
                max(
                    sequence
                    for sequence, _
                    in final_items
                ) + 1
            ),
            "last_source_sequence": (
                highest_source_sequence
            )
        }
    )

    total_duration = sum(
        duration
        for _, duration
        in final_items
    )

    print("Playlist güncellendi.")
    print(
        f"İlk segment: seg_{final_items[0][0]}.ts"
    )
    print(
        f"Son segment: seg_{final_items[-1][0]}.ts"
    )
    print(
        f"Oynatma süresi: "
        f"{total_duration / 60:.2f} dakika"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"HATA: {error}")
        raise
