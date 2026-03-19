import { useT } from "../../hooks/useT";

interface TextBlockProps {
  title: string;
  content: unknown;
  provider: string;
  tokens: number;
  latencyMs: number;
  pending?: boolean;
}

export function TextBlock({
  title,
  content,
  provider,
  tokens,
  latencyMs,
  pending = false,
}: TextBlockProps) {
  const t = useT();
  const text = typeof content === "string" ? content : JSON.stringify(content, null, 2);

  return (
    <div className="rounded-[10px] border-[0.5px] border-bg-border bg-bg-surface overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-bg-border">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-primary" />
          <span className="text-xs font-medium text-text-secondary">{t("block.text")}</span>
          <span className="text-xs text-text-muted truncate max-w-xs">{title}</span>
        </div>
        {!pending && (
          <div className="flex items-center gap-3 text-xs text-text-muted">
            <span>{provider}</span>
            <span>{tokens} {t("agent.tokens")}</span>
            <span>{latencyMs.toFixed(0)} ms</span>
          </div>
        )}
        {pending && (
          <span className="text-xs text-primary animate-pulse">{t("block.pending")}</span>
        )}
      </div>
      {/* body */}
      <div className="px-4 py-3">
        {pending ? (
          <div className="space-y-2">
            <div className="h-3 bg-bg-elevated rounded animate-pulse w-3/4" />
            <div className="h-3 bg-bg-elevated rounded animate-pulse w-1/2" />
          </div>
        ) : (
          <p className="text-sm text-text-primary whitespace-pre-wrap leading-relaxed">
            {text}
          </p>
        )}
      </div>
    </div>
  );
}
