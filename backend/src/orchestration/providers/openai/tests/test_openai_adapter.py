"""
OpenAIAdapter 单元测试
Unit tests for OpenAIAdapter — uses respx to mock HTTP calls.
"""

import pytest
import respx
import httpx

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import AuthError, ProviderUnavailable, RateLimitError
from orchestration.shared.types import RunContext
from orchestration.providers.openai.adapter import OpenAIAdapter


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


@pytest.fixture()
def adapter() -> OpenAIAdapter:
    return OpenAIAdapter(api_key="sk-test")


SAMPLE_PAYLOAD = {
    "model": "gpt-4o",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}],
}

SAMPLE_RESPONSE = {
    "id": "chatcmpl-1",
    "choices": [{"message": {"role": "assistant", "content": "Hi there!"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}


class TestCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_call(self, adapter: OpenAIAdapter, ctx: RunContext) -> None:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
        )
        result = await adapter.call(SAMPLE_PAYLOAD, ctx)
        assert result["choices"][0]["message"]["content"] == "Hi there!"

    @pytest.mark.asyncio
    @respx.mock
    async def test_bearer_auth_header(self, adapter: OpenAIAdapter, ctx: RunContext) -> None:
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
        )
        await adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        assert request.headers.get("authorization") == "Bearer sk-test"

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_auth_error(self, adapter: OpenAIAdapter, ctx: RunContext) -> None:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": {"message": "invalid key"}})
        )
        with pytest.raises(AuthError):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_raises_rate_limit(self, adapter: OpenAIAdapter, ctx: RunContext) -> None:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": "rate_limit"})
        )
        with pytest.raises(RateLimitError):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_raises_provider_unavailable(self, adapter: OpenAIAdapter, ctx: RunContext) -> None:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(ProviderUnavailable):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_network_error_raises_provider_unavailable(
        self, adapter: OpenAIAdapter, ctx: RunContext
    ) -> None:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("refused")
        )
        with pytest.raises(ProviderUnavailable):
            await adapter.call(SAMPLE_PAYLOAD, ctx)


class TestProviderMetadata:
    def test_provider_id(self, adapter: OpenAIAdapter) -> None:
        assert adapter.provider_id == ProviderID.OPENAI
