import { tasksApi } from "../api/tasks";
import { useAuthStore } from "../store/authStore";
import { useSessionStore } from "../store/sessionStore";
import { useTaskStore } from "../store/taskStore";

/**
 * Returns a `sendMessage` function that:
 *   1. Creates the task via POST /tasks
 *   2. Updates task/session store
 *   3. Returns { taskId, sessionId } for the caller to open a WS
 */
export function useTask() {
  const setTask = useTaskStore((s) => s.setTask);
  const setPhase = useTaskStore((s) => s.setPhase);
  const setUserMessage = useTaskStore((s) => s.setUserMessage);
  const reset = useTaskStore((s) => s.reset);
  const currentSessionId = useSessionStore((s) => s.currentSessionId);
  const setSessionId = useSessionStore((s) => s.setSessionId);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  async function sendMessage(
    message: string
  ): Promise<{ taskId: string; sessionId: string }> {
    if (!isAuthenticated()) {
      throw new Error("Not authenticated");
    }

    reset();
    setPhase("pending");
    setUserMessage(message);

    const resp = await tasksApi.create({
      message,
      session_id: currentSessionId ?? undefined,
    });

    setTask(resp.task_id, resp.session_id);
    setSessionId(resp.session_id);
    setPhase("running");

    return { taskId: resp.task_id, sessionId: resp.session_id };
  }

  return { sendMessage };
}
