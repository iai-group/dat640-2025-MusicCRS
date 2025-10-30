"""Simulator client to interact with MusicCRS server.

It connects to the MusicCRS server listening on localhost:5000 by default.
The current version simply sends a predefined sequence of messages to simulate
user interactions.
"""

import time

import socketio

MUSICCRS_SERVER_URL = "http://127.0.0.1:5000"

_MESSAGES = [
    "Hello!",
    "/add Bon Jovi: Always",
    "/add ABBA: Money, Money, Money",
    "/list",
    "/quit",
]


class SimulatorClient:
    def __init__(self, server_url):
        self.sio_client = socketio.Client()
        self.server_url = server_url
        self.log = []  # Keep track of emitted messages
        self.sio_client.on("*", self.on_any_event)

    def on_any_event(self, event, data=None):
        print(f"📩 Event from MusicCRS: {event}, Data: {data}")
        time.sleep(1)

        if data:
            # Check if agent terminates dialogue
            for dialogue_act in data["message"].get("dialogue_acts", []):
                if dialogue_act["intent"] == "EXIT":
                    print("Disconnecting...")
                    self.disconnect()
                    return

        if len(self.log) < len(_MESSAGES):
            message = _MESSAGES[len(self.log)]
            self.send(message)

    def connect(self):
        self.sio_client.connect(self.server_url)
        self.sio_client.wait()

    def disconnect(self):
        self.sio_client.disconnect()

    def send(self, message):
        """Send a message and log it"""
        self.sio_client.send({"message": message})
        self.log.append({"msg": message, "timestamp": time.time()})
        print(f"➡️ Sent: {message}")


if __name__ == "__main__":
    client = SimulatorClient(MUSICCRS_SERVER_URL)
    try:
        client.connect()
    except KeyboardInterrupt:
        client.disconnect()
        print("📝 Message log:", client.log)
