"""Simulator client to interact with MusicCRS server.

It connects to the MusicCRS server specified in config.py.
The current version is not final. It includes simulations based on a predefined sequence of messages, but dynamic interactions using LLMs remain to be added.

The simulator can be run with the following flags:
  --no-upload: Disables uploading the dialogue to the simulation server.
  --check-uploads: Checks the upload status of the simulations.
"""

import argparse
import sys
import time
from datetime import datetime
from typing import Any

import config
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

_HEADERS = {"X-Auth-Token": f"secret-group-token-{config.GROUP_ID}"}

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
]


class SimulatorClient:
    def __init__(
        self,
        server_url: str,
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
        self._sio_client.on("*", self.on_any_event)

    def _log_agent_message(self, message: dict) -> None:
        """Logs an agent message to the dialogue history."""
        agent_utterance = AnnotatedUtterance(
            text=message["text"],
            participant=DialogueParticipant.AGENT,
            timestamp=datetime.now(),
        )
        if message["dialogue_acts"]:
            print(f"             {message['dialogue_acts']}")
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
        print(f"💬 MusicCRS: {message['text']}")
        self._log_agent_message(message)
        time.sleep(1)

        # Check if agent terminates dialogue
        for dialogue_act in data["message"].get("dialogue_acts", []):
            if dialogue_act["intent"] == "EXIT":
                self.disconnect()
                return

        # Current logic is for predefined sequence only
        # TODO(#31): extend with LLM-based dynamic interactions
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
        print(f"➡️ Simulator: {message}")


def check_config() -> None:
    """Checks that the configs are set properly."""
    try:
        if config.GROUP_ID == 0:
            raise ValueError("Please set your assigned group ID in config.py")
        if config.GROUP_ID not in range(1, 17):
            raise ValueError(
                "Invalid GROUP_ID (must be an integer between 1 and 16)"
            )
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


def check_uploads() -> None:
    """Checks the status of uploads."""
    response = requests.get(
        f"{_SIMULATION_SERVER_URL}/check_uploads/{config.GROUP_ID}",
        headers=_HEADERS,
    )
    if response.status_code == 200:
        print("✅ Upload status:")
        statuses = response.json()
        for i, sim in enumerate(_SIMULATIONS):
            sim_id = str(i + 1)
            name = sim["name"]
            status = statuses.get(sim_id, "Not uploaded")
            print(f"  - Sim #{sim_id} ({name}):".ljust(62), status)
    else:
        print(
            "❌ Failed to check uploads: "
            f"{response.status_code} {response.text}"
        )


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

    if args.check_uploads:
        check_uploads()
        sys.exit(0)

    for sim_id, simulation in enumerate(_SIMULATIONS, start=1):
        print(f"\n▶️ Starting simulation {sim_id}: {simulation['name']}\n")
        client = SimulatorClient(
            config.MUSICCRS_SERVER_URL,
            agent_id=f"MusicCRS-{config.GROUP_ID}",
            simulated_user_id=f"SimUser-{sim_id}",
            simulation_config=simulation,
            upload=not args.no_upload,
        )
        try:
            client.connect()
        except KeyboardInterrupt:
            client.disconnect()
