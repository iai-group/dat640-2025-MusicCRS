import "./ChatEmbedded.css";
import { ReactNode } from "react";

export default function ChatEmbedded({ children }: { children: ReactNode }) {
  return (
    <div className="row">
      <div className="col-md-6 col-sm-12">{children}</div>
    </div>
  );
}
