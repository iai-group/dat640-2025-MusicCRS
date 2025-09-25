import "mdb-react-ui-kit/dist/css/mdb.min.css";
import "@fortawesome/fontawesome-free/css/all.min.css";
import "./index.css";

import React, { useContext, useEffect } from "react";
import ReactDOM from "react-dom/client";
import {
  Config,
  ConfigContext,
  ConfigProvider,
} from "./contexts/ConfigContext";
import { UserProvider } from "./contexts/UserContext";
import App from "./App";

import reportWebVitals from "./reportWebVitals";
import { SocketProvider } from "./contexts/SocketContext";

let root: ReactDOM.Root;

const ConfigLoader: React.FC<{ config: Partial<Config> }> = ({ config }) => {
  const { setConfig } = useContext(ConfigContext);

  useEffect(() => {
    setConfig((prevConfig) => ({ ...prevConfig, ...config }));
  }, [config, setConfig]);

  return <App />;
};

declare global {
  interface Window {
    ChatWidget: (config: Partial<Config>, containerId: string) => void;
  }
}

window.ChatWidget = (config, containerId) => {
  const container = document.getElementById(containerId);

  if (Object.keys(config).length === 0 && container) {
    // Read data properties from the container div and use them as the config
    const dataset = container.dataset;
    config = {
      useFeedback: "useFeedback" in dataset,
      useLogin: "useLogin" in dataset,
      useWidget: "useWidget" in dataset,
    };
    if (dataset.name) config.name = dataset.name;
    if (dataset.serverUrl) config.serverUrl = dataset.serverUrl;
    if (dataset.socketioPath) config.socketioPath = dataset.socketioPath;
  }

  if (!root) {
    root = ReactDOM.createRoot(container as HTMLElement);
  }

  root.render(
    <ConfigProvider>
      <SocketProvider>
        <UserProvider>
          <ConfigLoader config={config} />
        </UserProvider>
      </SocketProvider>
    </ConfigProvider>
  );
};

if (document.getElementById("chatWidgetContainer")) {
  window.ChatWidget({}, "chatWidgetContainer");
}

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
