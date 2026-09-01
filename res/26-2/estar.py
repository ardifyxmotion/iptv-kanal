import sys
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.eurostartv.com.tr/canli-izle"
TARGET_HOST = "dogusdyg-eurostar.lg.mncdn.com"


def main():
    found_urls = []

    print(
        "Eurostar canlı yayın sayfası açılıyor...",
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
            )
        )

        page = context.new_page()

        def handle_request(request):
            url = request.url.lower()

            if (
                TARGET_HOST in url
                and ".m3u8" in url
            ):
                if request.url not in found_urls:
                    found_urls.append(request.url)

                    print(
                        f"Eurostar M3U8 bulundu: {request.url}",
                        file=sys.stderr
                    )

        def handle_response(response):
            url = response.url.lower()

            if (
                TARGET_HOST in url
                and ".m3u8" in url
            ):
                if response.url not in found_urls:
                    found_urls.append(response.url)

                    print(
                        f"Eurostar M3U8 yanıtı bulundu: {response.url}",
                        file=sys.stderr
                    )

        page.on("request", handle_request)
        page.on("response", handle_response)

        try:
            page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            print(
                "Yayın oynatıcısının yüklenmesi bekleniyor...",
                file=sys.stderr
            )

            page.wait_for_timeout(5000)

            # Sayfadaki video elementlerini oynatmayı dene
            try:
                page.evaluate("""
                    () => {
                        const videos = document.querySelectorAll('video');

                        videos.forEach(video => {
                            video.muted = true;
                            video.play().catch(() => {});
                        });
                    }
                """)
            except Exception:
                pass

            # Yayın isteğinin oluşmasını bekle
            page.wait_for_timeout(20000)

        except Exception as e:
            print(
                f"Sayfa yükleme hatası: {e}",
                file=sys.stderr
            )

        browser.close()

    if not found_urls:
        print(
            "Eurostar M3U8 bağlantısı bulunamadı.",
            file=sys.stderr
        )
        sys.exit(1)

    # index.m3u8 bağlantısını önceliklendir
    best_url = None

    for url in found_urls:
        if "index.m3u8" in url.lower():
            best_url = url
            break

    if not best_url:
        best_url = found_urls[0]

    # IPTV playlist formatında çıktı oluştur
    print("#EXTM3U")
    print('#EXTINF:-1 tvg-name="EuroStar",EUROSTAR')
    print(best_url)


if __name__ == "__main__":
    main()
