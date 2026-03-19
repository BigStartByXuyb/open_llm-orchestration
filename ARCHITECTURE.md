# LLM 编排平台架构文档

> **本文档是后续所有开发的唯一参考。每次新对话开始时，开发者（Claude）应主动读取此文档了解项目背景，再继续当前 Sprint。**
> **如架构有变更，须立即更新本文档。**

---

## 项目基本信息

| 项目 | 值 |
|------|---|
| **项目目录** | `C:\Users\xuyb\Desktop\AI_CODE_COPY\llm-orchestration\` |
| **当前进度** | Sprint 20 ✅ 全部完成（基础可用性修复 + Coordinator Prompt 改进）|
| **Python 版本** | 3.11+ |
| **文档更新日期** | 2026-03-20 |

---

## Context（项目目标）

构建一个 SaaS 级多租户 LLM 编排平台。核心诉求：
- 每个 LLM 完全独立为子模块，一个模块变更不影响其他任何模块
- 设立专门的指令转换层（Instruction Transformer），负责将统一内部格式转换为各 LLM 的专有 API 格式，并支持版本化
- 支持插件/Skill 扩展
- 前后端严格分离

---

## 关键决策表

| 决策项 | 选择 |
|-------|------|
| **主 LLM（Coordinator）** | 可配置，通过环境变量 `ORCH_COORDINATOR_MODEL` 指定（如 `claude-sonnet-4-6`），不硬编码 |
| **实施顺序** | 后端骨架优先：shared → transformer → providers → orchestration → gateway，前端最后 |
| **代码语言** | 英文变量/函数/类名 + 中英双语注释（docstring 先中后英） |
| **数据库** | PostgreSQL — JSONB+GIN 索引存储结构化结果，asyncpg 驱动，原生 RLS 支持多租户隔离 |
| **多租户隔离** | 同表 + `tenant_id` 列 + PostgreSQL RLS + 默认拒绝兜底 |
| **上下文长度度量** | DB 存 `char_count`（provider 无关），截断阈值以字符数配置，调用前按 `chars/4` 估算 token |
| **上下文截断策略** | 滑动窗口（>80% 阈值丢弃旧轮次）+ 摘要压缩（>95% 阈值调主 LLM 生成摘要） |
| **子 Agent 上下文** | 无独立上下文，只接收主 LLM 明确分配的最小 CanonicalMessage（有意隔离）|
| **结果聚合模式** | 子 Task 完成即推 `block_done`（实时可见）；所有子 Task 完成后主 LLM 流式汇总（`summary_*` 事件）|
| **并行背压** | `ParallelExecutor` 持有 per-provider `asyncio.Semaphore`，上限由 `PROVIDER_CONCURRENCY_LIMITS` 配置 |
| **Transformer 错误边界** | Transformer 只抛 `TransformError`；Adapter 负责将 HTTP 错误翻译为 `ProviderError` 层级 |
| **CanonicalMessage 演进** | 只增不删，新字段必须有默认值，字段重命名禁止；`schema_version: int = 1` 占位供迁移工具使用；Sprint 11 新增 `ProviderResult.tool_calls` + `SubTask.tools`（向后兼容）|
| **汇总 token 上限** | `MAX_SUMMARY_INPUT_CHARS`（`shared/config.py`）限制汇总阶段总输入，超出时两级压缩 |
| **WS 断线占坑** | 所有 `BlockUpdate` 事件携带 `seq: int` 字段，断线重连逻辑第二期补充 |
| **可观测性占坑** | `RunContext` 携带 `trace_id: str`，Sprint 3 起透传，Sprint 8 补完整 OpenTelemetry |
| **MCP 定位** | 仅客户端——接入外部 MCP 服务，工具自动注册为 Skill |
| **MCP 与 Skill 共存** | MCP 工具作为 Skill 来源（`MCPSkill` 实现 `SkillProtocol`，经 `PluginRegistry` 统一管理）|
| **MCP 层级** | 独立 `mcp/` 模块，Layer 4，与 `plugins/` 并列 |
| **MCP 实现时机** | Sprint 5（随 `plugins/` 一起实现）|
| **即梦认证双模式** | `JIMENG_AUTH_MODE=bearer`（默认，平台 API Key）或 `volcano_signing`（火山引擎 HMAC-SHA256）；后者需设 `JIMENG_ACCESS_KEY` + `JIMENG_SECRET_KEY`；签名逻辑在 `providers/jimeng/signing.py` |

---

## 一、模块分层与依赖规则（核心约束）

```
Layer 0: shared/           ← 零内部依赖，系统语言底座
Layer 1: gateway/          ← 只导入 shared
Layer 2: orchestration/    ← 只导入 shared + protocols（不知道任何具体实现）
Layer 3: transformer/      ← 只导入 shared（不知道 providers）
Layer 4: providers/        ← 只导入 shared，各 provider 之间绝不互相导入
         plugins/          ← 只导入 shared
         mcp/              ← 只导入 shared（MCP 客户端，Sprint 5 实现）
         storage/          ← 只导入 shared
         scheduler/        ← 只导入 shared
