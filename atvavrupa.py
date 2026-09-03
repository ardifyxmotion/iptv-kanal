import os
import re
import json
import glob
import time
import hashlib
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

# ============================================================
# ATV AVRUPA - KALICI DVR KAYIT SİSTEMİ
#
# Mantık:
# - Her çalıştırmada kaynak canlı playlist okunur.
# - Daha önce kaydedilmiş segmentler M3U8'den okunur.
# - Yeni segmentler mevcut geçmişe eklenir.
# - Aynı segment tekrar eklenmez.
# - En fazla MAX_SEGMENTS kadar geçmiş korunur.
# - M3U8 dosyası atomik olarak güncellenir.
# ============================================================

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")

# GitHub RAW segment adresi
BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

# Yaklaşık 24 saatlik geçmiş için değer.
# Ortalama segment süresine göre gerektiğinde artırılabilir.
MAX_SEGMENTS = 10000

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_stream_url():
    """Streamlink ile gerçek canlı yayın M3U8 adresini bulur."""
    try:
        result = subprocess.run(
            [
                "streamlink",
                "--stream-url",
                "https://www.atvavrupa.tv/canli-yayin",
                "best"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        stream_url = result.stdout.strip()

        if not stream_url:
            print("Yayın URL'si bulunamadı.")
            print(result.stderr)
            return None

        return stream_url

    except Exception as error:
        print(f"Streamlink hatası: {error}")
        return None


def get_playlist(stream_url):
    """
    Kaynak canlı M3U8 listesini okur.

    Segmentler MEDIA-SEQUENCE yerine gerçek URL üzerinden
    benzersiz olarak takip edilir. Böylece yayın sağlayıcısının
    sıra numarasını sıfırlaması durumunda eski segmentlerin
    üzerine yanlışlıkla yazılması engellenir.
    """

    response = requests.get(
        stream_url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    lines = [
        line.strip()
        for line in response.text.splitlines()
        if line.strip()
    ]

    target_duration = 10
    segments = []

    for line in lines:
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("#EXTINF:"):
            try:
                duration = float(
                    line.split(
                        ":", 1
                    )[1].split(",", 1)[0]
                )
            except (IndexError, ValueError):
                index += 1
                continue

            next_index = index + 1

            while next_index < len(lines):
                next_line = lines[next_index]

                # EXTINF sonrasında URL bulunana kadar
                # diğer HLS etiketlerini geç.
                if not next_line.startswith("#"):
                    segment_url = urljoin(
                        stream_url,
                        next_line
                    )

                    segments.append(
                        {
                            "duration": duration,
                            "url": segment_url
                        }
                    )

                    index = next_index
                    break

                next_index += 1

        index += 1

    if not segments:
        return None

    return {
        "target_duration": target_duration,
        "segments": segments
    }


def make_segment_filename(segment_url):
    """
    Segment URL'sinden benzersiz dosya adı üretir.

    Sadece MEDIA-SEQUENCE kullanılmaz çünkü bazı yayınlarda
    sıra numaraları tekrar başlayabilir.
    """

    url_hash = hashlib.sha256(
        segment_url.encode("utf-8")
    ).hexdigest()[:24]

    return f"seg_{url_hash}.ts"


def read_existing_playlist():
    """
    Daha önce oluşturulmuş DVR playlistini okur.

    M3U8'deki segmentler korunur ve sonraki GitHub Actions
    çalıştırmasında yeni segmentlerle birleştirilir.
    """

    entries = []

    if not os.path.exists(M3U8_FILENAME):
        return entries

    try:
        with open(
            M3U8_FILENAME,
            "r",
            encoding="utf-8"
        ) as file:

            lines = [
                line.strip()
                for line in file
                if line.strip()
            ]

        index = 0

        while index < len(lines):
            line = lines[index]

            if line.startswith("#EXTINF:"):
                try:
                    duration = float(
                        line.split(
                            ":", 1
                        )[1].split(",", 1)[0]
                    )
                except (IndexError, ValueError):
                    index += 1
                    continue

                if index + 1 < len(lines):
                    segment_path = lines[
                        index + 1
                    ]

                    filename = (
                        segment_path
                        .split("?", 1)[0]
                        .rsplit("/", 1)[-1]
                    )

                    filepath = os.path.join(
                        STREAM_DIR,
                        filename
                    )

                    # Segment dosyası gerçekten mevcutsa
                    # DVR geçmişinde tut.
                    if (
                        filename.startswith("seg_")
                        and filename.endswith(".ts")
                        and os.path.exists(filepath)
                    ):
                        entries.append(
                            {
                                "duration": duration,
                                "filename": filename
                            }
                        )

                    index += 1

            index += 1

    except Exception as error:
        print(
            f"Eski DVR listesi okunamadı: "
            f"{error}"
        )

    return entries


def download_segment(item):
    """
    Segmenti indirir.

    Dosya daha önce indirilmişse tekrar indirmez.
    """

    filename, url = item

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if (
        os.path.exists(filepath)
        and os.path.getsize(filepath) > 100
    ):
        return filename

    temp_path = filepath + ".tmp"

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=60
        )

        response.raise_for_status()

        content = response.content

        if len(content) < 100:
            print(
                f"Geçersiz veya boş segment: "
                f"{filename}"
            )
            return None

        with open(
            temp_path,
            "wb"
        ) as file:
            file.write(content)

        os.replace(
            temp_path,
            filepath
        )

        return filename

    except Exception as error:
        print(
            f"Segment indirilemedi: "
            f"{filename} -> {error}"
        )

        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass

        return None


def write_playlist(
    entries,
    target_duration
):
    """
    DVR M3U8 dosyasını atomik olarak yazar.

    Önce geçici dosya oluşturulur. Yazma tamamen başarılı
    olduğunda eski playlist değiştirilir. Böylece GitHub
    Actions tam yazım sırasında kesilse bile playlist bozulmaz.
    """

    if not entries:
        return False

    temp_playlist = (
        M3U8_FILENAME + ".tmp"
    )

    try:
        with open(
            temp_playlist,
            "w",
            encoding="utf-8"
        ) as file:

            file.write("#EXTM3U\n")
            file.write("#EXT-X-VERSION:3\n")

            file.write(
                "#EXT-X-TARGETDURATION:"
                f"{int(target_duration)}\n"
            )

            # DVR playlistinin sıra numarası sabit olarak
            # sıfırdan başlatılır. Dosya sırası asıl geçmişi
            # belirler.
            file.write(
                "#EXT-X-MEDIA-SEQUENCE:0\n"
            )

            for entry in entries:
                file.write(
                    f"#EXTINF:"
                    f"{entry['duration']:.3f},\n"
                )

                file.write(
                    f"{BASE_URL}"
                    f"{entry['filename']}\n"
                )

        os.replace(
            temp_playlist,
            M3U8_FILENAME
        )

        return True

    except Exception as error:
        print(
            f"M3U8 yazılamadı: {error}"
        )

        try:
            if os.path.exists(temp_playlist):
                os.remove(temp_playlist)
        except OSError:
            pass

        return False


def clean_old_segments(valid_files):
    """
    Yalnızca MAX_SEGMENTS sınırının dışına çıkan
    segment dosyalarını siler.
    """

    for filepath in glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*.ts"
        )
    ):
        filename = os.path.basename(
            filepath
        )

        if filename not in valid_files:
            try:
                os.remove(filepath)
            except OSError:
                pass


