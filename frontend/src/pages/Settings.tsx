import { useState } from "react";
import { useT } from "../hooks/useT";
import { useUIStore } from "../store/uiStore";
import {
  useSettingsStore,
  type ProviderId,
  type CapKey,
} from "../store/settingsStore";

// ── helpers ────────────────────────────────────────────────────────────────

function maskKey(key: string): string {
  if (!key) return "";
  if (key.length <= 8) return "●".repeat(key.length);
  return key.slice(0, 4) + "●".repeat(key.length - 8) + key.slice(-4);
}

// ── sub-components ─────────────────────────────────────────────────────────

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-[10px] border-[0.5px] border-bg-border bg-bg-surface p-5">
      <h2 className="text-sm font-semibold text-text-primary mb-4">{title}</h2>
      {children}
    </section>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors ${
        checked ? "bg-primary" : "bg-bg-elevated"
      }`}
    >
      <span
        className={`inline-block h-4 w-4 translate-y-0.5 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-4" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

function ApiKeyRow({ id }: { id: ProviderId }) {
  const t = useT();
  const { providers, jimeng, setProviderKey, setProviderEnabled, setJimengAuthMode, setJimengVolcanoKey } =
    useSettingsStore();
  const [visible, setVisible] = useState(false);
  const provider = providers[id];

  return (
    <div className="mb-4">
      <div className="flex items-center gap-3">
        <span className="w-28 text-sm text-text-secondary shrink-0">{t(`provider.${id}`)}</span>
        <div className="relative flex-1">
          <input
            type={visible ? "text" : "password"}
            value={provider.apiKey}
            onChange={(e) => setProviderKey(id, e.target.value)}
            placeholder={
              provider.apiKey ? maskKey(provider.apiKey) : t("settings.not_configured")
            }
            className="w-full rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-3 py-1.5 pr-8 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary transition-colors"
          />
          <button
            type="button"
            onClick={() => setVisible((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors text-xs"
          >
            {visible ? "🙈" : "👁"}
          </button>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-xs text-text-muted">{t("settings.enabled")}</span>
          <Toggle checked={provider.enabled} onChange={(v) => setProviderEnabled(id, v)} />
        </div>
      </div>

      {/* Jimeng extra auth */}
      {id === "jimeng" && (
        <div className="mt-3 ml-[7.5rem] space-y-2">
          <div className="flex items-center gap-4">
            <span className="text-xs text-text-muted">{t("settings.auth_mode")}:</span>
            {(["bearer", "volcano"] as const).map((mode) => (
              <label key={mode} className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="jimeng-auth"
                  checked={jimeng.authMode === mode}
                  onChange={() => setJimengAuthMode(mode)}
                  className="accent-primary"
                />
                <span className="text-xs text-text-secondary">{t(`settings.${mode}`)}</span>
              </label>
            ))}
          </div>
          {jimeng.authMode === "volcano" && (
            <div className="space-y-2">
              <input
                type="text"
                value={jimeng.accessKey}
                onChange={(e) => setJimengVolcanoKey("accessKey", e.target.value)}
                placeholder={t("settings.access_key")}
                className="w-full rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary transition-colors"
              />
              <input
                type="password"
                value={jimeng.secretKey}
                onChange={(e) => setJimengVolcanoKey("secretKey", e.target.value)}
                placeholder={t("settings.secret_key")}
                className="w-full rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary transition-colors"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const COORDINATOR_PROVIDERS = ["anthropic", "openai", "deepseek", "gemini"] as const;
const ALL_PROVIDERS: ProviderId[] = ["anthropic", "openai", "deepseek", "gemini", "jimeng", "kling"];
const CAP_KEYS: CapKey[] = ["text", "image", "video", "code", "search"];

// ── main page ──────────────────────────────────────────────────────────────

export function Settings() {
  const t = useT();
  const { lang, setLang } = useUIStore();
  const {
    coordinatorProvider,
    coordinatorModelId,
    capabilities,
    templates,
    activeTemplateId,
    timezone,
    maxTokens,
    setCoordinator,
    setCapability,
    saveTemplate,
    activateTemplate,
    deleteTemplate,
    setTimezone,
    setMaxTokens,
  } = useSettingsStore();

  const [newTemplateName, setNewTemplateName] = useState("");

  const handleSaveTemplate = () => {
    const name = newTemplateName.trim();
    if (!name) return;
    saveTemplate(name);
    setNewTemplateName("");
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-4">
      <h1 className="text-lg font-semibold text-text-primary">{t("settings.title")}</h1>

      {/* §1 API Key management */}
      <SectionCard title={t("settings.api_keys")}>
        {ALL_PROVIDERS.map((id) => (
          <ApiKeyRow key={id} id={id} />
        ))}
      </SectionCard>

      {/* §2 Main LLM config */}
      <SectionCard title={t("settings.coordinator")}>
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <label className="text-sm text-text-secondary">{t("settings.coordinator_provider")}</label>
            <select
              value={coordinatorProvider}
              onChange={(e) => setCoordinator(e.target.value, coordinatorModelId)}
              className="rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-2 py-1.5 text-sm text-text-primary focus:outline-none focus:border-primary"
            >
              {COORDINATOR_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {t(`provider.${p}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2 flex-1">
            <label className="text-sm text-text-secondary shrink-0">
              {t("settings.coordinator_model")}
            </label>
            <input
              type="text"
              value={coordinatorModelId}
              onChange={(e) => setCoordinator(coordinatorProvider, e.target.value)}
              className="flex-1 rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-primary"
            />
          </div>
        </div>
      </SectionCard>

      {/* §3 Task assignment */}
      <SectionCard title={t("settings.capabilities")}>
        <div className="space-y-3">
          {CAP_KEYS.map((cap) => (
            <div key={cap} className="flex items-center gap-3">
              <span className="w-24 text-sm text-text-secondary shrink-0">
                {t(`settings.cap.${cap}`)}
              </span>
              <select
                value={capabilities[cap] ?? ""}
                onChange={(e) => setCapability(cap, e.target.value || null)}
                className="flex-1 rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-2 py-1.5 text-sm text-text-primary focus:outline-none focus:border-primary"
              >
                <option value="">{t("settings.cap.auto")}</option>
                {ALL_PROVIDERS.map((p) => (
                  <option key={p} value={p}>
                    {t(`provider.${p}`)}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* §4 Templates */}
      <SectionCard title={t("settings.templates")}>
        <div className="flex items-center gap-2 mb-4">
          <input
            type="text"
            value={newTemplateName}
            onChange={(e) => setNewTemplateName(e.target.value)}
            placeholder={t("settings.template_name")}
            className="flex-1 rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary"
            onKeyDown={(e) => e.key === "Enter" && handleSaveTemplate()}
          />
          <button
            onClick={handleSaveTemplate}
            className="px-3 py-1.5 rounded-[6px] bg-primary text-white text-sm hover:bg-primary/90 transition-colors"
          >
            {t("settings.save_template")}
          </button>
        </div>
        <div className="space-y-2">
          {templates.map((tpl) => {
            const isActive = tpl.id === activeTemplateId;
            const isDefault = tpl.id === "default";
            return (
              <div
                key={tpl.id}
                className={`flex items-center gap-2 rounded-[6px] px-3 py-2 ${
                  isActive ? "bg-primary/10" : "bg-bg-base"
                }`}
              >
                <span
                  className={`text-sm flex-1 ${
                    isActive ? "text-primary font-medium" : "text-text-secondary"
                  }`}
                >
                  {tpl.name}
                  {isDefault && (
                    <span className="ml-1.5 text-xs text-text-muted">(内置)</span>
                  )}
                </span>
                {isActive ? (
                  <span className="text-xs text-primary">{t("settings.active")}</span>
                ) : (
                  <button
                    onClick={() => activateTemplate(tpl.id)}
                    className="text-xs text-text-secondary hover:text-primary transition-colors"
                  >
                    {t("settings.activate")}
                  </button>
                )}
                {!isDefault && (
                  <button
                    onClick={() => deleteTemplate(tpl.id)}
                    className="text-xs text-text-muted hover:text-red-400 transition-colors"
                  >
                    ✕
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </SectionCard>

      {/* §5 General */}
      <SectionCard title={t("settings.general")}>
        <div className="space-y-4">
          {/* Language */}
          <div className="flex items-center gap-3">
            <span className="w-32 text-sm text-text-secondary shrink-0">{t("settings.lang")}</span>
            <div className="flex gap-2">
              {(["zh", "en"] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => setLang(l)}
                  className={`px-3 py-1 rounded-[6px] text-sm transition-colors ${
                    lang === l
                      ? "bg-primary text-white"
                      : "bg-bg-base text-text-secondary hover:text-text-primary border-[0.5px] border-bg-border"
                  }`}
                >
                  {l === "zh" ? "中文" : "English"}
                </button>
              ))}
            </div>
          </div>

          {/* Timezone */}
          <div className="flex items-center gap-3">
            <span className="w-32 text-sm text-text-secondary shrink-0">{t("settings.timezone")}</span>
            <input
              type="text"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="flex-1 rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-primary"
            />
          </div>

          {/* Max tokens */}
          <div className="flex items-center gap-3">
            <span className="w-32 text-sm text-text-secondary shrink-0">{t("settings.max_tokens")}</span>
            <input
              type="number"
              value={maxTokens}
              onChange={(e) => setMaxTokens(Number(e.target.value))}
              min={256}
              max={131072}
              className="flex-1 rounded-[6px] border-[0.5px] border-bg-border bg-bg-base px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-primary"
            />
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
