import os
import re
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILENAME = os.path.join(STREAM_DIR, "atvavrupa_state.txt")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"

# Yaklaşık 1 saatten fazla geçmiş için artırılabilir.
MAX_SEGMENTS = 1000

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
    """Kaynak M3U8 listesini ve segment bilgilerini alır."""

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
    media_sequence = 0
    segments = []

    for line in lines:

        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

        elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(
                    line.split(":", 1)[1]
                )
            except ValueError:
                pass

    index = 0

    while index < len(lines):

        if lines[index].startswith("#EXTINF:"):

            try:
                duration = (
                    lines[index]
                    .split(":", 1)[1]
                    .split(",", 1)[0]
                )
            except (IndexError, ValueError):
                index += 1
                continue

            next_index = index + 1

            while next_index < len(lines):

                next_line = lines[next_index]

                if not next_line.startswith("#"):

                    segment_url = urljoin(
                        stream_url,
                        next_line
                    )

                    source_sequence = (
                        media_sequence +
                        len(segments)
                    )

                    segments.append(
                        {
                            "duration": duration,
                            "url": segment_url,
                            "source_sequence": source_sequence
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


def read_old_playlist():
    """Mevcut M3U8 geçmişini okur."""

    if not os.path.exists(M3U8_FILENAME):
        return []

    entries = []
    current_duration = None

    try:

        with open(
            M3U8_FILENAME,
            "r",
            encoding="utf-8"
        ) as f:

            for raw_line in f:

                line = raw_line.strip()

                if not line:
                    continue

                if line.startswith("#EXTINF:"):

                    try:
                        current_duration = (
                            line
                            .split(":", 1)[1]
                            .split(",", 1)[0]
                        )
                    except (IndexError, ValueError):
                        current_duration = None

                elif (
                    current_duration is not None
                    and not line.startswith("#")
                ):

                    filename = line.split("/")[-1]

                    match = re.match(
                        r"seg_(\d+)\.ts$",
                        filename
                    )

                    if match:

                        sequence = int(
                            match.group(1)
                        )

                        filepath = os.path.join(
                            STREAM_DIR,
                            filename
                        )

                        if os.path.exists(filepath):

                            entries.append(
                                {
                                    "sequence": sequence,
                                    "duration": current_duration,
                                    "filename": filename
                                }
                            )

                    current_duration = None

    except Exception as error:

        print(
            f"Eski liste okunamadı: {error}"
        )

        return []

    return entries


def read_state():
    """
    Son indirilen kaynak segmentlerini ve
    kendi sürekli segment numaramızı okur.
    """

    state = {
        "last_source_sequence": -1,
        "last_local_sequence": 0
    }

    if not os.path.exists(STATE_FILENAME):
        return state

    try:

        with open(
            STATE_FILENAME,
            "r",
            encoding="utf-8"
        ) as f:

            for line in f:

                line = line.strip()

                if "=" not in line:
                    continue

                key, value = line.split(
                    "=",
                    1
                )

                try:
                    state[key] = int(value)
                except ValueError:
                    pass

    except Exception as error:
        print(f"State okunamadı: {error}")

    return state


def save_state(
    last_source_sequence,
    last_local_sequence
):
    """Son durum bilgilerini kaydeder."""

    temp_state = (
        STATE_FILENAME + ".tmp"
    )

    with open(
        temp_state,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            f"last_source_sequence="
            f"{last_source_sequence}\n"
        )

        f.write(
            f"last_local_sequence="
            f"{last_local_sequence}\n"
        )

    os.replace(
        temp_state,
        STATE_FILENAME
    )


def get_highest_local_sequence(entries):
    """Disk ve playlist içindeki en büyük yerel numarayı bulur."""

    highest = 0

    for entry in entries:
        highest = max(
            highest,
            entry["sequence"]
        )

    for filepath in glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*.ts"
        )
    ):

        filename = os.path.basename(
            filepath
        )

        match = re.match(
            r"seg_(\d+)\.ts$",
            filename
        )

        if match:
            highest = max(
                highest,
                int(match.group(1))
            )

    return highest


def download_segment(item):
    """Tek bir segmenti indirir."""

    filename, url = item

    filepath = os.path.join(
        STREAM_DIR,
        filename
    )

    if os.path.exists(filepath):
        return filename

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        if not response.content:
            return None

        temp_path = (
            filepath + ".tmp"
        )

        with open(
            temp_path,
            "wb"
        ) as f:

            f.write(response.content)

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

        return None


