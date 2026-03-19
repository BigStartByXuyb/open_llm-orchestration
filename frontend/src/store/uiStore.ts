import { create } from "zustand";
import { persist } from "zustand/middleware";

type Lang = "zh" | "en";

interface UIState {
  lang: Lang;
  sidebarOpen: boolean;
  setLang: (lang: Lang) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      lang: "zh",
      sidebarOpen: true,
      setLang: (lang) => set({ lang }),
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
    }),
    { name: "canopy-ui" }
  )
);
