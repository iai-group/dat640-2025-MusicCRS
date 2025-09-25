import { useState, useEffect, useRef } from "react";
import io, { Socket } from "socket.io-client";
import { AgentMessage, UserMessage, ChatMessage } from "../types";

export default function useSocketConnection(
  url: string = "http://127.0.0.1:5000",
  path: string | undefined
) {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectError, setConnectError] = useState<Error | null>(null);
  const onMessageRef = useRef<(message: ChatMessage) => void>();
  const onRestartRef = useRef<() => void>();
  const onAuthenticationRef =
    useRef<(success: boolean, error: string) => void>();

  useEffect(() => {
    const newSocket = io(url, { path: path });
    setSocket(newSocket);

    newSocket.on("connect_error", (error) => {
      console.error("Connection error", error);
      setConnectError(error); // Set connection error
    });

    newSocket.on("connect_timeout", () => {
      console.error("Connection timeout");
      setConnectError(new Error("Connection timeout")); // Set timeout as connection error
    });

    newSocket.on("connect", () => {
      setIsConnected(true);
      setConnectError(null);
    });

    newSocket.on("disconnect", () => {
      setIsConnected(false);
    });

    newSocket.on("message", (response: AgentMessage) => {
      if (response.info) {
        console.log(response.info);
      }
      if (response.message) {
        onMessageRef.current && onMessageRef.current(response.message);
      }
    });

    newSocket.on("restart", () => {
      onRestartRef.current && onRestartRef.current();
    });

    newSocket.on("authentication", ({ success, error }) => {
      onAuthenticationRef.current &&
        onAuthenticationRef.current(success, error);
    });

    return () => {
      newSocket.disconnect();
    };
  }, [url, path]);

  const startConversation = () => {
    socket?.emit("start_conversation", {});
  };

  const sendMessage = (message: UserMessage) => {
    socket?.emit("message", message);
  };

  const quickReply = (message: UserMessage) => {
    socket?.emit("message", message);
  };

  const giveFeedback = (message: string, event: string) => {
    socket?.emit("feedback", { message: message, event: event });
  };

  const onMessage = (callback: (response: ChatMessage) => void) => {
    onMessageRef.current = callback;
  };

  const onRestart = (callback: () => void) => {
    onRestartRef.current = callback;
  };

  const login = (username: string, password: string) => {
    socket?.emit("login", { username, password });
  };

  const register = (username: string, password: string) => {
    socket?.emit("register", { username, password });
  };

  const onAuthentication = (
    callback: (success: boolean, error: string) => void
  ) => {
    onAuthenticationRef.current = callback;
  };

  return {
    isConnected,
    startConversation,
    sendMessage,
    giveFeedback,
    quickReply,
    onRestart,
    onMessage,
    login,
    register,
    onAuthentication,
  };
}
