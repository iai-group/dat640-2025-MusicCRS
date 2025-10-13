from __future__ import annotations
import os, re, hashlib
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
from .playlist_db import (
    ensure_db, 
    search_by_artist_title, 
    get_track_by_uri,
    search_by_title_ranked,
)
from .cover_art import generate_cover

@dataclass
class Track:
    track_uri: str
    artist: str
    title: str
    album: str | None = None

@dataclass
class Playlist:
    name: str
    tracks: List[Track] = field(default_factory=list)
    cover_url: str | None = None

    def to_public(self) -> dict:
        return {
            "name": self.name,
            "tracks": [asdict(t) for t in self.tracks],
            "cover_url": self.cover_url,
        }

class PlaylistService:
    """Manages multiple playlists per user id (username or session id)."""

    def __init__(self):
        self._by_user: Dict[str, Dict[str, Playlist]] = {}
        self._current: Dict[str, str] = {}

    # Utilities
    def _ensure_user(self, user_id: str):
        if user_id not in self._by_user:
            self._by_user[user_id] = {"default": Playlist(name="default")}
            self._current[user_id] = "default"

    def current_playlist(self, user_id: str) -> Playlist:
        self._ensure_user(user_id)
        curr = self._current[user_id]
        return self._by_user[user_id][curr]

    def list_playlists(self, user_id: str) -> list[str]:
        self._ensure_user(user_id)
        return list(self._by_user[user_id].keys())

    def create_playlist(self, user_id: str, name: str) -> Playlist:
        self._ensure_user(user_id)
        if name in self._by_user[user_id]:
            raise ValueError(f"Playlist '{name}' already exists.")
        self._by_user[user_id][name] = Playlist(name=name)
        self._current[user_id] = name
        self._refresh_cover(user_id, name)
        return self._by_user[user_id][name]

    def switch_playlist(self, user_id: str, name: str) -> Playlist:
        self._ensure_user(user_id)
        if name not in self._by_user[user_id]:
            raise ValueError(f"Playlist '{name}' does not exist.")
        self._current[user_id] = name
        self._refresh_cover(user_id, name)
        return self._by_user[user_id][name]

    def clear(self, user_id: str, name: Optional[str] = None):
        self._ensure_user(user_id)
        name = name or self._current[user_id]
        self._by_user[user_id][name].tracks.clear()
        self._refresh_cover(user_id, name)

    def add(self, user_id: str, artist: str, title: str) -> Track:
        self._ensure_user(user_id)
        row = search_by_artist_title(artist, title)
        if not row:
            raise ValueError("Track not found in database. Provide as '[artist]: [title]'.")
        uri, a, t, alb = row
        track = Track(track_uri=uri, artist=a, title=t, album=alb)
        pl = self.current_playlist(user_id)
        # Prevent duplicates by URI
        if any(x.track_uri == uri for x in pl.tracks):
            return track
        pl.tracks.append(track)
        self._refresh_cover(user_id, pl.name)
        return track

    def add_by_uri(self, user_id: str, track_uri: str) -> Track:
        """Add a track by its URI directly."""
        self._ensure_user(user_id)
        row = get_track_by_uri(track_uri)
        if not row:
            raise ValueError("Track URI not found in database.")
        uri, a, t, alb = row
        track = Track(track_uri=uri, artist=a, title=t, album=alb)
        pl = self.current_playlist(user_id)
        # Prevent duplicates by URI
        if any(x.track_uri == uri for x in pl.tracks):
            return track
        pl.tracks.append(track)
        self._refresh_cover(user_id, pl.name)
        return track

    def search_tracks_by_title(self, user_id: str, title: str, limit: int = 20) -> List[Tuple[str, str, str, Optional[str]]]:
        """Search for tracks by title only. Returns list of (track_uri, artist, title, album)."""
        self._ensure_user(user_id)
        pl = self.current_playlist(user_id)
        existing_artists = [t.artist for t in pl.tracks]
        return search_by_title_ranked(title, existing_artists=existing_artists, limit=limit)

    def get_playlist_stats(self, user_id: str, include_spotify: bool = True) -> dict:
        """
        Get statistics about the current playlist.
        
        Args:
            user_id: User identifier
            include_spotify: If True, fetch Spotify data (popularity, genres, etc.)
        """
        pl = self.current_playlist(user_id)
        
        # Count tracks
        total_tracks = len(pl.tracks)
        
        # Count unique artists
        artists = [t.artist for t in pl.tracks]
        unique_artists = len(set(artists))
        
        # Top artists
        from collections import Counter
        artist_counts = Counter(artists)
        top_artists = artist_counts.most_common(5)
        
        # Albums
        albums = [t.album for t in pl.tracks if t.album]
        unique_albums = len(set(albums))
        
        stats = {
            "playlist_name": pl.name,
            "total_tracks": total_tracks,
            "unique_artists": unique_artists,
            "unique_albums": unique_albums,
            "top_artists": top_artists,
        }
        
        # Add Spotify-enhanced statistics
        if include_spotify and total_tracks > 0:
            try:
                from .spotify_api import get_spotify_api
                spotify = get_spotify_api()
                if spotify:
                    # Calculate average popularity
                    popularities = []
                    genres = []
                    total_duration = 0
                    
                    for track in pl.tracks[:20]:  # Limit to first 20 to avoid too many API calls
                        details = spotify.get_track_details(track.artist, track.title)
                        if details:
                            popularities.append(details['popularity'])
                            total_duration += details['duration_ms']
                    
                    # Get genres from top artists
                    for artist_name, _ in top_artists[:3]:
                        artist_info = spotify.get_artist_info(artist_name)
                        if artist_info and artist_info['genres']:
                            genres.extend(artist_info['genres'])
                    
                    if popularities:
                        stats['avg_popularity'] = sum(popularities) // len(popularities)
                        stats['estimated_duration_minutes'] = (total_duration // 1000 // 60)
                    
                    if genres:
                        # Count genre frequency
                        genre_counts = Counter(genres)
                        stats['top_genres'] = genre_counts.most_common(3)
            except Exception as e:
                print(f"Warning: Could not fetch Spotify stats: {e}")
        
        return stats

    def remove(self, user_id: str, identifier: str) -> Track:
        """Identifier can be integer index (1-based) or track_uri."""
        pl = self.current_playlist(user_id)
        if identifier.isdigit():
            idx = int(identifier) - 1
            if idx < 0 or idx >= len(pl.tracks):
                raise ValueError("Index out of range.")
            track = pl.tracks.pop(idx)
        else:
            # treat as uri
            for i, tr in enumerate(pl.tracks):
                if tr.track_uri == identifier:
                    track = pl.tracks.pop(i)
                    break
            else:
                raise ValueError("Track not found in current playlist.")
        self._refresh_cover(user_id, pl.name)
        return track

    def _refresh_cover(self, user_id: str, name: str):
        pl = self._by_user[user_id][name]
        pl.cover_url = generate_cover(user_id, pl)

    def serialize_state(self, user_id: str) -> dict:
        self._ensure_user(user_id)
        current = self._current[user_id]
        return {
            "current": current,
            "playlists": {k: v.to_public() for k, v in self._by_user[user_id].items()},
        }
