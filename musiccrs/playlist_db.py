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
    # Filter out invalid entries (must be dicts with required fields)
    if not isinstance(data, list):
        return 0
    rows = []
    for d in data:
        if isinstance(d, dict) and "track_uri" in d and "artist" in d and "title" in d:
            rows.append((d["track_uri"], d["artist"], d["title"], d.get("album")))
    if rows:
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
                    # Skip if t is not a dict
                    if not isinstance(t, dict):
                        continue
                    items.append((t.get("track_uri"), t.get("artist_name"), t.get("track_name"), t.get("album_name")))
        elif isinstance(payload, list):
            for t in payload:
                # Skip if t is not a dict
                if not isinstance(t, dict):
                    continue
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

# ========== R3.1: Search by title only ==========
def search_by_title(title: str, limit: int = 20, conn: Optional[sqlite3.Connection] = None):
    """Search for tracks by title only. Combines exact and fuzzy matching to handle variations.
    Returns list of (track_uri, artist, title, album)."""
    title = (title or "").strip()
    if not title:
        return []
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    # Get both exact matches AND fuzzy matches (title starts with search term)
    # This handles both "Hey Jude" and "Hey Jude - Remastered 2015"
    # Use UNION to combine and remove duplicates, order by exact match first
    rows = conn.execute(
        """
        SELECT track_uri, artist, title, album, 0 as priority, length(title) as title_len FROM tracks WHERE lower(title)=?
        UNION
        SELECT track_uri, artist, title, album, 1 as priority, length(title) as title_len FROM tracks WHERE lower(title) LIKE ? AND lower(title)!=?
        ORDER BY priority, title_len ASC
        LIMIT ?
        """,
        (title.lower(), title.lower() + '%', title.lower(), limit),
    ).fetchall()
    
    # Remove the priority and title_len columns from results
    rows = [(uri, artist, title, album) for uri, artist, title, album, _, _ in rows]
    
    if close:
        conn.close()
    return rows

def search_by_artist_title_fuzzy(artist: str, title: str, limit: int = 10, conn: Optional[sqlite3.Connection] = None):
    """
    Fuzzy search for tracks by artist and title using LIKE matching.
    Useful when exact match fails but user knows approximate title.
    Returns list of (track_uri, artist, title, album).
    """
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return []
    
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    # Try partial match with LIKE - title contains the search term
    rows = conn.execute(
        "SELECT track_uri, artist, title, album FROM tracks "
        "WHERE lower(artist)=? AND lower(title) LIKE ? "
        "ORDER BY length(title) ASC LIMIT ?",
        (artist.lower(), f"%{title.lower()}%", limit),
    ).fetchall()
    
    if close:
        conn.close()
    return rows

# ========== R3.2: Popularity-based ranking ==========
def get_track_popularity(track_uri: str, mpd_dir: Optional[Path] = None, conn: Optional[sqlite3.Connection] = None) -> int:
    """Count how many times a track appears in MPD playlists (approximation from loaded data)."""
    # For now, return a simple heuristic. Full implementation would scan MPD files.
    # We'll use a placeholder that can be enhanced later.
    return 0

