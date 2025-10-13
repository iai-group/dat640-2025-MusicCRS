"""Spotify API integration for popularity ranking and playback (R3.2 and R3.6)."""

import os
import base64
import requests
from typing import Optional, Dict, List, Tuple
from dotenv import load_dotenv

# Load environment variables from '.env' file
load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")


class SpotifyAPI:
    """Handle Spotify Web API interactions with caching for performance."""
    
    def __init__(self):
        self.client_id = SPOTIFY_CLIENT_ID
        self.client_secret = SPOTIFY_CLIENT_SECRET
        self.access_token = None
        self.token_type = None
        # Cache for popularity and track details to avoid redundant API calls
        self._popularity_cache = {}  # (artist, title) -> popularity
        self._details_cache = {}      # (artist, title) -> full details
        
    def _get_auth_header(self) -> str:
        """Create base64 encoded authorization header."""
        if not self.client_id or not self.client_secret:
            return None
        auth_str = f"{self.client_id}:{self.client_secret}"
        auth_bytes = auth_str.encode("utf-8")
        auth_base64 = base64.b64encode(auth_bytes).decode("utf-8")
        return auth_base64
    
    def _get_access_token(self) -> bool:
        """Get access token using client credentials flow."""
        auth_header = self._get_auth_header()
        if not auth_header:
            return False
        
        url = "https://accounts.spotify.com/api/token"
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"grant_type": "client_credentials"}
        
        try:
            response = requests.post(url, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            json_result = response.json()
            self.access_token = json_result.get("access_token")
            self.token_type = json_result.get("token_type")
            return True
        except Exception as e:
            print(f"Error getting Spotify access token: {e}")
            return False
    
    def _ensure_token(self) -> bool:
        """Ensure we have a valid access token."""
        if not self.access_token:
            return self._get_access_token()
        return True
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get headers with authorization token."""
        if not self._ensure_token():
            return {}
        return {"Authorization": f"{self.token_type} {self.access_token}"}
    
    def search_track(self, artist: str, title: str) -> Optional[Dict]:
        """
        Search for a track on Spotify.
        Returns track data including popularity, preview_url, etc.
        """
        headers = self._get_auth_headers()
        if not headers:
            return None
        
        # Clean up title - remove version info for better matching
        clean_title = title.split('-')[0].strip() if '-' in title else title
        
        # Build query: if artist is unknown/empty, search by title only
        if artist and artist.lower() not in ['unknown', '', 'various artists']:
            query = f"track:{clean_title} artist:{artist}"
        else:
            # Search by title only (more permissive)
            query = f"track:{clean_title}"
        
        url = "https://api.spotify.com/v1/search"
        params = {
            "q": query,
            "type": "track",
            "limit": 1
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("tracks") and data["tracks"].get("items"):
                return data["tracks"]["items"][0]
            return None
        except Exception as e:
            print(f"Error searching Spotify: {e}")
            return None
    
    def get_track_popularity(self, artist: str, title: str) -> int:
        """
        Get popularity score for a track (0-100).
        Returns 0 if track not found or API unavailable.
        Uses caching to improve performance.
        """
        cache_key = (artist.lower(), title.lower())
        
        # Check cache first
        if cache_key in self._popularity_cache:
            return self._popularity_cache[cache_key]
        
        # Fetch from API
        track_data = self.search_track(artist, title)
        if track_data:
            popularity = track_data.get("popularity", 0)
            self._popularity_cache[cache_key] = popularity
            return popularity
        
        # Cache the zero result too
        self._popularity_cache[cache_key] = 0
        return 0
    
    def get_track_preview_url(self, artist: str, title: str) -> Optional[str]:
        """
        Get preview URL (30-second clip) for a track.
        Returns None if not available.
        """
        track_data = self.search_track(artist, title)
        if track_data:
            return track_data.get("preview_url")
        return None
    
    def get_track_details(self, artist: str, title: str) -> Optional[Dict]:
        """
        Get detailed track information including:
        - popularity: int (0-100)
        - preview_url: str or None
        - external_url: str (link to Spotify)
        - duration_ms: int
        - explicit: bool
        Uses caching to improve performance.
        """
        cache_key = (artist.lower(), title.lower())
        
        # Check cache first
        if cache_key in self._details_cache:
            return self._details_cache[cache_key]
        
        # Fetch from API
        track_data = self.search_track(artist, title)
        if not track_data:
            self._details_cache[cache_key] = None
            return None
        
        details = {
            "popularity": track_data.get("popularity", 0),
            "preview_url": track_data.get("preview_url"),
            "spotify_url": track_data.get("external_urls", {}).get("spotify"),
            "duration_ms": track_data.get("duration_ms", 0),
            "explicit": track_data.get("explicit", False),
            "album_image": track_data.get("album", {}).get("images", [{}])[0].get("url") if track_data.get("album", {}).get("images") else None,
        }
        
        self._details_cache[cache_key] = details
        return details
    
    def get_artist_info(self, artist_name: str) -> Optional[Dict]:
        """
        Get artist information including:
        - popularity: int (0-100)
        - genres: list
        - followers: int
        - spotify_url: str
        """
        headers = self._get_auth_headers()
        if not headers:
            return None
        
        # Search for artist
        url = "https://api.spotify.com/v1/search"
        params = {
            "q": f"artist:{artist_name}",
            "type": "artist",
            "limit": 1
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("artists") and data["artists"].get("items"):
                artist = data["artists"]["items"][0]
                return {
                    "name": artist.get("name"),
                    "popularity": artist.get("popularity", 0),
                    "genres": artist.get("genres", []),
                    "followers": artist.get("followers", {}).get("total", 0),
                    "spotify_url": artist.get("external_urls", {}).get("spotify"),
                    "image": artist.get("images", [{}])[0].get("url") if artist.get("images") else None,
                }
            return None
        except Exception as e:
            print(f"Error getting artist info: {e}")
            return None
    
    def rank_tracks_by_popularity(self, tracks: List[Tuple[str, str, str, Optional[str]]]) -> List[Tuple[str, str, str, Optional[str], int]]:
        """
        Rank tracks by Spotify popularity.
        
        Args:
            tracks: List of (track_uri, artist, title, album) tuples
        
        Returns:
            List of (track_uri, artist, title, album, popularity) tuples sorted by popularity (highest first)
        """
        tracks_with_popularity = []
        
        for track_uri, artist, title, album in tracks:
            popularity = self.get_track_popularity(artist, title)
            tracks_with_popularity.append((track_uri, artist, title, album, popularity))
        
        # Sort by popularity (descending)
        return sorted(tracks_with_popularity, key=lambda x: x[4], reverse=True)


# Global instance
_spotify_api = None

def get_spotify_api() -> Optional[SpotifyAPI]:
    """Get global Spotify API instance (singleton)."""
    global _spotify_api
    if _spotify_api is None:
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            _spotify_api = SpotifyAPI()
        else:
            return None
    return _spotify_api
