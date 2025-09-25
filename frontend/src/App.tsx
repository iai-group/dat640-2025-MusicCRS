import { useContext } from "react";
import { ConfigContext } from "./contexts/ConfigContext";
import { UserContext } from "./contexts/UserContext";
import ChatBox from "./components/ChatBox/ChatBox";
import LoginForm from "./components/LoginForm/LoginForm";
import ChatWidget from "./components/Widget/ChatWidget";
import ChatEmbedded from "./components/Embedded/ChatEmbedded";

export default function App() {
  const { config } = useContext(ConfigContext);
  const { user } = useContext(UserContext);

  const content = !user && config.useLogin ? <LoginForm /> : <ChatBox />;
  return config.useWidget ? (
    <ChatWidget>{content}</ChatWidget>
  ) : (
    <ChatEmbedded>{content}</ChatEmbedded>
  );
}
