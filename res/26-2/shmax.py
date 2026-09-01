import requests
import re
import json

URL = "https://www.showmax.com.tr/canliyayin/"

headers = {
    "User-Agent": "Mozilla/5.0"
}

print("ShowMax canlı yayın sayfası kontrol ediliyor...")

response = requests.get(URL, headers=headers, timeout=15)
response.raise_for_status()

html = response.text

# Sayfadaki doğrudan M3U8 bağlantılarını ara
m3u8_links = re.findall(
    r'https?://[^"\'\\\s]+?\.m3u8[^"\'\\\s]*',
    html
)

# JSON içindeki src alanlarını da kontrol et
if not m3u8_links:
    src_matches = re.findall(
        r'"src"\s*:\s*"([^"]+\.m3u8[^"]*)"',
        html
    )

    for link in src_matches:
        link = link.replace("\\/", "/")
        m3u8_links.append(link)

if m3u8_links:
    m3u8_url = m3u8_links[0]

    print(f"Bulunan M3U8: {m3u8_url}")

    playlist = requests.get(
        m3u8_url,
        headers=headers,
        timeout=15
    )

    playlist.raise_for_status()

    print(playlist.text)

else:
    print("M3U8 bağlantısı sayfa kaynağında bulunamadı.")
