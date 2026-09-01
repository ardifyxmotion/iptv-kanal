import re
import sys
import html
import json
import requests
from urllib.parse import urljoin


PAGE_URL = "https://www.eurostartv.com.tr/canli-izle"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": PAGE_URL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


def get_url(url, referer=PAGE_URL):
    headers = HEADERS.copy()
    headers["Referer"] = referer

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.text, response.url


def clean_url(url):
    url = html.unescape(url)
    url = url.replace("\\/", "/")
    url = url.replace("\\u0026", "&")
    url = url.replace("\\", "")
    return url.strip()


def find_m3u8(content, base_url):
    content = html.unescape(content)

    patterns = [
        r'https?:\\/\\/[^"\'\s<>]+?\.m3u8(?:\?[^"\'\s<>]*)?',
        r'https?://[^"\'\s<>]+?\.m3u8(?:\?[^"\'\s<>]*)?',
        r'//[^"\'\s<>]+?\.m3u8(?:\?[^"\'\s<>]*)?',
        r'["\']([^"\']+?\.m3u8(?:\?[^"\']*)?)["\']'
    ]

    for pattern in patterns:
        matches = re.findall(
            pattern,
            content,
            re.IGNORECASE
        )

        for match in matches:
            if isinstance(match, tuple):
                match = match[0]

            match = clean_url(match)

            if match.startswith("//"):
                match = "https:" + match

            stream_url = urljoin(base_url, match)

            if ".m3u8" in stream_url.lower():
                return stream_url

    return None


def find_iframes(content, base_url):
    iframe_urls = re.findall(
        r'<iframe[^>]+src=["\']([^"\']+)["\']',
        content,
        re.IGNORECASE
    )

    ignored_domains = [
        "googletagmanager.com",
        "google.com",
        "doubleclick.net",
        "facebook.com",
        "instagram.com"
    ]

    result = []

    for iframe_url in iframe_urls:
        iframe_url = clean_url(iframe_url)
        full_url = urljoin(base_url, iframe_url)

        if any(domain in full_url.lower()
               for domain in ignored_domains):
            continue

        result.append(full_url)

    return result


def find_scripts(content, base_url):
    script_urls = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        content,
        re.IGNORECASE
    )

    result = []

    for script_url in script_urls:
        script_url = clean_url(script_url)
        full_url = urljoin(base_url, script_url)

        result.append(full_url)

    return result


def search_source(content, source_url):
    stream_url = find_m3u8(content, source_url)

    if stream_url:
        return stream_url

    return None


def main():
    try:
        print(
            "Eurostar canlı yayın sayfası kontrol ediliyor...",
            file=sys.stderr
        )

        page_content, final_url = get_url(PAGE_URL)

        # 1. Ana HTML içerisinde ara
        stream_url = search_source(
            page_content,
            final_url
        )

        # 2. Gerçek iframe'leri kontrol et
        if not stream_url:
            iframe_urls = find_iframes(
                page_content,
                final_url
            )

            for iframe_url in iframe_urls:
                try:
                    print(
                        f"Yayın iframe'i kontrol ediliyor: {iframe_url}",
                        file=sys.stderr
                    )

                    iframe_content, iframe_final_url = get_url(
                        iframe_url,
                        final_url
                    )

                    stream_url = search_source(
                        iframe_content,
                        iframe_final_url
                    )

                    if stream_url:
                        break

                except Exception as e:
                    print(
                        f"Iframe hatası: {e}",
                        file=sys.stderr
                    )

        # 3. JavaScript dosyalarını kontrol et
        if not stream_url:
            script_urls = find_scripts(
                page_content,
                final_url
            )

            print(
                f"{len(script_urls)} JavaScript dosyası kontrol ediliyor...",
                file=sys.stderr
            )

            for script_url in script_urls:
                try:
                    script_content, script_final_url = get_url(
                        script_url,
                        final_url
                    )

                    stream_url = search_source(
                        script_content,
                        script_final_url
                    )

                    if stream_url:
                        print(
                            f"Yayın JavaScript içerisinde bulundu.",
                            file=sys.stderr
                        )
                        break

                except Exception:
                    continue

        if not stream_url:
            print(
                "M3U8 bağlantısı bulunamadı.",
                file=sys.stderr
            )

            sys.exit(1)

        print(
            f"M3U8 bulundu: {stream_url}",
            file=sys.stderr
        )

        # Yayın listesini indir
        response = requests.get(
            stream_url,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        playlist = response.text

        # Playlist bağlantılarını mutlak URL yap
        output = []

        for line in playlist.splitlines():
            line = line.strip()

            if (
                line
                and not line.startswith("#")
                and not line.startswith("http")
            ):
                line = urljoin(stream_url, line)

            output.append(line)

        print("\n".join(output))

    except Exception as e:
        print(
            f"HATA: {e}",
            file=sys.stderr
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
