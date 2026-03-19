import { useT } from "../../hooks/useT";

interface VideoBlockProps {
  title: string;
  content: unknown;
  provider: string;
  tokens: number;
  latencyMs: number;
  pending?: boolean;
}

export function VideoBlock({
  title,
  content,
  provider,
  tokens,
  latencyMs,
  pending = false,
}: VideoBlockProps) {
  const t = useT();

  const videoUrl = (() => {
    if (typeof content === "string") return content;
    if (content && typeof content === "object") {
      const c = content as Record<string, unknown>;
      return (c.url as string) ?? null;
    }
    return null;
  })();

  return (
    <div className="rounded-[10px] border-[0.5px] border-bg-border bg-bg-surface overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-bg-border">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
          <span className="text-xs font-medium text-text-secondary">{t("block.video")}</span>
          <span className="text-xs text-text-muted truncate max-w-xs">{title}</span>
        </div>
        {!pending && (
          <span className="text-xs text-text-muted">
            {provider} · {tokens} {t("agent.tokens")} · {latencyMs.toFixed(0)} ms
          </span>
        )}
        {pending && (
          <span className="text-xs text-primary animate-pulse">{t("block.pending")}</span>
        )}
      </div>
      <div className="p-4">
        {pending ? (
          <div className="h-48 bg-bg-elevated rounded-lg animate-pulse" />
        ) : videoUrl ? (
          <video
            src={videoUrl}
            controls
            className="rounded-lg w-full max-h-96"
          />
        ) : (
          <div className="h-48 bg-bg-elevated rounded-lg flex items-center justify-center text-text-muted text-sm">
            {String(content)}
          </div>
        )}
      </div>
    </div>
  );
}
