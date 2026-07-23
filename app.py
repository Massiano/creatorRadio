import re
import json as _json
import urllib.request
import urllib.error
from flask import Flask, jsonify, request

app = Flask(__name__)
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

def parse_suno_track(track_id):
    url = f"https://suno.com/song/{track_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Parse RSC chunks
    chunks = []
    for m in re.finditer(r'self\.__next_f\.push\(\[\d+,\s*"((?:[^"\\]|\\.)*)"\]\)', html):
        chunks.append(unescape_json_string(m.group(1)))
    rsc = "".join(chunks)

    id_index = rsc.find('"id":"' + track_id + '"')
    if id_index == -1:
        m = re.search(r'"id":"[0-9a-f-]{8,}"', rsc, re.I)
        id_index = m.start() if m else -1

    window = rsc
    if id_index != -1:
        start = max(0, id_index - 500)
        end = min(len(rsc), id_index + 4000)
        window = rsc[start:end]

    id_match = re.search(r'"id":"([0-9a-f-]{8,})"', window, re.I)

    # Fallback Meta tags
    def meta(prop):
        m = re.search(r'<meta[^>]+property=["\']' + re.escape(prop) + r'["\'][^>]+content=["\']([^"\']*)["\']', html, re.I)
        return m.group(1) if m else None

    title_tag = re.search(r"<title>(.*?)</title>", html, re.I | re.S)

    return {
        "id": id_match.group(1) if id_match else track_id,
        "title": extract_field(window, "title") or meta("og:title") or (title_tag.group(1).strip() if title_tag else None),
        "description": meta("og:description"),
        "image_url": extract_field(window, "image_large_url") or extract_field(window, "image_url") or meta("og:image"),
        "audio_url": extract_field(window, "audio_url") or meta("og:audio"),
        "video_url": extract_field(window, "video_url"),
        "tags": extract_field(window, "tags"),
        "duration": extract_field(window, "duration", is_number=True),
        "play_count": extract_field(window, "play_count", is_number=True),
        "upvote_count": extract_field(window, "upvote_count", is_number=True),
        "display_name": extract_field(window, "display_name"),
        "handle": extract_field(window, "handle"),
        "created_at": extract_field(window, "created_at"),
    }

@app.route('/')
def index():
    return jsonify({
        "status": "online",
        "endpoints": {
            "Single Song": "/api/song/<uuid>",
            "Batch List": "/api/songs?ids=uuid1,uuid2"
        }
    })

@app.route('/api/song/<track_id>', methods=['GET'])
def get_song(track_id):
    try:
        data = parse_suno_track(track_id)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@app.route('/api/songs', methods=['GET'])
def get_songs_batch():
    ids_param = request.args.get('ids', '')
    if not ids_param:
        return jsonify({"error": "Please provide comma-separated IDs via ?ids=uuid1,uuid2"}), 400
    
    track_ids = [i.strip() for i in ids_param.split(',') if i.strip()]
    results = []
    
    for tid in track_ids[:20]: # Limit max batch size to protect performance
        try:
            results.append(parse_suno_track(tid))
        except Exception as e:
            results.append({"id": tid, "error": str(e)})
            
    return jsonify(results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)