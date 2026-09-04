import os
import subprocess
import sys

STREAM_PAGE = "https://www.atvavrupa.tv/canli-yayin"
OUTPUT_FILE = "streams/atvavrupa.m3u8"


def get_stream_url():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlink",
            "--stream-url",
            STREAM_PAGE,
            "best"
        ],
        capture_output=True,
        text=True,
        timeout=60
    )

    url = result.stdout.strip()

    if not url:
        print("Yayın URL'si alınamadı.")
        print(result.stderr)
        return None

    return url


def main():
    os.makedirs("streams", exist_ok=True)

    stream_url = get_stream_url()

    if not stream_url:
        raise SystemExit(1)

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        file.write("#EXTM3U\n")
        file.write(
            "#EXT-X-STREAM-INF:"
            "BANDWIDTH=5000000\n"
        )
        file.write(stream_url + "\n")

    print("M3U8 dosyası güncellendi:")
    print(stream_url)


if __name__ == "__main__":
    main()
