"""
AnthropicAdapter 单元测试
Unit tests for AnthropicAdapter — uses respx to mock HTTP calls.
"""

import pytest
import respx
import httpx

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import AuthError, ProviderUnavailable, RateLimitError
from orchestration.shared.types import RunContext
from orchestration.providers.anthropic.adapter import AnthropicAdapter


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


@pytest.fixture()
def adapter() -> AnthropicAdapter:
    return AnthropicAdapter(api_key="test-key")


SAMPLE_PAYLOAD = {
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}],
}

SAMPLE_RESPONSE = {
    "id": "msg_1",
    "content": [{"type": "text", "text": "Hello! How can I help?"}],
    "usage": {"input_tokens": 10, "output_tokens": 8},
}


class TestCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_call(self, adapter: AnthropicAdapter, ctx: RunContext) -> None:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
        )
        result = await adapter.call(SAMPLE_PAYLOAD, ctx)
        assert result["id"] == "msg_1"
        assert result["content"][0]["text"] == "Hello! How can I help?"

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_auth_headers(self, adapter: AnthropicAdapter, ctx: RunContext) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
        )
        await adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        assert request.headers.get("x-api-key") == "test-key"
        assert "anthropic-version" in request.headers

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_auth_error(self, adapter: AnthropicAdapter, ctx: RunContext) -> None:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with pytest.raises(AuthError):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_raises_rate_limit_error(self, adapter: AnthropicAdapter, ctx: RunContext) -> None:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                429,
                json={"error": "rate_limit"},
                headers={"retry-after": "30"},
            )
        )
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.call(SAMPLE_PAYLOAD, ctx)
        assert exc_info.value.retry_after == 30.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_raises_provider_unavailable(self, adapter: AnthropicAdapter, ctx: RunContext) -> None:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(500, json={"error": "internal_error"})
        )
        with pytest.raises(ProviderUnavailable):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_403_raises_auth_error(self, adapter: AnthropicAdapter, ctx: RunContext) -> None:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(403, json={"error": "forbidden"})
        )
        with pytest.raises(AuthError):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_network_error_raises_provider_unavailable(
        self, adapter: AnthropicAdapter, ctx: RunContext
    ) -> None:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            side_effect=httpx.NetworkError("connection refused")
        )
        with pytest.raises(ProviderUnavailable):
            await adapter.call(SAMPLE_PAYLOAD, ctx)


class TestProviderMetadata:
    def test_provider_id(self, adapter: AnthropicAdapter) -> None:
        assert adapter.provider_id == ProviderID.ANTHROPIC
