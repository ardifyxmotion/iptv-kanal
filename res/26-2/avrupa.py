import sys
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.atvavrupa.tv/canli-yayin"
TARGET_HOST = "trkvz-live.ercdn.net"


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

        def check_url(url):
            lower_url = url.lower()

            if (
                TARGET_HOST in lower_url
                and "atvavrupa" in lower_url
                and ".m3u8" in lower_url
            ):
                if url not in found_urls:
                    found_urls.append(url)

                    print(
                        f"ATV Avrupa M3U8 bulundu: {url}",
                        file=sys.stderr
                    )

        page.on("request", lambda request: check_url(request.url))
        page.on("response", lambda response: check_url(response.url))

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

            try:
                page.evaluate("""
                    () => {
                        document.querySelectorAll('video').forEach(video => {
                            video.muted = true;
                            video.play().catch(() => {});
                        });
                    }
                """)
            except Exception:
                pass

            page.wait_for_timeout(20000)

        except Exception as e:
            print(
                f"Sayfa yükleme hatası: {e}",
                file=sys.stderr
            )

        browser.close()

    if not found_urls:
        print(
            "ATV Avrupa M3U8 bağlantısı bulunamadı.",
            file=sys.stderr
        )
        sys.exit(1)

    best_url = None

    for url in found_urls:
        if "atvavrupa_576p.m3u8" in url.lower():
            best_url = url
            break

    if not best_url:
        best_url = found_urls[0]

    print("#EXTM3U")
    print('#EXTINF:-1 tvg-name="ATV Avrupa",ATV AVRUPA')
    print(best_url)


if __name__ == "__main__":
    main()
