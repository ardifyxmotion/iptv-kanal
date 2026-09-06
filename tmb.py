import os

M3U8_URL = "https://str.yodacdn.net/tmb_az_app/tracks-v1a1/mono.ts.m3u8?token=tmb_app_token_13579"

content = f"""#EXTM3U
#EXTINF:-1 tvg-name="TMB",TMB TV
{M3U8_URL}
"""

output_file = "tmb.m3u8"

with open(output_file, "w", encoding="utf-8") as file:
    file.write(content)

print(f"{output_file} başarıyla oluşturuldu.")
