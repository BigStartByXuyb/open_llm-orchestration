import { api } from "./client";

export interface ProviderUsage {
  provider_id: string;
  tokens: number;
}

export interface UsageSummary {
  total_tokens: number;
  by_provider: ProviderUsage[];
  since: string | null;
}

export async function getUsage(since?: string): Promise<UsageSummary> {
  const query = since ? `?since=${encodeURIComponent(since)}` : "";
  return api.get<UsageSummary>(`/usage${query}`);
}
