"""
WebSocket 流式端点 — GET /ws/{task_id}
WebSocket streaming endpoint — GET /ws/{task_id}.

Layer 1: Uses deps and engine for orchestration.

事件协议 / Event protocol:
  客户端连接后发送任务消息，服务端推送 BlockUpdate 事件流。
  Client connects, sends task message, server pushes BlockUpdate event stream.

  所有事件携带 seq: int 字段（断线重连占坑，第二期实现增量同步）。
  All events carry seq: int (placeholder for reconnect, incremental sync in Phase 2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from orchestration.shared.enums import TaskStatus
from orchestration.shared.errors import OrchestrationError
from orchestration.shared.types import CanonicalMessage, Role, RunContext, TextPart
from orchestration.orchestration.engine import BlockDoneEvent, SummaryEvent, EventPayload
from orchestration.gateway.middleware.auth import AuthMiddleware
from orchestration.gateway.schemas.ws_event import (
    BlockCreatedEvent,
    BlockDoneEvent as WsBlockDoneEvent,
    SummaryStartEvent,
    SummaryDeltaEvent,
    SummaryDoneEvent,
    ErrorEvent,
)
from orchestration.wiring.bootstrap import get_container

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class _WSEventSender:
    """
    管理 WebSocket 事件发送，自动递增 seq，并缓冲事件供断线重连（Sprint 18）。
    Manages WebSocket event sending with auto-incrementing seq and event buffering
    for reconnection (Sprint 18).
    """

    def __init__(self, ws: WebSocket, task_id: str, event_buffer=None) -> None:
        self._ws = ws
        self._task_id = task_id
        self._event_buffer = event_buffer  # TaskStateStore instance for buffering
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def send(self, event: Any) -> None:
        data = event.model_dump_json()
        await self._ws.send_text(data)
        # Sprint 18: buffer event for potential reconnect replay
        if self._event_buffer is not None:
            seq = getattr(event, "seq", 0)
            try:
                await self._event_buffer.push_event(self._task_id, data, seq)
            except Exception:
                pass  # Non-fatal: buffering failure must not block event delivery

    async def send_error(self, message: str, code: str = "internal_error",
                         block_id: str | None = None) -> None:
        await self.send(ErrorEvent(
            seq=self._next_seq(),
            message=message,
            code=code,
            block_id=block_id,
        ))

    async def send_block_created(self, block_id: str, title: str, worker_type: str) -> None:
        await self.send(BlockCreatedEvent(
            seq=self._next_seq(),
            block_id=block_id,
            title=title,
            worker_type=worker_type,
        ))

    async def send_block_done(self, ev: BlockDoneEvent, trace_id: str) -> None:
        await self.send(WsBlockDoneEvent(
            seq=self._next_seq(),
            block_id=ev.block_id,
            content=ev.content,
            provider_used=ev.provider_id,
            transformer_version=ev.transformer_version,
            tokens_used=ev.tokens_used,
            latency_ms=ev.latency_ms,
            trace_id=trace_id,
        ))

    async def send_summary_start(self) -> None:
        await self.send(SummaryStartEvent(seq=self._next_seq()))

    async def send_summary_delta(self, delta: str) -> None:
        await self.send(SummaryDeltaEvent(seq=self._next_seq(), delta=delta))

    async def send_summary_done(self, full_text: str) -> None:
        await self.send(SummaryDoneEvent(seq=self._next_seq(), full_text=full_text))


@router.websocket("/ws/{task_id}")
async def websocket_endpoint(
    ws: WebSocket,
    task_id: str,
    last_seq: int = 0,
) -> None:
    """
    WebSocket 流式端点 — 运行编排管道并推送 BlockUpdate 事件
    WebSocket streaming endpoint — runs orchestration pipeline and pushes BlockUpdate events.

    Protocol / 协议:
      1. 客户端连接，发送 JSON: {"message": "...", "session_id": "...", "token": "..."}
         Client connects, sends JSON: {"message": "...", "session_id": "...", "token": "..."}
      2. 服务端推送事件流（block_created → block_done → summary_start → summary_delta → summary_done）
         Server pushes event stream
      3. 任何错误发送 error 事件后关闭连接
         On any error, send error event and close connection
    """
    await ws.accept()
    # Use container's task_state_store for event buffering (Sprint 18)
    _container = get_container()
    _event_buffer = _container.make_task_state_store() if _container else None
    sender = _WSEventSender(ws, task_id, event_buffer=_event_buffer)

    # Sprint 18: replay missed events if client reconnects with last_seq > 0
    if last_seq > 0 and _event_buffer is not None:
        try:
            missed = await _event_buffer.get_events_after(task_id, last_seq)
            for evt_json in missed:
                await ws.send_text(evt_json)
            logger.info(
                "WS reconnect: replayed %d events after seq=%d for task_id=%s",
                len(missed), last_seq, task_id,
            )
        except Exception as exc:
            logger.warning("Failed to replay missed events for %s: %s", task_id, exc)

    try:
        # Step 1: Receive initial message from client
        # 步骤 1：接收客户端初始消息
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
        except asyncio.TimeoutError:
            await sender.send_error("Connection timeout: no initial message received", "timeout")
            await ws.close(code=1008)
            return

        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            await sender.send_error("Invalid JSON in initial message", "invalid_json")
            await ws.close(code=1003)
            return

        message_text: str = data.get("message", "").strip()
        session_id_str: str = data.get("session_id", "")
        token: str = data.get("token", "")

        if not message_text:
            await sender.send_error("'message' field is required and must not be empty", "bad_request")
            await ws.close(code=1003)
            return

        # Step 2: Authenticate via JWT token from message payload
        # 步骤 2：通过消息载荷中的 JWT token 进行认证
        container = get_container()
        settings = container.settings

        from jose import JWTError, jwt as jose_jwt
        try:
            payload = jose_jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as exc:
            await sender.send_error("Invalid or expired token", "unauthorized")
            await ws.close(code=1008)
            return

        tenant_id: str = payload.get("tenant_id", "")
        user_id: str = payload.get("sub", "")

        if not tenant_id:
            await sender.send_error("Token missing tenant_id claim", "unauthorized")
            await ws.close(code=1008)
            return

        # Step 3: Build RunContext
        # 步骤 3：构建 RunContext
        trace_id = str(uuid.uuid4())
        context = RunContext(
            tenant_id=tenant_id,
            session_id=session_id_str,
            task_id=task_id,
            trace_id=trace_id,
            user_id=user_id,
        )

        # Step 4: Load recent session history from DB (last MAX_HISTORY_ROUNDS rounds)
        # 步骤 4：从 DB 加载最近 MAX_HISTORY_ROUNDS 轮会话历史（防止大会话 OOM）
        history: list[CanonicalMessage] = []
        if session_id_str:
            try:
                sid = uuid.UUID(session_id_str)
                # Each round = 1 user message + 1 assistant reply = 2 messages
                # 每轮 = 1 条用户消息 + 1 条 assistant 回复 = 2 条消息
                max_history_msgs = settings.MAX_HISTORY_ROUNDS * 2
                async with container.db_session_factory() as db_session:
                    from orchestration.storage.postgres.repos.session_repo import SessionRepository  # noqa: PLC0415
                    repo = SessionRepository(db_session)
                    all_msgs = await repo.get_messages(sid, tenant_id)
                    # Take only the most recent window (sliding from tail)
                    # 只取最近的滑动窗口（从尾部截取）
                    history = all_msgs[-max_history_msgs:] if len(all_msgs) > max_history_msgs else all_msgs
            except Exception as exc:
                logger.warning("Failed to load session history: %s", exc)
                # Non-fatal — proceed without history
                history = []

        # Step 5: Build user CanonicalMessage
        # 步骤 5：构建用户 CanonicalMessage
        user_message = CanonicalMessage(
            role=Role.USER,
            content=[TextPart(text=message_text)],
        )

        # Step 6: Update task status to running in Redis
        # 步骤 6：在 Redis 中更新任务状态为 running
        task_state = container.make_task_state_store()
        await task_state.set_status(task_id, "running", trace_id=trace_id)

        # Step 7: Load tenant API key overrides from DB
        # 步骤 7：从 DB 加载租户 API Key 覆盖
        override_adapters = None
        try:
            async with container.db_session_factory() as db_session:
                from orchestration.storage.postgres.repos.tenant_key_repo import TenantKeyRepository  # noqa: PLC0415
                key_repo = TenantKeyRepository(db_session)
                tenant_keys = await key_repo.list_all(tenant_id)
                if tenant_keys:
                    key_map = {row.provider_id: row.api_key for row in tenant_keys}
                    override_adapters = container.build_tenant_adapters(key_map)
        except Exception as exc:
            logger.warning("Failed to load tenant API keys: %s", exc)
            # Non-fatal — fall back to global adapters
            # 非致命：回退到全局 adapter

        # Step 8: Run orchestration pipeline with event sink
        # 步骤 8：运行编排管道并挂接事件 sink
        engine = container.engine
        rag_retriever = container.make_rag_retriever()

        async def event_sink(event: EventPayload) -> None:
            if isinstance(event, BlockDoneEvent):
                # Announce block creation first (we don't have pre-creation event from engine)
                title = event.metadata.get("description") or f"Task {event.block_id}"
                worker_type = event.metadata.get("capability") or "analysis"
                await sender.send_block_created(
                    block_id=event.block_id,
                    title=title,
                    worker_type=worker_type,
                )
                await sender.send_block_done(event, trace_id)
            elif isinstance(event, SummaryEvent):
                if event.event_type == "start":
                    await sender.send_summary_start()
                elif event.event_type == "delta":
                    await sender.send_summary_delta(event.delta)
                elif event.event_type == "done":
                    await sender.send_summary_done(event.full_text)

        try:
            summary = await engine.run(
                user_message=user_message,
                history=history,
                context=context,
                event_sink=event_sink,
                doc_retriever=rag_retriever,
                override_adapters=override_adapters,
            )
        except OrchestrationError as exc:
            await sender.send_error(str(exc), "orchestration_error")
            await task_state.set_status(task_id, "failed", trace_id=trace_id,
                                        extra={"error": str(exc)})
            await ws.close(code=1011)
            return
        except Exception as exc:
            logger.exception("Unexpected error during orchestration task_id=%s", task_id)
            await sender.send_error("Internal server error", "internal_error")
            await task_state.set_status(task_id, "failed", trace_id=trace_id,
                                        extra={"error": str(exc)})
            await ws.close(code=1011)
            return

        # Step 9: Persist result and update status
        # 步骤 9：持久化结果并更新状态
        await task_state.set_status(task_id, "done", trace_id=trace_id)

        # Persist to DB (best-effort — WS already delivered result)
        # 持久化到 DB（尽力而为 — WS 已推送结果）
        try:
            async with container.db_session_factory() as db_session:
                from orchestration.storage.postgres.repos.task_repo import TaskRepository
                from orchestration.storage.postgres.repos.session_repo import SessionRepository
                task_repo = TaskRepository(db_session)
                try:
                    task_uuid = uuid.UUID(task_id)
                    await task_repo.update_status(
                        task_id=task_uuid,
                        tenant_id=tenant_id,
                        status=TaskStatus.DONE,
                        result={"summary": summary},
                    )
                except Exception as exc:
                    logger.warning("Failed to update task DB record: %s", exc)

                # Append assistant reply to session
                # 将 assistant 回复追加到会话
                if session_id_str:
                    try:
                        sid = uuid.UUID(session_id_str)
                        session_repo = SessionRepository(db_session)
                        reply = CanonicalMessage(
                            role=Role.ASSISTANT,
                            content=[TextPart(text=summary)],
                        )
                        await session_repo.append_messages(sid, tenant_id, [user_message, reply])
                    except Exception as exc:
                        logger.warning("Failed to append messages to session: %s", exc)

                await db_session.commit()
        except Exception as exc:
            logger.warning("DB persistence failed for task %s: %s", task_id, exc)

        logger.info("Task completed: task_id=%s trace_id=%s", task_id, trace_id)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: task_id=%s", task_id)
    except Exception as exc:
        logger.exception("Unhandled WebSocket error: task_id=%s error=%s", task_id, exc)
        try:
            await sender.send_error("Unexpected server error", "internal_error")
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
