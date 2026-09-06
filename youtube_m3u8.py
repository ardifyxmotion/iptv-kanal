import yt_dlp

YOUTUBE_URL = "https://www.youtube.com/watch?v=JpP13Wp1ke0"
OUTPUT_FILE = "aski-memnu.m3u8"

ydl_opts = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(YOUTUBE_URL, download=False)

    formats = info.get("formats", [])
    m3u8_url = None

    for f in formats:
        url = f.get("url", "")

        if "manifest.googlevideo.com" in url or "playlist/index.m3u8" in url:
            m3u8_url = url

            if f.get("height", 0) >= 720:
                break

    if not m3u8_url:
        raise Exception("M3U8 bağlantısı bulunamadı.")

    playlist = f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1280000
{m3u8_url}
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(playlist)

    print("M3U8 başarıyla güncellendi.")
    print(m3u8_url)

except Exception as e:
    print(f"HATA: {e}")
    raise
