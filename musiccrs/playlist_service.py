from __future__ import annotations
import os, re, hashlib
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
from .playlist_db import ensure_db, search_by_artist_title, get_track_by_uri
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
