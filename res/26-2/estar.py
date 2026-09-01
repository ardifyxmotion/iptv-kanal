import re
import sys
import html
import requests
from urllib.parse import urljoin

PAGE_URL = "https://www.eurostartv.com.tr/canli-izle"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": PAGE_URL
}


def get_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=20
    )
    response.raise_for_status()
    return response.text, response.url


def find_m3u8(content, base_url):
    content = html.unescape(content)

    # Normal ve JSON içerisindeki M3U8 bağlantılarını ara
    patterns = [
        r'https?://[^"\'\\\s<>]+\.m3u8(?:\?[^"\'\\\s<>]*)?',
        r'//[^"\'\\\s<>]+\.m3u8(?:\?[^"\'\\\s<>]*)?',
        r'[^"\'\\\s<>]+\.m3u8(?:\?[^"\'\\\s<>]*)?'
    ]

    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)

        for match in matches:
            match = match.replace("\\/", "/")

            if match.startswith("//"):
                match = "https:" + match

            stream_url = urljoin(base_url, match)

            if ".m3u8" in stream_url:
                return stream_url

    return None


def find_iframes(content, base_url):
    iframe_urls = re.findall(
        r'<iframe[^>]+src=["\']([^"\']+)["\']',
        content,
        re.IGNORECASE
    )

    return [
        urljoin(base_url, url)
        for url in iframe_urls
    ]


def main():
    try:
        print("Eurostar canlı yayın sayfası kontrol ediliyor...", file=sys.stderr)

        page_content, final_url = get_page(PAGE_URL)

        # Önce ana sayfada M3U8 ara
        stream_url = find_m3u8(page_content, final_url)

        # Bulunamazsa iframe'leri kontrol et
        if not stream_url:
            iframe_urls = find_iframes(page_content, final_url)

            for iframe_url in iframe_urls:
                try:
                    print(
                        f"Gömülü yayın kontrol ediliyor: {iframe_url}",
                        file=sys.stderr
                    )

                    iframe_content, iframe_final_url = get_page(iframe_url)

                    stream_url = find_m3u8(
                        iframe_content,
                        iframe_final_url
                    )

                    if stream_url:
                        break

                except Exception as e:
                    print(
                        f"Iframe okunamadı: {e}",
                        file=sys.stderr
                    )

        if not stream_url:
            print(
                "M3U8 bağlantısı bulunamadı.",
                file=sys.stderr
            )
            sys.exit(1)

        print(
            f"Bulunan yayın: {stream_url}",
            file=sys.stderr
        )

        # M3U8 içeriğini al
        response = requests.get(
            stream_url,
            headers=HEADERS,
            timeout=20
        )
        response.raise_for_status()

        playlist = response.text

        # Playlist içindeki göreceli bağlantıları düzelt
        lines = []

        for line in playlist.splitlines():
            line = line.strip()

            if (
                line
                and not line.startswith("#")
                and not line.startswith("http")
            ):
                line = urljoin(stream_url, line)

            lines.append(line)

        print("\n".join(lines))

    except Exception as e:
        print(
            f"HATA: {e}",
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
