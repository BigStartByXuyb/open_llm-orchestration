/**
 * SSE (Server-Sent Events) client for task status streaming.
 * Sprint 18/19: connects to GET /tasks/{taskId}/stream.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface TaskStatusEvent {
  event: "status" | "done" | "error";
  task_id?: string;
  status?: string;
  updated_at?: string;
  error?: string | null;
  message?: string;
}

export type SSEStatusCallback = (event: TaskStatusEvent) => void;
export type SSECloseCallback = () => void;

export interface SSEConnection {
  close: () => void;
}

/**
 * Connect to the SSE task status stream.
 *
 * Uses the Fetch API with ReadableStream to handle text/event-stream,
 * which works in all modern browsers without EventSource limitations
 * (EventSource doesn't support custom headers for Authorization).
 *
 * Automatically passes last_seq to replay missed WS events on reconnect.
 */
export async function connectTaskSSE(
  taskId: string,
  token: string,
  onEvent: SSEStatusCallback,
  onClose?: SSECloseCallback,
  lastSeq = 0
): Promise<SSEConnection> {
  let cancelled = false;
  const controller = new AbortController();

  const url = lastSeq > 0
    ? `${API_BASE}/tasks/${taskId}/stream?last_seq=${lastSeq}`
    : `${API_BASE}/tasks/${taskId}/stream`;

  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
    },
    signal: controller.signal,
  });

  if (!response.ok) {
    throw new Error(`SSE connect failed: ${response.status} ${response.statusText}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();

  (async () => {
    let buffer = "";
    try {
      while (!cancelled) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6).trim();
            if (!data) continue;
            try {
              const event = JSON.parse(data) as TaskStatusEvent;
              onEvent(event);
              if (event.event === "done" || event.event === "error") {
                cancelled = true;
                break;
              }
            } catch {
              console.warn("[sse] Failed to parse event:", data);
            }
          }
          // Ignore comment lines (': heartbeat')
        }
      }
    } catch (err) {
      if (!cancelled) {
        console.warn("[sse] Stream error:", err);
      }
    } finally {
      reader.releaseLock();
      onClose?.();
    }
  })();

  return {
    close: () => {
      cancelled = true;
      controller.abort();
    },
  };
}
