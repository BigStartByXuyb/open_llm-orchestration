import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useT } from "../hooks/useT";
import type { PluginListResponse, PluginInfo } from "../types/api";

export function Plugins() {
  const t = useT();
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PluginListResponse>("/plugins")
      .then((r) => setPlugins(r.plugins))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-col flex-1 px-6 py-6 gap-4">
      <h1 className="text-lg font-semibold text-text-primary">{t("plugins.title")}</h1>

      {loading && (
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div key={i} className="h-20 bg-bg-elevated rounded-xl animate-pulse" />
          ))}
        </div>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="flex flex-col gap-3">
        {plugins.map((p) => (
          <div
            key={p.plugin_id}
            className="px-4 py-3 rounded-xl border border-bg-border bg-bg-surface"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-text-primary font-mono">
                {p.plugin_id}
              </span>
              <span className="text-xs text-text-muted border border-bg-border rounded px-1.5 py-0.5">
                v{p.version}
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {p.skills.map((skill) => (
                <span
                  key={skill}
                  className="text-xs bg-accent/10 text-accent border border-accent/20 rounded px-2 py-0.5"
                >
                  {skill}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
