import { api } from "./client";
import type { SessionListResponse } from "../types/api";

export const sessionsApi = {
  list: (limit = 50, offset = 0) =>
    api.get<SessionListResponse>(`/sessions?limit=${limit}&offset=${offset}`),

  delete: (sessionId: string) =>
    api.delete<void>(`/sessions/${sessionId}`),
};