def search_by_title_ranked(title: str, existing_artists: list[str] = None, limit: int = 20, conn: Optional[sqlite3.Connection] = None):
    """
    Search for tracks by title and rank them:
    1. Tracks by artists already in the playlist (if existing_artists provided)
    2. By Spotify popularity (if available)
    3. Then alphabetically by artist
    
    Performance optimization: Fetches 2x limit, gets Spotify data for diverse subset.
    """
    # Strategy: Get more results but sample intelligently for Spotify API calls
    # This balances finding variations (like "Hey Jude - Remastered") with performance
    initial_limit = min(limit * 3, 60)  # Get 3x requested, max 60
    results = search_by_title(title, limit=initial_limit, conn=conn)
    if not results:
        return []
    
    existing_artists = [a.lower() for a in (existing_artists or [])]
    
    # Try to get Spotify popularity for ranking (R3.2 enhancement)
    try:
        from .spotify_api import get_spotify_api
        spotify = get_spotify_api()
        if spotify:
            # PERFORMANCE OPTIMIZATION: Limit Spotify API calls to stay under 3-5 second target
            # Strategy: Query Spotify for a strategic subset, infer for the rest
            
            MAX_SPOTIFY_CALLS = 12  # Limit API calls for performance (3-5 second target with network variance)
            
            # Group results by artist
            artist_groups = {}
            for uri, artist, track_title, album in results:
                key = artist.lower()
                if key not in artist_groups:
                    artist_groups[key] = []
                artist_groups[key].append((uri, artist, track_title, album))
            
            # Prioritize which artists to query:
            # 1. Artists already in playlist
            # 2. Common/well-known artists (more tracks = more popular)
            # 3. Take first N up to MAX_SPOTIFY_CALLS
            artists_to_query = []
            
            # First: existing artists
            for artist_key in existing_artists:
                if artist_key in artist_groups and artist_key not in artists_to_query:
                    artists_to_query.append(artist_key)
            
            # Second: artists with most tracks (likely more popular)
            sorted_by_count = sorted(artist_groups.items(), key=lambda x: len(x[1]), reverse=True)
            for artist_key, tracks in sorted_by_count:
                if artist_key not in artists_to_query:
                    artists_to_query.append(artist_key)
                if len(artists_to_query) >= MAX_SPOTIFY_CALLS:
                    break
            
            # Get popularity for selected artists
            artist_popularity = {}
            for artist_key in artists_to_query:
                tracks = artist_groups[artist_key]
                uri, artist, track_title, album = tracks[0]
                popularity = spotify.get_track_popularity(artist, track_title)
                artist_popularity[artist_key] = popularity
            
            # For unqueried artists, use a default low popularity
            DEFAULT_POPULARITY = 10
            
            # Apply popularity to all tracks
            results_with_popularity = []
            for uri, artist, track_title, album in results:
                popularity = artist_popularity.get(artist.lower(), DEFAULT_POPULARITY)
                results_with_popularity.append((uri, artist, track_title, album, popularity))
            
            # Sort: prioritize existing artists, then by popularity, then alphabetically
            def rank_key(row):
                artist = row[1].lower()
                popularity = row[4]
                # Artists in playlist get priority (0), others get 1
                priority = 0 if artist in existing_artists else 1
                # Higher popularity = lower sort key (negative to sort descending)
                return (priority, -popularity, artist, row[2])
            
            ranked = sorted(results_with_popularity, key=rank_key)
            # Remove popularity from output and apply final limit
            return [(uri, artist, title, album) for uri, artist, title, album, _ in ranked[:limit]]
    except Exception as e:
        print(f"Warning: Could not use Spotify for ranking: {e}")
    
    # Fallback: original ranking without Spotify
    def rank_key(row):
        artist = row[1].lower()
    # Fallback: original ranking without Spotify
    def rank_key(row):
        artist = row[1].lower()
        priority = 0 if artist in existing_artists else 1
        return (priority, artist, row[2])
    
    ranked = sorted(results, key=rank_key)
    return ranked[:limit]

# ========== R3.3: Q&A queries ==========
def get_track_info(track_uri: str = None, artist: str = None, title: str = None, conn: Optional[sqlite3.Connection] = None):
    """Get detailed track information."""
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    if track_uri:
        row = conn.execute(
            "SELECT track_uri, artist, title, album FROM tracks WHERE track_uri=?",
            (track_uri,),
        ).fetchone()
    elif artist and title:
        row = conn.execute(
            "SELECT track_uri, artist, title, album FROM tracks WHERE lower(artist)=? AND lower(title)=?",
            (artist.lower(), title.lower()),
        ).fetchone()
    else:
        row = None
    
    if close:
        conn.close()
    return row

def count_tracks_by_artist(artist: str, conn: Optional[sqlite3.Connection] = None) -> int:
    """Count how many tracks by an artist are in the database."""
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    count = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE lower(artist)=?",
        (artist.lower(),),
    ).fetchone()[0]
    
    if close:
        conn.close()
    return count

def get_albums_by_artist(artist: str, conn: Optional[sqlite3.Connection] = None):
    """Get all albums by an artist."""
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    rows = conn.execute(
        "SELECT DISTINCT album FROM tracks WHERE lower(artist)=? AND album IS NOT NULL ORDER BY album",
        (artist.lower(),),
    ).fetchall()
    
    if close:
        conn.close()
    return [r[0] for r in rows]

def get_top_tracks_by_artist(artist: str, limit: int = 10, conn: Optional[sqlite3.Connection] = None):
    """Get top tracks by an artist (ordered alphabetically for now, could be by popularity)."""
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    rows = conn.execute(
        "SELECT track_uri, artist, title, album FROM tracks WHERE lower(artist)=? ORDER BY title LIMIT ?",
        (artist.lower(), limit),
    ).fetchall()
    
    if close:
        conn.close()
    return rows

def search_similar_artists(artist: str, limit: int = 5, conn: Optional[sqlite3.Connection] = None):
    """Find similar artists (simple: artists with similar album names or alphabetically close)."""
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    # Simple heuristic: find artists that share albums or are alphabetically close
    rows = conn.execute(
        """
        SELECT DISTINCT artist, COUNT(*) as track_count 
        FROM tracks 
        WHERE lower(artist) != ? 
        AND (
            album IN (SELECT album FROM tracks WHERE lower(artist)=? AND album IS NOT NULL)
            OR lower(artist) LIKE ?
        )
        GROUP BY artist 
        ORDER BY track_count DESC 
        LIMIT ?
        """,
        (artist.lower(), artist.lower(), artist.lower()[:3] + '%', limit),
    ).fetchall()
    
    if close:
        conn.close()
    return [r[0] for r in rows]

def get_all_artists(conn: Optional[sqlite3.Connection] = None):
    """Get list of all artists in database."""
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    rows = conn.execute(
        "SELECT DISTINCT artist FROM tracks ORDER BY artist"
    ).fetchall()
    
    if close:
        conn.close()
    return [r[0] for r in rows]
