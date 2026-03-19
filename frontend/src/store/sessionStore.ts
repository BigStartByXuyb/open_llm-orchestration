import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SessionState {
  currentSessionId: string | null;
  setSessionId: (id: string | null) => void;
  clearSession: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      currentSessionId: null,
      setSessionId: (id) => set({ currentSessionId: id }),
      clearSession: () => set({ currentSessionId: null }),
    }),
    { name: "canopy-session" }
  )
);
