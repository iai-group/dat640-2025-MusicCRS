import React, { ReactNode, useState } from "react";

export type User = {
  username: string;
  isAnonymous: boolean;
};

type UserProviderProps = {
  children: React.ReactNode;
};

export const UserContext = React.createContext<{
  user: User | null;
  setUser: React.Dispatch<React.SetStateAction<User | null>>;
}>({
  user: null, // no default user
  setUser: () => {},
});

export const UserProvider: React.FC<UserProviderProps> = ({
  children,
}: {
  children: ReactNode;
}) => {
  const [user, setUser] = useState<User | null>(null);

  return (
    <UserContext.Provider value={{ user, setUser }}>
      {children}
    </UserContext.Provider>
  );
};
