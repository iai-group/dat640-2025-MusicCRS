"""Simulator client to interact with MusicCRS server.

It connects to the MusicCRS server specified in config.py.

The simulator can be run with the following flags:
  --no-upload: Disables uploading the dialogue to the simulation server.
  --check-uploads: Checks the upload status of the simulations.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from typing import Any

import colorama
import config
import ollama
import requests
import socketio
from dialoguekit.core.annotated_utterance import AnnotatedUtterance
from dialoguekit.core.dialogue import Dialogue
from dialoguekit.core.dialogue_act import DialogueAct
from dialoguekit.core.intent import Intent
from dialoguekit.core.slot_value_annotation import SlotValueAnnotation
from dialoguekit.core.utterance import Utterance
from dialoguekit.participant import DialogueParticipant

_SIMULATION_SERVER_URL = "http://gustav1.ux.uis.no:5000"

_HEADERS = {"X-Auth-Token": config.UPLOAD_TOKEN}

_OLLAMA_HOST = "https://ollama.ux.uis.no"
_OLLAMA_MODEL = "llama3.3:70b"

_PROMPT_TEMPLATE = """# 1. System Instructions: User Persona Simulation

You are an advanced conversational AI user simulator. Your sole task is to emulate the behavior, preferences, and conversational style of the user described below, in the context of a music recommendation system.

* **Goal:** Follow the sequence of planned interactions as closely as possible.
* **Decision-Making:** Determine the *next logical utterance* based on the current dialogue history and the overall interaction plan.
* **Style:** Maintain consistency with the user's stated personality and preferences.
* **Output Format:** You **must** only output the user's next utterance. Do not include any other text or reasoning and do not use quotes or any formatting around the text.

# 2. User Information (User Persona)

This JSON object contains the key personality traits, preferences, and situational context of the user you are simulating.

```json
{PERSONA}
```

# 3. Planned Interaction Sequence

{INTERACTION_PLAN}

# 4. Current Dialogue History

{DIALOGUE_HISTORY}

# 5. Your Next Utterance (JSON Output)

Based on the System Instructions (1), the User Persona (2), the Planned Sequence (3), and the Dialogue History (4), what is the next logical utterance from the simulated user?

