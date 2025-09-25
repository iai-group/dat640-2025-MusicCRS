export type ChatMessageButton = {
  title: string;
  payload: string;
  button_type: string;
};

export type ChatMessageAttachment = {
  type: string;
  payload: {
    images?: string[];
    buttons?: ChatMessageButton[];
  };
};

export type ChatMessage = {
  attachments?: ChatMessageAttachment[];
  text?: string;
  intent?: string;
};

export type AgentMessage = {
  recipient: string;
  message: ChatMessage;
  info?: string;
};

export type UserMessage = {
  message: string;
};
