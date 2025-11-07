"""Configuration for the MusicCRS simulator."""

MUSICCRS_SERVER_URL = "http://127.0.0.1:5000"  # URL of your MusicCRS agent

GROUP_ID = 0  # TODO: Set to your assigned group ID (int)
OLLAMA_API_KEY = "my-api-key"  # TODO: Set to your Ollama API key (str)

# TODO: Configure the commands recognized by your MusicCRS agent.
# Keys represent intents and must not be changed; only modify the values.
COMMANDS = {
    "ADD_TRACK": "/add [artist]: [track]",
    "GREETING": "Hello!",
    "QUIT": "/quit",
    "REMOVE_TRACK": "/del [artist]: [track]",
    "RECOMMEND": "/recommend",
    "SHOW_PLAYLIST": "/list",
}
