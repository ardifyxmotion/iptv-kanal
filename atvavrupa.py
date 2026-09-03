import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
STATE_FILENAME = os.path.join(STREAM_DIR, "atvavrupa_state.txt")

BASE_URL = "https://raw.githubusercontent.com/ardifyxmotion/iptv-kanal/main/streams/"
MAX_SEGMENTS = 500
HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_stream_url():
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

    media_sequence = 0
    target_duration = 10
    segments = []

    for line in lines:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(line.split(":", 1)[1])
            except ValueError:
                pass

        elif line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = int(line.split(":", 1)[1])
            except ValueError:
                pass

    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("#EXTINF:"):
            try:
                duration = line.split(":", 1)[1].split(",", 1)[0]
            except (IndexError, ValueError):
                index += 1
                continue

            next_index = index + 1

            while next_index < len(lines):
                next_line = lines[next_index]

                if not next_line.startswith("#"):
                    segments.append({
                        "duration": duration,
                        "url": urljoin(stream_url, next_line)
                    })
                    index = next_index
                    break

                next_index += 1

        index += 1

    if not segments:
        return None

    return {
        "media_sequence": media_sequence,
        "target_duration": target_duration,
        "segments": segments
    }


def load_state():
    """Son kullanılan kaynak ve yerel sıra numaralarını yükler."""

    state = {
        "last_source_sequence": None,
        "last_local_sequence": -1
    }

    if not os.path.exists(STATE_FILENAME):
        return state

    try:
        with open(STATE_FILENAME, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if "=" not in line:
                    continue

                key, value = line.split("=", 1)

                if key == "last_source_sequence":
                    state["last_source_sequence"] = int(value)

                elif key == "last_local_sequence":
                    state["last_local_sequence"] = int(value)

    except Exception as error:
        print(f"State dosyası okunamadı: {error}")

    return state


def save_state(last_source_sequence, last_local_sequence):
    """Son sıra numaralarını güvenli şekilde kaydeder."""

    temp_file = STATE_FILENAME + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(
            f"last_source_sequence={last_source_sequence}\n"
        )
        f.write(
            f"last_local_sequence={last_local_sequence}\n"
        )

    os.replace(temp_file, STATE_FILENAME)


def load_existing_playlist():
    """Mevcut M3U8 içindeki segmentleri okur."""

    entries = []

    if not os.path.exists(M3U8_FILENAME):
        return entries

    try:
        with open(
            M3U8_FILENAME,
            "r",
            encoding="utf-8"
        ) as f:
            lines = [
                line.strip()
                for line in f.readlines()
                if line.strip()
            ]

        current_duration = None

        for line in lines:
            if line.startswith("#EXTINF:"):
                current_duration = (
                    line.split(":", 1)[1]
                    .split(",", 1)[0]
                )

            elif (
                current_duration is not None
                and not line.startswith("#")
                and "seg_" in line
            ):
                filename = line.split("/")[-1]

                if (
                    filename.startswith("seg_")
                    and filename.endswith(".ts")
                ):
                    try:
                        sequence = int(
                            filename[4:-3]
                        )

                        filepath = os.path.join(
                            STREAM_DIR,
                            filename
                        )

                        if os.path.exists(filepath):
                            entries.append({
                                "sequence": sequence,
                                "duration": current_duration,
                                "filename": filename
                            })

                    except ValueError:
                        pass

                current_duration = None

    except Exception as error:
        print(f"Eski M3U8 okunamadı: {error}")

    return entries


def download_segment(item):
    filename, url = item
    filepath = os.path.join(STREAM_DIR, filename)

    # Dosya zaten varsa tekrar indirme
    if os.path.exists(filepath):
        return filename

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=60
        )

        response.raise_for_status()

        temp_path = filepath + ".tmp"

        with open(temp_path, "wb") as f:
            f.write(response.content)

        os.replace(temp_path, filepath)

        return filename

    except Exception as error:
        print(
            f"Segment indirilemedi: "
            f"{filename} -> {error}"
        )

        return None


def clean_old_segments(current_files):
    existing_files = glob.glob(
        os.path.join(STREAM_DIR, "seg_*.ts")
    )

    for filepath in existing_files:
        filename = os.path.basename(filepath)

        if filename not in current_files:
            try:
                os.remove(filepath)
            except OSError:
                pass


