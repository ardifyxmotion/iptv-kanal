import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


PAGE_URL = "https://www.atvavrupa.tv/canli-yayin"


def log(message):
    print(message, file=sys.stderr)


def main():
    m3u8_urls = []
    relevant_requests = []

    log("ATV Avrupa canlı yayın sayfası açılıyor...")

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

        def handle_request(request):
            url = request.url
            lower_url = url.lower()

            interesting = (
                "ercdn.net" in lower_url
                or ".m3u8" in lower_url
                or "atvavrupa" in lower_url
                or "live" in lower_url
                or "player" in lower_url
                or "video" in lower_url
            )

            if interesting and url not in relevant_requests:
                relevant_requests.append(url)

                log(f"[REQUEST] {request.method} {url}")

        def handle_response(response):
            url = response.url
            lower_url = url.lower()

            interesting = (
                "ercdn.net" in lower_url
                or ".m3u8" in lower_url
                or "atvavrupa" in lower_url
                or "live" in lower_url
                or "player" in lower_url
                or "video" in lower_url
            )

            if interesting:
                log(
                    f"[RESPONSE] {response.status} "
                    f"{response.request.method} {url}"
                )

            if (
                "trkvz-live.ercdn.net" in lower_url
                and ".m3u8" in lower_url
                and "atvavrupa" in lower_url
            ):

                if url not in m3u8_urls:
                    m3u8_urls.append(url)

                    log(f"[M3U8 BULUNDU] {url}")

        page.on("request", handle_request)
        page.on("response", handle_response)

        try:
            page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            log("Ana sayfa yüklendi.")

            page.wait_for_timeout(10000)

            log("Sayfadaki frame'ler kontrol ediliyor...")

            for frame in page.frames:

                try:
                    log(f"[FRAME] {frame.url}")

                    sources = frame.evaluate("""
                        () => {
                            const result = [];

                            document
                                .querySelectorAll(
                                    'video, source, iframe'
                                )
                                .forEach(element => {

                                    if (element.src) {
                                        result.push(element.src);
                                    }

                                    const src =
                                        element.getAttribute('src');

                                    if (src) {
                                        result.push(src);
                                    }
                                });

                            return result;
                        }
                    """)

                    for source in sources:

                        if source:
                            log(
                                f"[ELEMENT SOURCE] {source}"
                            )

                except Exception as e:
                    log(f"Frame kontrol hatası: {e}")

            log("Video oynatma işlemi deneniyor...")

            for frame in page.frames:

                try:
                    frame.evaluate("""
                        () => {
                            document
                                .querySelectorAll('video')
                                .forEach(video => {

                                    video.muted = true;

                                    video.play()
                                        .catch(() => {});
                                });
                        }
                    """)

                except Exception:
                    pass

            page.wait_for_timeout(30000)

            log("Performance kaynakları kontrol ediliyor...")

            resources = page.evaluate("""
                () => performance
                    .getEntriesByType('resource')
                    .map(item => item.name)
            """)

            for resource in resources:

                lower_resource = resource.lower()

                if (
                    "ercdn.net" in lower_resource
                    or ".m3u8" in lower_resource
                    or "atvavrupa" in lower_resource
                ):
                    log(f"[PERFORMANCE] {resource}")

        except Exception as e:

            log(f"SAYFA HATASI: {e}")

        browser.close()

    log("")
    log("========== BULUNAN M3U8 URL'LERİ ==========")

    for url in m3u8_urls:
        log(url)

    log("===========================================")

    if not m3u8_urls:

        log("ATV Avrupa M3U8 bağlantısı bulunamadı.")

        sys.exit(1)

    # Şimdilik son bulunan gerçek URL kullanılır.
    best_url = m3u8_urls[-1]

    # SADECE BU KISIM STDOUT'A YAZILIR
    print("#EXTM3U")
    print('#EXTINF:-1 tvg-name="ATV Avrupa",ATV AVRUPA')
    print(best_url)


if __name__ == "__main__":
    main()