Layer 5: wiring/           ← 唯一允许导入所有具体类的地方（DI 容器）
```

**执行方式**：CI 中运行 `tests/test_import_boundaries.py`，通过 AST 解析验证每层无越级导入。

---

## 二、数据流

```
用户输入
  ↓ [Gateway: 认证/限流/租户注入]
  ↓ [OrchestrationEngine]
      → [TaskDecomposer]
          1. 从 SessionRepo 加载对话历史（含截断/摘要逻辑）
          2. 调主 LLM → TaskPlan（含多个 SubTask）
      → [CapabilityRouter] 为每个 SubTask 分配 provider_id + transformer_version
      → [ParallelExecutor]（asyncio.gather，无依赖时并行）
          每个 SubTask：
            1. TransformerRegistry.get(provider_id, version)
            2. transformer.transform(CanonicalMessage) → dict
            3. adapter.call(dict) → raw dict
            4. transformer.parse_response(raw) → ProviderResult
            5. 推送 block_done 事件（实时推送，用户立即可见）
          （Skill 类型：直接调 PluginRegistry.get_skill(skill_id).execute()，跳过 transformer/adapter）
      → [ResultAggregator]
          收集所有 ProviderResult → 构建新 CanonicalMessage
          → 再次调主 LLM（流式）→ 推送 summary_start/delta/done 事件
  ↓ [WebSocket 流式推送到前端]
```

### 上下文截断策略（在 decomposer.py 中实现）

```
char_count > CONTEXT_TRUNCATION_THRESHOLD * 0.8
  → 滑动窗口：保留 system prompt + 最近 N 轮，丢弃最旧消息

char_count > CONTEXT_TRUNCATION_THRESHOLD * 0.95
  → 摘要压缩：调主 LLM 生成历史摘要，压缩为一条 system 消息
```

### 多租户 DB 隔离（含默认拒绝兜底）

```sql
-- ① 每张表启用 RLS
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions FORCE ROW LEVEL SECURITY;   -- 表 owner 也受约束

-- ② 默认拒绝策略（兜底）：未注入 tenant_id 时，current_setting 返回空串，匹配不到任何行
CREATE POLICY deny_by_default ON sessions USING (false);

-- ③ 租户隔离策略（覆盖兜底）
CREATE POLICY tenant_isolation ON sessions
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ④ 应用层注入（在 repos/ 的每个事务开头执行）
SET LOCAL app.current_tenant_id = '{tenant_id}';
```

### Aggregator 阶段上下文溢出策略（两级压缩）

```
压缩级别 1 — 单块截断
  每个 ProviderResult char_count > MAX_RESULT_CHARS_PER_BLOCK（默认 8000 chars ≈ 2000 tokens）
  → 保留前 N 字符，追加 "[已截断]" 标记

压缩级别 2 — 总量上限
  所有块合计 char_count > MAX_SUMMARY_INPUT_CHARS（对应 MAX_SUMMARY_INPUT_TOKENS）
  → 每块压缩为 1 行摘要（调主 LLM），再以压缩版拼接做最终汇总
