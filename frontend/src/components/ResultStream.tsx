import { useEffect, useRef } from "react";
import { useTaskStore, type Block } from "../store/taskStore";
import { useT } from "../hooks/useT";
import { TextBlock } from "./blocks/TextBlock";
import { CodeBlock } from "./blocks/CodeBlock";
import { ImageBlock } from "./blocks/ImageBlock";
import { VideoBlock } from "./blocks/VideoBlock";

function BlockCard({ block }: { block: Block }) {
  const pending = block.status === "pending";
  const props = {
    title: block.title,
    content: block.content,
    provider: block.provider_used,
    tokens: block.tokens_used,
    latencyMs: block.latency_ms,
    pending,
  };

  switch (block.worker_type) {
    case "code":
      return <CodeBlock {...props} />;
    case "image_gen":
    case "image":
      return <ImageBlock {...props} />;
    case "video_gen":
    case "video":
      return <VideoBlock {...props} />;
    default:
      return <TextBlock {...props} />;
  }
}

export function ResultStream() {
  const t = useT();
  const phase = useTaskStore((s) => s.phase);
  const blocks = useTaskStore((s) => s.blocks);
  const summaryText = useTaskStore((s) => s.summaryText);
  const errorMessage = useTaskStore((s) => s.errorMessage);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [blocks.length, summaryText]);

  if (phase === "idle") return null;

  return (
    <div className="flex flex-col gap-4">
      {/* Blocks */}
      {blocks.map((block) => (
        <BlockCard key={block.id} block={block} />
      ))}

      {/* Summary */}
      {(phase === "summary" || phase === "done") && summaryText && (
        <div className="rounded-xl border border-primary/30 bg-primary/5 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-primary/20">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            <span className="text-xs font-medium text-primary">{t("chat.summary")}</span>
            {phase === "summary" && (
              <span className="text-xs text-text-muted animate-pulse">…</span>
            )}
          </div>
          <div className="px-4 py-3">
            <p className="text-sm text-text-primary whitespace-pre-wrap leading-relaxed">
              {summaryText}
            </p>
          </div>
        </div>
      )}

      {/* Error */}
      {phase === "error" && errorMessage && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-3">
          <p className="text-sm text-red-400">
            {t("chat.error")}: {errorMessage}
          </p>
        </div>
      )}

      {/* Thinking indicator */}
      {(phase === "pending" || phase === "running") && blocks.length === 0 && (
        <div className="flex items-center gap-2 text-text-muted text-sm py-2">
          <span className="flex gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce [animation-delay:300ms]" />
          </span>
          {t("chat.thinking")}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
