import { useState, useRef, useCallback, type KeyboardEvent } from "react";
import { useT } from "../hooks/useT";

interface TaskInputProps {
  onSubmit: (message: string) => Promise<void>;
  disabled?: boolean;
}

export function TaskInput({ onSubmit, disabled = false }: TaskInputProps) {
  const t = useT();
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(async () => {
    const msg = value.trim();
    if (!msg || loading || disabled) return;
    setLoading(true);
    setValue("");
    try {
      await onSubmit(msg);
    } finally {
      setLoading(false);
    }
  }, [value, loading, disabled, onSubmit]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void handleSubmit();
      }
    },
    [handleSubmit]
  );

  const isDisabled = disabled || loading;

  return (
    <div className="border border-bg-border bg-bg-surface rounded-xl p-3 flex gap-3 items-end focus-within:border-primary/50 transition-colors">
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t("chat.placeholder")}
        disabled={isDisabled}
        className="flex-1 bg-transparent text-text-primary placeholder-text-muted text-sm resize-none outline-none leading-relaxed min-h-[24px] max-h-[160px] disabled:opacity-50"
        style={{
          height: "auto",
          minHeight: "24px",
        }}
        onInput={(e) => {
          const el = e.currentTarget;
          el.style.height = "auto";
          el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
        }}
      />
      <button
        onClick={() => void handleSubmit()}
        disabled={isDisabled || !value.trim()}
        aria-label={t("chat.send")}
        className="shrink-0 w-8 h-8 rounded-lg bg-primary text-bg-base font-semibold text-sm flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed hover:bg-primary-dim transition-colors"
      >
        {loading ? (
          <span className="w-3.5 h-3.5 border-2 border-bg-base border-t-transparent rounded-full animate-spin" />
        ) : (
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M13 1L1 13M13 1H5M13 1V9" />
          </svg>
        )}
      </button>
    </div>
  );
}