def main():
    os.makedirs(STREAM_DIR, exist_ok=True)

    try:
        # Daha önce kaydedilen yayın durumu
        state = load_state()

        last_source_sequence = (
            state["last_source_sequence"]
        )

        last_local_sequence = (
            state["last_local_sequence"]
        )

        # Mevcut oynatma listesini oku
        existing_entries = load_existing_playlist()

        if existing_entries:
            max_existing_sequence = max(
                entry["sequence"]
                for entry in existing_entries
            )

            last_local_sequence = max(
                last_local_sequence,
                max_existing_sequence
            )

        # Gerçek yayın adresini bul
        stream_url = get_stream_url()

        if not stream_url:
            return

        print(f"Canlı yayın bulundu:\n{stream_url}")

        playlist = get_playlist(stream_url)

        if not playlist:
            print("M3U8 içerisinde segment bulunamadı.")
            return

        source_media_sequence = (
            playlist["media_sequence"]
        )

        target_duration = (
            playlist["target_duration"]
        )

        source_segments = (
            playlist["segments"]
        )

        print(
            f"Kaynak segment sayısı: "
            f"{len(source_segments)}"
        )

        print(
            f"Kaynak MEDIA-SEQUENCE: "
            f"{source_media_sequence}"
        )

        # Kaynaktaki her segmente gerçek kaynak sıra numarası ata
        source_entries = []

        for index, segment in enumerate(
            source_segments
        ):
            source_sequence = (
                source_media_sequence + index
            )

            source_entries.append({
                "source_sequence": source_sequence,
                "duration": segment["duration"],
                "url": segment["url"]
            })

        new_source_entries = []

        for entry in source_entries:

            # İlk çalıştırmada kaynakta bulunan tüm
            # segmentler alınabilir.
            if last_source_sequence is None:
                new_source_entries.append(entry)

            # Son işlenen kaynak segmentinden
            # daha yeni olanları al.
            elif (
                entry["source_sequence"]
                > last_source_sequence
            ):
                new_source_entries.append(entry)

        if not new_source_entries:
            print(
                "Yeni segment bulunamadı. "
                "Mevcut yayın korunuyor."
            )

            # Eski M3U8'i kesinlikle silme
            return

        print(
            f"Yeni segment sayısı: "
            f"{len(new_source_entries)}"
        )

        # Yeni segmentlere yerel ve sürekli sıra numarası ver
        files_to_download = []
        new_entries = []

        next_local_sequence = (
            last_local_sequence + 1
        )

        for source_entry in new_source_entries:

            local_sequence = (
                next_local_sequence
            )

            filename = (
                f"seg_{local_sequence}.ts"
            )

            new_entries.append({
                "sequence": local_sequence,
                "source_sequence": (
                    source_entry["source_sequence"]
                ),
                "duration": source_entry["duration"],
                "filename": filename,
                "url": source_entry["url"]
            })

            files_to_download.append(
                (
                    filename,
                    source_entry["url"]
                )
            )

            next_local_sequence += 1

        # Segmentleri paralel indir
        with ThreadPoolExecutor(
            max_workers=10
        ) as executor:

            download_results = list(
                executor.map(
                    download_segment,
                    files_to_download
                )
            )

        successful_files = {
            filename
            for filename in download_results
            if filename is not None
        }

        successful_new_entries = [
            entry
            for entry in new_entries
            if entry["filename"]
            in successful_files
        ]

        if not successful_new_entries:
            print(
                "Yeni segmentlerin hiçbiri "
                "indirilemedi. Eski yayın korunuyor."
            )
            return

        # Eski ve yeni segmentleri birleştir
        all_entries = (
            existing_entries +
            [
                {
                    "sequence": entry["sequence"],
                    "duration": entry["duration"],
                    "filename": entry["filename"]
                }
                for entry in successful_new_entries
            ]
        )

        # Aynı yerel sıra numarasını bir kez tut
        unique_entries = {}

        for entry in all_entries:
            unique_entries[
                entry["sequence"]
            ] = entry

        all_entries = sorted(
            unique_entries.values(),
            key=lambda item: item["sequence"]
        )

        # Son MAX_SEGMENTS segmenti tut
        if len(all_entries) > MAX_SEGMENTS:
            all_entries = all_entries[
                -MAX_SEGMENTS:
            ]

        if not all_entries:
            print("Yazılacak segment yok.")
            return

        first_sequence = (
            all_entries[0]["sequence"]
        )

        # Yeni M3U8'i önce geçici dosyada oluştur
        temp_playlist = (
            M3U8_FILENAME + ".tmp"
        )

        with open(
            temp_playlist,
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

            for entry in all_entries:
                f.write(
                    f"#EXTINF:"
                    f"{entry['duration']},\n"
                )
                f.write(
                    f"{BASE_URL}"
                    f"{entry['filename']}\n"
                )

        # Başarıyla oluşturulduktan sonra değiştir
        os.replace(
            temp_playlist,
            M3U8_FILENAME
        )

        # State dosyasını güncelle
        latest_source_sequence = max(
            entry["source_sequence"]
            for entry in successful_new_entries
        )

        latest_local_sequence = max(
            entry["sequence"]
            for entry in successful_new_entries
        )

        save_state(
            latest_source_sequence,
            latest_local_sequence
        )

        # Artık kullanılmayan segmentleri sil
        current_files = {
            entry["filename"]
            for entry in all_entries
        }

        clean_old_segments(current_files)

        print(
            f"Başarılı: "
            f"{len(successful_new_entries)} "
            f"yeni segment eklendi."
        )

        print(
            f"Toplam segment: "
            f"{len(all_entries)}"
        )

        print(
            f"Son kaynak sıra: "
            f"{latest_source_sequence}"
        )

        print(
            f"Son yerel sıra: "
            f"{latest_local_sequence}"
        )

    except Exception as error:
        print(f"Genel hata: {error}")


if __name__ == "__main__":
    main()
