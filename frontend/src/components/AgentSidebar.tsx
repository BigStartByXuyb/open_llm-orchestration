import { useNavigate } from "react-router-dom";
import { useTaskStore, type Block } from "../store/taskStore";
import { useUIStore } from "../store/uiStore";
import { useT } from "../hooks/useT";

function workerColor(workerType: string): string {
  switch (workerType) {
    case "code": return "bg-accent";
    case "image_gen": case "image": return "bg-yellow-400";
    case "video_gen": case "video": return "bg-rose-400";
    case "search": return "bg-blue-400";
    default: return "bg-primary";
  }
}

function ProgressBar({ status }: { status: Block["status"] }) {
  if (status === "pending") {
    return (
      <div className="h-1 w-full bg-bg-hover rounded-full overflow-hidden mt-1">
        <div className="h-full bg-primary/40 rounded-full animate-pulse w-2/3" />
      </div>
    );
  }
  if (status === "done") {
    return (
      <div className="h-1 w-full bg-primary rounded-full mt-1" />
    );
  }
  return (
    <div className="h-1 w-full bg-red-500/50 rounded-full mt-1" />
  );
}

function BlockRow({ block }: { block: Block }) {
  return (
    <div className="flex flex-col gap-1 p-2.5 rounded-[6px] bg-bg-elevated border-[0.5px] border-bg-border">
      <div className="flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${workerColor(block.worker_type)} ${block.status === "pending" ? "animate-pulse" : ""}`} />
        <span className="text-xs text-text-primary truncate flex-1">{block.title}</span>
        {block.status === "done" && (
          <span className="text-xs text-primary shrink-0">✓</span>
        )}
        {block.status === "error" && (
          <span className="text-xs text-red-400 shrink-0">✗</span>
        )}
      </div>
      {block.provider_used && (
        <span className="text-[10px] text-text-muted pl-3.5">{block.provider_used}</span>
      )}
      <ProgressBar status={block.status} />
      {block.status === "done" && (
        <span className="text-[10px] text-text-muted pl-3.5">{block.latency_ms.toFixed(0)} ms</span>
      )}
    </div>
  );
}

export function AgentSidebar() {
  const t = useT();
  const navigate = useNavigate();
  const blocks = useTaskStore((s) => s.blocks);
  const phase = useTaskStore((s) => s.phase);
  const { sidebarOpen, toggleSidebar } = useUIStore();

  const totalTokens = blocks.reduce((sum, b) => sum + b.tokens_used, 0);
  const totalLatency = blocks.reduce((sum, b) => sum + b.latency_ms, 0);
  const estimatedCost = (totalTokens / 1000) * 0.002;

  return (
    <aside
      className={`flex flex-col transition-all duration-200 overflow-hidden ${
        sidebarOpen ? "w-60" : "w-10"
      }`}
    >
      {/* Toggle button */}
      <button
        onClick={toggleSidebar}
        className="flex items-center gap-2 px-2 py-3 text-text-muted hover:text-text-primary transition-colors shrink-0"
        title={sidebarOpen ? "收起" : "展开"}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="currentColor"
          className={`transition-transform shrink-0 ${sidebarOpen ? "" : "rotate-180"}`}
        >
          <path d="M11 8L6 3v10l5-5z" />
        </svg>
        {sidebarOpen && (
          <span className="text-xs font-medium truncate">{t("agent.sidebar")}</span>
        )}
      </button>

      {sidebarOpen && (
        <div className="flex flex-col flex-1 overflow-hidden px-2 pb-3 gap-2">
          {/* Block list */}
          <div className="flex flex-col gap-1.5 overflow-y-auto flex-1">
            {blocks.length === 0 && phase === "idle" && (
              <p className="text-xs text-text-muted px-1">—</p>
            )}
            {blocks.map((block) => (
              <BlockRow key={block.id} block={block} />
            ))}
          </div>

          {/* Topology link */}
          <button
            onClick={() => navigate("/topology")}
            className="flex items-center gap-2 px-2.5 py-2 rounded-[6px] text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors border-[0.5px] border-bg-border"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="6" cy="2" r="1.5" />
              <circle cx="2" cy="9" r="1.5" />
              <circle cx="10" cy="9" r="1.5" />
              <line x1="6" y1="3.5" x2="2" y2="7.5" />
              <line x1="6" y1="3.5" x2="10" y2="7.5" />
            </svg>
            {t("agent.topology")}
          </button>

          {/* Bottom stats */}
          <div className="grid grid-cols-3 gap-1 border-t border-bg-border pt-2">
            <div className="flex flex-col items-center gap-0.5">
              <span className="text-[10px] text-text-muted">{t("agent.total_tokens")}</span>
              <span className="text-xs text-text-primary font-medium">{totalTokens}</span>
            </div>
            <div className="flex flex-col items-center gap-0.5">
              <span className="text-[10px] text-text-muted">{t("agent.latency")}</span>
              <span className="text-xs text-text-primary font-medium">{(totalLatency / 1000).toFixed(1)}s</span>
            </div>
            <div className="flex flex-col items-center gap-0.5">
              <span className="text-[10px] text-text-muted">{t("agent.cost")}</span>
              <span className="text-xs text-text-primary font-medium">${estimatedCost.toFixed(3)}</span>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
