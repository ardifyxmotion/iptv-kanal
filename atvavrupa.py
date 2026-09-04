import subprocess
import requests

LIVE_PAGE = "https://www.atvavrupa.tv/canli-yayin"
OUTPUT_FILE = "atvavrupa_576p.m3u8"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": LIVE_PAGE,
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

REQUEST_TIMEOUT = 30


def get_stream_url():
    print("Güncel yayın URL'si aranıyor...")

    result = subprocess.run(
        [
            "streamlink",
            "--stream-url",
            LIVE_PAGE,
            "best"
        ],
        capture_output=True,
        text=True,
        timeout=60
    )

    stream_url = result.stdout.strip()

    if not stream_url.startswith("http"):
        print(result.stderr)
        raise Exception("Streamlink yayın URL'sini bulamadı.")

    print("Güncel yayın URL'si bulundu.")
    return stream_url


def download_playlist(stream_url):
    print("M3U8 playlist indiriliyor...")

    response = requests.get(
        stream_url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    playlist = response.text.strip()

    if not playlist.startswith("#EXTM3U"):
        raise Exception(
            "Geçerli bir M3U8 playlist alınamadı."
        )

    return playlist


def main():
    stream_url = get_stream_url()

    playlist = download_playlist(stream_url)

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(playlist + "\n")

    print(f"{OUTPUT_FILE} başarıyla güncellendi.")


if __name__ == "__main__":
    main()
