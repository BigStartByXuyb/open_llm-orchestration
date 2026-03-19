import { useState } from "react";
import { useT } from "../../hooks/useT";

interface CodeBlockProps {
  title: string;
  content: unknown;
  provider: string;
  tokens: number;
  latencyMs: number;
  pending?: boolean;
}

export function CodeBlock({
  title,
  content,
  provider,
  tokens,
  latencyMs,
  pending = false,
}: CodeBlockProps) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const code =
    typeof content === "string" ? content : JSON.stringify(content, null, 2);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="rounded-[10px] border-[0.5px] border-bg-border bg-bg-surface overflow-hidden">
      {/* header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-bg-border">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-accent" />
          <span className="text-xs font-medium text-text-secondary">{t("block.code")}</span>
          <span className="text-xs text-text-muted font-mono truncate max-w-xs">{title}</span>
        </div>
        <div className="flex items-center gap-3">
          {!pending && (
            <span className="text-xs text-text-muted">
              {provider} · {tokens} {t("agent.tokens")} · {latencyMs.toFixed(0)} ms
            </span>
          )}
          {pending && (
            <span className="text-xs text-primary animate-pulse">{t("block.pending")}</span>
          )}
          {!pending && (
            <button
              onClick={() => void handleCopy()}
              className="text-xs text-text-muted hover:text-text-primary transition-colors px-2 py-0.5 rounded border border-bg-border hover:border-primary/40"
            >
              {copied ? "✓" : "Copy"}
            </button>
          )}
        </div>
      </div>
      {/* body */}
      <div className="relative">
        {pending ? (
          <div className="p-4 space-y-2">
            <div className="h-3 bg-bg-elevated rounded animate-pulse w-4/5 font-mono" />
            <div className="h-3 bg-bg-elevated rounded animate-pulse w-2/3 font-mono" />
            <div className="h-3 bg-bg-elevated rounded animate-pulse w-1/2 font-mono" />
          </div>
        ) : (
          <pre className="overflow-x-auto p-4 text-sm font-mono text-text-primary leading-relaxed bg-bg-base/50">
            <code>{code}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
