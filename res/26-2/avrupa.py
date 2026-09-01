import re
import sys
import requests

URL = "https://www.atvavrupa.tv/canli-yayin"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.atvavrupa.tv/"
}


def find_m3u8(text):
    """Metin içerisinden M3U8 bağlantısını bulur."""
    
    patterns = [
        r'https?[^"\'\\\s]+?\.m3u8[^"\'\\\s]*',
        r'"src"\s*:\s*"([^"]+\.m3u8[^"]*)"',
        r"'src'\s*:\s*'([^']+\.m3u8[^']*)'",
        r'source\s*:\s*["\']([^"\']+\.m3u8[^"\']*)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            url = match.group(1) if match.lastindex else match.group(0)

            url = (
                url.replace("\\/", "/")
                   .replace("\\u0026", "&")
                   .replace("&amp;", "&")
            )

            return url

    return None


def main():
    try:
        print("ATV Avrupa canlı yayın sayfası kontrol ediliyor...", file=sys.stderr)

        session = requests.Session()
        session.headers.update(HEADERS)

        response = session.get(URL, timeout=20)
        response.raise_for_status()

        # Önce ana sayfada M3U8 ara
        m3u8_url = find_m3u8(response.text)

        # Ana sayfada bulunamazsa iframe bağlantılarını kontrol et
        if not m3u8_url:
            print("Ana sayfada M3U8 bulunamadı, iframe kontrol ediliyor...", file=sys.stderr)

            iframes = re.findall(
                r'<iframe[^>]+src=["\']([^"\']+)["\']',
                response.text,
                re.IGNORECASE
            )

            for iframe in iframes:
                if iframe.startswith("//"):
                    iframe = "https:" + iframe
                elif iframe.startswith("/"):
                    iframe = "https://www.atvavrupa.tv" + iframe

                try:
                    print(f"Iframe kontrol ediliyor: {iframe}", file=sys.stderr)

                    iframe_response = session.get(
                        iframe,
                        headers={
                            **HEADERS,
                            "Referer": URL
                        },
                        timeout=20
                    )

                    iframe_response.raise_for_status()

                    m3u8_url = find_m3u8(iframe_response.text)

                    if m3u8_url:
                        break

                except requests.RequestException as e:
                    print(f"Iframe hatası: {e}", file=sys.stderr)

        if not m3u8_url:
            print(
                "HATA: M3U8 bağlantısı bulunamadı.",
                file=sys.stderr
            )
            sys.exit(1)

        print("M3U8 bulundu:", m3u8_url, file=sys.stderr)

        # M3U8 dosyası çıktısı
        print("#EXTM3U")
        print('#EXTINF:-1 tvg-name="ATV Avrupa",ATV AVRUPA')
        print(m3u8_url)

    except requests.RequestException as e:
        print(f"İstek hatası: {e}", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(f"Beklenmeyen hata: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
