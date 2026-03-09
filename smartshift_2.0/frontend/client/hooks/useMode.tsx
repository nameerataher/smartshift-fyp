import { createContext, useContext, useState, ReactNode } from "react";

export type UserMode = "commercial" | "personal";

interface ModeContextType {
  mode: UserMode;
  setMode: (mode: UserMode) => void;
}

const ModeContext = createContext<ModeContextType | undefined>(undefined);

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<UserMode>("commercial");
  return (
    <ModeContext.Provider value={{ mode, setMode }}>
      {children}
    </ModeContext.Provider>
  );
}

export function useMode() {
  const context = useContext(ModeContext);
  if (!context) throw new Error("useMode must be used within ModeProvider");
  return context;
}