def main():
    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    try:
        # ----------------------------------------------------
        # 1. ÖNCE ESKİ DVR GEÇMİŞİNİ OKU
        # ----------------------------------------------------
        old_entries = (
            read_existing_playlist()
        )

        print(
            f"Korunan eski DVR segmenti: "
            f"{len(old_entries)}"
        )

        existing_files = {
            entry["filename"]
            for entry in old_entries
        }

        # ----------------------------------------------------
        # 2. GÜNCEL CANLI YAYINI BUL
        # ----------------------------------------------------
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            "Canlı yayın bulundu."
        )

        # ----------------------------------------------------
        # 3. GÜNCEL PLAYLIST'I OKU
        # ----------------------------------------------------
        playlist = get_playlist(
            stream_url
        )

        if not playlist:
            print(
                "Kaynak M3U8 içinde "
                "segment bulunamadı."
            )
            return

        target_duration = playlist[
            "target_duration"
        ]

        source_segments = playlist[
            "segments"
        ]

        print(
            f"Kaynak segment sayısı: "
            f"{len(source_segments)}"
        )

        # ----------------------------------------------------
        # 4. SADECE YENİ SEGMENTLERİ BELİRLE
        # ----------------------------------------------------
        new_items = []

        for segment in source_segments:
            filename = make_segment_filename(
                segment["url"]
            )

            if filename not in existing_files:
                new_items.append(
                    (
                        filename,
                        segment["url"],
                        segment["duration"]
                    )
                )

        print(
            f"Yeni segment adayı: "
            f"{len(new_items)}"
        )

        # ----------------------------------------------------
        # 5. YENİ SEGMENTLERİ PARALEL İNDİR
        # ----------------------------------------------------
        download_items = [
            (filename, url)
            for filename, url, duration
            in new_items
        ]

        successful_files = set()

        if download_items:
            with ThreadPoolExecutor(
                max_workers=10
            ) as executor:

                results = list(
                    executor.map(
                        download_segment,
                        download_items
                    )
                )

            successful_files = {
                filename
                for filename in results
                if filename is not None
            }

        print(
            f"Başarıyla indirilen yeni segment: "
            f"{len(successful_files)}"
        )

        # ----------------------------------------------------
        # 6. ESKİ DVR + YENİ SEGMENTLERİ BİRLEŞTİR
        # ----------------------------------------------------
        all_entries = list(
            old_entries
        )

        # Kaynak playlist sırası korunur.
        for filename, url, duration in new_items:
            if filename in successful_files:
                all_entries.append(
                    {
                        "duration": duration,
                        "filename": filename
                    }
                )

        # Aynı dosyanın iki kez eklenmesini engelle
        unique_entries = []
        seen_files = set()

        for entry in all_entries:
            filename = entry["filename"]

            if filename not in seen_files:
                seen_files.add(
                    filename
                )

                unique_entries.append(
                    entry
                )

        all_entries = unique_entries

        # ----------------------------------------------------
        # 7. SADECE SON MAX_SEGMENTS KADARINI KORU
        # ----------------------------------------------------
        if len(all_entries) > MAX_SEGMENTS:
            all_entries = all_entries[
                -MAX_SEGMENTS:
            ]

        if not all_entries:
            print(
                "DVR için kullanılabilir "
                "segment yok."
            )
            return

        # ----------------------------------------------------
        # 8. YENİ DVR PLAYLIST'INI YAZ
        # ----------------------------------------------------
        success = write_playlist(
            all_entries,
            target_duration
        )

        if not success:
            return

        # ----------------------------------------------------
        # 9. SADECE PLAYLIST'TE OLMAYAN ÇOK ESKİ
        #    SEGMENTLERİ SİL
        # ----------------------------------------------------
        valid_files = {
            entry["filename"]
            for entry in all_entries
        }

        clean_old_segments(
            valid_files
        )

        # Toplam DVR süresini hesapla
        total_duration = sum(
            entry["duration"]
            for entry in all_entries
        )

        total_hours = (
            total_duration / 3600
        )

        print(
            "================================="
        )

        print(
            f"Toplam DVR segmenti: "
            f"{len(all_entries)}"
        )

        print(
            f"Yaklaşık DVR geçmişi: "
            f"{total_hours:.2f} saat"
        )

        print(
            "DVR playlist başarıyla "
            "güncellendi."
        )

        print(
            "================================="
        )

    except Exception as error:
        print(
            f"Genel hata: {error}"
        )


if __name__ == "__main__":
    main()
