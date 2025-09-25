import { useContext, useEffect, useState } from "react";
import { useSocket } from "../../contexts/SocketContext";
import {
  MDBInput,
  MDBBtn,
  MDBCard,
  MDBCardBody,
  MDBCardTitle,
  MDBCardHeader,
  MDBCardText,
} from "mdb-react-ui-kit";
import "./LoginForm.css";
import { UserContext } from "../../contexts/UserContext";
import { ConfigContext } from "../../contexts/ConfigContext";

const LoginForm = () => {
  const { config } = useContext(ConfigContext);
  const { setUser } = useContext(UserContext);
  const { login, register, onAuthentication } = useSocket();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const handleAnonymousLogin = () => {
    setUser({ username: "Anonymous", isAnonymous: true });
  };

  const handleLogin = () => {
    login(username, password);
  };

  const handleRegister = () => {
    register(username, password);
  };

  useEffect(() => {
    onAuthentication((success: boolean, error: string) => {
      if (success) {
        setUser({ username, isAnonymous: false });
      } else {
        setErrorMessage(error);
      }
    });
  }, [onAuthentication, setUser, setErrorMessage, username]);

  return (
    <div className="chat-widget-content">
      <MDBCard
        id="loginForm"
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
        </MDBCardHeader>

        <MDBCardBody className="login">
          <MDBCardTitle>Login</MDBCardTitle>
          <MDBInput
            className="mb-3"
            label="Username"
            onChange={(e) => setUsername(e.target.value)}
          />
          <MDBInput
            type="password"
            label="Password"
            onChange={(e) => setPassword(e.target.value)}
          />
          {errorMessage && (
            <MDBCardText className="text-danger">{errorMessage}</MDBCardText>
          )}
          <div className="d-flex justify-content-between mt-3">
            <MDBBtn onClick={handleRegister}>Register</MDBBtn>
            <MDBBtn onClick={handleLogin}>Sign In</MDBBtn>
            <MDBBtn onClick={handleAnonymousLogin}>Anonymous</MDBBtn>
          </div>
        </MDBCardBody>
      </MDBCard>
    </div>
  );
};

export default LoginForm;