def clean_old_segments(current_files):
    """Artık playlist içinde olmayan segmentleri siler."""

    existing_files = glob.glob(
        os.path.join(
            STREAM_DIR,
            "seg_*.ts"
        )
    )

    for filepath in existing_files:

        filename = os.path.basename(
            filepath
        )

        if filename not in current_files:

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

        # 1. Mevcut geçmişi oku
        old_entries = read_old_playlist()

        print(
            f"Korunan eski segment: "
            f"{len(old_entries)}"
        )

        # 2. Son durumu oku
        state = read_state()

        last_source_sequence = state.get(
            "last_source_sequence",
            -1
        )

        last_local_sequence = max(
            state.get(
                "last_local_sequence",
                0
            ),
            get_highest_local_sequence(
                old_entries
            )
        )

        # 3. Canlı yayın adresini bul
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(
            f"Canlı yayın bulundu:\n"
            f"{stream_url}"
        )

        # 4. Kaynak playlist'i al
        playlist = get_playlist(
            stream_url
        )

        if not playlist:
            print("Segment bulunamadı.")
            return

        source_segments = playlist[
            "segments"
        ]

        target_duration = playlist[
            "target_duration"
        ]

        print(
            f"Kaynak segment sayısı: "
            f"{len(source_segments)}"
        )

        # 5. Daha önce işlenmemiş segmentleri bul
        new_source_segments = [

            segment

            for segment in source_segments

            if segment["source_sequence"]
            > last_source_sequence

        ]

        # İlk çalıştırmada kaynakta görünen
        # segmentlerin tamamını indir.
        if last_source_sequence < 0:

            new_source_segments = source_segments

        if not new_source_segments:

            print(
                "Yeni segment bulunamadı. "
                "Eski liste korunuyor."
            )

            # Mevcut state'i ve playlist'i değiştirme.
            return

        # 6. Her yeni segmente kendi sürekli numaramızı ver
        files_to_download = []
        pending_entries = []

        for segment in new_source_segments:

            last_local_sequence += 1

            filename = (
                f"seg_{last_local_sequence}.ts"
            )

            files_to_download.append(
                (
                    filename,
                    segment["url"]
                )
            )

            pending_entries.append(
                {
                    "sequence": last_local_sequence,
                    "duration": segment[
                        "duration"
                    ],
                    "filename": filename,
                    "source_sequence": segment[
                        "source_sequence"
                    ]
                }
            )

        # 7. Segmentleri paralel indir
        with ThreadPoolExecutor(
            max_workers=10
        ) as executor:

            results = list(
                executor.map(
                    download_segment,
                    files_to_download
                )
            )

        successful_files = {

            filename
            for filename in results
            if filename is not None

        }

        successful_entries = [

            entry

            for entry in pending_entries

            if entry["filename"]
            in successful_files

        ]

        if not successful_entries:

            print(
                "Yeni segmentler indirilemedi. "
                "Eski playlist korunuyor."
            )

            return

        # 8. Eski ve yeni segmentleri birleştir
        playlist_entries = (
            old_entries +
            successful_entries
        )

        # Yerel sıra numarasına göre sırala
        playlist_entries = sorted(
            playlist_entries,
            key=lambda x: x["sequence"]
        )

        # Aynı yerel sıra numarasını tekrar etme
        unique_entries = {}
        for entry in playlist_entries:
            unique_entries[
                entry["sequence"]
            ] = entry

        playlist_entries = sorted(
            unique_entries.values(),
            key=lambda x: x["sequence"]
        )

        # 9. Maksimum geçmiş sınırı
        if len(playlist_entries) > MAX_SEGMENTS:

            playlist_entries = (
                playlist_entries[-MAX_SEGMENTS:]
            )

        # 10. Yeni M3U8'i güvenli oluştur
        temp_m3u8 = (
            M3U8_FILENAME + ".tmp"
        )

        first_sequence = (
            playlist_entries[0]["sequence"]
        )

        with open(
            temp_m3u8,
            "w",
            encoding="utf-8"
        ) as f:

            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")

            f.write(
                f"#EXT-X-TARGETDURATION:"
                f"{target_duration}\n"
            )

            f.write(
                f"#EXT-X-MEDIA-SEQUENCE:"
                f"{first_sequence}\n"
            )

            for entry in playlist_entries:

                f.write(
                    f"#EXTINF:"
                    f"{entry['duration']},\n"
                )

                f.write(
                    f"{BASE_URL}"
                    f"{entry['filename']}\n"
                )

        # Playlist tamamen hazır olduktan sonra değiştir
        os.replace(
            temp_m3u8,
            M3U8_FILENAME
        )

        # 11. State'i yalnızca başarılı segmentlere göre güncelle
        last_successful_source = max(
            entry["source_sequence"]
            for entry in successful_entries
        )

        last_successful_local = max(
            entry["sequence"]
            for entry in successful_entries
        )

        save_state(
            last_successful_source,
            last_successful_local
        )

        # 12. Playlist dışındaki eski segmentleri sil
        current_files = {

            entry["filename"]
            for entry in playlist_entries

        }

        clean_old_segments(
            current_files
        )

        print(
            f"Toplam geçmiş: "
            f"{len(playlist_entries)} segment"
        )

        print(
            f"Son yerel segment: "
            f"{last_successful_local}"
        )

        print(
            f"Son kaynak segment: "
            f"{last_successful_source}"
        )

    except Exception as error:
        print(f"Genel hata: {error}")


if __name__ == "__main__":
    main()
