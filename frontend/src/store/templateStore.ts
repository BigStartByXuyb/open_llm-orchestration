import { create } from "zustand";
import {
  listTemplates,
  createTemplate,
  updateTemplate,
  deleteTemplate,
  type TemplateData,
} from "../api/templates";
import { useSettingsStore } from "./settingsStore";
import type { CapKey } from "./settingsStore";

const DEFAULT_CAPABILITIES: Record<CapKey, string | null> = {
  text: null,
  image: null,
  video: null,
  code: null,
  search: null,
};

const DEFAULT_TEMPLATE: TemplateData = {
  id: "default",
  name: "智能调配 / Smart Routing",
  capabilities: { ...DEFAULT_CAPABILITIES },
};

interface TemplateState {
  templates: TemplateData[];
  activeTemplateId: string;
  loading: boolean;
  error: string | null;

  fetch: () => Promise<void>;
  save: (name: string, capabilities: Record<CapKey, string | null>) => Promise<void>;
  update: (id: string, name: string, capabilities: Record<CapKey, string | null>) => Promise<void>;
  remove: (id: string) => Promise<void>;
  activate: (id: string) => void;
}

export const useTemplateStore = create<TemplateState>()((set, get) => ({
  templates: [DEFAULT_TEMPLATE],
  activeTemplateId: "default",
  loading: false,
  error: null,

  fetch: async () => {
    set({ loading: true, error: null });
    try {
      const remote = await listTemplates();
      set({ templates: [DEFAULT_TEMPLATE, ...remote], loading: false });
    } catch (err) {
      set({ loading: false, error: String(err) });
    }
  },

  save: async (name, capabilities) => {
    set({ loading: true, error: null });
    try {
      const tpl = await createTemplate(name, capabilities);
      set((s) => ({
        templates: [...s.templates, tpl],
        activeTemplateId: tpl.id,
        loading: false,
      }));
      useSettingsStore.getState().setCapabilities(capabilities);
    } catch (err) {
      set({ loading: false, error: String(err) });
      throw err;
    }
  },

  update: async (id, name, capabilities) => {
    set({ loading: true, error: null });
    try {
      const tpl = await updateTemplate(id, name, capabilities);
      set((s) => ({
        templates: s.templates.map((t) => (t.id === id ? tpl : t)),
        loading: false,
      }));
    } catch (err) {
      set({ loading: false, error: String(err) });
      throw err;
    }
  },

  remove: async (id) => {
    if (id === "default") return;
    set({ loading: true, error: null });
    try {
      await deleteTemplate(id);
      set((s) => {
        const templates = s.templates.filter((t) => t.id !== id);
        const activeTemplateId = s.activeTemplateId === id ? "default" : s.activeTemplateId;
        return { templates, activeTemplateId, loading: false };
      });
      if (get().activeTemplateId === "default") {
        useSettingsStore.getState().setCapabilities({ ...DEFAULT_CAPABILITIES });
      }
    } catch (err) {
      set({ loading: false, error: String(err) });
      throw err;
    }
  },

  activate: (id) => {
    const tpl = get().templates.find((t) => t.id === id);
    if (!tpl) return;
    set({ activeTemplateId: id });
    useSettingsStore.getState().setCapabilities(tpl.capabilities);
  },
}));
