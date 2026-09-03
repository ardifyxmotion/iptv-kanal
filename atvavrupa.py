import os
import glob
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor

STREAM_DIR = "streams"
M3U8_FILENAME = os.path.join(STREAM_DIR, "atvavrupa.m3u8")
SEQUENCE_FILE = os.path.join(STREAM_DIR, "sequence.txt")
MAX_SEGMENTS = 160

BASE_URL = "https://bnyusuf67-crypto.github.io/streams/"

def download_segment(args):
    fname, url = args
    fpath = os.path.join(STREAM_DIR, fname)
    if os.path.exists(fpath): 
        return
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            with open(fpath, 'wb') as f: 
                f.write(res.content)
    except: 
        pass

def get_next_sequence():
    seq = 0
    if os.path.exists(SEQUENCE_FILE):
        try:
            with open(SEQUENCE_FILE, "r") as f:
                seq = int(f.read().strip())
        except:
            seq = 0
    return seq

def save_sequence(seq):
    with open(SEQUENCE_FILE, "w") as f:
        f.write(str(seq))

def main():
    os.makedirs(STREAM_DIR, exist_ok=True)
    
    # 1. Streamlink ile canlı yayın adresini al
    try:
        cmd = ["streamlink", "--stream-url", "https://www.atvavrupa.tv/canli-yayin", "best"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        stream_url = result.stdout.strip()
        if not stream_url: 
            return
    except: 
        return

    # 2. M3U8 listesini çek
    try:
        r = requests.get(stream_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r.status_code != 200: 
            return
        
        lines = [l for l in r.text.splitlines() if l and not l.startswith("#")]
        base_url = stream_url.rsplit('/', 1)[0] + '/'
        
        target_urls = [l if l.startswith("http") else base_url + l for l in lines[-MAX_SEGMENTS:]]
        
        start_seq = get_next_sequence()
        
        target_files = {}
        for i, url in enumerate(target_urls):
            current_seq_num = start_seq + i
            fname = f"seg_{current_seq_num}.ts"
            target_files[fname] = url

        # 3. ThreadPoolExecutor İle Hızlı İndirme
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(download_segment, target_files.items())

        # 4. Eski segmentleri temizle ve sequence'i kaydet
        existing_files = set(os.path.basename(f) for f in glob.glob(os.path.join(STREAM_DIR, "*.ts")))
        for fname in (existing_files - set(target_files.keys())):
            try:
                os.remove(os.path.join(STREAM_DIR, fname))
            except:
                pass
                
        new_start_seq = start_seq + len(target_urls) - MAX_SEGMENTS
        if new_start_seq < 0:
            new_start_seq = 0
        save_sequence(new_start_seq)

        # 5. M3U8 dosyasını sabit 10 saniye hedef süreyle yaz
        media_sequence = start_seq
        with open(M3U8_FILENAME, "w") as f:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")
            f.write(f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}\n")
            f.write("#EXT-X-TARGETDURATION:10\n") # Doğru hedef süre
            
            for fname in sorted(target_files.keys(), key=lambda x: int(x.split('_')[1].split('.')[0])):
                f.write(f"#EXTINF:10.0,\n{BASE_URL}{fname}\n")

    except: 
        pass

if __name__ == "__main__":
    main()
