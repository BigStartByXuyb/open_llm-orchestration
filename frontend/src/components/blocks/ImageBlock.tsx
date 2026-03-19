import { useT } from "../../hooks/useT";

interface ImageBlockProps {
  title: string;
  content: unknown;
  provider: string;
  tokens: number;
  latencyMs: number;
  pending?: boolean;
}

export function ImageBlock({
  title,
  content,
  provider,
  tokens,
  latencyMs,
  pending = false,
}: ImageBlockProps) {
  const t = useT();

  // content may be a URL string or an object with url/data fields
  const imageUrl = (() => {
    if (typeof content === "string") return content;
    if (content && typeof content === "object") {
      const c = content as Record<string, unknown>;
      return (c.url as string) ?? (c.data as string) ?? null;
    }
    return null;
  })();

  return (
    <div className="rounded-[10px] border-[0.5px] border-bg-border bg-bg-surface overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-bg-border">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
          <span className="text-xs font-medium text-text-secondary">{t("block.image")}</span>
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
          <div className="h-40 bg-bg-elevated rounded-lg animate-pulse" />
        ) : imageUrl ? (
          <img
            src={imageUrl}
            alt={title}
            className="rounded-lg max-h-96 object-contain"
          />
        ) : (
          <div className="h-40 bg-bg-elevated rounded-lg flex items-center justify-center text-text-muted text-sm">
            {String(content)}
          </div>
        )}
      </div>
    </div>
  );
}
