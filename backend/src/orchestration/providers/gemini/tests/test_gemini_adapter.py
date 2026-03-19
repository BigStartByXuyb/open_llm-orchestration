"""
GeminiAdapter 单元测试
Unit tests for GeminiAdapter — uses respx to mock HTTP calls.
"""

import pytest
import respx
import httpx

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import AuthError, ProviderUnavailable, RateLimitError
from orchestration.shared.types import RunContext
from orchestration.providers.gemini.adapter import GeminiAdapter


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


@pytest.fixture()
def adapter() -> GeminiAdapter:
    return GeminiAdapter(api_key="gemini-test-key")


SAMPLE_PAYLOAD = {
    "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
    "generationConfig": {"maxOutputTokens": 1024},
}

SAMPLE_RESPONSE = {
    "candidates": [{
        "content": {"parts": [{"text": "Hi there!"}], "role": "model"},
        "finishReason": "STOP",
    }],
    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
}


class TestCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_call(self, adapter: GeminiAdapter, ctx: RunContext) -> None:
        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        payload_with_model = {**SAMPLE_PAYLOAD, "model": "gemini-2.0-flash"}
        result = await adapter.call(payload_with_model, ctx)
        assert result["candidates"][0]["content"]["parts"][0]["text"] == "Hi there!"

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_key_as_query_param(self, adapter: GeminiAdapter, ctx: RunContext) -> None:
        route = respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        payload_with_model = {**SAMPLE_PAYLOAD, "model": "gemini-2.0-flash"}
        await adapter.call(payload_with_model, ctx)
        request = route.calls.last.request
        # API key should be in query params, not auth header
        assert "key=gemini-test-key" in str(request.url)
        assert "authorization" not in [k.lower() for k in request.headers]

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_auth_error(self, adapter: GeminiAdapter, ctx: RunContext) -> None:
        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(401, json={"error": {"message": "API key invalid"}}))

        with pytest.raises(AuthError):
            await adapter.call({**SAMPLE_PAYLOAD, "model": "gemini-2.0-flash"}, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_raises_rate_limit(self, adapter: GeminiAdapter, ctx: RunContext) -> None:
        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(429, json={"error": "quota exceeded"}))

        with pytest.raises(RateLimitError):
            await adapter.call({**SAMPLE_PAYLOAD, "model": "gemini-2.0-flash"}, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_raises_provider_unavailable(self, adapter: GeminiAdapter, ctx: RunContext) -> None:
        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

        with pytest.raises(ProviderUnavailable):
            await adapter.call({**SAMPLE_PAYLOAD, "model": "gemini-2.0-flash"}, ctx)


class TestProviderMetadata:
    def test_provider_id(self, adapter: GeminiAdapter) -> None:
        assert adapter.provider_id == ProviderID.GEMINI
