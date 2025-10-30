# User simulator

This folder contains the user simulator for requirement set R6.

In principle, there should be no need to make changes to your MusicCRS to be able to interact with the simulator. However, keep in mind that the simulator only considers the `text` and `dialogue_acts` fields of the messages sent by MusicCRS, i.e., it is not aware of any advanced features your UI might support.

The current code is a minimalistic version that connects to MusicCRS (R6.1) and supports adding tracks to a playlist (partial fulfillment of R6.2). The complete simulator is planned to be released by Nov 7.

To run the simulator, first make sure that MusicCRS is running on <http://127.0.0.1:5000>. The frontend does not need to be started. Start the simulator from the root folder of the repo by running `python simulation/simulator.py`.

The current version simply sends a predefined sequence of messages to add some tracks to a playlist. The final simulator will use and LLM for more dynamic interactions and will require you to have a key to the Ollama service on uix.uis.no.

For the submission of R6, you'll need to download the latest version of the simulator, perform minimalistic configuration, and run it on your local machine together with your MusicCRS.
