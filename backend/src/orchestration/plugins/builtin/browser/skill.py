"""
BrowserSkill — 浏览器自动化 Skill（Playwright 驱动）
BrowserSkill — Browser automation skill (Playwright-powered).

Layer 4: Only imports from shared/ and stdlib.
第 4 层：只导入 shared/ 和标准库。

支持的动作 / Supported actions:
  navigate    — 导航到 URL，返回最终 URL
                Navigate to URL, return final URL
  get_text    — 导航到 URL，提取指定选择器（默认 body）的纯文本
                Navigate to URL, extract plain text of selector (default: body)
  click       — 导航到 URL，点击指定选择器
                Navigate to URL, click the specified selector
  fill_form   — 导航到 URL，向指定选择器输入文本
                Navigate to URL, type text into the specified selector
  screenshot  — 导航到 URL，返回 Base64 PNG 截图
                Navigate to URL, return Base64-encoded PNG screenshot

安全说明 / Security notes:
  - 浏览器以 headless 模式运行
    Browser runs in headless mode
  - 超时默认 30 秒，最大 120 秒
    Default 30 s timeout, maximum 120 s
  - Playwright 为可选依赖；未安装时 execute() 抛 PluginError
    Playwright is an optional dependency; execute() raises PluginError if not installed

依赖安装 / Dependency installation:
  pip install playwright
  playwright install chromium
"""

from __future__ import annotations

import base64
from typing import Any

from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext

_VALID_ACTIONS = frozenset({"navigate", "get_text", "click", "fill_form", "screenshot"})
_MAX_TIMEOUT = 120.0
_DEFAULT_TIMEOUT = 30.0
_MAX_TEXT = 50_000  # 单次 get_text 最大字符数 / Max chars for single get_text


class BrowserSkill:
    """
    浏览器自动化 Skill
    Browser automation skill.

    input:  {"action": str, "url": str, "selector"?: str, "text"?: str, "timeout"?: float}
    output: {"success": bool, "content": str, "action": str, "url": str, "error": str|null}
    """

    skill_id = "browser"
    description = "Automate browser actions (navigate, extract text, click, fill form, screenshot)"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_VALID_ACTIONS),
                "description": "Browser action to perform",
            },
            "url": {
                "type": "string",
                "description": "Target URL (required for all actions)",
            },
            "selector": {
                "type": "string",
                "description": "CSS/XPath selector for click, fill_form, get_text (default: body)",
            },
            "text": {
                "type": "string",
                "description": "Text to type for fill_form action",
            },
            "timeout": {
                "type": "number",
                "default": _DEFAULT_TIMEOUT,
                "description": "Timeout in seconds (max 120)",
            },
        },
        "required": ["action", "url"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "content": {"type": "string"},
            "action": {"type": "string"},
            "url": {"type": "string"},
            "error": {"type": ["string", "null"]},
        },
    }

    async def execute(self, inputs: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        执行浏览器动作（使用 Playwright 异步 API）
        Execute a browser action (uses Playwright async API).
        """
        action = inputs.get("action", "")
        url = inputs.get("url", "").strip()
        selector = inputs.get("selector", "body")
        text = inputs.get("text", "")
        timeout_s = min(float(inputs.get("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)
        timeout_ms = int(timeout_s * 1000)

        if not action or action not in _VALID_ACTIONS:
            raise PluginError(
                f"Invalid action '{action}'. Must be one of: {sorted(_VALID_ACTIONS)}",
                skill_id=self.skill_id,
            )
        if not url:
            raise PluginError("url must not be empty", skill_id=self.skill_id)

        try:
            from playwright.async_api import async_playwright  # noqa: PLC0415
        except ImportError as exc:
            raise PluginError(
                "playwright is not installed. Run: pip install playwright && playwright install chromium",
                skill_id=self.skill_id,
            ) from exc

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    content = await self._run_action(
                        page, action, url, selector, text, timeout_ms
                    )
                finally:
                    await browser.close()
        except PluginError:
            raise
        except Exception as exc:
            raise PluginError(
                f"Browser action '{action}' failed: {exc}",
                skill_id=self.skill_id,
            ) from exc

        return {
            "success": True,
            "content": content,
            "action": action,
            "url": url,
            "error": None,
        }

    async def _run_action(
        self,
        page: Any,
        action: str,
        url: str,
        selector: str,
        text: str,
        timeout_ms: int,
    ) -> str:
        """
        在已打开的 Page 上执行具体动作
        Execute the specific action on an already-opened Page.
        """
        if action == "navigate":
            await page.goto(url, timeout=timeout_ms)
            return page.url

        if action == "get_text":
            await page.goto(url, timeout=timeout_ms)
            content: str = await page.inner_text(selector or "body", timeout=timeout_ms)
            return content[: _MAX_TEXT]

        if action == "click":
            await page.goto(url, timeout=timeout_ms)
            await page.click(selector, timeout=timeout_ms)
            return f"Clicked '{selector}' on {url}"

        if action == "fill_form":
            await page.goto(url, timeout=timeout_ms)
            await page.fill(selector, text, timeout=timeout_ms)
            return f"Filled '{selector}' with text on {url}"

        if action == "screenshot":
            await page.goto(url, timeout=timeout_ms)
            png_bytes: bytes = await page.screenshot()
            return base64.b64encode(png_bytes).decode("ascii")

        raise PluginError(f"Unhandled action '{action}'", skill_id=self.skill_id)
