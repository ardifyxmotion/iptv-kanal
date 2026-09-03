import os
import subprocess

# 24 saatlik HLS DVR
# Yalnızca kaydetme veya yeniden dağıtma hakkınız bulunan yayınlarla kullanın.

INPUT_PAGE = "https://www.atvavrupa.tv/canli-yayin"

OUTPUT_DIR = "streams"
PLAYLIST_NAME = "atvavrupa.m3u8"

# 10 saniyelik segmentlerde:
# 24 * 60 * 60 / 10 = 8640 segment
SEGMENT_SECONDS = 10
LIST_SIZE = 8640


def get_stream_url():
    """Streamlink ile canlı yayının gerçek akış URL'sini alır."""

    try:
        result = subprocess.run(
            [
                "streamlink",
                "--stream-url",
                INPUT_PAGE,
                "best"
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False
        )

        stream_url = result.stdout.strip()

        if not stream_url:
            print("Yayın URL'si bulunamadı.")
            print(result.stderr)
            return None

        print("Canlı yayın URL'si bulundu.")
        return stream_url

    except Exception as error:
        print(f"Streamlink hatası: {error}")
        return None


def main():
    # streams klasörünü oluştur
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Önce gerçek canlı yayın URL'sini al
    input_url = get_stream_url()

    if not input_url:
        return

    playlist_path = os.path.join(
        OUTPUT_DIR,
        PLAYLIST_NAME
    )

    segment_pattern = os.path.join(
        OUTPUT_DIR,
        "seg_%09d.ts"
    )

    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",

        # Bağlantı kesilirse yeniden bağlanmayı dene
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "10",

        "-i", input_url,

        # Kaynak codec'lerini yeniden kodlamadan kopyala
        "-c", "copy",

        # HLS çıkışı
        "-f", "hls",

        # Her segment yaklaşık 10 saniye
        "-hls_time", str(SEGMENT_SECONDS),

        # Yaklaşık 24 saatlik DVR listesi
        "-hls_list_size", str(LIST_SIZE),

        # 24 saatlik pencerenin dışındaki segmentleri sil
        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        # Segment dosyalarının adı
        "-hls_segment_filename",
        segment_pattern,

        # M3U8 oynatma listesi
        playlist_path
    ]

    print("========================================")
    print("24 saatlik HLS DVR başlatılıyor...")
    print("Canlı yayın sayfası:", INPUT_PAGE)
    print("Çıkış klasörü:", OUTPUT_DIR)
    print("M3U8 dosyası:", playlist_path)
    print("Segment süresi:", SEGMENT_SECONDS, "saniye")
    print("Maksimum segment:", LIST_SIZE)
    print("========================================")

    try:
        subprocess.run(command, check=True)

    except KeyboardInterrupt:
        print("\nDVR durduruldu.")

    except subprocess.CalledProcessError as error:
        print("FFmpeg hatası:", error)


if __name__ == "__main__":
    main()
