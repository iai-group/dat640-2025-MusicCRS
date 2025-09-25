import { useContext, useEffect } from "react";
import { render } from "@testing-library/react";
import App from "../App";
import { ConfigContext } from "../contexts/ConfigContext";

test("Renders Embedded", () => {
  render(<App />);
});

test("Renders Widget", () => {
  const { setConfig } = useContext(ConfigContext);

  useEffect(() => {
    const config = {
      useWidget: true,
    };

    setConfig((prevConfig) => ({ ...prevConfig, ...config }));
  }, [setConfig]);

  render(<App />);
});
