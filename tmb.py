import requests

URL = "https://str.yodacdn.net/tmb_tr_app/tracks-v1a1/mono.ts.m3u8?token=tmb_app_token_13579"

headers = {
    "User-Agent": "Mozilla/5.0"
}

try:
    response = requests.get(
        URL,
        headers=headers,
        timeout=30
    )
    response.raise_for_status()
    print(response.text)

except requests.RequestException as e:
    print(f"# HATA: {e}")
