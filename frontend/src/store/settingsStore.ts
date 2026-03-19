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

export interface RoutingTemplate {
  id: string;
  name: string;
  capabilities: Record<CapKey, string | null>;
}

interface SettingsState {
  providers: Record<ProviderId, ProviderSettings>;
  jimeng: JimengExtras;
  coordinatorProvider: string;
  coordinatorModelId: string;
  capabilities: Record<CapKey, string | null>;
  templates: RoutingTemplate[];
  activeTemplateId: string;
  timezone: string;
  maxTokens: number;
  setProviderKey: (id: ProviderId, key: string) => void;
  setProviderEnabled: (id: ProviderId, enabled: boolean) => void;
  setJimengAuthMode: (mode: "bearer" | "volcano") => void;
  setJimengVolcanoKey: (field: "accessKey" | "secretKey", val: string) => void;
  setCoordinator: (provider: string, modelId: string) => void;
  setCapability: (cap: CapKey, provider: string | null) => void;
  saveTemplate: (name: string) => void;
  activateTemplate: (id: string) => void;
  deleteTemplate: (id: string) => void;
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

const defaultTemplate: RoutingTemplate = {
  id: "default",
  name: "智能调配 / Smart Routing",
  capabilities: { ...defaultCapabilities },
};

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      providers: { ...defaultProviders },
      jimeng: { authMode: "bearer", accessKey: "", secretKey: "" },
      coordinatorProvider: "anthropic",
      coordinatorModelId: "claude-sonnet-4-6",
      capabilities: { ...defaultCapabilities },
      templates: [defaultTemplate],
      activeTemplateId: "default",
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

      saveTemplate: (name) =>
        set((s) => {
          const id = Date.now().toString(36);
          const newTemplate: RoutingTemplate = {
            id,
            name,
            capabilities: { ...s.capabilities },
          };
          return {
            templates: [...s.templates, newTemplate],
            activeTemplateId: id,
          };
        }),

      activateTemplate: (id) =>
        set((s) => {
          const tpl = s.templates.find((t) => t.id === id);
          if (!tpl) return {};
          return {
            activeTemplateId: id,
            capabilities: { ...tpl.capabilities },
          };
        }),

      deleteTemplate: (id) =>
        set((s) => {
          if (id === "default") return {};
          const templates = s.templates.filter((t) => t.id !== id);
          const activeTemplateId = s.activeTemplateId === id ? "default" : s.activeTemplateId;
          return { templates, activeTemplateId };
        }),

      setTimezone: (tz) => set({ timezone: tz }),

      setMaxTokens: (n) => set({ maxTokens: n }),
    }),
    { name: "canopy-settings" }
  )
);
