import { describe, it, expect, beforeEach } from "vitest";
import { useTaskStore } from "../store/taskStore";
import type { WSEvent } from "../types/api";

// Simulate what useStream.dispatch does
function dispatch(event: WSEvent) {
  const store = useTaskStore.getState();
  switch (event.type) {
    case "block_created":
      store.addBlock(event.block_id, event.title, event.worker_type);
      break;
    case "block_done":
      store.completeBlock(
        event.block_id,
        event.content,
        event.provider_used,
        event.tokens_used,
        event.latency_ms,
        event.trace_id
      );
      break;
    case "summary_start":
      store.setPhase("summary");
      break;
    case "summary_delta":
      store.appendSummaryDelta(event.delta);
      break;
    case "summary_done":
      store.setSummaryDone(event.full_text);
      break;
    case "error":
      if (event.block_id) store.errorBlock(event.block_id);
      store.setError(event.message);
      break;
  }
}

beforeEach(() => {
  useTaskStore.getState().reset();
});

describe("WS event dispatch", () => {
  it("handles full happy-path event sequence", () => {
    dispatch({ type: "block_created", seq: 1, block_id: "st_1", title: "Write code", worker_type: "code" });
    dispatch({ type: "block_created", seq: 2, block_id: "st_2", title: "Analyse", worker_type: "analysis" });
    dispatch({
      type: "block_done",
      seq: 3,
      block_id: "st_1",
      content: "result 1",
      provider_used: "anthropic",
      transformer_version: "v1",
      tokens_used: 100,
      latency_ms: 500,
      trace_id: "t1",
    });
    dispatch({
      type: "block_done",
      seq: 4,
      block_id: "st_2",
      content: "result 2",
      provider_used: "anthropic",
      transformer_version: "v1",
      tokens_used: 80,
      latency_ms: 300,
      trace_id: "t2",
    });
    dispatch({ type: "summary_start", seq: 5 });
    dispatch({ type: "summary_delta", seq: 6, delta: "Final " });
    dispatch({ type: "summary_delta", seq: 7, delta: "answer" });
    dispatch({ type: "summary_done", seq: 8, full_text: "Final answer" });

    const state = useTaskStore.getState();
    expect(state.blocks).toHaveLength(2);
    expect(state.blocks[0].status).toBe("done");
    expect(state.blocks[1].status).toBe("done");
    expect(state.summaryText).toBe("Final answer");
    expect(state.phase).toBe("done");
  });

  it("handles error event for a block", () => {
    dispatch({ type: "block_created", seq: 1, block_id: "st_1", title: "Fail", worker_type: "text" });
    dispatch({ type: "error", seq: 2, message: "Provider failed", code: "provider_error", block_id: "st_1" });

    const state = useTaskStore.getState();
    expect(state.blocks[0].status).toBe("error");
    expect(state.errorMessage).toBe("Provider failed");
    expect(state.phase).toBe("error");
  });
});
