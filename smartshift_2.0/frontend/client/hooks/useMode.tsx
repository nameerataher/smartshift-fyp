import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { useAuth } from "./useAuth";

export type UserMode = "commercial" | "personal";

interface ModeContextType {
  mode: UserMode;
  setMode: (mode: UserMode) => void;
  isPersonalUser: boolean;
}

const ModeContext = createContext<ModeContextType | undefined>(undefined);

export function ModeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const isPersonalUser = user?.user_type === "personal";

  const [mode, setModeState] = useState<UserMode>(() =>
    isPersonalUser ? "personal" : "commercial"
  );

  useEffect(() => {
    if (isPersonalUser) {
      setModeState("personal");
    }
  }, [isPersonalUser]);

  const setMode = (newMode: UserMode) => {
    if (isPersonalUser && newMode === "commercial") return;
    setModeState(newMode);
  };

  const effectiveMode = isPersonalUser ? "personal" : mode;

  return (
    <ModeContext.Provider value={{ mode: effectiveMode, setMode, isPersonalUser }}>
      {children}
    </ModeContext.Provider>
  );
}

export function useMode() {
  const context = useContext(ModeContext);
  if (!context) throw new Error("useMode must be used within ModeProvider");
  return context;
}
