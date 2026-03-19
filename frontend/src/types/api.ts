// Mirrors backend gateway/schemas/ws_event.py and task_request.py

// ---------------------------------------------------------------------------
// WebSocket events
// ---------------------------------------------------------------------------

export interface BlockCreatedEvent {
  type: "block_created";
  seq: number;
  block_id: string;
  title: string;
  worker_type: string;
}

export interface BlockStreamingEvent {
  type: "block_streaming";
  seq: number;
  block_id: string;
  delta: string;
}

export interface BlockDoneEvent {
  type: "block_done";
  seq: number;
  block_id: string;
  content: unknown;
  provider_used: string;
  transformer_version: string;
  tokens_used: number;
  latency_ms: number;
  trace_id: string;
}

export interface SummaryStartEvent {
  type: "summary_start";
  seq: number;
}

export interface SummaryDeltaEvent {
  type: "summary_delta";
  seq: number;
  delta: string;
}

export interface SummaryDoneEvent {
  type: "summary_done";
  seq: number;
  full_text: string;
}

export interface ErrorEvent {
  type: "error";
  seq: number;
  message: string;
  code: string;
  block_id?: string;
}

export type WSEvent =
  | BlockCreatedEvent
  | BlockStreamingEvent
  | BlockDoneEvent
  | SummaryStartEvent
  | SummaryDeltaEvent
  | SummaryDoneEvent
  | ErrorEvent;

// ---------------------------------------------------------------------------
// REST API types
// ---------------------------------------------------------------------------

export type TaskStatus = "pending" | "running" | "done" | "failed";

export interface TaskCreateRequest {
  message: string;
  session_id?: string;
  metadata?: Record<string, unknown>;
}

export interface TaskCreateResponse {
  task_id: string;
  session_id: string;
  status: TaskStatus;
  message: string;
}

export interface TaskStatusResponse {
  task_id: string;
  session_id: string;
  status: TaskStatus;
  result?: string;
  error?: string;
  metadata: Record<string, unknown>;
}

export interface SessionListItem {
  session_id: string;
  message_count: number;
  char_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface SessionListResponse {
  sessions: SessionListItem[];
  total: number;
}

export interface PluginInfo {
  plugin_id: string;
  version: string;
  skills: string[];
}

export interface PluginListResponse {
  plugins: PluginInfo[];
  total: number;
}

// ---------------------------------------------------------------------------
// Document management (Sprint 19)
// ---------------------------------------------------------------------------

export interface DocumentInfo {
  document_id: string;
  title: string;
  content_type: string;
  chunk_count: number;
  char_count: number;
  created_at: string | null;
}

export interface DocumentListResponse {
  documents: DocumentInfo[];
  total: number;
}

export interface DocumentUploadResponse {
  document_id: string;
  title: string;
  chunk_count: number;
  message: string;
}

// ---------------------------------------------------------------------------
// Tenant API keys (Sprint 19 / N-08)
// ---------------------------------------------------------------------------

export interface TenantKeyInfo {
  provider_id: string;
  api_key_masked: string;
  configured: boolean;
}

export interface TenantKeyListResponse {
  keys: TenantKeyInfo[];
}

export interface TenantKeyUpsertResponse {
  provider_id: string;
  configured: boolean;
}

// ---------------------------------------------------------------------------
// SSE events (Sprint 18/19)
// ---------------------------------------------------------------------------

export interface SSEStatusEvent {
  event: "status" | "done" | "error";
  task_id?: string;
  status?: string;
  updated_at?: string;
  error?: string | null;
  message?: string;
}
