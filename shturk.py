import requests
import re
import urllib3

base_url = "https://ciner-live.ercdn.net/showturk/"

# Güvenlik uyarılarını kapat
urllib3.disable_warnings()

response = requests.get(
    "https://www.showturk.com.tr/canli-yayin",
    verify=False,
    timeout=15
)

if response.status_code == 200:
    # JSON veya HTML içindeki ters bölü (\/) kaçış karakterlerini temizle
    site_content = response.text.replace("\\/", "/")

    # HTML içinde doğrudan http/https ile başlayıp .m3u8 ile biten ilk linki bulur
    # data-hope-video veya src etiketlerine hiç bakmaz
    m3u8_match = re.search(r"https?://[^\s\"']+\.m3u8[^\s\"']*", site_content)

    if m3u8_match:
        ht_stream_m3u8 = m3u8_match.group(0)
        print(f"")

        # Canlı yayın içeriğini çekme ve base_url ekleme mantığı
        content_response = requests.get(ht_stream_m3u8)

        if content_response.status_code == 200:
            content = content_response.text
            lines = content.split("\n")
            modified_content = ""

            for line in lines:
                if line.startswith("showturk"):
                    full_url = base_url + line
                    modified_content += full_url + "\n"
                else:
                    modified_content += line + "\n"

            print(modified_content)
        else:
            print("Canlı yayın URL'sinden içerik alınamadı.")
    else:
        print("Sayfa kaynak kodunda herhangi bir .m3u8 linki bulunamadı.")

else:
    print(f"Hata: Durum kodu {response.status_code}")
