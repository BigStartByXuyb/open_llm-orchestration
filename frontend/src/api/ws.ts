import type { WSEvent } from "../types/api";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000";

export type WSEventCallback = (event: WSEvent) => void;
export type WSCloseCallback = (code: number, reason: string) => void;

export interface WSConnection {
  close: () => void;
  /** Current highest seq received (for reconnect) */
  readonly lastSeq: number;
}

/**
 * Open a WebSocket to /ws/{taskId}, send the initial auth message,
 * and dispatch parsed events to the callback.
 *
 * Sprint 18: supports reconnection via last_seq query param.
 * On abnormal close (code != 1000), automatically reconnects up to maxReconnects times,
 * passing the last received seq so the server can replay missed events.
 *
 * Protocol (mirrors ws.py):
 *   1. Connect to ws://host/ws/{taskId}?last_seq={lastSeq}
 *   2. Send JSON: { message, session_id, token }
 *   3. Receive stream of WS events until connection closes
 */
export function connectTaskWS(
  taskId: string,
  message: string,
  sessionId: string,
  token: string,
  onEvent: WSEventCallback,
  onClose?: WSCloseCallback,
  options: { maxReconnects?: number; reconnectDelayMs?: number } = {}
): WSConnection {
  const { maxReconnects = 3, reconnectDelayMs = 1500 } = options;

  let lastSeq = 0;
  let reconnectCount = 0;
  let manualClose = false;
  let ws: WebSocket;

  function connect(isReconnect = false) {
    const url = isReconnect
      ? `${WS_BASE}/ws/${taskId}?last_seq=${lastSeq}`
      : `${WS_BASE}/ws/${taskId}`;
    ws = new WebSocket(url);

    ws.addEventListener("open", () => {
      reconnectCount = 0; // reset on successful connect
      ws.send(JSON.stringify({ message, session_id: sessionId, token }));
    });

    ws.addEventListener("message", (ev) => {
      try {
        const event = JSON.parse(ev.data as string) as WSEvent;
        // Track latest seq for reconnect
        if ("seq" in event && typeof event.seq === "number") {
          if (event.seq > lastSeq) lastSeq = event.seq;
        }
        onEvent(event);
      } catch {
        console.warn("[ws] Failed to parse event:", ev.data);
      }
    });

    ws.addEventListener("close", (ev) => {
      if (manualClose || ev.code === 1000) {
        // Normal close or manual — no reconnect
        onClose?.(ev.code, ev.reason);
        return;
      }

      if (reconnectCount < maxReconnects) {
        reconnectCount++;
        console.info(
          `[ws] Connection lost (code=${ev.code}), reconnecting ${reconnectCount}/${maxReconnects} after ${reconnectDelayMs}ms (last_seq=${lastSeq})`
        );
        setTimeout(() => connect(true), reconnectDelayMs);
      } else {
        console.warn(`[ws] Max reconnects (${maxReconnects}) reached, giving up.`);
        onClose?.(ev.code, ev.reason);
      }
    });

    ws.addEventListener("error", () => {
      // error always fires before close — let onClose handle it
    });
  }

  connect(false);

  return {
    close: () => {
      manualClose = true;
      ws.close(1000, "client closed");
    },
    get lastSeq() {
      return lastSeq;
    },
  };
}
