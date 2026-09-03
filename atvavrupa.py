"""
24 saatlik HLS DVR örneği

Bu örnek yalnızca sahip olduğunuz veya yeniden dağıtım hakkınız bulunan
canlı yayın kaynakları için kullanılmalıdır.

Kullanım:
1. INPUT_URL değerine yetkili olduğunuz HLS (.m3u8) kaynağını yazın.
2. ffmpeg ve Python kurulu olmalıdır.
3. python3 dvr.py

Sistem FFmpeg'i sürekli çalıştırır, HLS segmentleri oluşturur ve yaklaşık
24 saatlik segment penceresini korur.
"""

import os
import subprocess

# Yetkili olduğunuz canlı HLS kaynağını buraya yazın.
INPUT_URL = "https://example.com/authorized-live-stream.m3u8"

OUTPUT_DIR = "streams"
PLAYLIST_NAME = "live.m3u8"

# 10 saniyelik segmentlerde yaklaşık 24 saat:
# 24 * 60 * 60 / 10 = 8640 segment
SEGMENT_SECONDS = 10
LIST_SIZE = 8640


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

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

        # Kaynağı otomatik yeniden bağlanabilir şekilde okumaya çalış.
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "10",

        "-i", INPUT_URL,

        # Kaynak codec'lerini yeniden kodlamadan kopyala.
        "-c", "copy",

        "-f", "hls",
        "-hls_time", str(SEGMENT_SECONDS),

        # Yaklaşık 24 saatlik DVR penceresi.
        "-hls_list_size", str(LIST_SIZE),

        # Pencereden çıkan segmentleri otomatik sil.
        "-hls_flags", "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        segment_pattern,

        playlist_path
    ]

    print("24 saatlik HLS DVR başlatılıyor...")
    print("Çıkış klasörü:", OUTPUT_DIR)

    try:
        subprocess.run(command, check=True)

    except KeyboardInterrupt:
        print("\nDVR durduruldu.")

    except subprocess.CalledProcessError as error:
        print("FFmpeg hatası:", error)


if __name__ == "__main__":
    main()
