import re
import requests
from urllib.parse import urljoin

LIVE_PAGE = "https://www.atvavrupa.tv/canli-yayin"
OUTPUT_FILE = "atvavrupa_576p.m3u8"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def find_m3u8(text):
    """Sayfa içeriğinden M3U8 bağlantısını bulur."""

    patterns = [
        r'https?://[^"\'\\\s]+?\.m3u8[^"\'\\\s]*',
        r'["\'](?:src|file|url)["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)

        for match in matches:
            if ".m3u8" in match:
                return match.replace("\\/", "/")

    return None


def main():
    print("ATV Avrupa canlı yayın sayfası kontrol ediliyor...")

    session = requests.Session()
    session.headers.update(HEADERS)

    response = session.get(LIVE_PAGE, timeout=30)
    response.raise_for_status()

    m3u8_url = find_m3u8(response.text)

    if not m3u8_url:
        raise Exception("Canlı yayın sayfasında M3U8 adresi bulunamadı.")

    m3u8_url = urljoin(LIVE_PAGE, m3u8_url)

    print("Güncel M3U8 bulundu:")
    print(m3u8_url)

    playlist_response = session.get(m3u8_url, timeout=30)
    playlist_response.raise_for_status()

    playlist = playlist_response.text.strip()

    if not playlist.startswith("#EXTM3U"):
        raise Exception("Geçerli bir M3U8 playlist alınamadı.")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(playlist + "\n")

    print(f"Başarılı! {OUTPUT_FILE} güncellendi.")


if __name__ == "__main__":
    main()
