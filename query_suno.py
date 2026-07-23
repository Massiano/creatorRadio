import requests
import json

TRACK_ID = "f9506dcb-dd47-4b66-ae09-eefad81958e4"
URL = f"https://studio-api.suno.ai/api/feed/{TRACK_ID}"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://suno.com/",
    "Origin": "https://suno.com/"
}

try:
    response = requests.get(URL, headers=headers)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("Metadata Retrieved Successfully:")
        print(json.dumps(data, indent=2))
    else:
        print(f"Failed to fetch metadata: {response.text}")

except Exception as e:
    print(f"An error occurred: {e}")