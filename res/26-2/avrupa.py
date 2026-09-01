import sys
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.atvavrupa.tv/canli-yayin"
TARGET_HOST = "trkvz-live.ercdn.net"
TARGET_PATH = "/atvavrupa/"


def is_valid_stream_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme != "https":
            return False

        if parsed.netloc.lower() != TARGET_HOST:
            return False

        if TARGET_PATH not in parsed.path.lower():
            return False

        if not parsed.path.lower().endswith(".m3u8"):
            return False

        query = parse_qs(parsed.query)

        return bool(query.get("st")) and bool(query.get("e"))

    except Exception:
        return False


def main():
    found_urls = []

    print(
        "ATV Avrupa canlı yayın sayfası açılıyor...",
        file=sys.stderr
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required"
            ]
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        def handle_response(response):
            url = response.url

            if not is_valid_stream_url(url):
                return

            try:
                # Sadece gerçekten başarılı olan M3U8 yanıtlarını kabul et
                if response.status != 200:
                    print(
                        f"Geçersiz yayın yanıtı: "
                        f"{response.status} - {url}",
                        file=sys.stderr
                    )
                    return

                content_type = response.headers.get(
                    "content-type",
                    ""
                ).lower()

                # Bazı CDN'ler farklı content-type gönderebilir;
                # yine de başarılı URL'yi kabul ediyoruz.
                if url not in found_urls:
                    found_urls.append(url)

                    print(
                        f"Geçerli ATV Avrupa M3U8 bulundu: {url}",
                        file=sys.stderr
                    )

            except Exception as e:
                print(
                    f"Yayın kontrol hatası: {e}",
                    file=sys.stderr
                )

        page.on("response", handle_response)

        try:
            page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            print(
                "Yayın oynatıcısı bekleniyor...",
                file=sys.stderr
            )

            # Sayfanın JavaScript ve oyuncu bileşenlerinin yüklenmesi
            page.wait_for_timeout(8000)

            # Video ve iframe içindeki oynatıcıları mümkün olduğunca başlat
            for frame in page.frames:
                try:
                    frame.evaluate("""
                        () => {
                            const videos =
                                document.querySelectorAll('video');

                            videos.forEach(video => {
                                video.muted = true;
                                video.play().catch(() => {});
                            });
                        }
                    """)
                except Exception:
                    pass

            # Bazı oynatıcılarda kullanıcı tıklaması gerekir.
            try:
                page.mouse.click(
                    page.viewport_size["width"] // 2,
                    page.viewport_size["height"] // 2
                )
            except Exception:
                pass

            # Canlı yayın isteğinin oluşmasını bekle
            page.wait_for_timeout(20000)

        except Exception as e:
            print(
                f"Sayfa yükleme hatası: {e}",
                file=sys.stderr
            )

        browser.close()

    if not found_urls:
        print(
            "Geçerli ATV Avrupa M3U8 bağlantısı bulunamadı.",
            file=sys.stderr
        )
        sys.exit(1)

    # Tercih edilen yayın kalitesi
    preferred_urls = [
        url for url in found_urls
        if "atvavrupa_576p.m3u8" in url.lower()
    ]

    if preferred_urls:
        # En son başarılı yanıtı kullan
        best_url = preferred_urls[-1]
    else:
        best_url = found_urls[-1]

    # IPTV M3U çıktısı
    print("#EXTM3U")
    print('#EXTINF:-1 tvg-name="ATV Avrupa",ATV AVRUPA')
    print(best_url)


if __name__ == "__main__":
    main()
