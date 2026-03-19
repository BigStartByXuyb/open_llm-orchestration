import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
  isAuthenticated: () => boolean;
}

// Seed from env var if present (dev mode only)
const devToken = import.meta.env.VITE_DEV_JWT_TOKEN as string | undefined;

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: devToken || null,
      setToken: (token) => set({ token }),
      clearToken: () => set({ token: null }),
      isAuthenticated: () => Boolean(get().token),
    }),
    {
      name: "canopy-auth",
    }
  )
);
