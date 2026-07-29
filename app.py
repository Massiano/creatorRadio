import hashlib
import json as _json
import os
import time
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enables CORS for cross-origin requests from frontend

# ==================== RADIO STATE & CONFIG ====================

PLAYLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "playlist.json"
)
LOOKAHEAD_TRACKS = 2
ANCHOR_EPOCH = 0

skip_offset = 0.0
skip_counter = 0


# ==================== HELPERS ====================


def load_playlist():
    with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
    tracks = _json.loads(raw)["tracks"]
    base_version = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    version = f"{base_version}-v{skip_counter}"
    return tracks, sum(t["duration"] for t in tracks), version


def compute_schedule(tracks, total_duration, now, lookahead=LOOKAHEAD_TRACKS):
    virtual_now = now + skip_offset
    elapsed = (virtual_now - ANCHOR_EPOCH) % total_duration
    cumulative, current_index = 0, 0

    for i, t in enumerate(tracks):
        if cumulative + t["duration"] > elapsed:
            current_index = i
            break
        cumulative += t["duration"]
    else:
        current_index, cumulative = (
            len(tracks) - 1,
            cumulative - tracks[-1]["duration"],
        )

    time_into_track = elapsed - cumulative
    started_at, entries = now - time_into_track, []

    for offset in range(1 + lookahead):
        t = tracks[(current_index + offset) % len(tracks)]
        entries.append({
            "id": t["id"],
            "title": t["title"],
            "audio_url": t["audio_url"],
            "duration": t["duration"],
            "starts_at": started_at,
        })
        started_at += t["duration"]

    return {"current": entries[0], "up_next": entries[1:]}


# ==================== ROUTES ====================


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "service": "Creator Radio Backend"})


@app.route("/api/radio", methods=["GET"])
def get_radio():
    tracks, total_duration, version = load_playlist()
    now = time.time()

    payload = {"server_time_now": now, "schedule_version": version}
    if request.args.get("schedule_version") != version:
        payload.update(compute_schedule(tracks, total_duration, now))

    return jsonify(payload)


@app.route("/api/radio/skip", methods=["POST"])
def skip_radio_track():
    global skip_offset, skip_counter
    tracks, total_duration, _ = load_playlist()
    skip_offset += compute_schedule(tracks, total_duration, time.time())[
        "current"
    ]["duration"]
    skip_counter += 1
    return get_radio()


# ==================== ENTRY POINT ====================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
