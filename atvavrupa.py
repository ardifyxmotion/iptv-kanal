import asyncio
import requests
from playwright.async_api import async_playwright

LIVE_PAGE = "https://www.atvavrupa.tv/canli-yayin"
OUTPUT_FILE = "atvavrupa_576p.m3u8"


async def find_m3u8():
    found_urls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        def check_request(request):
            url = request.url

            if ".m3u8" in url.lower():
                if url not in found_urls:
                    print(f"M3U8 bulundu: {url}")
                    found_urls.append(url)

        page.on("request", check_request)

        print("ATV Avrupa canlı yayın sayfası açılıyor...")

        await page.goto(
            LIVE_PAGE,
            wait_until="domcontentloaded",
            timeout=60000
        )

        print("Yayın bağlantısı aranıyor...")

        await page.wait_for_timeout(15000)

        await browser.close()

    if not found_urls:
        return None

    for url in found_urls:
        if "atvavrupa" in url.lower():
            return url

    return found_urls[0]


async def main():
    m3u8_url = await find_m3u8()

    if not m3u8_url:
        raise Exception(
            "Sayfa yüklenirken herhangi bir M3U8 bağlantısı bulunamadı."
        )

    print("\nPlaylist indiriliyor...")

    response = requests.get(
        m3u8_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
            ),
            "Referer": LIVE_PAGE
        },
        timeout=30
    )

    response.raise_for_status()

    playlist = response.text.strip()

    if not playlist.startswith("#EXTM3U"):
        raise Exception(
            "Bulunan bağlantı geçerli bir M3U8 playlist döndürmedi."
        )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(playlist + "\n")

    print("\nBaşarılı!")
    print(f"{OUTPUT_FILE} güncellendi.")


if __name__ == "__main__":
    asyncio.run(main())