"""

_SIMULATIONS = [
    {
        "name": "Predefined command sequence (add only)",
        "mode": "predefined_sequence",
        "dialogue_acts": [
            {"intent": "GREETING"},
            {"intent": "ADD_TRACK", "artist": "Bon Jovi", "track": "Always"},
            {
                "intent": "ADD_TRACK",
                "artist": "ABBA",
                "track": "Money, Money, Money",
            },
            {"intent": "QUIT"},
        ],
    },
    {
        "name": "Predefined command sequence (add, remove, list)",
        "mode": "predefined_sequence",
        "dialogue_acts": [
            {"intent": "ADD_TRACK", "artist": "Bon Jovi", "track": "Always"},
            {
                "intent": "ADD_TRACK",
                "artist": "ABBA",
                "track": "Money, Money, Money",
            },
            {
                "intent": "REMOVE_TRACK",
                "artist": "Bon Jovi",
                "track": "Bad Medicine",
            },
            {
                "intent": "REMOVE_TRACK",
                "artist": "ABBA",
                "track": "Money, Money, Money",
            },
            {
                "intent": "ADD_TRACK",
                "artist": "Bon Jovi",
                "track": "Bad Medicine",
            },
            {"intent": "SHOW_PLAYLIST"},
            {"intent": "QUIT"},
        ],
    },
    {
        "name": "Predefined command sequence (recommend)",
        "mode": "predefined_sequence",
        "dialogue_acts": [
            {
                "intent": "ADD_TRACK",
                "artist": "Green Day",
                "track": "Wake Me Up When September Ends",
            },
            {
                "intent": "ADD_TRACK",
                "artist": "Good Charlotte",
                "track": "We Believe",
            },
            {
                "intent": "ADD_TRACK",
                "artist": "My Chemical Romance",
                "track": "Disenchanted",
            },
            {"intent": "RECOMMEND"},
            {"intent": "QUIT"},
        ],
    },
    {
        "name": "NL interactions (add, non-existing)",
        "mode": "llm",
        "interaction_plan": "Ask for the track 'Bohemian Rhapsody' by Queen to be added to the playlist. Greet the agent first, and then say goodbye at the end.",
    },
    {
        "name": "NL interactions (add, ambiguous)",
        "mode": "llm",
        "interaction_plan": "Ask for the track 'Goodbye' to be added to the playlist without stating the artist. If the agent asks for the artist, then say that it's 'Chris Young'. If a song with the same title by some other artist is added, then ask for it to be removed from the playlist and have the one by 'Chris Young' added instead. Greet the agent first, and then say goodbye at the end.",
    },
    {
        "name": "NL interactions (add, remove, list)",
        "mode": "llm",
        "interaction_plan": "\n".join(
            [
                "- Ask for 'Money, Money, Money' by 'ABBA' to be added to the playlist.",
                "- Then ask for 'Bad Medicine' by 'Bon Jovi' to be added.",
                "- Next, request the removal of 'Money, Money, Money' from the playlist.",
                "- After that, ask to see the current playlist.",
                "- Finally, say goodbye to the agent.",
            ]
        ),
    },
    {
        "name": "NL interactions (recommend)",
        "mode": "llm",
        "use_persona": True,
        "repeat_count": 3,
        "interaction_plan": "Identify 2-3 popular tracks that this person might like, given the context. Then, ask the agent to add these one by one to the playlist, without stating the context. Next, ask the agent to recommend one additional track based on the current playlist. Choose a track that this person would most likely enjoy listening to in the given context. Finally, say goodbye to the agent.",
    },
    {
        "name": "NL interactions (generate playlist)",
        "mode": "llm",
        "use_persona": True,
        "repeat_count": 3,
        "interaction_plan": "Ask the agent to generate a playlist for the given context defined in the user persona. Greet the agent first, and then say goodbye at the end.",
    },
]

# Maximum number of dialogue turns before terminating the simulation.
_MAX_SIMULATION_TURNS = 12

# Enable cross-platform functionality of colored terminal text.
colorama.init(autoreset=True)


class SimulatorClient:
    def __init__(
        self,
        server_url: str,
        llm: ollama.Client,
        agent_id: str = "MusicCRS",
        simulated_user_id: str = "sim_user",
        simulation_config: dict[str, Any] = {},
        upload: bool = True,
    ) -> None:
        self._server_url = server_url
        self._agent_id = agent_id
        self._simulated_user_id = simulated_user_id
        self._simulation_config = simulation_config
        self._upload = upload
        self._sio_client = socketio.Client()
        self._sent_messages = []  # Keep track of emitted messages
        self._dialogue_history = Dialogue(agent_id, simulated_user_id)
        self._llm = llm
        self._sio_client.on("*", self.on_any_event)

    def _log_agent_message(self, message: dict) -> None:
        """Logs an agent message to the dialogue history."""
        agent_utterance = AnnotatedUtterance(
            text=message["text"],
            participant=DialogueParticipant.AGENT,
            timestamp=datetime.now(),
        )
        if message["dialogue_acts"]:
            dialogue_acts = []
            for da in message["dialogue_acts"]:
                annotations = []
                for annotation in da.get("annotations", []):
                    if "slot" in annotation and "value" in annotation:
                        annotations.append(
                            SlotValueAnnotation(
                                slot=annotation["slot"],
                                value=annotation["value"],
                            )
                        )
                dialogue_acts.append(
                    DialogueAct(
                        intent=Intent(label=da["intent"]),
                        annotations=annotations,
                    )
                )
            agent_utterance.add_dialogue_acts(dialogue_acts)
        self._dialogue_history.add_utterance(agent_utterance)

    def on_any_event(self, event: str, data: Any | None = None) -> None:
        if event != "message" or not data or "message" not in data:
            return

        message = data["message"]
        print(colorama.Style.DIM + f"💬 MusicCRS: {message['text']}")
        self._log_agent_message(message)
        time.sleep(1)

        # Check if agent terminates dialogue
        for dialogue_act in data["message"].get("dialogue_acts", []):
            if dialogue_act["intent"] == "EXIT":
                self.disconnect()
                return

        # Make sure we don't exceed max turns
        if len(self._sent_messages) >= _MAX_SIMULATION_TURNS:
            print("⚠️ Max simulation turns reached, terminating...")
            self.disconnect()
            return

        # Simulation logic based on predefined sequence
        if self._simulation_config.get("mode") == "predefined_sequence":
            if len(self._sent_messages) < len(
                self._simulation_config["dialogue_acts"]
            ):
                dialogue_act = self._simulation_config["dialogue_acts"][
                    len(self._sent_messages)
                ]
                message = config.COMMANDS[dialogue_act["intent"]]
                for key, value in dialogue_act.items():
                    if key != "intent":
                        message = message.replace(f"[{key}]", value)
                self.send(message)
        # Simulation logic based on LLM
        elif self._simulation_config.get("mode") == "llm":
            prompt = _get_llm_prompt(
                persona=self._simulation_config.get("persona", "{}"),
                dialogue_history=self._dialogue_history,
                instructions=self._simulation_config.get(
                    "interaction_plan", ""
                ),
            )
            llm_response = get_llm_response(self._llm, prompt)
            self.send(llm_response)

    def connect(self) -> None:
        self._sio_client.connect(self._server_url)
        self._sio_client.wait()

    def disconnect(self) -> None:
        print("⛓️‍💥 Disconnecting...")
        if self._upload:
            upload_dialogue(
                self._dialogue_history, self._agent_id, self._simulated_user_id
            )
        self._sio_client.disconnect()

    def send(self, message: str) -> None:
        """Sends a message and logs it."""
        self._sio_client.send({"message": message})
        self._sent_messages.append(message)
        self._dialogue_history.add_utterance(
            Utterance(
                text=message,
                participant=DialogueParticipant.USER,
                timestamp=datetime.now(),
            )
        )
        print(
            colorama.Style.DIM
            + colorama.Fore.YELLOW
            + f"➡️ Simulator: {message}"
        )


def _get_llm_prompt(
    persona: str, dialogue_history: Dialogue, instructions: str
) -> str:
    """Returns the prompt template for LLM-based simulations."""
    dialogue_turns = []
    for utterance in dialogue_history.utterances:
        speaker = (
            "AGENT"
            if utterance.participant == DialogueParticipant.AGENT
            else "USER"
        )
        dialogue_turns.append({"speaker": speaker, "text": utterance.text})

    return (
        _PROMPT_TEMPLATE.replace("{PERSONA}", json.dumps(persona, indent=2))
        .replace("{DIALOGUE_HISTORY}", json.dumps(dialogue_turns, indent=2))
        .replace("{INTERACTION_PLAN}", instructions)
    )


def get_llm_response(
    llm: ollama.Client, prompt: str, debug: bool = False
) -> str:
    """Calls a large language model (LLM) with the given prompt."""
    if debug:
        print("🧠 Calling LLM...")
        print(prompt)
    try:
        llm_response = llm.generate(
            model=_OLLAMA_MODEL,
            prompt=prompt,
            options={
                "stream": False,
                "temperature": 0.1,
                "max_tokens": 100,
            },
        )
    except Exception as e:
        print(f"⚠️ Error during LLM call: {e}")
        return ""
    if debug:
        print("🧠 LLM response:")
        print(llm_response["response"])
    return llm_response["response"]


def compute_hash(filename: str) -> str:
    """Computes the SHA256 hash of a file."""
    hasher = hashlib.sha256()
    with open(filename, "rb") as f:
        buf = f.read()
        hasher.update(buf)
    return hasher.hexdigest()


def check_config() -> None:
    """Checks that the configs are set properly."""
    try:
        if config.GROUP_ID == 0:
            raise ValueError("Please set your assigned group ID in config.py")
        if config.GROUP_ID not in range(1, 17):
            if config.GROUP_ID != 99:
                raise ValueError(
                    "Invalid GROUP_ID (must be an integer between 1 and 16)"
                )
        if not (
            config.UPLOAD_TOKEN.startswith("R6-")
            and config.UPLOAD_TOKEN.endswith(f"-{config.GROUP_ID}")
        ):
            raise ValueError("Please set your upload token in config.py")
        print("✅ Config looks good")
    except Exception as e:
        print("❌ Problem with config: ", e)
        sys.exit(1)


def check_simulation_server() -> None:
    """Checks that the simulation server is reachable."""
    try:
        r = requests.get(f"{_SIMULATION_SERVER_URL}/test", timeout=5)
        data = r.json()
        if data.get("status") == "ok":
            print("✅ Simulation server is available")
        else:
            raise RuntimeError(f"Server responded, but not OK: {data}")
    except Exception as e:
        print("❌ Could not reach upload server:", e)
        sys.exit(1)


def _get_sim_id(sim_idx: int, repeat_idx: int, repeat_count: int) -> str:
    """Returns the simulation ID based on indices."""
    return (
        f"{sim_idx + 1}_{repeat_idx + 1}"
        if repeat_count > 1
        else f"{sim_idx + 1}"
    )


def check_uploads() -> None:
    """Checks the status of uploads."""
    response = requests.get(
        f"{_SIMULATION_SERVER_URL}/check_uploads/{config.GROUP_ID}",
        headers=_HEADERS,
    )
    if response.status_code == 200:
        print("✅ Upload status:")
        statuses = response.json()
        for sim_idx, simulation in enumerate(_SIMULATIONS):
            repeat_count = simulation.get("repeat_count", 1)
            for repeat_idx in range(repeat_count):
                sim_id = _get_sim_id(sim_idx, repeat_idx, repeat_count)
                name = simulation["name"]
                status = statuses.get(sim_id, "Not uploaded")
                print(f"  - Sim #{sim_id} ({name}):".ljust(62), status)
    else:
        print(
            "❌ Failed to check uploads: "
            f"{response.status_code} {response.text}"
        )


def check_llm(llm: ollama.Client) -> None:
    """Checks whether the LLM is responding."""
    response = get_llm_response(
        llm, "What is 2 + 2? Respond with just the number."
    )
    if response.strip() == "4":
        print("✅ LLM is responding correctly")
    else:
        print("❌ LLM did not respond")
        sys.exit(1)


def upload_dialogue(
    dialogue: Dialogue, agent_id: str, simulated_user_id: str
) -> None:
    """Uploads a dialogue to the simulation server."""
    dialogue_as_dict = dialogue.to_dict()
    dialogue_as_dict["agent"] = agent_id
    dialogue_as_dict["user"] = simulated_user_id

    payload = {
        "group_id": config.GROUP_ID,
        "results": dialogue.to_dict(),
    }
    response = requests.post(
        f"{_SIMULATION_SERVER_URL}/upload",
        json=payload,
        headers=_HEADERS,
    )
    if response.status_code == 200:
        print("✅ Dialogue uploaded successfully")
    else:
        print(
            f"❌ Failed to upload dialogue: {response.status_code} {response.text}"
        )


def fetch_personas() -> list[dict[str, Any]]:
    """Fetches personas from the simulation server."""
    try:
        response = requests.get(
            f"{_SIMULATION_SERVER_URL}/personas/{config.GROUP_ID}",
            headers=_HEADERS,
            timeout=5,
        )
        response.raise_for_status()
        personas = response.json()
        if not isinstance(personas, list):
            raise ValueError("Invalid personas data received from server.")
        print("✅ Personas fetched successfully")
        return personas
    except (requests.exceptions.RequestException, ValueError):
        print("❌ Failed to fetch or validate personas")
        sys.exit(1)


def check_hash() -> None:
    """Checks that the simulator has not been modified."""
    response = requests.post(
        f"{_SIMULATION_SERVER_URL}/check_hash",
        json={"hash": compute_hash(__file__)},
        headers=_HEADERS,
    )
    if response.status_code == 200:
        print("✅ Simulator hash matches")
    else:
        print("❌ Simulator hash does not match!")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MusicCRS Simulator")
    parser.add_argument(
        "--no-upload", action="store_true", help="Disable dialogue upload"
    )
    parser.add_argument(
        "--check-uploads",
        action="store_true",
        help="Check upload status",
    )
    args = parser.parse_args()

    check_config()
    check_simulation_server()
    check_hash()

    if args.check_uploads:
        check_uploads()
        sys.exit(0)

    llm = ollama.Client(
        host=_OLLAMA_HOST,
        headers={"Authorization": f"Bearer {config.OLLAMA_API_KEY}"},
    )
    check_llm(llm)

    personas = fetch_personas()

    print("\n🚀 Starting simulations...")

    for sim_idx, simulation in enumerate(_SIMULATIONS):
        repeat_count = simulation.get("repeat_count", 1)
        for repeat_idx in range(repeat_count):
            sim_id = _get_sim_id(sim_idx, repeat_idx, repeat_count)
            print(
                colorama.Style.BRIGHT
                + f"\n▶️ Simulation {sim_id}: {simulation['name']}\n"
            )
            simuser_id = sim_id
            if simulation.get("use_persona", False):
                simulation["persona"] = personas.pop()
                simuser_id += f"-P{simulation['persona']['persona_id']}"
            client = SimulatorClient(
                config.MUSICCRS_SERVER_URL,
                llm=llm,
                agent_id=f"MusicCRS-{config.GROUP_ID}",
                simulated_user_id=f"SimUser-{simuser_id}",
                simulation_config=simulation,
                upload=not args.no_upload,
            )
            try:
                client.connect()
            except KeyboardInterrupt:
                client.disconnect()
