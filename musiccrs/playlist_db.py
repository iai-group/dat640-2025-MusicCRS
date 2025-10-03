import os
import json
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_DB_PATH = Path(os.environ.get("MPD_SQLITE_PATH", "data/mpd.sqlite")).resolve()
DEFAULT_MPD_DIR = Path(os.environ.get("MPD_DIR", "")).expanduser().resolve()
SAMPLE_TRACKS = Path("data/sample_tracks.json")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tracks (
    track_uri TEXT PRIMARY KEY,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist_title ON tracks(artist, title);
"""

def get_conn(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA_SQL)
    return conn

def seed_from_sample(conn: sqlite3.Connection, sample_json: Path = SAMPLE_TRACKS) -> int:
    if not sample_json.exists():
        return 0
    with sample_json.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows = [(d["track_uri"], d["artist"], d["title"], d.get("album")) for d in data]
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO tracks(track_uri, artist, title, album) VALUES (?,?,?,?)", rows
        )
    return len(rows)

def build_from_mpd_folder(mpd_dir: Path, conn: Optional[sqlite3.Connection] = None) -> int:
    """Load MPD original JSON slices (if present). Accepts files that contain 'playlists' key aligned with MPD structure."""
    close = False
    if conn is None:
        conn = get_conn()
        close = True
    count = 0
    for p in mpd_dir.rglob("*.json"):
        try:
            with p.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        # Two known variants: MPD playlists list, or plain list of tracks (like our sample)
        items = []
        if isinstance(payload, dict) and "playlists" in payload:
            for pl in payload["playlists"]:
                for t in pl.get("tracks", []):
                    items.append((t.get("track_uri"), t.get("artist_name"), t.get("track_name"), t.get("album_name")))
        elif isinstance(payload, list):
            for t in payload:
                items.append((t.get("track_uri"), t.get("artist") or t.get("artist_name"), t.get("title") or t.get("track_name"), t.get("album") or t.get("album_name")))
        # Filter valid
        items = [i for i in items if i[0] and i[1] and i[2]]
        with conn:
            conn.executemany("INSERT OR IGNORE INTO tracks(track_uri, artist, title, album) VALUES (?,?,?,?)", items)
            count += len(items)
    if close:
        conn.close()
    return count

def ensure_db(db_path: Path = DEFAULT_DB_PATH, mpd_dir: Optional[Path] = None) -> sqlite3.Connection:
    conn = get_conn(db_path)
    # If empty, try populate
    cur = conn.execute("SELECT COUNT(*) FROM tracks")
    n = cur.fetchone()[0]
    if n == 0:
        # Seed from MPD_DIR if available, else fallback to sample
        use_dir = mpd_dir or DEFAULT_MPD_DIR
        if use_dir and use_dir.exists():
            build_from_mpd_folder(use_dir, conn)
        if conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 0:
            seed_from_sample(conn, SAMPLE_TRACKS)
    return conn

def search_by_artist_title(artist: str, title: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Tuple[str, str, str, Optional[str]]]:
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return None
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    row = conn.execute(
        "SELECT track_uri, artist, title, album FROM tracks WHERE lower(artist)=? AND lower(title)=?",
        (artist.lower(), title.lower()),
    ).fetchone()
    if close:
        conn.close()
    return row

def get_track_by_uri(uri: str, conn: Optional[sqlite3.Connection] = None):
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    row = conn.execute(
        "SELECT track_uri, artist, title, album FROM tracks WHERE track_uri=?",
        (uri,),
    ).fetchone()
    if close:
        conn.close()
    return row
