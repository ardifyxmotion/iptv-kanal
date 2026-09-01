name: ShowMax IPTV

on:
schedule:
- cron: "16 */2 * * *"
workflow_dispatch:

permissions:
contents: write

jobs:
update:
runs-on: ubuntu-latest

```
steps:
  - name: Depoyu indir
    uses: actions/checkout@v4

  - name: Python kur
    uses: actions/setup-python@v5
    with:
      python-version: "3.x"

  - name: Gerekli kütüphaneleri yükle
    run: |
      pip install requests

  - name: ShowMax M3U8 güncelle
    run: |
      python res/26-2/shmax.py > res/26-2/shmax.m3u8

  - name: Değişiklikleri kaydet
    run: |
      git config --global user.name "github-actions[bot]"
      git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

      git add res/26-2/shmax.m3u8

      if git diff --cached --quiet; then
        echo "Değişiklik yok."
      else
        git commit -m "shmax updated"
        git push
      fi
```
