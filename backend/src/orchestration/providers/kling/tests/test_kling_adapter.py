"""
KlingAdapter 单元测试
Unit tests for KlingAdapter — uses respx to mock HTTP calls (including polling).
"""

import pytest
import respx
import httpx

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import AuthError, ProviderUnavailable
from orchestration.shared.types import RunContext
from orchestration.providers.kling.adapter import KlingAdapter


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


@pytest.fixture()
def adapter() -> KlingAdapter:
    # Use short poll interval and few attempts for tests
    # 测试中使用短轮询间隔和少量尝试次数
    return KlingAdapter(api_key="kling-test-key", poll_interval=0.01, poll_max_attempts=5)


SAMPLE_PAYLOAD = {
    "model": "kling-v1",
    "prompt": "A sunset over the ocean",
    "duration": "5",
    "aspect_ratio": "16:9",
}

SUBMIT_RESPONSE = {
    "code": 0,
    "message": "SUBMITTED",
    "data": {"task_id": "task_abc123", "task_status": "submitted"},
}

STATUS_RUNNING = {
    "code": 0,
    "data": {"task_id": "task_abc123", "task_status": "processing"},
}

STATUS_DONE = {
    "code": 0,
    "data": {
        "task_id": "task_abc123",
        "task_status": "succeed",
        "task_result": {
            "videos": [{"url": "https://cdn.kling.com/video.mp4", "duration": "5"}]
        },
    },
}


class TestCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_submit_and_poll(self, adapter: KlingAdapter, ctx: RunContext) -> None:
        # Submit returns task_id
        respx.post("https://api.klingai.com/v1/videos/text2video").mock(
            return_value=httpx.Response(200, json=SUBMIT_RESPONSE)
        )
        # First poll: still running
        # Second poll: done
        respx.get("https://api.klingai.com/v1/videos/text2video/task_abc123").mock(
            side_effect=[
                httpx.Response(200, json=STATUS_RUNNING),
                httpx.Response(200, json=STATUS_DONE),
            ]
        )

        result = await adapter.call(SAMPLE_PAYLOAD, ctx)
        video_url = result["data"]["task_result"]["videos"][0]["url"]
        assert video_url == "https://cdn.kling.com/video.mp4"

    @pytest.mark.asyncio
    @respx.mock
    async def test_submit_returns_no_task_id_raises(
        self, adapter: KlingAdapter, ctx: RunContext
    ) -> None:
        respx.post("https://api.klingai.com/v1/videos/text2video").mock(
            return_value=httpx.Response(200, json={"code": 0, "data": {}})
        )
        with pytest.raises(ProviderUnavailable, match="task_id"):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_poll_timeout_raises(self, adapter: KlingAdapter, ctx: RunContext) -> None:
        respx.post("https://api.klingai.com/v1/videos/text2video").mock(
            return_value=httpx.Response(200, json=SUBMIT_RESPONSE)
        )
        # Always return "processing" — never completes
        respx.get("https://api.klingai.com/v1/videos/text2video/task_abc123").mock(
            return_value=httpx.Response(200, json=STATUS_RUNNING)
        )
        with pytest.raises(ProviderUnavailable, match="timed out"):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_auth_error(self, adapter: KlingAdapter, ctx: RunContext) -> None:
        respx.post("https://api.klingai.com/v1/videos/text2video").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with pytest.raises(AuthError):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_bearer_auth_header(self, adapter: KlingAdapter, ctx: RunContext) -> None:
        route = respx.post("https://api.klingai.com/v1/videos/text2video").mock(
            return_value=httpx.Response(200, json=SUBMIT_RESPONSE)
        )
        respx.get("https://api.klingai.com/v1/videos/text2video/task_abc123").mock(
            return_value=httpx.Response(200, json=STATUS_DONE)
        )
        await adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        assert request.headers.get("authorization") == "Bearer kling-test-key"


class TestProviderMetadata:
    def test_provider_id(self, adapter: KlingAdapter) -> None:
        assert adapter.provider_id == ProviderID.KLING
