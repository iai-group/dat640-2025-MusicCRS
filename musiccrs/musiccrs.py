"""MusicCRS conversational agent with playlist + MPD validation.

Keeps original template commands:
  /info
  /ask_llm <prompt>
  /options
  /quit

Adds playlist commands (R2):
  /help
  /add [artist]: [title]
  /remove [index|track_uri]
  /view
  /clear
  /create [playlist_name]
  /switch [playlist_name]
  /list

Adds R3 commands:
  /add [title]  (search by title only)
  /ask [question]  (Q&A about tracks/artists)
  /stats  (playlist statistics)
"""

from __future__ import annotations

import os
import json
import re
from typing import List

import ollama
from dotenv import load_dotenv

from dialoguekit.core.annotated_utterance import AnnotatedUtterance
from dialoguekit.core.dialogue_act import DialogueAct
from dialoguekit.core.intent import Intent
from dialoguekit.core.slot_value_annotation import SlotValueAnnotation
from dialoguekit.core.utterance import Utterance
from dialoguekit.participant.agent import Agent
from dialoguekit.participant.participant import DialogueParticipant
from dialoguekit.platforms import FlaskSocketPlatform

from .playlist_service import PlaylistService
from .qa_system import QASystem

# Load environment variables from '.env' file
load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")

_INTENT_OPTIONS = Intent("OPTIONS")
_INTENT_DISAMBIGUATE = Intent("DISAMBIGUATE")

# ---------- helpers for the playlist UI sync ----------
def _playlist_marker(payload: dict | None) -> str:
    """Encode playlist payload in a hidden HTML comment the frontend can parse."""
    if not payload:
        return ""
    return f"<!--PLAYLIST:{json.dumps(payload, separators=(',', ':'))}-->"


