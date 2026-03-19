import { useCallback, useEffect, useState } from "react";
import { getUsage } from "../api/billing";
import type { UsageSummary } from "../api/billing";
import { useT } from "../hooks/useT";

const PROVIDER_COLORS: Record<string, string> = {
  anthropic: "bg-[#c96442]/20 text-[#c96442] border-[#c96442]/30",
  openai: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  deepseek: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  gemini: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  jimeng: "bg-pink-500/10 text-pink-400 border-pink-500/20",
  kling: "bg-amber-500/10 text-amber-400 border-amber-500/20",
};

function providerColor(id: string): string {
  return (
    PROVIDER_COLORS[id] ?? "bg-text-muted/10 text-text-muted border-text-muted/20"
  );
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function BarRow({
  provider_id,
  tokens,
  maxTokens,
}: {
  provider_id: string;
  tokens: number;
  maxTokens: number;
}) {
  const pct = maxTokens > 0 ? Math.max(2, (tokens / maxTokens) * 100) : 2;
  const colorCls = providerColor(provider_id);
  const barCls = colorCls.split(" ")[0]; // bg-xxx part

  return (
    <div className="flex items-center gap-3 py-2.5">
      <span
        className={`text-xs font-mono px-2 py-0.5 rounded border min-w-[90px] text-center ${colorCls}`}
      >
        {provider_id}
      </span>
      <div className="flex-1 h-2 bg-bg-elevated rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${barCls}`}
          style={{ width: `${pct}%`, transition: "width 0.4s ease" }}
        />
      </div>
      <span className="text-sm font-mono text-text-primary min-w-[60px] text-right">
        {formatTokens(tokens)}
      </span>
    </div>
  );
}

export function Usage() {
  const t = useT();
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sinceInput, setSinceInput] = useState("");
  const [activeFilter, setActiveFilter] = useState<string | undefined>(undefined);

  const load = useCallback((since?: string) => {
    setLoading(true);
    setError(null);
    getUsage(since)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(activeFilter);
  }, [load, activeFilter]);

  const handleApply = () => {
    const trimmed = sinceInput.trim() || undefined;
    setActiveFilter(trimmed);
  };

  const handleClear = () => {
    setSinceInput("");
    setActiveFilter(undefined);
  };

  const maxTokens =
    data ? Math.max(...data.by_provider.map((p) => p.tokens), 1) : 1;

  return (
    <div className="flex flex-col flex-1 px-6 py-6 gap-5 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">
          {t("usage.title")}
        </h1>
        <button
          onClick={() => load(activeFilter)}
          className="text-xs text-text-muted hover:text-text-primary transition-colors px-2 py-1 rounded border border-bg-border hover:border-text-muted"
        >
          {t("usage.refresh")}
        </button>
      </div>

      {/* Filter bar */}
      <div className="rounded-[10px] border-[0.5px] border-bg-border bg-bg-surface p-4">
        <p className="text-xs text-text-muted mb-2">{t("usage.filter_since")}</p>
        <div className="flex gap-2 items-center">
          <input
            type="text"
            placeholder="2025-01-01T00:00:00"
            value={sinceInput}
            onChange={(e) => setSinceInput(e.target.value)}
            className="flex-1 bg-bg-elevated border border-bg-border rounded-lg px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent transition-colors"
          />
          <button
            onClick={handleApply}
            className="px-3 py-1.5 text-xs rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors"
          >
            {t("usage.apply_filter")}
          </button>
          {activeFilter && (
            <button
              onClick={handleClear}
              className="px-3 py-1.5 text-xs rounded-lg border border-bg-border text-text-muted hover:text-text-primary transition-colors"
            >
              {t("usage.clear_filter")}
            </button>
          )}
        </div>
      </div>

      {/* Total tokens card */}
      {!loading && !error && data && (
        <div className="rounded-[10px] border-[0.5px] border-bg-border bg-bg-surface p-5">
          <p className="text-xs text-text-muted mb-1">{t("usage.total_tokens")}</p>
          <p className="text-3xl font-semibold text-text-primary font-mono">
            {formatTokens(data.total_tokens)}
          </p>
        </div>
      )}

      {/* Per-provider breakdown */}
      <div className="rounded-[10px] border-[0.5px] border-bg-border bg-bg-surface p-5">
        <p className="text-xs font-medium text-text-muted mb-3 uppercase tracking-wide">
          {t("usage.by_provider")}
        </p>

        {loading && (
          <div className="space-y-3 py-1">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-8 bg-bg-elevated rounded-lg animate-pulse"
              />
            ))}
          </div>
        )}

        {error && !loading && (
          <div className="py-4 text-center">
            <p className="text-sm text-red-400">{t("usage.error")}</p>
            <button
              onClick={() => load(activeFilter)}
              className="mt-2 text-xs text-text-muted hover:text-text-primary underline"
            >
              {t("usage.refresh")}
            </button>
          </div>
        )}

        {!loading && !error && data && data.by_provider.length === 0 && (
          <p className="text-sm text-text-muted py-4 text-center">
            {t("usage.no_data")}
          </p>
        )}

        {!loading && !error && data && data.by_provider.length > 0 && (
          <div className="divide-y divide-bg-border/50">
            {data.by_provider.map((p) => (
              <BarRow
                key={p.provider_id}
                provider_id={p.provider_id}
                tokens={p.tokens}
                maxTokens={maxTokens}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
