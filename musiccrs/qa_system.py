"""Q&A system for answering questions about tracks and artists (R3.3)."""

from __future__ import annotations
import re
from typing import Optional, Tuple
from .playlist_db import (
    get_track_info,
    count_tracks_by_artist,
    get_albums_by_artist,
    get_top_tracks_by_artist,
    search_similar_artists,
    search_by_artist_title,
)


class QASystem:
    """Handles questions about tracks and artists."""
    
    def __init__(self):
        # Compile regex patterns for different question types
        self._patterns = self._compile_patterns()
    
    def _compile_patterns(self):
        """Define patterns for different question types."""
        return {
            # Track questions
            'track_album': [
                re.compile(r"what album is ['\"]?(.+?)['\"]?\s+(?:by|from)\s+['\"]?(.+?)['\"]?\s+(?:on|from|in)", re.IGNORECASE),
                re.compile(r"(?:what|which) album (?:is|does) ['\"]?(.+?)['\"]?\s+(?:by|from)\s+['\"]?(.+?)['\"]?\s+(?:appear )?(?:on|in|from)", re.IGNORECASE),
                re.compile(r"(?:what|which) album (?:is|does) ['\"]?(.+?)['\"]?\s+(?:by|from)\s+['\"]?(.+?)['\"]?$", re.IGNORECASE),
            ],
            'track_artist': [
                re.compile(r"who (?:sings|performs|recorded|made) ['\"]?(.+?)['\"]?", re.IGNORECASE),
                re.compile(r"who (?:is|was) the artist (?:of|for) ['\"]?(.+?)['\"]?", re.IGNORECASE),
            ],
            'track_exists': [
                re.compile(r"do you have (?:the song )?['\"]?(.+?)['\"]?\s+by\s+['\"]?(.+?)['\"]?$", re.IGNORECASE),
                re.compile(r"is ['\"]?(.+?)['\"]?\s+by\s+['\"]?(.+?)['\"]?\s+in (?:the |your )?(?:database|library)", re.IGNORECASE),
            ],
            'track_info': [
                re.compile(r"tell me about (?:the song |the track )?['\"]?(.+?)['\"]?\s+by\s+['\"]?(.+?)['\"]?$", re.IGNORECASE),
                re.compile(r"(?:what|give me) (?:info|information) (?:about|on) ['\"]?(.+?)['\"]?\s+by\s+['\"]?(.+?)['\"]?$", re.IGNORECASE),
            ],
            
            # Artist questions
            'artist_track_count': [
                re.compile(r"how many (?:songs|tracks) (?:by|from) ['\"]?(.+?)['\"]?(?:\s+(?:have|has|are there|in)|$)", re.IGNORECASE),
                re.compile(r"how many (?:songs|tracks) (?:are there )?(?:by|from) ['\"]?(.+?)['\"]?$", re.IGNORECASE),
                re.compile(r"how many (?:songs|tracks) (?:does |do )?['\"]?(.+?)['\"]? have", re.IGNORECASE),
            ],
            'artist_albums': [
                re.compile(r"what albums (?:does |did |has |have )?['\"]?(.+?)['\"]? (?:release|made|recorded|have)", re.IGNORECASE),
                re.compile(r"(?:list|show|tell me) (?:the )?albums (?:by|from) ['\"]?(.+?)['\"]?$", re.IGNORECASE),
            ],
            'artist_top_tracks': [
                re.compile(r"what are (?:the )?(?:most popular |top |best )?(?:songs|tracks) (?:by|from) ['\"]?(.+?)['\"]?$", re.IGNORECASE),
                re.compile(r"show me (?:the )?(?:most popular |top |best )?(?:songs|tracks) (?:by|from) ['\"]?(.+?)['\"]?$", re.IGNORECASE),
            ],
            'artist_similar': [
                re.compile(r"(?:what|which) artists are (?:like|similar to) ['\"]?(.+?)['\"]?$", re.IGNORECASE),
                re.compile(r"who (?:sounds|are artists) (?:like|similar to) ['\"]?(.+?)['\"]?$", re.IGNORECASE),
                re.compile(r"(?:what artists) (?:are|sound like|are similar to) ['\"]?(.+?)['\"]?$", re.IGNORECASE),
                re.compile(r"find (?:me )?(?:artists )?(?:like|similar to) ['\"]?(.+?)['\"]?$", re.IGNORECASE),
            ],
        }
    
    def answer_question(self, question: str):
        """
        Parse a question and return an answer or disambiguation request.
        Returns:
            - str: Direct answer text
            - dict: Disambiguation request with 'type': 'disambiguate', 'options': [...], 'context': {...}
            - None: Question cannot be parsed
        """
        question = question.strip()
        
        # Try track questions first
        result = self._try_track_questions(question)
        if result:
            return result
        
        # Try artist questions
        result = self._try_artist_questions(question)
        if result:
            return result
        
        return None
    
    def answer_from_selection(self, question_type: str, track_info: tuple) -> str:
        """
        Answer a question after user has selected from disambiguation options.
        
        Args:
            question_type: The type of question ('track_album', 'track_info', 'track_exists')
            track_info: Tuple of (track_uri, artist, title, album)
        
        Returns:
            Answer string
        """
        uri, artist, title, album = track_info
        
        if question_type == 'track_album':
            if album:
                return f"<b>{title}</b> by <b>{artist}</b> is on the album <b>{album}</b>."
            else:
                return f"<b>{title}</b> by <b>{artist}</b> is in the database, but no album information is available."
        
        elif question_type == 'track_info':
            if album:
                return f"<b>{title}</b> is a song by <b>{artist}</b> from the album <b>{album}</b>."
            else:
                return f"<b>{title}</b> is a song by <b>{artist}</b>. No album information is available."
        
        elif question_type == 'track_exists':
            return f"Yes, I have <b>{title}</b> by <b>{artist}</b> in the database."
        
        return "I'm not sure how to answer that question."
    
    def _rank_by_spotify_popularity(self, results: list) -> list:
        """
        Rank search results by Spotify popularity (R3.2 enhancement).
        
        Args:
            results: List of (track_uri, artist, title, album) tuples
        
        Returns:
            Same list sorted by Spotify popularity (highest first)
        """
        try:
            from .spotify_api import get_spotify_api
            spotify = get_spotify_api()
            if not spotify:
                return results  # Return as-is if Spotify unavailable
            
            # Add popularity scores
            with_popularity = []
            for uri, artist, title, album in results:
                popularity = spotify.get_track_popularity(artist, title)
                with_popularity.append((uri, artist, title, album, popularity))
            
            # Sort by popularity (descending)
            sorted_results = sorted(with_popularity, key=lambda x: x[4], reverse=True)
            
            # Remove popularity from output
            return [(uri, artist, title, album) for uri, artist, title, album, _ in sorted_results]
        except Exception as e:
            print(f"Warning: Could not rank by Spotify popularity: {e}")
            return results  # Return original order on error
    
    def _try_track_questions(self, question: str) -> Optional[str]:
        """Try to match and answer track-related questions."""
        
        # Track album question
        for pattern in self._patterns['track_album']:
            match = pattern.search(question)
            if match:
                title, artist = match.groups()
                return self._answer_track_album(artist.strip(), title.strip())
        
        # Track artist question
        for pattern in self._patterns['track_artist']:
            match = pattern.search(question)
            if match:
                title = match.group(1)
                return self._answer_track_artist(title.strip())
        
        # Track exists question
        for pattern in self._patterns['track_exists']:
            match = pattern.search(question)
            if match:
                if len(match.groups()) == 2:
                    title, artist = match.groups()
                    return self._answer_track_exists(artist.strip(), title.strip())
        
        # Track info question
        for pattern in self._patterns['track_info']:
            match = pattern.search(question)
            if match:
                if len(match.groups()) == 2:
                    title, artist = match.groups()
                    return self._answer_track_info(artist.strip(), title.strip())
        
        return None
    
    def _try_artist_questions(self, question: str) -> Optional[str]:
        """Try to match and answer artist-related questions."""
        
        # Artist track count
        for pattern in self._patterns['artist_track_count']:
            match = pattern.search(question)
            if match:
                artist = match.group(1)
                return self._answer_artist_track_count(artist.strip())
        
        # Artist albums
        for pattern in self._patterns['artist_albums']:
            match = pattern.search(question)
            if match:
                artist = match.group(1)
                return self._answer_artist_albums(artist.strip())
        
        # Artist top tracks
        for pattern in self._patterns['artist_top_tracks']:
            match = pattern.search(question)
            if match:
                artist = match.group(1)
                return self._answer_artist_top_tracks(artist.strip())
        
        # Similar artists
        for pattern in self._patterns['artist_similar']:
            match = pattern.search(question)
            if match:
                artist = match.group(1)
                return self._answer_similar_artists(artist.strip())
        
        return None
    
    # ========== Track answer methods ==========
    
    def _answer_track_album(self, artist: str, title: str):
        """Answer: What album is a track on?"""
        from .playlist_db import search_by_artist_title_fuzzy
        
        # First try exact match
        row = get_track_info(artist=artist, title=title)
        if row:
            _, a, t, album = row
            if album:
                return f"<b>{t}</b> by <b>{a}</b> is on the album <b>{album}</b>."
            else:
                return f"<b>{t}</b> by <b>{a}</b> is in the database, but no album information is available."
        
        # If exact match fails, try fuzzy search
        results = search_by_artist_title_fuzzy(artist, title, limit=10)
        
        if not results:
            return f"I couldn't find the track <b>{title}</b> by <b>{artist}</b> in the database."
        
        if len(results) == 1:
            # Only one match, answer directly
            uri, a, t, album = results[0]
            if album:
                return f"<b>{t}</b> by <b>{a}</b> is on the album <b>{album}</b>."
            else:
                return f"<b>{t}</b> by <b>{a}</b> is in the database, but no album information is available."
        
        # Multiple matches - return disambiguation request with Spotify ranking
        ranked_results = self._rank_by_spotify_popularity(results)
        return {
            'type': 'disambiguate',
            'question_type': 'track_album',
            'options': ranked_results,
            'context': {
                'artist': artist,
                'title': title,
                'action': 'answer album question'
            }
        }
    
    def _answer_track_artist(self, title: str) -> str:
        """Answer: Who sings/performs a track?"""
        # This is ambiguous - search for all tracks with this title
        from .playlist_db import search_by_title
        results = search_by_title(title, limit=10)
        
        if not results:
            return f"I couldn't find any track named <b>{title}</b> in the database."
        
        if len(results) == 1:
            _, artist, t, _ = results[0]
            return f"<b>{t}</b> is performed by <b>{artist}</b>."
        else:
            # Multiple artists have songs with this title
            artists = [row[1] for row in results[:5]]
            artists_html = ", ".join([f"<b>{a}</b>" for a in artists])
            more = f" (and {len(results) - 5} more)" if len(results) > 5 else ""
            return f"There are multiple songs named <b>{title}</b> by different artists: {artists_html}{more}. Please specify the artist."
    
    def _answer_track_exists(self, artist: str, title: str):
        """Answer: Does a track exist in the database?"""
        from .playlist_db import search_by_artist_title_fuzzy
        
        # First try exact match
        row = search_by_artist_title(artist, title)
        if row:
            return f"Yes, I have <b>{title}</b> by <b>{artist}</b> in the database."
        
        # Try fuzzy search
        results = search_by_artist_title_fuzzy(artist, title, limit=10)
        
        if not results:
            return f"No, I don't have <b>{title}</b> by <b>{artist}</b> in the database."
        
        if len(results) == 1:
            _, a, t, _ = results[0]
            return f"Yes, I have <b>{t}</b> by <b>{a}</b> in the database."
        
        # Multiple matches - return disambiguation with Spotify ranking
        ranked_results = self._rank_by_spotify_popularity(results)
        return {
            'type': 'disambiguate',
            'question_type': 'track_exists',
            'options': ranked_results,
            'context': {
                'artist': artist,
                'title': title,
                'action': 'answer track exists question'
            }
        }
    
    def _answer_track_info(self, artist: str, title: str):
        """Answer: General info about a track."""
        from .playlist_db import search_by_artist_title_fuzzy
        
        # First try exact match
        row = get_track_info(artist=artist, title=title)
        if row:
            _, a, t, album = row
            if album:
                return f"<b>{t}</b> is a song by <b>{a}</b> from the album <b>{album}</b>."
            else:
                return f"<b>{t}</b> is a song by <b>{a}</b>. No album information is available."
        
        # Try fuzzy search
        results = search_by_artist_title_fuzzy(artist, title, limit=10)
        
        if not results:
            return f"I couldn't find the track <b>{title}</b> by <b>{artist}</b> in the database."
        
        if len(results) == 1:
            uri, a, t, album = results[0]
            if album:
                return f"<b>{t}</b> is a song by <b>{a}</b> from the album <b>{album}</b>."
            else:
                return f"<b>{t}</b> is a song by <b>{a}</b>. No album information is available."
        
        # Multiple matches - return disambiguation with Spotify ranking
        ranked_results = self._rank_by_spotify_popularity(results)
        return {
            'type': 'disambiguate',
            'question_type': 'track_info',
            'options': ranked_results,
            'context': {
                'artist': artist,
                'title': title,
                'action': 'answer track info question'
            }
        }
    
    # ========== Artist answer methods ==========
    
    def _answer_artist_track_count(self, artist: str) -> str:
        """Answer: How many tracks by an artist?"""
        count = count_tracks_by_artist(artist)
        if count == 0:
            return f"I couldn't find any tracks by <b>{artist}</b> in the database."
        elif count == 1:
            return f"There is <b>1 track</b> by <b>{artist}</b> in the database."
        else:
            return f"There are <b>{count} tracks</b> by <b>{artist}</b> in the database."
    
    def _answer_artist_albums(self, artist: str) -> str:
        """Answer: What albums has an artist released?"""
        albums = get_albums_by_artist(artist)
        if not albums:
            count = count_tracks_by_artist(artist)
            if count > 0:
                return f"<b>{artist}</b> has tracks in the database, but no album information is available."
            else:
                return f"I couldn't find any information about <b>{artist}</b> in the database."
        
        if len(albums) <= 5:
            albums_html = ", ".join([f"<b>{a}</b>" for a in albums])
            return f"<b>{artist}</b> has the following albums in the database: {albums_html}."
        else:
            # Show first 5
            albums_html = ", ".join([f"<b>{a}</b>" for a in albums[:5]])
            return f"<b>{artist}</b> has {len(albums)} albums in the database. First few: {albums_html}... (and {len(albums) - 5} more)."
    
    def _answer_artist_top_tracks(self, artist: str) -> str:
        """Answer: What are the top/most popular tracks by an artist?"""
        tracks = get_top_tracks_by_artist(artist, limit=5)
        if not tracks:
            return f"I couldn't find any tracks by <b>{artist}</b> in the database."
        
        tracks_html = "<ol>" + "".join([f"<li><b>{t[2]}</b></li>" for t in tracks]) + "</ol>"
        return f"Here are some tracks by <b>{artist}</b>:{tracks_html}"
    
    def _answer_similar_artists(self, artist: str) -> str:
        """Answer: Which artists are similar?"""
        # First check if the artist exists
        count = count_tracks_by_artist(artist)
        if count == 0:
            return f"I couldn't find any tracks by <b>{artist}</b> in the database."
        
        similar = search_similar_artists(artist, limit=5)
        if not similar:
            return f"I couldn't find any similar artists to <b>{artist}</b> based on the database."
        
        artists_html = ", ".join([f"<b>{a}</b>" for a in similar])
        return f"Artists similar to <b>{artist}</b>: {artists_html}."
