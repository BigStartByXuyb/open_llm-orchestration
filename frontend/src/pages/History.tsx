import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { sessionsApi } from "../api/sessions";
import { useSessionStore } from "../store/sessionStore";
import { useTaskStore } from "../store/taskStore";
import { useT } from "../hooks/useT";
import type { SessionListItem } from "../types/api";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function History() {
  const t = useT();
  const navigate = useNavigate();
  const setSessionId = useSessionStore((s) => s.setSessionId);
  const reset = useTaskStore((s) => s.reset);

  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    sessionsApi
      .list()
      .then((r) => setSessions(r.sessions))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleOpen = (sessionId: string) => {
    setSessionId(sessionId);
    reset();
    void navigate("/");
  };

  return (
    <div className="flex flex-col flex-1 px-6 py-6 gap-4">
      <h1 className="text-lg font-semibold text-text-primary">{t("history.title")}</h1>

      {loading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-bg-elevated rounded-xl animate-pulse" />
          ))}
        </div>
      )}

      {error && (
        <p className="text-sm text-red-400">{error}</p>
      )}

      {!loading && sessions.length === 0 && (
        <p className="text-sm text-text-muted py-8 text-center">{t("history.empty")}</p>
      )}

      <div className="flex flex-col gap-2">
        {sessions.map((s) => (
          <button
            key={s.session_id}
            onClick={() => handleOpen(s.session_id)}
            className="flex items-center justify-between px-4 py-3 rounded-xl border border-bg-border bg-bg-surface hover:border-primary/40 hover:bg-bg-elevated transition-colors text-left group"
          >
            <div>
              <p className="text-sm text-text-primary font-mono">
                {s.session_id.slice(0, 16)}…
              </p>
              <p className="text-xs text-text-muted mt-0.5">
                {s.message_count} {t("history.messages")} · {s.char_count} {t("history.chars")} · {formatDate(s.updated_at)}
              </p>
            </div>
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className="text-text-muted group-hover:text-primary transition-colors"
            >
              <path d="M5 3l4 4-4 4" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  );
}
