import { useCallback, useRef } from "react";
import { connectTaskWS, type WSConnection } from "../api/ws";
import { useAuthStore } from "../store/authStore";
import { useTaskStore } from "../store/taskStore";
import type { WSEvent } from "../types/api";

/**
 * Returns an `openStream` function that connects to WS and dispatches events
 * to the task store. Cleans up on unmount or when called again.
 */
export function useStream() {
  const wsRef = useRef<WSConnection | null>(null);

  const addBlock = useTaskStore((s) => s.addBlock);
  const completeBlock = useTaskStore((s) => s.completeBlock);
  const errorBlock = useTaskStore((s) => s.errorBlock);
  const appendSummaryDelta = useTaskStore((s) => s.appendSummaryDelta);
  const setSummaryDone = useTaskStore((s) => s.setSummaryDone);
  const setError = useTaskStore((s) => s.setError);
  const setPhase = useTaskStore((s) => s.setPhase);

  const dispatch = useCallback(
    (event: WSEvent) => {
      switch (event.type) {
        case "block_created":
          addBlock(event.block_id, event.title, event.worker_type);
          break;

        case "block_done":
          completeBlock(
            event.block_id,
            event.content,
            event.provider_used,
            event.tokens_used,
            event.latency_ms,
            event.trace_id
          );
          break;

        case "block_streaming":
          // streaming delta — no store update needed (content finalised in block_done)
          break;

        case "summary_start":
          setPhase("summary");
          break;

        case "summary_delta":
          appendSummaryDelta(event.delta);
          break;

        case "summary_done":
          setSummaryDone(event.full_text);
          break;

        case "error":
          if (event.block_id) {
            errorBlock(event.block_id);
          }
          setError(event.message);
          break;
      }
    },
    [
      addBlock,
      completeBlock,
      errorBlock,
      appendSummaryDelta,
      setSummaryDone,
      setError,
      setPhase,
    ]
  );

  const openStream = useCallback(
    (taskId: string, message: string, sessionId: string) => {
      // Close any existing connection
      wsRef.current?.close();

      const token = useAuthStore.getState().token ?? "";
      wsRef.current = connectTaskWS(
        taskId,
        message,
        sessionId,
        token,
        dispatch,
        (code, reason) => {
          console.info(`[ws] closed code=${code} reason=${reason}`);
        }
      );
    },
    [dispatch]
  );

  const closeStream = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  return { openStream, closeStream };
}
