import hashlib, json, os, threading, time
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enables CORS for cross-origin requests from frontend

# ==================== RADIO STATE & CONFIG ====================
PLAYLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlist.json")
LOOKAHEAD_TRACKS = 2
ANCHOR_EPOCH = 0


class PlaylistError(Exception):
    """Raised when playlist.json is missing or malformed."""


class RadioState:
    """Holds mutable schedule state behind a lock instead of bare module globals."""

    def __init__(self):
        self._lock = threading.Lock()
        self._skip_offset = 0.0
        self._skip_counter = 0

    def snapshot(self):
        with self._lock:
            return self._skip_offset, self._skip_counter

    def apply_skip(self, remaining):
        with self._lock:
            self._skip_offset += remaining
            self._skip_counter += 1
            return self._skip_offset, self._skip_counter


state = RadioState()


class PlaylistCache:
    """Caches parsed playlist + hash, invalidated by file mtime."""

    def __init__(self, path):
        self._path = path
        self._lock = threading.Lock()
        self._mtime = None
        self._tracks = None
        self._total_duration = None
        self._base_version = None

    def load(self):
        with self._lock:
            try:
                mtime = os.path.getmtime(self._path)
            except OSError as e:
                raise PlaylistError(f"playlist file not found: {self._path}") from e

            if mtime != self._mtime:
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        raw = f.read()
                    tracks = json.loads(raw)["tracks"]
                except (OSError, ValueError, KeyError) as e:
                    raise PlaylistError(f"playlist file invalid: {e}") from e

                if not tracks or sum(t["duration"] for t in tracks) <= 0:
                    raise PlaylistError("playlist has no tracks with positive duration")

                self._tracks, self._total_duration = tracks, sum(t["duration"] for t in tracks)
                self._base_version = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
                self._mtime = mtime

            return self._tracks, self._total_duration, self._base_version


playlist_cache = PlaylistCache(PLAYLIST_PATH)


# ==================== HELPERS ====================
def load_playlist():
    tracks, total_duration, base_version = playlist_cache.load()
    _, skip_counter = state.snapshot()
    return tracks, total_duration, f"{base_version}-v{skip_counter}"


def find_current_track(tracks, total_duration, elapsed):
    cumulative = 0
    for i, t in enumerate(tracks):
        if elapsed < cumulative + t["duration"]:
            return i, elapsed - cumulative
        cumulative += t["duration"]
    return len(tracks) - 1, 0.0  # only reached via float rounding at the exact boundary


def compute_schedule(tracks, total_duration, now, skip_offset, lookahead=LOOKAHEAD_TRACKS):
    virtual_now = now + skip_offset
    elapsed = (virtual_now - ANCHOR_EPOCH) % total_duration
    current_index, time_into_track = find_current_track(tracks, total_duration, elapsed)

    started_at, entries = now - time_into_track, []
    for offset in range(1 + lookahead):
        t = tracks[(current_index + offset) % len(tracks)]
        entries.append({"id": t["id"], "title": t["title"], "audio_url": t["audio_url"], "duration": t["duration"], "starts_at": started_at})
        started_at += t["duration"]

    return {"current": entries[0], "up_next": entries[1:], "time_into_track": time_into_track}


# ==================== ROUTES ====================
import sys, platform
@app.route("/", methods=["GET"])
def index():
    now = time.time()
    try:
        tracks, total_duration, version = load_playlist()
        playlist_status = {"status": "ok", "file_path": PLAYLIST_PATH, "exists": os.path.exists(PLAYLIST_PATH), "track_count": len(tracks), "total_duration_sec": total_duration, "total_duration_formatted": f"{int(total_duration // 60)}m {int(total_duration % 60)}s", "schedule_version": version, "last_modified": time.ctime(os.path.getmtime(PLAYLIST_PATH)) if os.path.exists(PLAYLIST_PATH) else None}
    except Exception as e:
        playlist_status = {"status": "error", "file_path": PLAYLIST_PATH, "exists": os.path.exists(PLAYLIST_PATH), "error_message": str(e)}
    skip_offset, skip_counter = state.snapshot()
    debug_payload = {"service": "Creator Radio Backend", "status": "ok" if playlist_status.get("status") == "ok" else "degraded", "timestamp": {"epoch": now, "iso_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}, "radio_state": {"skip_offset_seconds": skip_offset, "total_skips_applied": skip_counter, "anchor_epoch": ANCHOR_EPOCH}, "playlist_health": playlist_status, "request_debug": {"remote_addr": request.remote_addr, "user_agent": request.headers.get("User-Agent"), "host": request.host, "scheme": request.scheme, "query_params": dict(request.args)}, "environment": {"python_version": sys.version.split()[0], "platform": platform.platform(), "port": int(os.environ.get("PORT", 5000)), "flask_env": os.environ.get("FLASK_ENV", "production")}}
    return jsonify(debug_payload), (200 if playlist_status.get("status") == "ok" else 503)
    

@app.route("/api/radio", methods=["GET"])
def get_radio():
    try:
        tracks, total_duration, version = load_playlist()
    except PlaylistError as e:
        return jsonify({"error": str(e)}), 503

    skip_offset, _ = state.snapshot()
    now = time.time()
    payload = {"server_time_now": now, "schedule_version": version}
    if request.args.get("schedule_version") != version:
        schedule = compute_schedule(tracks, total_duration, now, skip_offset)
        schedule.pop("time_into_track", None)
        payload.update(schedule)
    return jsonify(payload)


# NOTE: unauthenticated for now (skips are global/shared across all listeners) — routed under an unguessable path as a stopgap until real auth is added.
@app.route("/api/radio/skip243756", methods=["POST"])
def skip_radio_track():
    try:
        tracks, total_duration, _ = load_playlist()
    except PlaylistError as e:
        return jsonify({"error": str(e)}), 503

    skip_offset, _ = state.snapshot()
    now = time.time()
    current = compute_schedule(tracks, total_duration, now, skip_offset)
    state.apply_skip(current["current"]["duration"] - current["time_into_track"])

    return get_radio()


# ==================== ENTRY POINT ====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
