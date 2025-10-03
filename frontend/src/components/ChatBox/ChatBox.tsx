import "./ChatBox.css";

import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useContext,
} from "react";
import QuickReplyButton from "../QuickReply";
import { useSocket } from "../../contexts/SocketContext";
import { UserContext } from "../../contexts/UserContext";
import { PlaylistContext } from "../../contexts/PlaylistContext";
import {
  MDBCard,
  MDBCardHeader,
  MDBCardBody,
  MDBIcon,
  MDBCardFooter,
} from "mdb-react-ui-kit";
import { AgentChatMessage, UserChatMessage } from "../ChatMessage";
import { ChatMessage } from "../../types";
import { ConfigContext } from "../../contexts/ConfigContext";

function extractMessageText(message: any): string {
  // Be liberal in what we accept: text could be at different paths depending on server/lib versions
  const candidates = [
    message?.text,
    message?.utterance?.text,
    message?.payload?.text,
    message?.data?.text,
    message?.message, // some backends do this
  ];
  const first = candidates.find((v) => typeof v === "string");
  return typeof first === "string" ? first : "";
}

function extractFirstImageUrl(message: any): string | undefined {
  // Current project format
  const img1 =
    message?.attachments
      ?.find((a: any) => a?.type === "images")
      ?.payload?.images?.[0];

  // Fallbacks for other shapes if needed in future
  const img2 = message?.payload?.images?.[0];
  const img3 = message?.images?.[0];

  return img1 || img2 || img3 || undefined;
}

export default function ChatBox() {
  const { config } = useContext(ConfigContext);
  const { user } = useContext(UserContext);
  const { setState: setPlaylistState } = useContext(PlaylistContext);

  const {
    startConversation,
    sendMessage,
    quickReply,
    onMessage,
    onRestart,
    giveFeedback,
  } = useSocket();

  const [chatMessages, setChatMessages] = useState<JSX.Element[]>([]);
  const [chatButtons, setChatButtons] = useState<JSX.Element[]>([]);
  const [inputValue, setInputValue] = useState<string>("");
  const chatMessagesRef = useRef(chatMessages);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    startConversation();
  }, [startConversation]);

  const updateMessages = (message: JSX.Element) => {
    chatMessagesRef.current = [...chatMessagesRef.current, message];
    setChatMessages(chatMessagesRef.current);
  };

  const handleInput = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inputValue.trim() === "") return;
    updateMessages(
      <UserChatMessage
        key={chatMessagesRef.current.length}
        message={inputValue}
      />
    );
    sendMessage({ message: inputValue });
    setInputValue("");
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  };

  const handleQuickReply = useCallback(
    (message: string) => {
      updateMessages(
        <UserChatMessage
          key={chatMessagesRef.current.length}
          message={message}
        />
      );
      quickReply({ message });
    },
    [chatMessagesRef, quickReply]
  );

  const handelMessage = useCallback(
    (message: ChatMessage) => {
      // Debug raw inbound messages for diagnosis
      // Open your browser DevTools (F12) -> Console to see these
      // You can remove this once everything is stable.
      // eslint-disable-next-line no-console
      console.debug("[socket message]", message);

      // 1) Update playlist panel if a playlist attachment is present
      const plAttachment = (message as any).attachments?.find(
        (a: any) => a?.type === "playlist"
      );
      if (plAttachment && (plAttachment as any).payload?.playlist) {
        const playlist = (plAttachment as any).payload.playlist;
        setPlaylistState((prev) => ({
          current: playlist.name ?? prev.current,
          playlists: { ...prev.playlists, [playlist.name]: playlist },
        }));
      }

      // 2) Parse hidden marker in text: <!--PLAYLIST:{...}-->
      let cleanText = extractMessageText(message);
      if (cleanText.includes("<!--PLAYLIST:")) {
        const re = /<!--PLAYLIST:(\{[\s\S]*?\})-->/;
        const m = cleanText.match(re);
        if (m) {
          try {
            const playlist = JSON.parse(m[1]);
            setPlaylistState((prev) => ({
              current: playlist.name ?? prev.current,
              playlists: { ...prev.playlists, [playlist.name]: playlist },
            }));
          } catch {
            // ignore JSON parse errors silently
          }
          cleanText = cleanText.replace(re, "").trim();
        }
      }

      // 3) Render the chat message (strip marker; still show images/buttons below)
      if (!!cleanText) {
        const image_url = extractFirstImageUrl(message);
        updateMessages(
          <AgentChatMessage
            key={chatMessagesRef.current.length}
            feedback={config.useFeedback ? giveFeedback : null}
            message={cleanText}
            image_url={image_url}
          />
        );
      }
    },
    [giveFeedback, chatMessagesRef, config, setPlaylistState]
  );

  const handleButtons = useCallback(
    (message: ChatMessage) => {
      const buttons = (message as any).attachments?.find(
        (attachment: any) => attachment?.type === "buttons"
      )?.payload?.buttons;
      if (!!buttons && buttons.length > 0) {
        setChatButtons(
          buttons.map((button: any, index: number) => {
            return (
              <QuickReplyButton
                key={index}
                text={button.title}
                message={button.payload}
                click={handleQuickReply}
              />
            );
          })
        );
      } else {
        setChatButtons([]);
      }
    },
    [handleQuickReply]
  );

  useEffect(() => {
    onMessage((message: ChatMessage) => {
      handelMessage(message);
      handleButtons(message);
    });
  }, [onMessage, handleButtons, handelMessage]);

  useEffect(() => {
    onRestart(() => {
      setChatMessages([]);
      setChatButtons([]);
    });
  }, [onRestart]);

  return (
    <div className="chat-widget-content">
      <MDBCard
        id="chatBox"
        className="chat-widget-card"
        style={{ borderRadius: "15px" }}
      >
        <MDBCardHeader
          className="d-flex justify-content-between align-items-center p-3 bg-info text-white border-bottom-0"
          style={{
            borderTopLeftRadius: "15px",
            borderTopRightRadius: "15px",
          }}
        >
          <p className="mb-0 fw-bold">{config.name}</p>
          <p className="mb-0 fw-bold">{user?.username}</p>
        </MDBCardHeader>

        <MDBCardBody>
          <div className="card-body-messages">
            {chatMessages}
            <div className="d-flex flex-wrap justify-content-between">
              {chatButtons}
            </div>
          </div>
        </MDBCardBody>
        <MDBCardFooter className="text-muted d-flex justify-content-start align-items-center p-2">
          <form className="d-flex flex-grow-1" onSubmit={handleInput}>
            <input
              type="text"
              className="form-control form-control-lg"
              id="ChatInput"
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Type message"
              ref={inputRef}
            ></input>
            <button type="submit" className="btn btn-link text-muted">
              <MDBIcon fas size="2x" icon="paper-plane" />
            </button>
          </form>
        </MDBCardFooter>
      </MDBCard>
    </div>
  );
}
