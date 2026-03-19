"""
KlingAdapter — 可灵视频生成 API 异步 HTTP 客户端（含轮询）
KlingAdapter — Async HTTP client for Kling video generation API (with polling).

Layer 4: Only imports from shared/ and providers/_base_http.py.

Kling video generation is async: submit task → poll until done.
可灵视频生成是异步的：提交任务 → 轮询直到完成。

Polling strategy / 轮询策略:
  - Submit task → get task_id
  - Poll GET /v1/videos/text2video/{task_id} every POLL_INTERVAL seconds
  - Max POLL_MAX_ATTEMPTS attempts before raising ProviderUnavailable
  - call() blocks until video is ready (or timeout)
  - stream() yields progress updates during polling
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import ProviderUnavailable
from orchestration.shared.types import RunContext, StreamChunk
from orchestration.providers._base_http import BaseHttpAdapter


# Polling configuration / 轮询配置
POLL_INTERVAL: float = 5.0
POLL_MAX_ATTEMPTS: int = 60


class KlingAdapter(BaseHttpAdapter):
    """
    可灵视频生成 API 异步适配器（阻塞式轮询）
    Async adapter for Kling video generation API (blocking polling).
    """

    BASE_URL = "https://api.klingai.com"
    DEFAULT_TIMEOUT = 30.0

    provider_id: ProviderID = ProviderID.KLING

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        poll_interval: float = POLL_INTERVAL,
        poll_max_attempts: int = POLL_MAX_ATTEMPTS,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url)
        self.poll_interval = poll_interval
        self.poll_max_attempts = poll_max_attempts

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def call(self, payload: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        提交视频生成任务并阻塞轮询直到完成
        Submit video generation task and block-poll until completion.

        Returns the final completed task response (with video URL).
        返回最终完成的任务响应（包含视频 URL）。
        """
        # Step 1: Submit task / 提交任务
        submit_response = await self._post("/v1/videos/text2video", payload, context)

        data = submit_response.get("data", {})
        task_id = data.get("task_id", "")
        if not task_id:
            raise ProviderUnavailable(
                "Kling API returned no task_id in submission response",
                provider_id=str(self.provider_id),
            )

        # Step 2: Poll for completion / 轮询等待完成
        return await self._poll_task(task_id, context)

    async def stream(
        self,
        payload: dict[str, Any],
        context: RunContext,
    ) -> AsyncIterator[StreamChunk]:
        """
        流式提交并轮询 — 轮询过程中推送进度事件
        Streaming submit + polling — push progress events during polling.
        """
        # Submit task
        submit_response = await self._post("/v1/videos/text2video", payload, context)
        data = submit_response.get("data", {})
        task_id = data.get("task_id", "")

        if not task_id:
            raise ProviderUnavailable("Kling returned no task_id", provider_id=str(self.provider_id))

        yield StreamChunk(
            delta=f"Task submitted: {task_id}",
            is_final=False,
            metadata={"task_id": task_id, "task_status": "submitted"},
        )

        # Poll and yield progress
        for attempt in range(self.poll_max_attempts):
            await asyncio.sleep(self.poll_interval)
            status_response = await self._get_task_status(task_id, context)
            task_data = status_response.get("data", {})
            task_status = task_data.get("task_status", "")

            if task_status == "succeed":
                videos = task_data.get("task_result", {}).get("videos", [])
                video_url = videos[0].get("url", "") if videos else ""
                yield StreamChunk(
                    delta=video_url,
                    is_final=True,
                    metadata={"task_id": task_id, "task_status": "succeed", "video_url": video_url},
                )
                return

            if task_status in ("failed", "error"):
                raise ProviderUnavailable(
                    f"Kling task {task_id} failed with status: {task_status}",
                    provider_id=str(self.provider_id),
                )

            yield StreamChunk(
                delta="",
                is_final=False,
                metadata={"task_id": task_id, "task_status": task_status, "attempt": attempt + 1},
            )

        raise ProviderUnavailable(
            f"Kling task {task_id} timed out after {self.poll_max_attempts} attempts",
            provider_id=str(self.provider_id),
        )

    async def _poll_task(self, task_id: str, context: RunContext) -> dict[str, Any]:
        """
        轮询任务状态直到完成或超时
        Poll task status until completion or timeout.
        """
        for attempt in range(self.poll_max_attempts):
            await asyncio.sleep(self.poll_interval)
            response = await self._get_task_status(task_id, context)
            data = response.get("data", {})
            task_status = data.get("task_status", "")

            if task_status == "succeed":
                return response

            if task_status in ("failed", "error"):
                raise ProviderUnavailable(
                    f"Kling task {task_id} failed: {task_status}",
                    provider_id=str(self.provider_id),
                )

        raise ProviderUnavailable(
            f"Kling task {task_id} timed out after {self.poll_max_attempts * self.poll_interval}s",
            provider_id=str(self.provider_id),
        )

    async def _get_task_status(self, task_id: str, context: RunContext) -> dict[str, Any]:
        """查询任务状态 / Query task status."""
        return await self._get(f"/v1/videos/text2video/{task_id}", context)
