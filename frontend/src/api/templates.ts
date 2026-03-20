import { api } from "./client";
import type { CapKey } from "../store/settingsStore";

export interface TemplateData {
  id: string;
  name: string;
  capabilities: Record<CapKey, string | null>;
}

export function listTemplates(): Promise<TemplateData[]> {
  return api.get<TemplateData[]>("/templates");
}

export function createTemplate(
  name: string,
  capabilities: Record<CapKey, string | null>
): Promise<TemplateData> {
  return api.post<TemplateData>("/templates", { name, capabilities });
}

export function updateTemplate(
  id: string,
  name: string,
  capabilities: Record<CapKey, string | null>
): Promise<TemplateData> {
  return api.put<TemplateData>(`/templates/${id}`, { name, capabilities });
}

export function deleteTemplate(id: string): Promise<void> {
  return api.delete<void>(`/templates/${id}`);
}
