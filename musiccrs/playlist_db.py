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
        # Two known variants: MPD playlists list, or plain list of tracks
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
    Intelligent fuzzy search for tracks by artist and title.
    Handles common patterns like:
    - Exact artist, fuzzy title (e.g., "smells like teen spirit" matches "Smells Like Teen Spirit - Remastered")
    - Fuzzy artist name (e.g., "nirvana" matches "Nirvana")
    
    Returns results ranked by:
    1. Artist name match quality (exact > fuzzy)
    2. Title match quality (exact > starts with > contains)
    3. MPD popularity
    """
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return []
    
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    artist_lower = artist.lower()
    title_lower = title.lower()
    
    # Query for multiple match types and rank them
    # Priority: exact artist match, then fuzzy artist match
    # For title: exact > starts with > contains
    query = """
    SELECT track_uri, artist, title, album,
        CASE 
            WHEN lower(artist) = ? THEN 0  -- Exact artist match
            WHEN lower(artist) LIKE ? THEN 1  -- Fuzzy artist match
            ELSE 2
        END as artist_priority,
        CASE
            WHEN lower(title) = ? THEN 0  -- Exact title
            WHEN lower(title) LIKE ? THEN 1  -- Title starts with search
            WHEN lower(title) LIKE ? THEN 2  -- Title contains search
            ELSE 3
        END as title_priority,
        length(title) as title_len
    FROM tracks 
    WHERE (lower(artist) = ? OR lower(artist) LIKE ?)
      AND (lower(title) = ? OR lower(title) LIKE ?)
    ORDER BY artist_priority ASC, title_priority ASC, title_len ASC
    LIMIT ?
    """
    
    rows = conn.execute(
        query,
        (
            artist_lower,  # exact artist
            f"%{artist_lower}%",  # fuzzy artist
            title_lower,  # exact title
            f"{title_lower}%",  # title starts with
            f"%{title_lower}%",  # title contains
            artist_lower,  # WHERE exact artist
            f"%{artist_lower}%",  # WHERE fuzzy artist  
            title_lower,  # WHERE exact title
            f"%{title_lower}%",  # WHERE title fuzzy
            limit
        ),
    ).fetchall()
    
    if close:
        conn.close()
    
    # Remove the priority and length columns from results
    return [(uri, artist, title, album) for uri, artist, title, album, _, _, _ in rows]


# ========== R3.2: Popularity-based ranking ==========
def get_track_popularity(track_uri: str, mpd_dir: Optional[Path] = None, conn: Optional[sqlite3.Connection] = None) -> int:
    """Count how many times a track appears in MPD playlists (local database popularity)."""
    close = False
    if conn is None:
        conn = ensure_db()
        close = True
    
    try:
        # Count occurrences in the tracks table (tracks that appear in loaded playlists)
        # This uses the MPD database to estimate popularity
        result = conn.execute(
            "SELECT COUNT(*) FROM tracks WHERE track_uri = ?",
            (track_uri,)
        ).fetchone()
        count = result[0] if result else 0
        if close:
            conn.close()
        return count
    except Exception:
        if close:
            conn.close()
        return 0

def search_by_title_ranked(title: str, existing_artists: list[str] = None, limit: int = 20, conn: Optional[sqlite3.Connection] = None):
    """
    Search for tracks by title and rank them intelligently:
    1. Tracks by artists already in the playlist (if existing_artists provided)
    2. By MPD database popularity (how often track appears in playlists)
    3. By artist name match quality
    4. Alphabetically as tiebreaker
    
    Spotify is used as optional enhancement only - system works fully without it.
    """
    # Get initial results
    initial_limit = min(limit * 3, 60)  # Get 3x requested, max 60 for variety
    results = search_by_title(title, limit=initial_limit, conn=conn)
    if not results:
        return []
    
    existing_artists = [a.lower() for a in (existing_artists or [])]
    
    # Get MPD popularity for all tracks (LOCAL, fast, always available)
    results_with_data = []
    for uri, artist, track_title, album in results:
        mpd_popularity = get_track_popularity(uri, conn=conn)
        results_with_data.append((uri, artist, track_title, album, mpd_popularity))
    
    # Optional: Try to enhance with Spotify popularity if available
    # This is purely optional - system works without it
    spotify_popularity = {}
    try:
        from .spotify_api import get_spotify_api
        spotify = get_spotify_api()
        if spotify:
            # Only query Spotify for top candidates to avoid slowdown
            MAX_SPOTIFY_CALLS = 5  # Very conservative - most ranking is MPD-based
            
            # Get Spotify data for most promising candidates (by MPD popularity)
            top_by_mpd = sorted(results_with_data, key=lambda x: x[4], reverse=True)[:MAX_SPOTIFY_CALLS]
            
            for uri, artist, track_title, album, mpd_pop in top_by_mpd:
                try:
                    pop = spotify.get_track_popularity(artist, track_title)
                    if pop > 0:  # Only cache successful lookups
                        spotify_popularity[uri] = pop
                except Exception:
                    pass  # Silently ignore per-track failures
    except Exception:
        pass  # Spotify entirely optional - don't print errors
    
    # Apply final popularity scores combining MPD + optional Spotify
    final_results = []
    for uri, artist, track_title, album, mpd_pop in results_with_data:
        # MPD popularity is primary (0-N occurrences)
        # Spotify popularity is bonus enhancement (0-100) - scale down to avoid dominance
        spotify_pop = spotify_popularity.get(uri, 0)
        combined_popularity = mpd_pop * 10 + spotify_pop  # Weight MPD 10x more than Spotify
        final_results.append((uri, artist, track_title, album, combined_popularity))
    
    # Sort: prioritize existing artists, then by combined popularity, then alphabetically
    def rank_key(row):
        artist = row[1].lower()
        popularity = row[4]
        # Artists in playlist get priority (0), others get 1
        priority = 0 if artist in existing_artists else 1
        # Higher popularity = lower sort key (negative to sort descending)
        return (priority, -popularity, artist, row[2])
    
    ranked = sorted(final_results, key=rank_key)
    # Remove popularity from output and apply final limit
    return [(uri, artist, title, album) for uri, artist, title, album, _ in ranked[:limit]]
    
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
