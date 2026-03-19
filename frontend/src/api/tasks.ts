import { api } from "./client";
import type {
  TaskCreateRequest,
  TaskCreateResponse,
  TaskStatusResponse,
} from "../types/api";

export const tasksApi = {
  create: (body: TaskCreateRequest) =>
    api.post<TaskCreateResponse>("/tasks", body),

  getStatus: (taskId: string) =>
    api.get<TaskStatusResponse>(`/tasks/${taskId}`),
};
