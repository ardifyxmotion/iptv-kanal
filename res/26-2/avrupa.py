import sys
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright


PAGE_URL = "https://www.atvavrupa.tv/canli-yayin"
TARGET_HOST = "trkvz-live.ercdn.net"
TARGET_PATH = "/atvavrupa/atvavrupa.m3u8"


def log(text):
    print(text, file=sys.stderr, flush=True)


def is_master_playlist(url):
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        return (
            parsed.scheme == "https"
            and parsed.netloc.lower() == TARGET_HOST
            and parsed.path == TARGET_PATH
            and params.get("st")
            and params.get("e")
        )
    except Exception:
        return False


def main():
    master_urls = []

    log("ATV Avrupa canlı yayın sayfası açılıyor...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080}
        )

        page = context.new_page()

        def capture(url, source):
            if is_master_playlist(url):
                if url not in master_urls:
                    master_urls.append(url)
                    log(f"[ANA PLAYLIST - {source}] {url}")

        page.on(
            "request",
            lambda request: capture(request.url, "REQUEST")
        )

        page.on(
            "response",
            lambda response: capture(response.url, "RESPONSE")
        )

        try:
            page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(5000)

            # Tüm iframe'lerdeki video elementlerini başlat.
            for frame in page.frames:
                try:
                    frame.evaluate("""
                        async () => {
                            const videos =
                                document.querySelectorAll("video");

                            for (const video of videos) {
                                video.muted = true;
                                await video.play().catch(() => {});
                            }
                        }
                    """)
                except Exception:
                    pass

            # Sayfanın farklı noktalarına tıklayarak
            # olası Play butonunu tetikle.
            try:
                page.mouse.click(960, 540)
            except Exception:
                pass

            # Ana manifest isteğinin oluşmasını bekle.
            page.wait_for_timeout(30000)

            # CDP/Performance kayıtlarından da tara.
            resources = page.evaluate("""
                () => performance
                    .getEntriesByType("resource")
                    .map(x => x.name)
            """)

            for url in resources:
                capture(url, "PERFORMANCE")

        except Exception as error:
            log(f"HATA: {error}")

        browser.close()

    if not master_urls:
        log("Ana ATV Avrupa manifesti bulunamadı.")
        sys.exit(1)

    # En son alınan ana manifest.
    url = master_urls[-1]

    log(f"SEÇİLEN ANA PLAYLIST: {url}")

    print("#EXTM3U")
    print('#EXTINF:-1 tvg-name="ATV Avrupa",ATV AVRUPA')
    print(url)


if __name__ == "__main__":
    main()