class MusicCRS(Agent):
    def __init__(self, use_llm: bool = True):
        """Initialize MusicCRS agent compatible with your DialogueKit template."""
        super().__init__(id="MusicCRS")

        if use_llm and OLLAMA_HOST and OLLAMA_MODEL:
            self._llm = ollama.Client(
                host=OLLAMA_HOST,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else None,
            )
        else:
            self._llm = None

        # --- R2 state ---
        self._ps = PlaylistService()
        # If you later expose per-session IDs, replace this with the session/user id.
        self._user_key = "default"

        # --- R3 state ---
        self._qa = QASystem()
        self._pending_disambiguation = None  # Stores disambiguation state: {'type': 'add'|'qa', 'options': [...], 'context': {...}}

        # Pre-compiled command regexes
        self._cmd_add = re.compile(r"^/add\s+([^:]+)\s*:\s*(.+)$", re.IGNORECASE)
        self._cmd_add_title = re.compile(r"^/add\s+(.+)$", re.IGNORECASE)
        self._cmd_remove = re.compile(r"^/remove\s+(.+)$", re.IGNORECASE)
        self._cmd_view = re.compile(r"^/view$", re.IGNORECASE)
        self._cmd_clear = re.compile(r"^/clear$", re.IGNORECASE)
        self._cmd_create = re.compile(r"^/create\s+(.+)$", re.IGNORECASE)
        self._cmd_switch = re.compile(r"^/switch\s+(.+)$", re.IGNORECASE)
        self._cmd_list = re.compile(r"^/list$", re.IGNORECASE)
        self._cmd_help = re.compile(r"^/help$|^/options$", re.IGNORECASE)
        self._cmd_ask = re.compile(r"^/ask\s+(.+)$", re.IGNORECASE)
        self._cmd_stats = re.compile(r"^/stats$", re.IGNORECASE)
        self._cmd_play = re.compile(r"^/play(?:\s+(\d+))?$", re.IGNORECASE)  # R3.6: Play/preview
        self._cmd_preview = re.compile(r"^/preview\s+(.+)$", re.IGNORECASE)  # R3.6: Preview by search

    # ---------- DialogueKit lifecycle ----------
    def welcome(self) -> None:
        """Sends the agent's welcome message."""
        self._send_text("Hello, I'm MusicCRS. Type /help to see what I can do.")

    def goodbye(self) -> None:
        """Quits the conversation."""
        self._send_text(
            "It was nice talking to you. Bye",
            dialogue_acts=[DialogueAct(intent=self.stop_intent)],
        )

    # ---------- main dispatcher ----------
    def receive_utterance(self, utterance: Utterance) -> None:
        """Gets called each time there is a new user utterance (template-compatible)."""
        text = (utterance.text or "").strip()
        if not text:
            return

        try:
            # Handle numeric selections for disambiguation (R3.1)
            if self._pending_disambiguation and text.isdigit():
                self._handle_disambiguation_selection(int(text))
                return

            # Original template commands
            if text.startswith("/info"):
                self._send_text(self._info(), include_playlist=False)
                return

            if text.startswith("/ask_llm "):
                prompt = text[9:]
                self._send_text(self._ask_llm(prompt), include_playlist=False)
                return

            if text.startswith("/options"):
                options = [
                    "Play some jazz music",
                    "Recommend me some pop songs",
                    "Create a workout playlist",
                ]
                self._send_options(options)
                return

            if text == "/quit":
                self.goodbye()
                return

            # --- R3 commands (before R2 to handle /add with just title) ---
            
            # R3.3: Q&A system
            if m := self._cmd_ask.match(text):
                question = m.group(1).strip()
                answer = self._qa.answer_question(question)
                
                if answer is None:
                    self._send_text("I'm sorry, I don't understand that question. Try asking about tracks or artists.", include_playlist=False)
                elif isinstance(answer, dict) and answer.get('type') == 'disambiguate':
                    # Handle disambiguation for QA questions
                    self._handle_qa_disambiguation(answer)
                else:
                    # Direct answer
                    self._send_text(answer, include_playlist=False)
                return

            # R3.5: Playlist statistics
            if self._cmd_stats.match(text):
                stats = self._ps.get_playlist_stats(self._user_key)
                html = self._format_stats(stats)
                self._send_playlist_text(html)
                return
            
            # R3.6: Play/preview commands
            if m := self._cmd_play.match(text):
                track_num = m.group(1)
                self._handle_play(int(track_num) if track_num else None)
                return
            
            if m := self._cmd_preview.match(text):
                query = m.group(1).strip()
                self._handle_preview_search(query)
                return

            # --- R2 playlist commands ---
            
            # R3.1 Enhanced: Parse natural language patterns for /add
            # Support: "title by artist", "artist - title", "artist: title"
            if text.startswith("/add "):
                query = text[5:].strip()  # Remove "/add " prefix
                
                artist = None
                title = None
                
                # Pattern 1: "artist: title" (original format)
                if ":" in query:
                    m = self._cmd_add.match(text)
                    if m:
                        artist = m.group(1).strip()
                        title = m.group(2).strip()
                
                # Pattern 2: "title by artist" (natural language)
                elif " by " in query.lower():
                    # Split on " by " case-insensitively
                    parts = query.lower().split(" by ")
                    if len(parts) == 2:
                        # Get original case versions
                        idx = query.lower().index(" by ")
                        title = query[:idx].strip()
                        artist = query[idx + 4:].strip()  # +4 for " by "
                
                # Pattern 3: "artist - title" (common format)
                elif " - " in query:
                    parts = query.split(" - ", 1)
                    if len(parts) == 2:
                        artist = parts[0].strip()
                        title = parts[1].strip()
                
                # If artist and title are parsed, search by both
                if artist and title:
                    # Try exact match first
                    from .playlist_db import get_track
                    track_data = get_track(artist, title)
                    if track_data:
                        track = self._ps.add_by_uri(self._user_key, track_data[0])
                        self._send_playlist_text(f"Added <b>{track.artist} – {track.title}</b>.")
                        return
                    else:
                        # Try fuzzy search
                        from .playlist_db import search_by_artist_title_fuzzy
                        fuzzy_results = search_by_artist_title_fuzzy(artist, title, limit=10)
                        if fuzzy_results:
                            if len(fuzzy_results) == 1:
                                track = self._ps.add_by_uri(self._user_key, fuzzy_results[0][0])
                                self._send_playlist_text(f"Added <b>{track.artist} – {track.title}</b>.")
                                return
                            else:
                                # Multiple fuzzy matches, show disambiguation
                                self._handle_disambiguation(f"{artist} - {title}", fuzzy_results)
                                return
                        else:
                            self._send_text(f"No tracks found with artist <b>{artist}</b> and title <b>{title}</b>.", include_playlist=False)
                            return
                
                # Pattern 4: Title only (fallback)
                else:
                    title = query
                    results = self._ps.search_tracks_by_title(self._user_key, title)
                    if not results:
                        self._send_text(f"No tracks found with title <b>{title}</b>.", include_playlist=False)
                    elif len(results) == 1:
                        # Only one match, add it directly
                        track = self._ps.add_by_uri(self._user_key, results[0][0])
                        self._send_playlist_text(f"Added <b>{track.artist} – {track.title}</b>.")
                    else:
                        # Multiple matches, ask user to choose (R3.1 disambiguation)
                        self._handle_disambiguation(title, results)
                    return

            if m := self._cmd_remove.match(text):
                ident = m.group(1).strip()
                track = self._ps.remove(self._user_key, ident)
                self._send_playlist_text(f"Removed <b>{track.artist} – {track.title}</b>.")
                return

            if self._cmd_view.match(text):
                pl = self._ps.current_playlist(self._user_key)
                if pl.tracks:
                    lines = "".join([f"<li>{i+1}. {t.artist} – {t.title}</li>" for i, t in enumerate(pl.tracks)])
                    html = f"<b>{pl.name}</b> ({len(pl.tracks)} tracks)<ol>{lines}</ol>"
                else:
                    html = f"<b>{pl.name}</b> is empty."
                self._send_playlist_text(html)
                return

            if self._cmd_clear.match(text):
                self._ps.clear(self._user_key)
                self._send_playlist_text("Cleared the current playlist.")
                return

            if m := self._cmd_create.match(text):
                name = m.group(1).strip()
                self._ps.create_playlist(self._user_key, name)
                self._send_playlist_text(f"Created and switched to playlist <b>{name}</b>.")
                return

            if m := self._cmd_switch.match(text):
                name = m.group(1).strip()
                self._ps.switch_playlist(self._user_key, name)
                self._send_playlist_text(f"Switched to playlist <b>{name}</b>.")
                return

            if self._cmd_list.match(text):
                names = self._ps.list_playlists(self._user_key)
                html = "Your playlists: " + ", ".join(f"<b>{n}</b>" for n in names)
                self._send_playlist_text(html)
                return

            if self._cmd_help.match(text):
                self._send_playlist_text(self._help_text())
                return

            # Fallback if unknown
            self._send_text("I'm sorry, I don't understand that command. Type /help.", include_playlist=False)

        except Exception as e:
            self._send_text(f"Error: {str(e)}", include_playlist=False)

    # ---------- Original template helpers ----------
    def _info(self) -> str:
        return "I am MusicCRS, a conversational recommender system for music."

    def _ask_llm(self, prompt: str) -> str:
        if not self._llm:
            return "The agent is not configured to use an LLM"
        llm_response = self._llm.generate(
            model=OLLAMA_MODEL,
            prompt=prompt,
            options={
                "stream": False,
                "temperature": 0.7,
                "max_tokens": 100,
            },
        )
        return f"LLM response: {llm_response['response']}"

    def _send_options(self, options: list[str]) -> None:
        """Mimic your template /options with dialogue_acts for quick-replies."""
        response = (
            "Here are some options:\n<ol>\n"
            + "\n".join([f"<li>{option}</li>" for option in options])
            + "</ol>\n"
        )
        dialogue_acts = [
            DialogueAct(
                intent=_INTENT_OPTIONS,
                annotations=[SlotValueAnnotation("option", option) for option in options],
            )
        ]
        self._send_text(response, include_playlist=False, dialogue_acts=dialogue_acts)

    # ---------- R2 helpers ----------
    def _help_text(self) -> str:
        return (
            "I can manage playlists for you. Use these commands:<br/>"
            "<ul>"
            "<li><code>/add [title]</code> &mdash; add a song by title (I'll help you choose if multiple matches)</li>"
            "<li><code>/add [title] by [artist]</code> &mdash; natural language format</li>"
            "<li><code>/add [artist] - [title]</code> &mdash; dash-separated format</li>"
            "<li><code>/add [artist]: [title]</code> &mdash; colon-separated format</li>"
            "<li><code>/remove [index|track_uri]</code> &mdash; remove by 1-based index or track URI</li>"
            "<li><code>/view</code> &mdash; show current playlist</li>"
            "<li><code>/clear</code> &mdash; remove all tracks</li>"
            "<li><code>/create [name]</code> &mdash; create and switch to a new playlist</li>"
            "<li><code>/switch [name]</code> &mdash; switch current playlist</li>"
            "<li><code>/list</code> &mdash; list your playlists</li>"
            "<li><code>/ask [question]</code> &mdash; ask about tracks or artists</li>"
            "<li><code>/stats</code> &mdash; show playlist statistics</li>"
            "<li><code>/play [number]</code> &mdash; get Spotify link for a track in your playlist</li>"
            "<li><code>/preview [artist/title]</code> &mdash; search for a track preview</li>"
            "</ul>"
            "Tip: songs must exist in the database. You can use natural formats like <code>Hey Jude by The Beatles</code> or <code>The Beatles - Hey Jude</code>."
        )

    # ---------- R3 helpers ----------
    def _handle_disambiguation(self, title: str, results: list) -> None:
        """Present disambiguation options to user (R3.1)."""
        self._pending_disambiguation = {
            'type': 'add',
            'options': results,
            'context': {'title': title, 'action': 'add track'}
        }
        
        # Limit to first 10 results
        display_results = results[:10]
        
        html = f"I found <b>{len(results)}</b> tracks with the title <b>{title}</b>. Please choose:<br/><ol>"
        for i, (uri, artist, track_title, album) in enumerate(display_results, 1):
            album_text = f" (from <i>{album}</i>)" if album else ""
            html += f"<li><b>{artist}</b> – {track_title}{album_text}</li>"
        html += "</ol>"
        
        if len(results) > 10:
            html += f"<br/><i>Showing first 10 of {len(results)} results.</i><br/>"
        
        html += "Type the number to add that track."
        
        # Create options for the dialogue acts
        options = [f"{i}. {results[i-1][1]} – {results[i-1][2]}" for i in range(1, min(len(results) + 1, 11))]
        
        dialogue_acts = [
            DialogueAct(
                intent=_INTENT_DISAMBIGUATE,
                annotations=[SlotValueAnnotation("option", opt) for opt in options],
            )
        ]
        
        self._send_text(html, include_playlist=False, dialogue_acts=dialogue_acts)
    
    def _handle_qa_disambiguation(self, disambiguation_result: dict) -> None:
        """Present disambiguation options for QA questions (R3.3)."""
        options = disambiguation_result['options']
        context = disambiguation_result['context']
        question_type = disambiguation_result.get('question_type', 'track_info')
        
        self._pending_disambiguation = {
            'type': 'qa',
            'options': options,
            'context': {
                **context,
                'question_type': question_type
            }
        }
        
        # Limit to first 10 results
        display_results = options[:10]
        
        artist_query = context.get('artist', '')
        title_query = context.get('title', '')
        
        html = f"I found <b>{len(options)}</b> tracks matching <b>{title_query}</b> by <b>{artist_query}</b>. Which one did you mean?<br/><ol>"
        for i, (uri, artist, track_title, album) in enumerate(display_results, 1):
            album_text = f" (from <i>{album}</i>)" if album else ""
            html += f"<li><b>{artist}</b> – {track_title}{album_text}</li>"
        html += "</ol>"
        
        if len(options) > 10:
            html += f"<br/><i>Showing first 10 of {len(options)} results.</i><br/>"
        
        html += "Type the number to select that track."
        
        # Create options for the dialogue acts
        option_strs = [f"{i}. {options[i-1][1]} – {options[i-1][2]}" for i in range(1, min(len(options) + 1, 11))]
        
        dialogue_acts = [
            DialogueAct(
                intent=_INTENT_DISAMBIGUATE,
                annotations=[SlotValueAnnotation("option", opt) for opt in option_strs],
            )
        ]
        
        self._send_text(html, include_playlist=False, dialogue_acts=dialogue_acts)
    
    def _handle_disambiguation_selection(self, choice: int) -> None:
        """Handle user's selection from disambiguation options (R3.1 and R3.3)."""
        if not self._pending_disambiguation:
            self._send_text("No pending selection. Use <code>/add [title]</code> or <code>/ask</code> to get options.", include_playlist=False)
            return
        
        # Get disambiguation type and options
        if isinstance(self._pending_disambiguation, dict):
            # New format: {'type': 'add'|'qa', 'options': [...], 'context': {...}}
            dtype = self._pending_disambiguation.get('type', 'add')
            options = self._pending_disambiguation.get('options', [])
            context = self._pending_disambiguation.get('context', {})
        else:
            # Legacy format: just a list of options (for /add)
            dtype = 'add'
            options = self._pending_disambiguation
            context = {}
        
        if choice < 1 or choice > len(options):
            self._send_text(f"Invalid choice. Please select a number between 1 and {len(options)}.", include_playlist=False)
            return
        
        # Get the selected track
        selected = options[choice - 1]
        track_uri = selected[0]
        
        # Clear pending disambiguation
        self._pending_disambiguation = None
        
        # Handle based on type
        try:
            if dtype == 'qa':
                # Answer the question with the selected track
                question_type = context.get('question_type', 'track_info')
                answer = self._qa.answer_from_selection(question_type, selected)
                self._send_text(answer, include_playlist=False)
            else:
                # Add the track (R3.1)
                track = self._ps.add_by_uri(self._user_key, track_uri)
                self._send_playlist_text(f"Added <b>{track.artist} – {track.title}</b>.")
        except Exception as e:
            self._send_text(f"Error: {str(e)}", include_playlist=False)
    
    def _handle_play(self, track_num: int = None) -> None:
        """Handle /play command - get Spotify link for a track (R3.6)."""
        pl = self._ps.current_playlist(self._user_key)
        
        if not pl.tracks:
            self._send_text("Your playlist is empty. Add some tracks first!", include_playlist=False)
            return
        
        # If no track number specified, show list with play options
        if track_num is None:
            html = f"<b>{pl.name}</b> tracks:<br/><ol>"
            for i, track in enumerate(pl.tracks, 1):
                html += f"<li>{track.artist} – {track.title}</li>"
            html += "</ol>"
            html += "Use <code>/play [number]</code> to get the Spotify link for a track."
            self._send_text(html, include_playlist=False)
            return
        
        # Validate track number
        if track_num < 1 or track_num > len(pl.tracks):
            self._send_text(f"Invalid track number. Please choose between 1 and {len(pl.tracks)}.", include_playlist=False)
            return
        
        track = pl.tracks[track_num - 1]
        
        # Get Spotify details
        try:
            from .spotify_api import get_spotify_api
            spotify = get_spotify_api()
            if not spotify:
                self._send_text("Spotify integration is not available.", include_playlist=False)
                return
            
            details = spotify.get_track_details(track.artist, track.title)
            if details and details['spotify_url']:
                # Extract track ID from Spotify URL for embed
                track_id = details['spotify_url'].split('/')[-1].split('?')[0]
                
                html = f"🎵 <b>{track.artist} – {track.title}</b><br/>"
                html += f"<a href='{details['spotify_url']}' target='_blank'>▶️ Play on Spotify</a><br/>"
                html += f"Popularity: {details['popularity']}/100 ⭐<br/>"
                html += f"Duration: {details['duration_ms'] // 1000 // 60}:{(details['duration_ms'] // 1000) % 60:02d}<br/>"
                
                # Add Spotify iframe embed for playback (works without Web Playback SDK)
                # Users can play 30-second previews or full tracks (with Spotify account)
                html += f"<br/><iframe style='border-radius:12px' src='https://open.spotify.com/embed/track/{track_id}' "
                html += f"width='100%' height='152' frameBorder='0' allowfullscreen='' "
                html += f"allow='autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture' loading='lazy'></iframe>"
                
                self._send_text(html, include_playlist=False)
            else:
                self._send_text(f"Could not find <b>{track.artist} – {track.title}</b> on Spotify.", include_playlist=False)
        except Exception as e:
            self._send_text(f"Error getting Spotify info: {str(e)}", include_playlist=False)
    
    def _handle_preview_search(self, query: str) -> None:
        """Handle /preview command - search and preview a track (R3.6)."""
        try:
            from .spotify_api import get_spotify_api
            spotify = get_spotify_api()
            if not spotify:
                self._send_text("Spotify integration is not available.", include_playlist=False)
                return
            
            # Parse query (simple: assume "artist - title" or just search as-is)
            if ' - ' in query or ':' in query:
                parts = query.replace(':', '-').split('-', 1)
                artist = parts[0].strip()
                title = parts[1].strip() if len(parts) > 1 else query
            else:
                # Search by title only (empty artist allows broader search)
                artist = ""
                title = query
            
            track_data = spotify.search_track(artist, title)
            if track_data:
                name = track_data['name']
                artist_name = track_data['artists'][0]['name'] if track_data.get('artists') else "Unknown"
                spotify_url = track_data.get('external_urls', {}).get('spotify')
                popularity = track_data.get('popularity', 0)
                duration_ms = track_data.get('duration_ms', 0)
                track_id = track_data.get('id', '')
                
                html = f"🎵 <b>{artist_name} – {name}</b><br/>"
                if spotify_url:
                    html += f"<a href='{spotify_url}' target='_blank'>▶️ Play on Spotify</a><br/>"
                html += f"Popularity: {popularity}/100 ⭐<br/>"
                html += f"Duration: {duration_ms // 1000 // 60}:{(duration_ms // 1000) % 60:02d}<br/>"
                
                # Add Spotify iframe embed for playback
                if track_id:
                    html += f"<br/><iframe style='border-radius:12px' src='https://open.spotify.com/embed/track/{track_id}' "
                    html += f"width='100%' height='152' frameBorder='0' allowfullscreen='' "
                    html += f"allow='autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture' loading='lazy'></iframe>"
                
                self._send_text(html, include_playlist=False)
            else:
                self._send_text(f"Could not find '{query}' on Spotify.", include_playlist=False)
        except Exception as e:
            self._send_text(f"Error searching Spotify: {str(e)}", include_playlist=False)

    def _format_stats(self, stats: dict) -> str:
        """Format playlist statistics for display (R3.5)."""
        html = f"<h3>📊 Statistics for <b>{stats['playlist_name']}</b></h3>"
        html += "<ul>"
        html += f"<li><b>Total tracks:</b> {stats['total_tracks']}</li>"
        html += f"<li><b>Unique artists:</b> {stats['unique_artists']}</li>"
        html += f"<li><b>Unique albums:</b> {stats['unique_albums']}</li>"
        
        # Spotify-enhanced statistics
        if 'avg_popularity' in stats:
            html += f"<li><b>Average popularity:</b> {stats['avg_popularity']}/100 ⭐</li>"
        
        if 'estimated_duration_minutes' in stats:
            html += f"<li><b>Estimated duration:</b> ~{stats['estimated_duration_minutes']} minutes</li>"
        
        if stats.get('top_genres'):
            html += "<li><b>Top genres:</b> "
            genre_list = [f"<i>{genre}</i> ({count})" for genre, count in stats['top_genres']]
            html += ", ".join(genre_list)
            html += "</li>"
        
        if stats['top_artists']:
            html += "<li><b>Top artists:</b><ol>"
            for artist, count in stats['top_artists']:
                plural = "track" if count == 1 else "tracks"
                html += f"<li><b>{artist}</b> ({count} {plural})</li>"
            html += "</ol></li>"
        
        html += "</ul>"
        
        if stats['total_tracks'] == 0:
            html = f"<b>{stats['playlist_name']}</b> is empty. Add some tracks to see statistics!"
        
        return html

    def _current_playlist_payload(self) -> dict:
        state = self._ps.serialize_state(self._user_key)
        curr = state["current"]
        return state["playlists"][curr]

    # ---------- message send utilities (template-compatible) ----------
    def _send_text(self, text_html: str, *, include_playlist: bool = False, dialogue_acts: list[DialogueAct] | None = None) -> None:
        """Send a message exactly how your template does (register with connector)."""
        payload = self._current_playlist_payload() if include_playlist else None
        text = text_html + _playlist_marker(payload)
        self._dialogue_connector.register_agent_utterance(
            AnnotatedUtterance(
                text,
                participant=DialogueParticipant.AGENT,
                dialogue_acts=dialogue_acts or [],
            )
        )

    def _send_playlist_text(self, text_html: str) -> None:
        """Convenience: always include the current playlist marker."""
        self._send_text(text_html, include_playlist=True)


if __name__ == "__main__":
    platform = FlaskSocketPlatform(MusicCRS)
    platform.start()
