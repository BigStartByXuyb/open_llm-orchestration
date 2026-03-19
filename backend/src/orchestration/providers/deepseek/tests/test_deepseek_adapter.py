"""
DeepSeekAdapter 单元测试
Unit tests for DeepSeekAdapter — uses respx to mock HTTP calls.
"""

import pytest
import respx
import httpx

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import AuthError, ProviderUnavailable, RateLimitError
from orchestration.shared.types import RunContext
from orchestration.providers.deepseek.adapter import DeepSeekAdapter


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


@pytest.fixture()
def adapter() -> DeepSeekAdapter:
    return DeepSeekAdapter(api_key="ds-test-key")


SAMPLE_PAYLOAD = {
    "model": "deepseek-chat",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}],
}

SAMPLE_RESPONSE = {
    "choices": [{"message": {"role": "assistant", "content": "Hi!"}}],
    "usage": {"total_tokens": 10},
}


class TestCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_call(self, adapter: DeepSeekAdapter, ctx: RunContext) -> None:
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
        )
        result = await adapter.call(SAMPLE_PAYLOAD, ctx)
        assert result["choices"][0]["message"]["content"] == "Hi!"

    @pytest.mark.asyncio
    @respx.mock
    async def test_bearer_auth_header(self, adapter: DeepSeekAdapter, ctx: RunContext) -> None:
        route = respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
        )
        await adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        assert request.headers.get("authorization") == "Bearer ds-test-key"

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_auth_error(self, adapter: DeepSeekAdapter, ctx: RunContext) -> None:
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with pytest.raises(AuthError):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_raises_rate_limit(self, adapter: DeepSeekAdapter, ctx: RunContext) -> None:
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": "rate_limit"})
        )
        with pytest.raises(RateLimitError):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_503_raises_provider_unavailable(self, adapter: DeepSeekAdapter, ctx: RunContext) -> None:
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(503, text="Service Unavailable")
        )
        with pytest.raises(ProviderUnavailable):
            await adapter.call(SAMPLE_PAYLOAD, ctx)


class TestProviderMetadata:
    def test_provider_id(self, adapter: DeepSeekAdapter) -> None:
        assert adapter.provider_id == ProviderID.DEEPSEEK
