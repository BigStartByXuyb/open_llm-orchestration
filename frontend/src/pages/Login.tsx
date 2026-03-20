import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Logo } from "../components/Logo";
import { useAuthStore } from "../store/authStore";
import { useSettingsStore } from "../store/settingsStore";
import { useT } from "../hooks/useT";
import { registerTenant } from "../api/auth";

/**
 * After login, push any locally-stored API keys to the backend (one-time migration).
 * Uses raw fetch (not api.put) to avoid triggering clearToken() on 401 errors,
 * which would log the user out right after registering.
 */
async function migrateLocalKeys(token: string): Promise<void> {
  const providers = useSettingsStore.getState().providers;
  const syncs = Object.entries(providers)
    .filter(([, v]) => v.apiKey.trim())
    .map(([id, v]) =>
      fetch(`/api/tenant/keys/${id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ api_key: v.apiKey }),
      }).catch((err) => console.warn(`[login] Failed to migrate ${id} key:`, err))
    );
  await Promise.allSettled(syncs);
}

export function Login() {
  const t = useT();
  const navigate = useNavigate();
  const setToken = useAuthStore((s) => s.setToken);
  const [value, setValue] = useState("");
  const [creating, setCreating] = useState(false);
  const [newTenantId, setNewTenantId] = useState<string | null>(null);

  const handleSubmit = async () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setToken(trimmed);
    await migrateLocalKeys(trimmed);
    void navigate("/");
  };

  const handleCreate = async () => {
    setCreating(true);
    try {
      const res = await registerTenant();
      setNewTenantId(res.tenant_id);
      setToken(res.access_token);
      await migrateLocalKeys(res.access_token);
      void navigate("/");
    } catch (err) {
      console.error("Registration failed:", err);
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg-base flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex justify-center mb-8">
          <Logo size={48} />
        </div>

        <div className="rounded-2xl border border-bg-border bg-bg-surface p-6 flex flex-col gap-4">
          <h1 className="text-lg font-semibold text-text-primary text-center">
            {t("login.title")}
          </h1>

          {/* Create New Identity */}
          <button
            onClick={() => void handleCreate()}
            disabled={creating}
            className="w-full py-2.5 rounded-lg bg-primary text-bg-base font-semibold text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-primary-dim transition-colors"
          >
            {creating ? t("login.creating") : t("login.create_identity")}
          </button>

          {newTenantId && (
            <div className="text-xs text-text-muted bg-bg-elevated rounded-lg px-3 py-2">
              <span className="text-text-secondary">{t("login.tenant_id_label")}: </span>
              <span className="font-mono break-all">{newTenantId}</span>
            </div>
          )}

          <div className="flex items-center gap-2">
            <hr className="flex-1 border-bg-border" />
            <span className="text-xs text-text-muted">{t("login.or")}</span>
            <hr className="flex-1 border-bg-border" />
          </div>

          {/* Paste existing token */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-text-secondary">{t("login.token_label")}</label>
            <textarea
              rows={4}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={t("login.token_placeholder")}
              className="bg-bg-elevated border border-bg-border rounded-lg px-3 py-2.5 text-sm text-text-primary placeholder-text-muted outline-none focus:border-primary/50 resize-none font-mono"
            />
          </div>

          <button
            onClick={() => void handleSubmit()}
            disabled={!value.trim()}
            className="w-full py-2.5 rounded-lg border border-bg-border text-text-primary font-semibold text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-bg-elevated transition-colors"
          >
            {t("login.submit")}
          </button>

          <p className="text-xs text-text-muted text-center">{t("login.hint")}</p>
        </div>
      </div>
    </div>
  );
}
