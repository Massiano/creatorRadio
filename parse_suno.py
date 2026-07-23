import re
import json as _json
import urllib.request
import urllib.error

# ---- Target Configuration ----
TRACK_ID = "f9506dcb-dd47-4b66-ae09-eefad81958e4"
URL = f"https://suno.com/song/{TRACK_ID}"
USER_AGENT = "Mozilla/5.0 (compatible; suno-meta-fetcher/1.0)"

def unescape_json_string(raw):
    try:
        return _json.loads('"' + raw + '"')
    except Exception:
        return raw

def extract_field(text, key, is_number=False):
    if is_number:
        pat = r'"' + key + r'":([\d.]+)'
    else:
        pat = r'"' + key + r'":"((?:[^"\\]|\\.)*)"'
    m = re.search(pat, text)
    if not m:
        return None
    return m.group(1) if is_number else unescape_json_string(m.group(1))

def parse_rsc(html, guess_id):
    chunks = []
    for m in re.finditer(r'self\.__next_f\.push\(\[\d+,\s*"((?:[^"\\]|\\.)*)"\]\)', html):
        chunks.append(unescape_json_string(m.group(1)))
    rsc = "".join(chunks)
    if not rsc:
        return {}

    id_index = -1
    if guess_id:
        id_index = rsc.find('"id":"' + guess_id + '"')
    if id_index == -1:
        m = re.search(r'"id":"[0-9a-f-]{8,}"', rsc, re.I)
        id_index = m.start() if m else -1

    window = rsc
    if id_index != -1:
        start = max(0, id_index - 500)
        end = min(len(rsc), id_index + 4000)
        window = rsc[start:end]

    id_match = re.search(r'"id":"([0-9a-f-]{8,})"', window, re.I)

    return {
        "id": id_match.group(1) if id_match else None,
        "title": extract_field(window, "title"),
        "image_url": extract_field(window, "image_large_url") or extract_field(window, "image_url"),
        "audio_url": extract_field(window, "audio_url"),
        "video_url": extract_field(window, "video_url"),
        "tags": extract_field(window, "tags"),
        "duration": extract_field(window, "duration", is_number=True),
        "play_count": extract_field(window, "play_count", is_number=True),
        "upvote_count": extract_field(window, "upvote_count", is_number=True),
        "display_name": extract_field(window, "display_name"),
        "handle": extract_field(window, "handle"),
        "created_at": extract_field(window, "created_at"),
    }

def parse_html_meta(html):
    def meta(prop):
        m = re.search(r'<meta[^>]+property=["\']' + re.escape(prop) + r'["\'][^>]+content=["\']([^"\']*)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']' + re.escape(prop) + r'["\']', html, re.I)
        return m.group(1) if m else None

    title_tag = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    return {
        "title": meta("og:title") or (title_tag.group(1).strip() if title_tag else None),
        "description": meta("og:description"),
        "image_url": meta("og:image"),
        "audio_url": meta("og:audio"),
    }

# ---- Execution ----
print(f"Fetching metadata for target: {TRACK_ID}")
req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
        
    rsc_data = parse_rsc(html, TRACK_ID)
    meta_data = parse_html_meta(html)
    
    result = {
        "id": rsc_data.get("id") or TRACK_ID,
        "title": rsc_data.get("title") or meta_data.get("title"),
        "image_url": rsc_data.get("image_url") or meta_data.get("image_url"),
        "audio_url": rsc_data.get("audio_url") or meta_data.get("audio_url"),
        "video_url": rsc_data.get("video_url"),
        "tags": rsc_data.get("tags"),
        "duration": rsc_data.get("duration"),
        "play_count": rsc_data.get("play_count"),
        "upvote_count": rsc_data.get("upvote_count"),
        "display_name": rsc_data.get("display_name"),
        "handle": rsc_data.get("handle"),
        "created_at": rsc_data.get("created_at"),
    }
    
    print("\nSuccessfully Extracted Track Metadata:")
    print(_json.dumps(result, indent=2))
    
except Exception as e:
    print(f"Error fetching or parsing track: {e}")