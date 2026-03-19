import { useCallback, useEffect } from "react";
import { TaskInput } from "../components/TaskInput";
import { ResultStream } from "../components/ResultStream";
import { AgentSidebar } from "../components/AgentSidebar";
import { useTask } from "../hooks/useTask";
import { useStream } from "../hooks/useStream";
import { useTaskStore } from "../store/taskStore";
import { useUIStore } from "../store/uiStore";
import { useT } from "../hooks/useT";

export function Home() {
  const { sendMessage } = useTask();
  const { openStream, closeStream } = useStream();
  const phase = useTaskStore((s) => s.phase);
  const taskId = useTaskStore((s) => s.taskId);
  const blocks = useTaskStore((s) => s.blocks);
  const userMessage = useTaskStore((s) => s.userMessage);
  const { lang, setLang } = useUIStore();
  const t = useT();

  // Cleanup WS on unmount
  useEffect(() => () => closeStream(), [closeStream]);

  const handleSubmit = useCallback(
    async (message: string) => {
      const { taskId: tid, sessionId } = await sendMessage(message);
      openStream(tid, message, sessionId);
    },
    [sendMessage, openStream]
  );

  const isRunning = phase === "pending" || phase === "running" || phase === "summary";
  const runningCount = blocks.filter((b) => b.status === "pending").length;

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top bar */}
        <div className="border-b border-bg-border bg-bg-base px-6 py-3 flex items-center justify-between shrink-0">
          <span className="text-sm font-medium text-text-primary">
            {taskId ? taskId.slice(0, 8) + "…" : t("chat.new")}
          </span>
          {isRunning && runningCount > 0 && (
            <span className="bg-primary/10 text-primary rounded-full px-3 py-1 text-xs">
              {runningCount} {t("chat.agents_running")}
            </span>
          )}
          <button
            onClick={() => setLang(lang === "zh" ? "en" : "zh")}
            className="text-xs text-text-muted hover:text-text-primary transition-colors"
          >
            {t("lang.switch")}
          </button>
        </div>

        {/* Scrollable results area */}
        <div className="flex-1 overflow-y-auto px-6 py-6 flex flex-col gap-4">
          {phase === "idle" && (
            <div className="flex flex-col items-center justify-center h-full text-center py-16">
              <div className="w-14 h-14 rounded-[10px] bg-primary/10 border border-primary/20 flex items-center justify-center mb-4">
                <svg
                  width="24"
                  height="24"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#4ade80"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
                </svg>
              </div>
              <p className="text-text-secondary text-sm">{t("chat.new")}</p>
            </div>
          )}

          {/* User message bubble */}
          {userMessage && phase !== "idle" && (
            <div className="flex justify-end">
              <div className="ml-auto max-w-[70%] bg-bg-elevated rounded-[10px] px-4 py-2.5 text-sm text-text-primary border border-bg-border">
                {userMessage}
              </div>
            </div>
          )}

          <ResultStream />
        </div>

        {/* Input bar */}
        <div className="border-t border-bg-border px-6 py-4 shrink-0">
          <TaskInput onSubmit={handleSubmit} disabled={isRunning} />
        </div>
      </div>

      {/* Agent sidebar */}
      <div className="border-l border-bg-border flex shrink-0">
        <AgentSidebar />
      </div>
    </div>
  );
}
