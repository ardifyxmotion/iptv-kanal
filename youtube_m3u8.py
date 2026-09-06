import os
import yt_dlp

YOUTUBE_URL = "https://www.youtube.com/watch?v=JpP13Wp1ke0"
OUTPUT_FILE = "aski-memnu.m3u8"

ydl_opts = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "cookiefile": "cookies.txt",
}

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(YOUTUBE_URL, download=False)

    m3u8_url = None

    for f in info.get("formats", []):
        url = f.get("url", "")

        if (
            "manifest.googlevideo.com" in url
            or "playlist/index.m3u8" in url
        ):
            m3u8_url = url

            if f.get("height", 0) >= 720:
                break

    if not m3u8_url:
        raise Exception("M3U8 bağlantısı bulunamadı.")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write("#EXTM3U\n")
        file.write("#EXT-X-STREAM-INF:BANDWIDTH=1280000\n")
        file.write(m3u8_url)

    print("M3U8 başarıyla güncellendi.")

except Exception as e:
    print(f"HATA: {e}")
    raise
