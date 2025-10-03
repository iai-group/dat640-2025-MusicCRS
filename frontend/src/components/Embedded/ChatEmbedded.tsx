import "./ChatEmbedded.css";
import { ReactNode } from "react";
import PlaylistPanel from "../../components/PlaylistPanel";

export default function ChatEmbedded({ children }: { children: ReactNode }) {
  return (
    <div className="row">
      <div className="col-md-6 col-sm-12">{children}</div>
      <div className="col-md-6 col-sm-12"><PlaylistPanel /></div>
    </div>
  );
}
