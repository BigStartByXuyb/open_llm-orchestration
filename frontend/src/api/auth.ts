const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export interface RegisterResponse {
  access_token: string;
  tenant_id: string;
  token_type: string;
}

export async function registerTenant(name?: string): Promise<RegisterResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name ?? "default" }),
  });
  if (!res.ok) {
    throw new Error(`Registration failed: HTTP ${res.status}`);
  }
  return res.json() as Promise<RegisterResponse>;
}
