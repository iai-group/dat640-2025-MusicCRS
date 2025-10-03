import { useContext, useState } from "react";
import { PlaylistContext } from "../contexts/PlaylistContext";
import { useSocket } from "../contexts/SocketContext";
import { MDBIcon } from "mdb-react-ui-kit";

export default function PlaylistPanel() {
  const { current, playlists } = useContext(PlaylistContext);
  const { sendMessage } = useSocket();
  const [newPlaylistName, setNewPlaylistName] = useState<string>("");
  const [addInput, setAddInput] = useState<string>("");

  const playlist = playlists[current] || { name: current, tracks: [] };
  const cover = playlist.cover_url;

  function addTrack() {
    if (!addInput.trim()) return;
    sendMessage({ message: `/add ${addInput}` });
    setAddInput("");
  }
  function removeTrack(uriOrIndex: string) {
    sendMessage({ message: `/remove ${uriOrIndex}` });
  }
  function clearPlaylist() {
    sendMessage({ message: "/clear" });
  }
  function createPlaylist() {
    if (!newPlaylistName.trim()) return;
    sendMessage({ message: `/create ${newPlaylistName}` });
    setNewPlaylistName("");
  }
  function switchPlaylist(name: string) {
    sendMessage({ message: `/switch ${name}` });
  }

  return (
    <div className="p-2">
      <div className="d-flex align-items-center gap-2 mb-2">
        <h5 className="mb-0">Playlist</h5>
        <select
          className="form-select form-select-sm w-auto"
          value={current}
          onChange={(e) => switchPlaylist(e.target.value)}
        >
          {Object.keys(playlists).map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <input
          className="form-control form-control-sm w-auto"
          placeholder="New playlist name"
          value={newPlaylistName}
          onChange={(e) => setNewPlaylistName(e.target.value)}
        />
        <button className="btn btn-sm btn-outline-primary" onClick={createPlaylist}>
          <MDBIcon fas icon="plus" /> New
        </button>
      </div>

      <div className="mb-3">
        {cover ? (
          <img
            src={cover}
            alt="cover"
            style={{ width: "100%", maxWidth: "320px", borderRadius: "8px" }}
          />
        ) : (
          <div
            style={{
              width: "100%",
              maxWidth: "320px",
              height: "200px",
              borderRadius: "8px",
              background: "#f2f2f2",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontStyle: "italic",
            }}
          >
            No cover yet
          </div>
        )}
      </div>

      <div className="input-group mb-2">
        <input
          className="form-control"
          placeholder="Artist: Title"
          value={addInput}
          onChange={(e) => setAddInput(e.target.value)}
        />
        <button className="btn btn-primary" onClick={addTrack}>
          Add
        </button>
        <button className="btn btn-outline-danger" onClick={clearPlaylist}>
          Clear
        </button>
      </div>

      <ol className="list-group list-group-numbered">
        {(playlist.tracks || []).map((t, i) => (
          <li
            key={t.track_uri}
            className="list-group-item d-flex justify-content-between align-items-center"
          >
            <div className="me-2">
              <div className="fw-bold">{t.artist} – {t.title}</div>
              <div className="text-muted small">{t.album}</div>
              <div className="text-muted small">{t.track_uri}</div>
            </div>
            <button
              className="btn btn-sm btn-outline-secondary"
              title="Remove"
              onClick={() => removeTrack(String(i + 1))}
            >
              <MDBIcon fas icon="trash" />
            </button>
          </li>
        ))}
      </ol>

      <div className="mt-3">
        <details>
          <summary>How to use</summary>
          <ul className="mt-2">
            <li>Add songs with exact syntax <code>Artist: Title</code>.</li>
            <li>Only songs from the database can be added.</li>
            <li>You can also type commands in chat: <code>/add</code>, <code>/remove</code>, <code>/view</code>, <code>/clear</code>, <code>/create</code>, <code>/switch</code>, <code>/list</code>.</li>
          </ul>
        </details>
      </div>
    </div>
  );
}
