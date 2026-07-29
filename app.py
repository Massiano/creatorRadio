import re
import os
import time
import hashlib
import json as _json
import urllib.request
import urllib.error
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS globally for all routes

USER_AGENT = "Mozilla/5.0 (compatible; suno-meta-fetcher/1.0)"

# ==================== SUNO SONG FETCHER LOGIC ====================

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
            "Batch List": "/api/songs?ids=uuid1,uuid2",
            "Chat Polling": "/api/messages",
            "Radio Polling": "/api/radio?schedule_version=<version>",
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
    
    for tid in track_ids[:20]:
        try:
            results.append(parse_suno_track(tid))
        except Exception as e:
            results.append({"id": tid, "error": str(e)})
            
    return jsonify(results)


# ==================== SUNO EXTENSION CHAT ENDPOINTS ====================

messages_db = []
message_counter = 0

@app.route('/api/messages', methods=['GET', 'POST'])
def handle_messages():
    global message_counter
    
    if request.method == 'POST':
        data = request.json or {}
        queued_items = data.get('messages', [])
            
        saved_messages = []
        for item in queued_items:
            # Handle item whether it's sent as an object payload or a legacy string
            if isinstance(item, dict):
                text = item.get("text", "").strip()
                sender = item.get("sender", "Anonymous").strip()
            else:
                text = str(item).strip()
                sender = "Anonymous"
                
            if text:
                message_counter += 1
                msg = {"id": message_counter, "text": text, "sender": sender}
                messages_db.append(msg)
                saved_messages.append(msg)
                
        return jsonify({"status": "ok", "saved": saved_messages})

    else:
        since_id = int(request.args.get('since_id', 0))
        fresh_messages = [m for m in messages_db if m["id"] > since_id]
        return jsonify({"messages": fresh_messages})


# ==================== RADIO PLAYLIST (static file, no network calls at request time) ====================

PLAYLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlist.json")
LOOKAHEAD_TRACKS = 2  # how many "up next" entries the poll response includes
ANCHOR_EPOCH = 0      # fixed reference point (unix epoch) so the schedule survives restarts/deploys unchanged

def load_playlist():
    # re-reads playlist.json fresh each call so an edited file is picked up without a restart; cheap since it only runs on startup + whenever schedule_version is stale
    with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
    tracks = _json.loads(raw)["tracks"]
    version = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]  # derived from file content, so it changes automatically when playlist.json is edited
    return tracks, sum(t["duration"] for t in tracks), version

def compute_schedule(tracks, total_duration, now, lookahead=LOOKAHEAD_TRACKS):
    elapsed = (now - ANCHOR_EPOCH) % total_duration
    cumulative, current_index = 0, 0
    for i, t in enumerate(tracks):
        if cumulative + t["duration"] > elapsed:
            current_index = i
            break
        cumulative += t["duration"]
    else:
        current_index, cumulative = len(tracks) - 1, cumulative - tracks[-1]["duration"]

    started_at, entries = now - (elapsed - cumulative), []
    for offset in range(1 + lookahead):
        t = tracks[(current_index + offset) % len(tracks)]
        entries.append({"id": t["id"], "title": t["title"], "audio_url": t["audio_url"], "duration": t["duration"], "starts_at": started_at})
        started_at += t["duration"]

    return {"current": entries[0], "up_next": entries[1:]}

@app.route('/api/radio', methods=['GET'])
def get_radio():
    tracks, total_duration, version = load_playlist()
    now = time.time()

    payload = {"server_time_now": now, "schedule_version": version}
    if request.args.get('schedule_version') != version:  # only send the (tiny) track list when the client is stale
        payload.update(compute_schedule(tracks, total_duration, now))

    return jsonify(payload)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
