import { api } from "./client";

export async function syncProviderKey(providerId: string, apiKey: string): Promise<void> {
  await api.put(`/tenant/keys/${providerId}`, { api_key: apiKey });
}
