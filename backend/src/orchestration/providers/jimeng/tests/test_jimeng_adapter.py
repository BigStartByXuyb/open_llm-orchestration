"""
JimengAdapter 单元测试（含双模式认证）
Unit tests for JimengAdapter — bearer mode and volcano_signing mode.
Uses respx to mock HTTP calls; signing.py tested separately with deterministic inputs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pytest
import respx

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import AuthError, ProviderUnavailable
from orchestration.shared.types import RunContext
from orchestration.providers.jimeng.adapter import JimengAdapter
from orchestration.providers.jimeng.config import JimengConfig
from orchestration.providers.jimeng.signing import build_volcano_auth_headers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


@pytest.fixture()
def adapter() -> JimengAdapter:
    """Bearer 模式适配器（向后兼容）/ Bearer mode adapter (backward-compatible)."""
    return JimengAdapter(api_key="jm-test-key")


@pytest.fixture()
def volcano_adapter() -> JimengAdapter:
    """Volcano 签名模式适配器 / Volcano signing mode adapter."""
    config = JimengConfig(
        API_KEY="",
        AUTH_MODE="volcano_signing",
        ACCESS_KEY="test-ak",
        SECRET_KEY="test-sk",
    )
    return JimengAdapter(config=config)


SAMPLE_PAYLOAD = {
    "model_version": "jimeng-3.0",
    "prompt": "A beautiful mountain landscape",
    "width": 1024,
    "height": 1024,
    "req_key": "jimeng_high_aes_general_v30",
}

SAMPLE_RESPONSE = {
    "data": {
        "algorithm_base_resp": {"status_code": 0, "status_message": "Success"},
        "image_urls": ["https://cdn.example.com/gen_img_1.jpg"],
    }
}

_API_URL = "https://visual.volcengineapi.com/?Action=CVProcess&Version=2022-08-31"


# ---------------------------------------------------------------------------
# Bearer 模式测试（原有测试保持不变）
# Bearer mode tests (original tests unchanged)
# ---------------------------------------------------------------------------

class TestCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_call(self, adapter: JimengAdapter, ctx: RunContext) -> None:
        respx.post(_API_URL).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        result = await adapter.call(SAMPLE_PAYLOAD, ctx)
        assert result["data"]["image_urls"][0] == "https://cdn.example.com/gen_img_1.jpg"

    @pytest.mark.asyncio
    @respx.mock
    async def test_bearer_auth_header(self, adapter: JimengAdapter, ctx: RunContext) -> None:
        route = respx.post(_API_URL).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        await adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        assert request.headers.get("authorization") == "Bearer jm-test-key"

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_raises_auth_error(self, adapter: JimengAdapter, ctx: RunContext) -> None:
        respx.post(_API_URL).mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))

        with pytest.raises(AuthError):
            await adapter.call(SAMPLE_PAYLOAD, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_500_raises_provider_unavailable(self, adapter: JimengAdapter, ctx: RunContext) -> None:
        respx.post(_API_URL).mock(return_value=httpx.Response(500, text="Server Error"))

        with pytest.raises(ProviderUnavailable):
            await adapter.call(SAMPLE_PAYLOAD, ctx)


class TestProviderMetadata:
    def test_provider_id(self, adapter: JimengAdapter) -> None:
        assert adapter.provider_id == ProviderID.JIMENG


# ---------------------------------------------------------------------------
# Volcano 签名模式测试（新增）
# Volcano signing mode tests (new)
# ---------------------------------------------------------------------------

class TestVolcanoSigningMode:
    @pytest.mark.asyncio
    @respx.mock
    async def test_volcano_signing_adds_x_date_header(
        self, volcano_adapter: JimengAdapter, ctx: RunContext
    ) -> None:
        """volcano_signing 模式下请求应包含 X-Date 头。"""
        route = respx.post(_API_URL).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        await volcano_adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        assert "x-date" in request.headers

    @pytest.mark.asyncio
    @respx.mock
    async def test_volcano_signing_adds_hmac_authorization_header(
        self, volcano_adapter: JimengAdapter, ctx: RunContext
    ) -> None:
        """volcano_signing 模式下 Authorization 头应以 HMAC-SHA256 开头。"""
        route = respx.post(_API_URL).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        await volcano_adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        auth = request.headers.get("authorization", "")
        assert auth.startswith("HMAC-SHA256 ")

    @pytest.mark.asyncio
    @respx.mock
    async def test_volcano_signing_authorization_contains_credential(
        self, volcano_adapter: JimengAdapter, ctx: RunContext
    ) -> None:
        """Authorization 头应包含 Credential=test-ak/ 字段。"""
        route = respx.post(_API_URL).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        await volcano_adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        auth = request.headers.get("authorization", "")
        assert "Credential=test-ak/" in auth

    @pytest.mark.asyncio
    @respx.mock
    async def test_bearer_mode_does_not_add_x_date(
        self, adapter: JimengAdapter, ctx: RunContext
    ) -> None:
        """bearer 模式下不应有 X-Date 头。"""
        route = respx.post(_API_URL).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        await adapter.call(SAMPLE_PAYLOAD, ctx)
        request = route.calls.last.request
        assert "x-date" not in request.headers


# ---------------------------------------------------------------------------
# 配置校验测试
# Config validation tests
# ---------------------------------------------------------------------------

class TestConfigValidation:
    def test_missing_access_key_in_volcano_mode_raises(self) -> None:
        """volcano_signing 模式下缺少 ACCESS_KEY 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="ACCESS_KEY"):
            JimengConfig(AUTH_MODE="volcano_signing", SECRET_KEY="sk")

    def test_missing_secret_key_in_volcano_mode_raises(self) -> None:
        """volcano_signing 模式下缺少 SECRET_KEY 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="SECRET_KEY"):
            JimengConfig(AUTH_MODE="volcano_signing", ACCESS_KEY="ak")

    def test_bearer_mode_does_not_require_access_key(self) -> None:
        """bearer 模式下不需要 ACCESS_KEY / SECRET_KEY。"""
        config = JimengConfig(AUTH_MODE="bearer", API_KEY="some-key")
        assert config.AUTH_MODE == "bearer"

    def test_default_auth_mode_is_bearer(self) -> None:
        """默认认证模式应为 bearer。"""
        config = JimengConfig(API_KEY="k")
        assert config.AUTH_MODE == "bearer"


# ---------------------------------------------------------------------------
# 签名函数确定性测试
# Signing function determinism tests
# ---------------------------------------------------------------------------

class TestSigningDeterminism:
    _FIXED_NOW = datetime(2026, 3, 19, 12, 0, 0, tzinfo=timezone.utc)

    def test_fixed_datetime_produces_deterministic_output(self) -> None:
        """相同输入（含固定时间）应产生完全相同的签名头。"""
        headers_a = build_volcano_auth_headers(
            method="POST",
            path="/",
            body=b'{"prompt":"test"}',
            access_key="ak",
            secret_key="sk",
            query_string="Action=CVProcess&Version=2022-08-31",
            now=self._FIXED_NOW,
        )
        headers_b = build_volcano_auth_headers(
            method="POST",
            path="/",
            body=b'{"prompt":"test"}',
            access_key="ak",
            secret_key="sk",
            query_string="Action=CVProcess&Version=2022-08-31",
            now=self._FIXED_NOW,
        )
        assert headers_a == headers_b

    def test_x_date_format(self) -> None:
        """X-Date 格式应为 YYYYMMDDTHHmmSSZ。"""
        headers = build_volcano_auth_headers(
            method="POST",
            path="/",
            body=b"{}",
            access_key="ak",
            secret_key="sk",
            now=self._FIXED_NOW,
        )
        assert headers["X-Date"] == "20260319T120000Z"

    def test_authorization_structure(self) -> None:
        """Authorization 头应包含三个部分：Credential, SignedHeaders, Signature。"""
        headers = build_volcano_auth_headers(
            method="POST",
            path="/",
            body=b"{}",
            access_key="my-ak",
            secret_key="my-sk",
            now=self._FIXED_NOW,
        )
        auth = headers["Authorization"]
        assert "Credential=my-ak/" in auth
        assert "SignedHeaders=" in auth
        assert "Signature=" in auth

    def test_different_bodies_produce_different_signatures(self) -> None:
        """不同请求体应产生不同签名（body hash 参与签名计算）。"""
        headers_a = build_volcano_auth_headers(
            method="POST", path="/", body=b'{"prompt":"a"}',
            access_key="ak", secret_key="sk", now=self._FIXED_NOW,
        )
        headers_b = build_volcano_auth_headers(
            method="POST", path="/", body=b'{"prompt":"b"}',
            access_key="ak", secret_key="sk", now=self._FIXED_NOW,
        )
        assert headers_a["Authorization"] != headers_b["Authorization"]