```

---

## 三、项目目录结构

```
llm-orchestration/
├── ARCHITECTURE.md                         ← 本文件，唯一架构参考
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   └── src/orchestration/
│       ├── shared/                         # Layer 0
│       │   ├── types.py                    # CanonicalMessage, SubTask, TaskPlan, ProviderResult ✅
│       │   ├── enums.py                    # Role, ProviderID, Capability, TaskStatus ✅
│       │   ├── errors.py                   # 异常层级 ✅
│       │   ├── protocols.py                # 所有跨模块 Protocol 定义 ✅
│       │   └── config.py                   # pydantic-settings 配置 ✅
│       │
│       ├── gateway/                        # Layer 1
│       │   ├── app.py                      # FastAPI 工厂函数
│       │   ├── middleware/
│       │   │   ├── auth.py                 # JWT 验证
│       │   │   ├── rate_limit.py           # Redis 滑动窗口
│       │   │   ├── tenant.py               # 多租户上下文注入
│       │   │   └── tracing.py              # OTel TracingMiddleware ★ Sprint 9
│       │   ├── routers/
│       │   │   ├── tasks.py                # POST /tasks, GET /tasks/{id}
│       │   │   ├── sessions.py
│       │   │   ├── plugins.py              # 插件管理端点
│       │   │   ├── ws.py                   # WebSocket 流式端点
│       │   │   ├── webhooks.py             # POST /webhooks/{event_type} ★ Sprint 12
│       │   │   ├── usage.py                # GET /usage（按 provider 聚合）★ Sprint 12
│       │   │   └── documents.py            # POST/GET/DELETE /documents（文档摄入）★ Sprint 14
│       │   ├── schemas/
│       │   │   ├── task_request.py
│       │   │   └── ws_event.py             # BlockUpdate 事件类型
│       │   └── deps.py                     # FastAPI 依赖注入器（含 BillingRepoDep + EmbeddingRepoDep）★ Sprint 12/14
│       │
│       ├── orchestration/                  # Layer 2
│       │   ├── engine.py                   # OrchestrationEngine
│       │   ├── decomposer.py               # TaskDecomposer
│       │   ├── router.py                   # CapabilityRouter
│       │   ├── executor.py                 # ParallelExecutor
│       │   └── aggregator.py               # ResultAggregator
│       │
│       ├── transformer/                    # Layer 3 ★ 指令转换层
│       │   ├── base.py                     # BaseTransformer ABC
│       │   ├── registry.py                 # TransformerRegistry（版本化查找）
│       │   ├── canonical.py                # CanonicalMessage 构建工具函数
│       │   └── providers/
│       │       ├── anthropic_v3/           # AnthropicV3Transformer
│       │       ├── openai_v1/              # OpenAIV1Transformer
│       │       ├── deepseek_v1/
│       │       ├── gemini_v1/
│       │       ├── jimeng_v1/              # 极梦图像生成
│       │       └── kling_v1/              # 可灵视频生成
│       │
│       ├── providers/                      # Layer 4
│       │   ├── anthropic/
│       │   ├── openai/
│       │   ├── deepseek/
│       │   ├── gemini/
│       │   ├── jimeng/
│       │   └── kling/
│       │
│       ├── plugins/                        # Layer 4
│       │   ├── registry.py
│       │   ├── loader.py                   # 新增 load_from_mcp_server() 扩展点（Sprint 5）
│       │   └── builtin/
│       │       ├── web_search/
│       │       ├── code_exec/
│       │       │   ├── skill.py            # CodeExecSkill（subprocess）
│       │       │   └── iterative_skill.py  # CodeIterativeSkill（自动纠错）★ Sprint 10
│       │       └── browser/
│       │           ├── skill.py            # BrowserSkill（Playwright，5 个动作）★ Sprint 13
│       │           └── plugin.py           # BrowserPlugin（PluginProtocol 包装）★ Sprint 13
│       │
│       ├── mcp/                            # Layer 4 — MCP 客户端（Sprint 5 实现）
│       │   ├── client.py                   # MCP 协议客户端（连接外部 MCP 服务）
│       │   ├── skill_adapter.py            # MCPSkill：将 MCP 工具包装为 SkillProtocol
│       │   ├── plugin_adapter.py           # MCPPlugin：将 MCP 服务器包装为 PluginProtocol
│       │   └── registry.py                 # MCP server 连接注册表
│       │
│       ├── storage/                        # Layer 4
│       │   ├── postgres/
│       │   │   ├── models.py               # SQLAlchemy async ORM（含 UsageRow + DocumentEmbeddingRow）★ Sprint 13
│       │   │   └── repos/
│       │   ├── billing/
│       │   │   └── billing_repo.py         # BillingRepository ★ Sprint 10
│       │   ├── vector/
│       │   │   └── vector_store.py         # EmbeddingRepository（余弦相似度搜索）★ Sprint 13
│       │   └── redis/
│       │
│       ├── scheduler/                      # Layer 4 ★ Sprint 14
│       │   ├── setup.py                    # SchedulerManager（APScheduler AsyncIOScheduler）
│       │   └── jobs/
│       │       └── billing_rollup.py       # 定时账单汇总任务
│       │
│       └── wiring/                         # Layer 5 ★ 唯一知道所有具体类的地方
│           ├── container.py
│           └── bootstrap.py
│
├── frontend/
│   ├── index.html                    # 无 Google Fonts，使用系统字体栈
│   └── src/
│       ├── api/
│       │   ├── client.ts             # fetch 封装（JWT header）
│       │   ├── tasks.ts              # POST /tasks, GET /tasks/:id
│       │   ├── sessions.ts           # GET /sessions 等
│       │   ├── ws.ts                 # WebSocket 工厂
│       │   └── billing.ts            # GET /usage ★ Sprint 12
│       ├── types/api.ts              # 后端类型镜像（只读，禁止加业务逻辑）
│       ├── store/
│       │   ├── authStore.ts          # JWT token（persist → localStorage）
│       │   ├── sessionStore.ts       # 当前 session_id
│       │   ├── taskStore.ts          # 任务状态 + blocks + userMessage
│       │   ├── uiStore.ts            # lang + sidebarOpen（persist）
│       │   └── settingsStore.ts      # API Keys / coordinator / routing（persist）★ Sprint 8
│       ├── hooks/
│       │   ├── useT.ts               # i18n 翻译
│       │   ├── useTask.ts            # sendMessage → POST /tasks + setUserMessage
│       │   └── useStream.ts          # WebSocket dispatch → taskStore
│       ├── i18n/index.ts             # zh/en 翻译表
│       ├── components/
│       │   ├── Logo.tsx              # showSubtitle prop
│       │   ├── Sidebar.tsx           # 200px；nav: home/tasks/plugins/usage + 底部 settings
│       │   ├── AgentSidebar.tsx      # 240px；进度条 + 模型名 + 拓扑入口 + 底部统计
│       │   ├── TaskInput.tsx
│       │   ├── ResultStream.tsx
│       │   ├── ComingSoon.tsx
│       │   └── blocks/
│       │       ├── TextBlock.tsx     # rounded-[10px], border-[0.5px]
│       │       ├── CodeBlock.tsx
│       │       ├── ImageBlock.tsx
│       │       └── VideoBlock.tsx
│       └── pages/
│           ├── Home.tsx              # 三栏；顶部栏；用户消息右对齐气泡
│           ├── Login.tsx
│           ├── History.tsx
│           ├── Plugins.tsx
│           ├── Settings.tsx          # 5 个模块；纯 localStorage ★ Sprint 8
│           └── Usage.tsx             # 用量统计；总 token + 按 provider 条形图 ★ Sprint 12
│
└── tests/
    ├── test_import_boundaries.py           # 验证无越级导入（CI 必跑）
    └── integration/
        ├── test_task_full_flow.py
        └── test_ws_streaming.py
