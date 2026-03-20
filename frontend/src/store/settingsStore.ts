import { create } from "zustand";
import { persist } from "zustand/middleware";
import { syncProviderKey } from "../api/tenant_keys";

export type ProviderId = "anthropic" | "openai" | "deepseek" | "gemini" | "jimeng" | "kling";
export type CapKey = "text" | "image" | "video" | "code" | "search";

interface ProviderSettings {
  apiKey: string;
  enabled: boolean;
}

interface JimengExtras {
  authMode: "bearer" | "volcano";
  accessKey: string;
  secretKey: string;
}

interface SettingsState {
  providers: Record<ProviderId, ProviderSettings>;
  jimeng: JimengExtras;
  coordinatorProvider: string;
  coordinatorModelId: string;
  capabilities: Record<CapKey, string | null>;
  timezone: string;
  maxTokens: number;
  setProviderKey: (id: ProviderId, key: string) => void;
  setProviderEnabled: (id: ProviderId, enabled: boolean) => void;
  setJimengAuthMode: (mode: "bearer" | "volcano") => void;
  setJimengVolcanoKey: (field: "accessKey" | "secretKey", val: string) => void;
  setCoordinator: (provider: string, modelId: string) => void;
  setCapability: (cap: CapKey, provider: string | null) => void;
  setCapabilities: (caps: Record<CapKey, string | null>) => void;
  setTimezone: (tz: string) => void;
  setMaxTokens: (n: number) => void;
}

const defaultCapabilities: Record<CapKey, string | null> = {
  text: null,
  image: null,
  video: null,
  code: null,
  search: null,
};

const defaultProviders: Record<ProviderId, ProviderSettings> = {
  anthropic: { apiKey: "", enabled: true },
  openai: { apiKey: "", enabled: true },
  deepseek: { apiKey: "", enabled: true },
  gemini: { apiKey: "", enabled: true },
  jimeng: { apiKey: "", enabled: true },
  kling: { apiKey: "", enabled: true },
};

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      providers: { ...defaultProviders },
      jimeng: { authMode: "bearer", accessKey: "", secretKey: "" },
      coordinatorProvider: "anthropic",
      coordinatorModelId: "claude-sonnet-4-6",
      capabilities: { ...defaultCapabilities },
      timezone: "Asia/Shanghai",
      maxTokens: 4096,

      setProviderKey: (id, key) => {
        set((s) => ({
          providers: { ...s.providers, [id]: { ...s.providers[id], apiKey: key } },
        }));
        if (key.trim()) {
          syncProviderKey(id, key).catch((err) =>
            console.warn(`[settingsStore] Failed to sync ${id} key to backend:`, err)
          );
        }
      },

      setProviderEnabled: (id, enabled) =>
        set((s) => ({
          providers: { ...s.providers, [id]: { ...s.providers[id], enabled } },
        })),

      setJimengAuthMode: (mode) =>
        set((s) => ({ jimeng: { ...s.jimeng, authMode: mode } })),

      setJimengVolcanoKey: (field, val) =>
        set((s) => ({ jimeng: { ...s.jimeng, [field]: val } })),

      setCoordinator: (provider, modelId) =>
        set({ coordinatorProvider: provider, coordinatorModelId: modelId }),

      setCapability: (cap, provider) =>
        set((s) => ({ capabilities: { ...s.capabilities, [cap]: provider } })),

      setCapabilities: (caps) => set({ capabilities: { ...caps } }),

      setTimezone: (tz) => set({ timezone: tz }),

      setMaxTokens: (n) => set({ maxTokens: n }),
    }),
    { name: "canopy-settings" }
  )
);
