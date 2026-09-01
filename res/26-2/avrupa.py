import re
import sys
import html
import requests
from urllib.parse import urljoin

LIVE_PAGE = "https://www.atvavrupa.tv/canli-yayin"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.atvavrupa.tv/"
}


def clean_url(url):
    """JavaScript ve HTML içindeki URL kaçışlarını temizler."""
    url = html.unescape(url)
    url = url.replace("\\/", "/")
    url = url.replace("\\u0026", "&")
    url = url.replace("\\x26", "&")
    url = url.replace("\\\\", "\\")

    return url.strip("\"' ")


def find_m3u8(text):
    """ATV Avrupa'nın güncel imzalı M3U8 bağlantısını arar."""

    patterns = [
        r'https?://trkvz-live\.ercdn\.net/atvavrupa/[^"\'\s<>]+\.m3u8[^"\'\s<>]*',
        r'["\']([^"\']*trkvz-live\.ercdn\.net[^"\']*atvavrupa[^"\']*\.m3u8[^"\']*)["\']',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)

        for match in matches:
            if isinstance(match, tuple):
                match = match[0]

            url = clean_url(match)

            if (
                "trkvz-live.ercdn.net" in url
                and "atvavrupa" in url
                and ".m3u8" in url
            ):
                return url

    return None


def get_urls_from_page(text, base_url):
    """HTML içindeki script ve iframe kaynaklarını çıkarır."""

    urls = set()

    for src in re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        text,
        re.IGNORECASE
    ):
        urls.add(urljoin(base_url, html.unescape(src)))

    for src in re.findall(
        r'<iframe[^>]+src=["\']([^"\']+)["\']',
        text,
        re.IGNORECASE
    ):
        full_url = urljoin(base_url, html.unescape(src))

        skip = [
            "doubleclick",
            "googlesyndication",
            "mirriad",
            "ad01.",
            "/js/biframe"
        ]

        if not any(item in full_url.lower() for item in skip):
            urls.add(full_url)

    return urls


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        print(
            "ATV Avrupa canlı yayın sayfası kontrol ediliyor...",
            file=sys.stderr
        )

        response = session.get(LIVE_PAGE, timeout=30)
        response.raise_for_status()

        # Önce ana sayfada ara
        m3u8_url = find_m3u8(response.text)

        # Ardından JavaScript ve iframe kaynaklarını kontrol et
        if not m3u8_url:
            resources = get_urls_from_page(
                response.text,
                response.url
            )

            print(
                f"{len(resources)} kaynak kontrol ediliyor...",
                file=sys.stderr
            )

            for resource_url in resources:
                try:
                    print(
                        f"Kontrol ediliyor: {resource_url}",
                        file=sys.stderr
                    )

                    resource_response = session.get(
                        resource_url,
                        headers={
                            **HEADERS,
                            "Referer": response.url
                        },
                        timeout=20
                    )

                    if resource_response.status_code != 200:
                        continue

                    m3u8_url = find_m3u8(resource_response.text)

                    if m3u8_url:
                        break

                except requests.RequestException as error:
                    print(
                        f"Kaynak atlandı: {error}",
                        file=sys.stderr
                    )

        if not m3u8_url:
            print(
                "HATA: ATV Avrupa için güncel M3U8 bağlantısı bulunamadı.",
                file=sys.stderr
            )
            sys.exit(1)

        print(
            f"Güncel M3U8 bulundu: {m3u8_url}",
            file=sys.stderr
        )

        print("#EXTM3U")
        print('#EXTINF:-1 tvg-name="ATV Avrupa",ATV Avrupa')
        print(m3u8_url)

    except requests.RequestException as error:
        print(
            f"İstek hatası: {error}",
            file=sys.stderr
        )
        sys.exit(1)

    except Exception as error:
        print(
            f"Beklenmeyen hata: {error}",
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