```

---

## 四、关键接口定义

### 4.1 CanonicalMessage

```python
@dataclass(frozen=True)
class CanonicalMessage:
    role: Role                       # system | user | assistant | tool
    content: list[ContentPart]       # TextPart | ImagePart | ToolCallPart | ToolResultPart
    message_id: str = ""
    schema_version: int = 1          # 演进占位：只增不删，新字段必须有默认值
    metadata: dict[str, Any] = field(default_factory=dict)
```

**演进规则**：
- ✅ 允许：新增字段（必须有默认值）
- ❌ 禁止：删除字段、重命名字段、修改已有字段类型

### 4.2 RunContext

```python
@dataclass
class RunContext:
    tenant_id: str
    session_id: str
    task_id: str
    trace_id: str = ""               # Sprint 3 起透传，Sprint 8 接 OTel
    user_id: str = ""
```

### 4.3 核心 Protocols（全部在 shared/protocols.py）

- `InstructionTransformer` — 格式转换，只抛 `TransformError`
- `ProviderAdapter` — HTTP 调用，HTTP 错误翻译为 `ProviderError` 子类
- `SkillProtocol` — 单个 Skill 执行
- `PluginProtocol` — 插件生命周期
- `TransformerRegistryProtocol` — 版本化 Transformer 查找
- `PluginRegistryProtocol` — Skill 查找

### 4.4 错误层级（shared/errors.py）

```
OrchestrationError（基类）
  ├── TransformError         # Transformer 格式转换失败
  ├── ProviderError          # Adapter HTTP/网络错误
  │   ├── RateLimitError     # 429
  │   ├── AuthError          # 401/403
  │   └── ProviderUnavailable  # 5xx
  ├── ContextOverflowError   # token/char 超限
  ├── TenantIsolationError   # RLS 注入失败
  └── PluginError            # Skill 执行失败
