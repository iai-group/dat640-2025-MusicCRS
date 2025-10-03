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

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")

_INTENT_OPTIONS = Intent("OPTIONS")

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

        # Pre-compiled command regexes
        self._cmd_add = re.compile(r"^/add\s+([^:]+)\s*:\s*(.+)$", re.IGNORECASE)
        self._cmd_remove = re.compile(r"^/remove\s+(.+)$", re.IGNORECASE)
        self._cmd_view = re.compile(r"^/view$", re.IGNORECASE)
        self._cmd_clear = re.compile(r"^/clear$", re.IGNORECASE)
        self._cmd_create = re.compile(r"^/create\s+(.+)$", re.IGNORECASE)
        self._cmd_switch = re.compile(r"^/switch\s+(.+)$", re.IGNORECASE)
        self._cmd_list = re.compile(r"^/list$", re.IGNORECASE)
        self._cmd_help = re.compile(r"^/help$|^/options$", re.IGNORECASE)

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

            # --- R2 playlist commands ---
            if m := self._cmd_add.match(text):
                artist, title = m.group(1).strip(), m.group(2).strip()
                track = self._ps.add(self._user_key, artist, title)
                self._send_playlist_text(f"Added <b>{track.artist} – {track.title}</b>.")
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
            "<li><code>/add [artist]: [title]</code> &mdash; add a song (exact match in DB)</li>"
            "<li><code>/remove [index|track_uri]</code> &mdash; remove by 1-based index or track URI</li>"
            "<li><code>/view</code> &mdash; show current playlist</li>"
            "<li><code>/clear</code> &mdash; remove all tracks</li>"
            "<li><code>/create [name]</code> &mdash; create and switch to a new playlist</li>"
            "<li><code>/switch [name]</code> &mdash; switch current playlist</li>"
            "<li><code>/list</code> &mdash; list your playlists</li>"
            "</ul>"
            "Tip: songs must exist in the database. Provide them as <code>Artist: Title</code>."
        )

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
