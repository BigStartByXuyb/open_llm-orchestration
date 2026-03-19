import { describe, it, expect, beforeEach } from "vitest";
import { useTaskStore } from "../store/taskStore";

// Reset store before each test
beforeEach(() => {
  useTaskStore.getState().reset();
});

describe("taskStore", () => {
  it("starts in idle phase with no blocks", () => {
    const state = useTaskStore.getState();
    expect(state.phase).toBe("idle");
    expect(state.blocks).toHaveLength(0);
    expect(state.summaryText).toBe("");
  });

  it("addBlock adds a pending block", () => {
    useTaskStore.getState().addBlock("b1", "Analyse data", "analysis");
    const { blocks } = useTaskStore.getState();
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({
      id: "b1",
      title: "Analyse data",
      worker_type: "analysis",
      status: "pending",
    });
  });

  it("completeBlock updates status to done", () => {
    useTaskStore.getState().addBlock("b1", "Code task", "code");
    useTaskStore
      .getState()
      .completeBlock("b1", "print('hello')", "anthropic", 42, 300, "trace-1");
    const { blocks } = useTaskStore.getState();
    expect(blocks[0].status).toBe("done");
    expect(blocks[0].content).toBe("print('hello')");
    expect(blocks[0].tokens_used).toBe(42);
  });

  it("errorBlock updates status to error", () => {
    useTaskStore.getState().addBlock("b2", "Search", "search");
    useTaskStore.getState().errorBlock("b2");
    expect(useTaskStore.getState().blocks[0].status).toBe("error");
  });

  it("appendSummaryDelta accumulates text", () => {
    useTaskStore.getState().appendSummaryDelta("Hello");
    useTaskStore.getState().appendSummaryDelta(" world");
    expect(useTaskStore.getState().summaryText).toBe("Hello world");
  });

  it("setSummaryDone sets full text and phase=done", () => {
    useTaskStore.getState().setSummaryDone("Final answer");
    const state = useTaskStore.getState();
    expect(state.summaryText).toBe("Final answer");
    expect(state.phase).toBe("done");
  });

  it("setError sets error message and phase=error", () => {
    useTaskStore.getState().setError("Something went wrong");
    const state = useTaskStore.getState();
    expect(state.errorMessage).toBe("Something went wrong");
    expect(state.phase).toBe("error");
  });

  it("reset clears all state", () => {
    useTaskStore.getState().addBlock("b1", "Test", "text");
    useTaskStore.getState().appendSummaryDelta("partial");
    useTaskStore.getState().reset();
    const state = useTaskStore.getState();
    expect(state.blocks).toHaveLength(0);
    expect(state.summaryText).toBe("");
    expect(state.phase).toBe("idle");
  });
});
