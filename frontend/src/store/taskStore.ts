import { create } from "zustand";

export type BlockStatus = "pending" | "done" | "error";

export interface Block {
  id: string;
  title: string;
  worker_type: string;
  status: BlockStatus;
  content: unknown;
  provider_used: string;
  tokens_used: number;
  latency_ms: number;
  trace_id: string;
}

export type TaskPhase =
  | "idle"
  | "pending"
  | "running"
  | "summary"
  | "done"
  | "error";

interface TaskState {
  taskId: string | null;
  sessionId: string | null;
  phase: TaskPhase;
  blocks: Block[];
  summaryText: string;
  errorMessage: string | null;
  userMessage: string | null;

  // actions
  setTask: (taskId: string, sessionId: string) => void;
  setPhase: (phase: TaskPhase) => void;
  setUserMessage: (msg: string) => void;
  addBlock: (id: string, title: string, worker_type: string) => void;
  completeBlock: (
    id: string,
    content: unknown,
    provider_used: string,
    tokens_used: number,
    latency_ms: number,
    trace_id: string
  ) => void;
  errorBlock: (id: string) => void;
  appendSummaryDelta: (delta: string) => void;
  setSummaryDone: (fullText: string) => void;
  setError: (message: string) => void;
  reset: () => void;
}

const initialState = {
  taskId: null,
  sessionId: null,
  phase: "idle" as TaskPhase,
  blocks: [],
  summaryText: "",
  errorMessage: null,
  userMessage: null,
};

export const useTaskStore = create<TaskState>()((set) => ({
  ...initialState,

  setTask: (taskId, sessionId) => set({ taskId, sessionId }),

  setPhase: (phase) => set({ phase }),

  setUserMessage: (msg) => set({ userMessage: msg }),

  addBlock: (id, title, worker_type) =>
    set((s) => ({
      blocks: [
        ...s.blocks,
        {
          id,
          title,
          worker_type,
          status: "pending",
          content: null,
          provider_used: "",
          tokens_used: 0,
          latency_ms: 0,
          trace_id: "",
        },
      ],
    })),

  completeBlock: (id, content, provider_used, tokens_used, latency_ms, trace_id) =>
    set((s) => ({
      blocks: s.blocks.map((b) =>
        b.id === id
          ? { ...b, status: "done", content, provider_used, tokens_used, latency_ms, trace_id }
          : b
      ),
    })),

  errorBlock: (id) =>
    set((s) => ({
      blocks: s.blocks.map((b) =>
        b.id === id ? { ...b, status: "error" } : b
      ),
    })),

  appendSummaryDelta: (delta) =>
    set((s) => ({ summaryText: s.summaryText + delta })),

  setSummaryDone: (fullText) =>
    set({ summaryText: fullText, phase: "done" }),

  setError: (message) =>
    set({ errorMessage: message, phase: "error" }),

  reset: () => set(initialState),
}));
