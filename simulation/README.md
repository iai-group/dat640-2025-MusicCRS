# User simulator

This folder contains the user simulator for requirement set R6.

In principle, there should be no need to make changes to your MusicCRS to be able to interact with the simulator. However, keep in mind that the simulator only considers the `text` and `dialogue_acts` fields of the messages sent by MusicCRS, i.e., it is not aware of any advanced features your UI might support.

The simulator conducts multiple dialogues of varying complexity with the MusicCRS, ranging from executing a fixed sequences of commands to dynamic natural language interactions based on user personas. The simulator automatically uploads the completed dialogues to a server, and these uploaded dialogues will be the basis for scoring your MusicCRS for R6. The results will only be released after manually checking the uploaded results.

## ⚙️ Configuration

Before launching the simulator, you need to configure it by setting the MusicCRS server URL (<http://127.0.0.1:5000> by default), group ID, upload token, Ollama API key, and the mapping of intents to the specific commands your MusicCRS recognizes in [config.py](config.py).

  * The UPLOAD_TOKEN is unique for each group and has been sent to you by email.
  * The final version of the simulator will require you to have a key to the Ollama service on uix.uis.no. Don't leave this to the very last minute.
  * Make sure you have all the Python packages installed that are listed in [requirements.txt](../requirements.txt).
  * **Crucially, you're not allowed to make changes to any other parts of the simulation code outside config.py.** This is being checked and the simulator will not run if changes are made to the source code.

## ▶️ Running the simulator

You need to run the simulator on your local machine together with your MusicCRS.

First, make sure that MusicCRS is running on the URL specified in config.py (`MUSICCRS_SERVER_URL`). The frontend does not need to be started.

Run the simulator from the root folder of the repo by running `python simulation/simulator.py`.

It'll first perform some configuration checks and then will run a sequence of simulations.

The simulator can be run with the following flags:

  * `--no-upload`: Disables uploading the dialogue to the simulation server. This is useful for local testing and debugging.
  * `--check-uploads`: Checks the upload status of the simulations. This allows you to quickly verify that all simulations have been successfully uploaded.

You can run and upload simulations as many times as you like, but **only the last upload will be considered in the evaluation**.

For non-deterministic scenarios (i.e., those involving user personas) the simulations are repeated multiple times and the evaluation will consider the best performing among those.
