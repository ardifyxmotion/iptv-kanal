import sys
import requests
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright


PAGE_URL = "https://www.atvavrupa.tv/canli-yayin"
TARGET_HOST = "trkvz-live.ercdn.net"


def is_target_url(url):
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        return (
            parsed.netloc.lower() == TARGET_HOST
            and "atvavrupa" in parsed.path.lower()
            and ".m3u8" in parsed.path.lower()
            and "st" in query
            and "e" in query
        )
    except Exception:
        return False


def validate_stream(url):
    """URL'nin gerçekten bir M3U8 playlist döndürdüğünü kontrol eder."""

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Referer": PAGE_URL
            },
            timeout=15
        )

        if response.status_code != 200:
            return False

        return "#EXTM3U" in response.text[:1000]

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

        def add_url(url):

            if not is_target_url(url):
                return

            if url not in found_urls:

                found_urls.append(url)

                print(
                    f"M3U8 adayı bulundu: {url}",
                    file=sys.stderr
                )

        page.on(
            "request",
            lambda request: add_url(request.url)
        )

        page.on(
            "response",
            lambda response: add_url(response.url)
        )

        try:

            page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(8000)

            # Sayfadaki tüm iframe'leri kontrol et
            for frame in page.frames:

                try:
                    sources = frame.evaluate("""
                        () => {
                            const urls = [];

                            document
                                .querySelectorAll('video, source')
                                .forEach(element => {

                                    if (element.src) {
                                        urls.push(element.src);
                                    }

                                    if (element.getAttribute('src')) {
                                        urls.push(
                                            element.getAttribute('src')
                                        );
                                    }
                                });

                            return urls;
                        }
                    """)

                    for url in sources:

                        if url:
                            add_url(url)

                except Exception:
                    pass

            # Video elementlerini başlatmayı dene
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

            # Oynatıcının son yayın isteklerini yapması için bekle
            page.wait_for_timeout(20000)

            # Performance API üzerinden ağ kaynaklarını al
            try:

                resources = page.evaluate("""
                    () => performance
                        .getEntriesByType('resource')
                        .map(item => item.name)
                """)

                for url in resources:
                    add_url(url)

            except Exception:
                pass

        except Exception as e:

            print(
                f"Sayfa hatası: {e}",
                file=sys.stderr
            )

        browser.close()

    if not found_urls:

        print(
            "ATV Avrupa M3U8 bağlantısı bulunamadı.",
            file=sys.stderr
        )

        sys.exit(1)

    print(
        f"{len(found_urls)} aday bağlantı bulundu.",
        file=sys.stderr
    )

    # En son oluşturulan URL'leri önce dene.
    # Yeni imzalı URL'nin geçerli olma ihtimali daha yüksektir.
    best_url = None

    for url in reversed(found_urls):

        print(
            f"Bağlantı doğrulanıyor: {url}",
            file=sys.stderr
        )

        if validate_stream(url):

            best_url = url

            print(
                "Geçerli M3U8 bağlantısı doğrulandı.",
                file=sys.stderr
            )

            break

    if not best_url:

        print(
            "Geçerli bir M3U8 playlist doğrulanamadı.",
            file=sys.stderr
        )

        sys.exit(1)

    print("#EXTM3U")
    print('#EXTINF:-1 tvg-name="ATV Avrupa",ATV AVRUPA')
    print(best_url)


if __name__ == "__main__":
    main()
