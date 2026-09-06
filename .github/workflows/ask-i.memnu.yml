name: YouTube M3U8 Güncelleme

on:
  schedule:
    - cron: "0 */4 * * *"

  workflow_dispatch:

permissions:
  contents: write

jobs:
  update-m3u8:
    runs-on: ubuntu-latest

    steps:
      - name: Repository indiriliyor
        uses: actions/checkout@v4

      - name: Python kuruluyor
        uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: yt-dlp kuruluyor
        run: |
          python -m pip install --upgrade pip
          pip install -U yt-dlp

      - name: M3U8 bağlantısı güncelleniyor
        run: python youtube_m3u8.py

      - name: Değişiklikler GitHub'a gönderiliyor
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add aski-memnu.m3u8
          git diff --cached --quiet || git commit -m "M3U8 link güncellendi"
          git push
