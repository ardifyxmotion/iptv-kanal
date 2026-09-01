import requests
import re
import html

url = "https://www.showmax.com.tr/canliyayin/"

headers = {
    "User-Agent": "Mozilla/5.0"
}

print("ShowMax canlı yayın sayfası kontrol ediliyor...", flush=True)

response = requests.get(
    url,
    headers=headers,
    timeout=20
)

response.raise_for_status()

source = html.unescape(response.text)

# showmax_1080p.m3u8 şeklindeki imzalı bağlantıyı ara
pattern = (
    r'https?[^"\'\\\s]+'
    r'ciner-live\.ercdn\.net'
    r'[^"\'\\\s]+'
    r'showmax_1080p\.m3u8'
    r'\?[^"\'\\\s<]+'
)

matches = re.findall(pattern, source)

if not matches:
    # JSON içerisinde escape edilmiş bağlantıları da ara
    source = source.replace("\\/", "/")

    pattern = (
        r'https?[^"\'\s]+'
        r'ciner-live\.ercdn\.net'
        r'[^"\'\s]+'
        r'showmax_1080p\.m3u8'
        r'\?[^"\'\s<]+'
    )

    matches = re.findall(pattern, source)

if matches:
    m3u8_url = matches[0]

    print(m3u8_url)

else:
    print("# ShowMax M3U8 bağlantısı bulunamadı.")
