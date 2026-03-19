"""
BrowserSkill 单元测试（mock Playwright）
Unit tests for BrowserSkill (mocked Playwright).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext
from orchestration.plugins.builtin.browser.skill import BrowserSkill


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture()
def skill() -> BrowserSkill:
    return BrowserSkill()


@pytest.fixture()
def context() -> RunContext:
    return RunContext(
        tenant_id="tenant-1",
        session_id="session-1",
        task_id="task-1",
        trace_id="trace-1",
    )


def _make_pw_mock(inner_text: str = "Page content", current_url: str = "https://example.com") -> tuple[MagicMock, MagicMock, MagicMock]:
    """
    Build a minimal mock of async_playwright context manager + page.
    Returns (async_playwright_callable, page_mock, fake_playwright_async_api_module).

    Usage in tests:
        async_pw, page, fake_module = _make_pw_mock(...)
        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": fake_module}):
            ...
    """
    page = AsyncMock()
    page.url = current_url
    page.goto = AsyncMock()
    page.inner_text = AsyncMock(return_value=inner_text)
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n")

    browser = AsyncMock()
    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)

    pw_instance = MagicMock()
    pw_instance.chromium = chromium

    pw_ctx = AsyncMock()
    pw_ctx.__aenter__ = AsyncMock(return_value=pw_instance)
    pw_ctx.__aexit__ = AsyncMock(return_value=None)

    async_pw = MagicMock(return_value=pw_ctx)

    # Build a fake playwright.async_api module that exports async_playwright
    fake_module = MagicMock()
    fake_module.async_playwright = async_pw

    return async_pw, page, fake_module


# -----------------------------------------------------------------------
# Validation tests
# -----------------------------------------------------------------------


class TestValidation:
    @pytest.mark.asyncio
    async def test_invalid_action_raises(self, skill: BrowserSkill, context: RunContext) -> None:
        with pytest.raises(PluginError, match="Invalid action"):
            await skill.execute({"action": "fly", "url": "https://x.com"}, context)

    @pytest.mark.asyncio
    async def test_empty_url_raises(self, skill: BrowserSkill, context: RunContext) -> None:
        with pytest.raises(PluginError, match="url must not be empty"):
            await skill.execute({"action": "navigate", "url": ""}, context)

    @pytest.mark.asyncio
    async def test_playwright_not_installed_raises(
        self, skill: BrowserSkill, context: RunContext
    ) -> None:
        with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
            with pytest.raises(PluginError, match="playwright is not installed"):
                await skill.execute({"action": "navigate", "url": "https://x.com"}, context)


# -----------------------------------------------------------------------
# Action tests
# -----------------------------------------------------------------------


class TestActions:
    @pytest.mark.asyncio
    async def test_navigate_returns_final_url(
        self, skill: BrowserSkill, context: RunContext
    ) -> None:
        _, page, fake_module = _make_pw_mock(current_url="https://example.com/redirected")

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": fake_module}):
            result = await skill.execute(
                {"action": "navigate", "url": "https://example.com"}, context
            )

        assert result["success"] is True
        assert result["content"] == "https://example.com/redirected"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_get_text_returns_page_text(
        self, skill: BrowserSkill, context: RunContext
    ) -> None:
        _, page, fake_module = _make_pw_mock(inner_text="Hello World!")

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": fake_module}):
            result = await skill.execute(
                {"action": "get_text", "url": "https://example.com", "selector": "h1"},
                context,
            )

        assert result["success"] is True
        assert result["content"] == "Hello World!"

    @pytest.mark.asyncio
    async def test_click_returns_confirmation(
        self, skill: BrowserSkill, context: RunContext
    ) -> None:
        _, page, fake_module = _make_pw_mock()

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": fake_module}):
            result = await skill.execute(
                {"action": "click", "url": "https://example.com", "selector": "#btn"},
                context,
            )

        assert result["success"] is True
        assert "#btn" in result["content"]
        page.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_fill_form_calls_fill(
        self, skill: BrowserSkill, context: RunContext
    ) -> None:
        _, page, fake_module = _make_pw_mock()

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": fake_module}):
            result = await skill.execute(
                {
                    "action": "fill_form",
                    "url": "https://example.com",
                    "selector": "#input",
                    "text": "hello",
                },
                context,
            )

        assert result["success"] is True
        page.fill.assert_called_once_with("#input", "hello", timeout=30000)

    @pytest.mark.asyncio
    async def test_screenshot_returns_base64(
        self, skill: BrowserSkill, context: RunContext
    ) -> None:
        import base64

        _, page, fake_module = _make_pw_mock()
        page.screenshot = AsyncMock(return_value=b"PNG_DATA")

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": fake_module}):
            result = await skill.execute(
                {"action": "screenshot", "url": "https://example.com"}, context
            )

        assert result["success"] is True
        assert result["content"] == base64.b64encode(b"PNG_DATA").decode("ascii")

    @pytest.mark.asyncio
    async def test_browser_exception_wrapped_in_plugin_error(
        self, skill: BrowserSkill, context: RunContext
    ) -> None:
        _, page, fake_module = _make_pw_mock()
        page.goto.side_effect = Exception("Connection refused")

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": fake_module}):
            with pytest.raises(PluginError, match="Connection refused"):
                await skill.execute(
                    {"action": "navigate", "url": "https://bad-host.example"}, context
                )

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_max(
        self, skill: BrowserSkill, context: RunContext
    ) -> None:
        _, page, fake_module = _make_pw_mock()

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": fake_module}):
            result = await skill.execute(
                {
                    "action": "navigate",
                    "url": "https://example.com",
                    "timeout": 9999,  # way above 120 s max
                },
                context,
            )

        assert result["success"] is True
        # page.goto should be called with timeout=120_000 (120 s in ms)
        call_kwargs = page.goto.call_args.kwargs
        assert call_kwargs.get("timeout") == 120_000
