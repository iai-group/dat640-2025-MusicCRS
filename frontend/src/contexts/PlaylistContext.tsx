import React, { createContext, useState, ReactNode } from "react";

export type PlaylistTrack = {
  track_uri: string;
  artist: string;
  title: string;
  album?: string | null;
};

export type Playlist = {
  name: string;
  tracks: PlaylistTrack[];
  cover_url?: string | null;
};

export const PlaylistContext = createContext<{
  current: string;
  playlists: Record<string, Playlist>;
  setState: React.Dispatch<
    React.SetStateAction<{
      current: string;
      playlists: Record<string, Playlist>;
    }>
  >;
}>({
  current: "default",
  playlists: { default: { name: "default", tracks: [] } },
  setState: () => {},
});

export function PlaylistProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{
    current: string;
    playlists: Record<string, Playlist>;
  }>({
    current: "default",
    playlists: { default: { name: "default", tracks: [] } },
  });

  return (
    <PlaylistContext.Provider
      value={{
        current: state.current,
        playlists: state.playlists,
        setState,
      }}
    >
      {children}
    </PlaylistContext.Provider>
  );
}