```

### 4.5 ProviderID 枚举

```python
class ProviderID(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    JIMENG = "jimeng"
    KLING = "kling"
    SKILL = "skill"
```

---

## 五、关键配置项（shared/config.py）

> **环境变量命名规则**：Python 字段名加前缀 `ORCH_` 即为实际环境变量名。
> 例如：字段 `COORDINATOR_MODEL` → 环境变量 `ORCH_COORDINATOR_MODEL`

| Python 字段名 | 实际环境变量 | 默认值 | 说明 |
|--------|--------|--------|------|
| `COORDINATOR_MODEL` | `ORCH_COORDINATOR_MODEL` | `claude-sonnet-4-6` | 主 LLM 模型 ID |
| `CONTEXT_TRUNCATION_THRESHOLD` | `ORCH_CONTEXT_TRUNCATION_THRESHOLD` | `400_000` | session 历史截断阈值（字符数）|
| `MAX_SUBTASK_CONTEXT_CHARS` | `ORCH_MAX_SUBTASK_CONTEXT_CHARS` | `40_000` | 子 Agent 上下文上限 |
| `MAX_RESULT_CHARS_PER_BLOCK` | `ORCH_MAX_RESULT_CHARS_PER_BLOCK` | `8_000` | 单块 ProviderResult 截断阈值 |
| `MAX_SUMMARY_INPUT_CHARS` | `ORCH_MAX_SUMMARY_INPUT_CHARS` | `120_000` | 汇总阶段总输入上限（≈30k tokens）|
| `PROVIDER_CONCURRENCY_LIMITS` | `ORCH_PROVIDER_CONCURRENCY_LIMITS` | `{anthropic:5, openai:10, ...}` | per-provider 并发上限 |
| `ENABLE_REVIEW_GATE` | `ORCH_ENABLE_REVIEW_GATE` | `false` | 启用主 Agent 审查门 |
| `WEBHOOK_SECRET` | `ORCH_WEBHOOK_SECRET` | `""` | Webhook 端点签名密钥（留空=跳过验证）★ Sprint 12 |

---

## 六、前端 WebSocket 事件类型

```typescript
// seq 字段：断线重连占坑（第二期实现）
type BlockUpdate =
  | { type: "block_created";    seq: number; block: UIBlock }
  | { type: "block_streaming";  seq: number; block_id: string; delta: string }
  | { type: "block_done";       seq: number; block_id: string; content: any }
  | { type: "summary_start";    seq: number }
  | { type: "summary_delta";    seq: number; delta: string }
  | { type: "summary_done";     seq: number; full_text: string }
  | { type: "error";            seq: number; message: string; block_id?: string }

type UIBlock = {
  id: string
  title: string
  worker_type: "search" | "code" | "image" | "video" | "analysis"
  status: "pending" | "running" | "done" | "error"
  content: any
  provider_used: string
  transformer_version: string
  tokens_used: number
  latency_ms: number
  trace_id: string
}
```

---

## 七、测试策略

| 模块 | 测试位置 | 测试方式 | Mock 边界 |
|------|---------|---------|---------|
| `shared/` | `shared/tests/` | 单元测试序列化/反序列化 | 无 Mock |
| `transformer/providers/xxx/` | 同目录 `tests/` | 单元测试格式转换 | 无 Mock（纯函数）|
| `providers/xxx/` | 同目录 `tests/` | respx 模拟 HTTP | Mock 网络层 |
| `orchestration/` | `orchestration/tests/` | AsyncMock 所有 Protocol | Mock 所有边界 |
| `plugins/` | 同目录 `tests/` | 单元 + 集成 | Mock HTTP |
| 边界验证 | `tests/test_import_boundaries.py` | AST 解析禁止导入 | — |
| 集成 | `tests/integration/` | 真实 DB/Redis（testcontainers）| Mock 外部 API |

---

## 八、实施阶段（Sprint 计划）

| Sprint | 周次 | 内容 | 状态 |
|--------|------|------|------|
| **Sprint 1** | 1-2 | `shared/`：types, enums, errors, protocols, config | ✅ 完成（90/90 测试通过）|
| **Sprint 2** | 3-4 | `transformer/base` + `registry` + 6个 provider transformer | ✅ 完成（132/132 测试通过）|
| **Sprint 3** | 5-6 | `providers/` 6个 adapter（httpx + respx 测试）| ✅ 完成（38/38 测试通过）|
| **Sprint 4** | 7-8 | `orchestration/` 编排核心（decomposer/router/executor/aggregator/engine）| ✅ 完成（76/76 测试通过）|
| **Sprint 6** | 9-10 | `storage/` + `plugins/` + `mcp/`（testcontainers 集成测试）| ✅ 完成（57/57 新增测试通过，累计 405）|
| **Sprint 7** | 11-12 | `wiring/` + `gateway/`（FastAPI + WS）| ✅ 完成（28/28 新增测试通过，累计 433）|
| **Sprint 8** | 13-14 | 前端（React + Vite + TS）+ 设置页 | ✅ 完成（21/21 测试通过）|
| **Sprint 9** | 15-16 | CI 加固 + OTel + RLS 安全审计 | ✅ 完成（447/447 单元测试 + 14/14 边界测试）|
| **Sprint 10** | 17-18 | Docker 沙箱 + CodeIterativeSkill + 计费聚合 | ✅ 完成（472/472 单元测试通过）|
| **Sprint 11** | 19-20 | Function Calling 完整实现（tool_call / tool_result 回路）| ✅ 完成（485/485 单元测试通过）|
| **Sprint 12** | 21-22 | Webhook 被动触发 + 前端 /usage 计费页面 | ✅ 完成（502/502 单元测试通过）|
| **Sprint 13** | 23-24 | 向量数据库/RAG + 浏览器自动化 Skill | ✅ 完成（527/527 单元测试通过）|
| **Sprint 14** | 25-26 | Scheduler（APScheduler）+ 文档摄入 API（POST /documents）| ✅ 完成（550/550 单元测试通过）|
| **Sprint 15** | — | N 系列 15 项缺陷修复（代码审查）| ✅ 完成（668 tests passed，+89）|
| **Sprint 16** | 27-28 | 集成测试覆盖（testcontainers + 真实 PostgreSQL/Redis）| ✅ 完成（668 unit + 41 integration tests，需 Docker 运行）|
| **Sprint 17** | 29-30 | 韧性加固（重试、熔断器、provider 超时、/readyz 详细状态）| ✅ 完成（690 unit tests，+22）|
| **Sprint 18** | 31-32 | 流式输出（SSE token streaming + WS 断线重连 seq 对齐）| ✅ 完成（693 unit tests，+3）|
| **Sprint 19** | 33-34 | 前端完善（对话界面 + Plugin/文档管理页）| ✅ 完成（Documents 页、SSE 客户端、WS 断线重连、API types）|
| **Sprint 20** | 35-36 | 基础可用性修复 + Coordinator Prompt 改进 | ✅ 完成（Auth 端点、DB 自动建表、Settings API Key 后端同步、Coordinator Prompt 重写+验证+可配置）|

---

## 九、MCP 支持

### 9.1 定位与原则

- **仅客户端**：本平台只作为 MCP 客户端，接入外部 MCP 服务器提供的工具；不实现 MCP 服务器。
- **零侵入**：MCP 工具对编排层完全透明——`MCPSkill` 实现 `SkillProtocol`，经 `PluginRegistry` 统一管理，与内置 Skill 等价。
- **Sprint 1-3 代码零改动**：`shared/`、`transformer/`、`providers/` 无需任何修改。

### 9.2 目录结构

```
mcp/                            # Layer 4，与 plugins/ 并列
├── client.py                   # 底层 MCP 协议客户端（stdio / SSE transport）
├── skill_adapter.py            # MCPSkill：将单个 MCP 工具包装为 SkillProtocol
├── plugin_adapter.py           # MCPPlugin：将 MCP 服务器包装为 PluginProtocol（含生命周期）
└── registry.py                 # MCP server 连接注册表（地址 / transport / 凭据）
```

### 9.3 数据流

```
MCP server（外部进程/服务）
  ↓ [MCP协议：tool_list / tool_call]
  mcp/client.py
  ↓
  MCPPlugin（mcp/plugin_adapter.py）── on_load() 自动注册工具
  ↓
  MCPSkill（mcp/skill_adapter.py） ── 实现 SkillProtocol
  ↓
  PluginRegistry.get_skill(skill_id)
  ↓
  ParallelExecutor（与内置 Skill 完全等价）
```


---

## 十、新增 LLM 流程（维护最小化）

要接入全新 LLM（如 `Qwen`）只需改 4 个文件：
1. `transformer/providers/qwen_v1/transformer.py`（新增）
2. `providers/qwen/adapter.py`（新增）
3. `wiring/container.py`（添加 2 行注册代码）
4. `shared/enums.py` 的 `ProviderID`（添加 1 行）

---


## 十一、验证命令

```bash
# 后端测试
cd backend
pytest tests/test_import_boundaries.py        # 边界验证（CI 必跑）
pytest src/orchestration/transformer/         # Transformer 测试（纯函数）
pytest src/orchestration/providers/           # Provider 测试（respx mock）
pytest src/orchestration/orchestration/       # 编排测试（AsyncMock）
pytest tests/integration/                     # 集成测试（testcontainers）

# 全栈启动
docker-compose up -d                          # 启动 PG + Redis
uvicorn orchestration.gateway.app:create_app --factory
```

---

## 十四、历史缺陷（已全部修复）

D-01~D-12（Sprint 14-15）、N-01~N-15（Sprint 15）共 27 项缺陷全部修复。详见 git log。

---

## 十五、N 系列缺陷修复（Sprint 15，全部 ✅）

| ID | 描述 | 状态 |
|----|------|------|
| N-01 | app.py 缺少 Response 导入 | ✅ |
| N-02 | PromptPlugin 未加载 | ✅ |
| N-03 | auth 未放行 /healthz /readyz /metrics | ✅ |
| N-04 | executor._execute_skill() 读取 prompt 字段（false positive）| ✅ |
| N-05 | builtin/prompt_skills/ 多余 plugin.toml | ✅ |
| N-06 | context_slice 序列化丢失内容 | ✅ |
| N-07 | CORS 来源硬编码 | ✅ |
| N-08 | TenantKey 明文存储（Fernet 加密）| ✅ |
| N-09 | AppContainer God Object 重构 | ✅ |
| N-10 | Coordinator provider 硬编码 Anthropic | ✅ |
| N-11 | SafeFormatMap 静默忽略缺失占位符 | ✅ |
| N-12 | 内置 skill 文件名不符规范 | ✅ |
| N-13 | executor 处理 prompt_injection（false positive）| ✅ |
| N-14 | 缺少 executor 内部 Prometheus 指标 | ✅ |
| N-15 | docker-compose healthcheck 用 /readyz | ✅ |

---

