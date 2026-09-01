import sys
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright


PAGE_URL = "https://www.atvavrupa.tv/canli-yayin"

TARGET_HOST = "trkvz-live.ercdn.net"
TARGET_FILE = "atvavrupa_576p.m3u8"


def is_valid_target(url):
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        return (
            parsed.scheme == "https"
            and parsed.netloc.lower() == TARGET_HOST
            and parsed.path.lower().endswith(TARGET_FILE)
            and bool(params.get("st"))
            and bool(params.get("e"))
        )

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
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={
                "width": 1920,
                "height": 1080
            }
        )

        page = context.new_page()

        def capture_url(url):

            if is_valid_target(url):

                if url not in found_urls:

                    found_urls.append(url)

                    print(
                        f"Gerçek yayın URL'si bulundu: {url}",
                        file=sys.stderr
                    )

        page.on(
            "request",
            lambda request: capture_url(request.url)
        )

        page.on(
            "response",
            lambda response: capture_url(response.url)
        )

        try:

            page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            print(
                "Sayfanın tüm içerikleri yükleniyor...",
                file=sys.stderr
            )

            page.wait_for_timeout(10000)

            # Sayfadaki iframe'leri bekle ve incele
            for frame in page.frames:

                try:

                    # Video elementlerini başlat
                    frame.evaluate("""
                        () => {
                            const videos =
                                document.querySelectorAll('video');

                            videos.forEach(video => {

                                video.muted = true;

                                video.play()
                                    .catch(() => {});
                            });
                        }
                    """)

                except Exception:
                    pass

            # Sayfanın ortasına tıklayarak
            # olası "play" işlemini tetikle
            try:

                page.mouse.click(
                    960,
                    540
                )

            except Exception:
                pass

            # Yayın isteğinin başlamasını bekle
            page.wait_for_timeout(30000)

        except Exception as e:

            print(
                f"Sayfa hatası: {e}",
                file=sys.stderr
            )

        browser.close()

    if not found_urls:

        print(
            "Gerçek ATV Avrupa M3U8 URL'si bulunamadı.",
            file=sys.stderr
        )

        sys.exit(1)

    # En son yakalanan imzalı URL kullanılır
    best_url = found_urls[-1]

    print("#EXTM3U")
    print('#EXTINF:-1 tvg-name="ATV Avrupa",ATV AVRUPA')
    print(best_url)


if __name__ == "__main__":
    main()
