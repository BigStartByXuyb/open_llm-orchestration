English isn't my first language, so I used Claude to help polish this post. The architecture and implementation are my own — AI assisted with some of the boilerplate code within the framework I designed.

# LLM Orchestration Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178c6.svg)](https://www.typescriptlang.org/)

A self-hostable, multi-tenant LLM orchestration engine. **Not an end-user product** — a framework for building AI-powered platforms that need to coordinate multiple LLM providers in parallel, with structured task decomposition, plugin extensions, and full observability.

---

## Architecture

```
Layer 0: shared/           zero-dependency base (types, errors, protocols, config)
Layer 1: gateway/          HTTP boundary (FastAPI, auth, rate-limit, tenant injection)
Layer 2: orchestration/    core engine (decomposer → router → executor → aggregator)
Layer 3: transformer/      instruction translation (CanonicalMessage → provider format)
Layer 4: providers/        LLM adapters  |  plugins/  |  mcp/  |  storage/  |  scheduler/
Layer 5: wiring/           sole DI container (the only layer that knows all concrete types)
```

**Data flow:**

```
Request → Gateway → OrchestrationEngine → TaskDecomposer → ParallelExecutor
       → ResultAggregator → WebSocket SSE stream → Frontend
```

---

## Features

- **6 LLM providers** — Anthropic Claude, OpenAI, DeepSeek, Google Gemini, Jimeng (image), Kling (video)
- **RAG** — vector store with cosine similarity search, document ingestion API (`POST /documents`)
- **Function Calling** — full `tool_call` / `tool_result` round-trip across all providers
- **Browser Automation** — Playwright-based `BrowserSkill` (5 actions: navigate, click, fill, screenshot, extract)
- **Scheduler** — APScheduler-backed cron jobs (e.g., billing rollup)
- **Webhooks** — passive trigger endpoint (`POST /webhooks/{event_type}`) with HMAC signing
- **SSE streaming** — real-time token streaming + WebSocket disconnect/reconnect with `seq` alignment
- **Multi-tenant isolation** — PostgreSQL RLS with per-row `tenant_id`, default-deny policy
- **MCP client** — connect external MCP servers; tools auto-register as Skills
- **Observability** — OpenTelemetry tracing, Prometheus metrics, `/readyz` health endpoint

---

## Quick Start

### Prerequisites

- Docker + Docker Compose
- Python 3.11+
- Node.js 18+

### 1. Start infrastructure

```bash
docker-compose up -d        # PostgreSQL + Redis
```

### 2. Configure environment

```bash
cp backend/.env.example backend/.env
# Edit backend/.env — set your API keys and DB credentials
```

Key variables:

| Variable | Description |
|----------|-------------|
| `ORCH_COORDINATOR_MODEL` | Main LLM model ID (default: `claude-sonnet-4-6`) |
| `DATABASE_URL` | PostgreSQL async DSN (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis connection URL |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `GEMINI_API_KEY` | Google Gemini API key |

### 3. Start backend

```bash
cd backend
pip install -e ".[dev]"
uvicorn orchestration.gateway.app:create_app --factory --reload
```

### 4. Start frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`, backend at `http://localhost:8000`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend framework | FastAPI + SQLAlchemy async + asyncpg |
| Frontend | React 18 + Zustand + Tailwind CSS 3 + TypeScript strict |
| Database | PostgreSQL (JSONB + GIN index, RLS multi-tenancy) |
| Cache / rate-limit | Redis (sliding window) |
| Vector store | pgvector / cosine similarity |
| Task scheduling | APScheduler AsyncIOScheduler |
| Browser automation | Playwright |
| Tracing | OpenTelemetry |
| Metrics | Prometheus |
| Testing | pytest + respx + testcontainers |

---

## Running Tests

```bash
cd backend

# Import boundary validation (required in CI)
pytest tests/test_import_boundaries.py

# Unit tests by layer
pytest src/orchestration/transformer/    # Transformer (pure functions, no mocks)
pytest src/orchestration/providers/      # Provider adapters (respx HTTP mocks)
pytest src/orchestration/orchestration/  # Core engine (AsyncMock boundaries)

# Integration tests (requires Docker for PostgreSQL + Redis)
pytest tests/integration/
```

---

## Adding a New LLM Provider

Only 4 files need to change:

1. **`transformer/providers/qwen_v1/transformer.py`** — new `InstructionTransformer` implementation
2. **`providers/qwen/adapter.py`** — new `ProviderAdapter` implementation
3. **`wiring/container.py`** — 2 lines to register the new transformer + adapter
4. **`shared/enums.py`** — add 1 entry to `ProviderID`

No other files need modification. The layered architecture guarantees zero cross-layer impact.

---

## Attribution

If you use this framework as a base for your own product or project, please include a visible credit link back to this repository. A line in your README or About page is sufficient:

> Built on [LLM Orchestration Platform](https://github.com/BigStartByXuyb/open_llm-orchestration) by BigStartByXuyb.

---

## License

MIT License — see [LICENSE](LICENSE) for full text.

Copyright (c) 2026 BigStartByXuyb

You are free to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of this software. The copyright notice and permission notice must be preserved in all copies or substantial portions.

## Roadmap

The following features are planned but not yet implemented. Contributions are especially welcome in these areas.

### Subtask Topology Graph

A real-time DAG visualization showing how the orchestration engine decomposes a request into parallel subtasks, which provider handles each node, and the execution order and dependencies between them.

- Frontend: interactive graph (D3.js or React Flow) rendered from the task plan emitted by `TaskDecomposer`
- Backend: expose `GET /tasks/{id}/topology` returning the full `TaskPlan` graph structure
- Live updates via existing WebSocket events (`block_created`, `block_done`)

### Real-time Task Tracking

End-to-end trace view for each request, connected to the existing `trace_id` field carried by `RunContext` and every `BlockUpdate` event.

- Per-task timeline: latency breakdown by subtask, provider, and transformer phase
- Integration with the existing OpenTelemetry `trace_id` infrastructure (Sprint 9)
- Frontend trace viewer: swimlane view by provider with token counts and latency bars

### Subtask Detail Panel

Clicking any subtask block opens a detail view showing:

- Full input sent to the provider (post-transformer canonical format)
- Raw provider response
- Token usage breakdown (`prompt_tokens`, `completion_tokens`)
- Latency per phase (transform → HTTP → parse)
- Transformer version used and any tool calls / tool results in the round-trip

---

## Contributing

Contributions are welcome — bug fixes, new LLM providers, or feature extensions.

Before contributing, please read `ARCHITECTURE.md` to understand the 6-layer
dependency rules. The most common mistake is importing across layers — CI will
catch this via `tests/test_import_boundaries.py`.

**Good first contributions:**
- Adding a new LLM provider (only 4 files — see section above)
- Improving test coverage for existing providers
- Frontend UI improvements

**Known limitations / areas for improvement:**
- WebSocket reconnect seq alignment is implemented but not battle-tested
- MCP client supports stdio/SSE transport only
- No admin UI for tenant management
- Billing rollup job needs more granular provider-level tracking

Please open an issue before submitting a large PR so we can discuss the approach
and make sure it fits the architecture.
