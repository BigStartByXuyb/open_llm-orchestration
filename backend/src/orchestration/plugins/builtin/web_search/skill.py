"""
WebSearchSkill — 内置 Web 搜索 Skill
WebSearchSkill — Built-in web search skill.

Layer 4: Only imports from shared/ and uses httpx.

实现 shared/protocols.py 中的 SkillProtocol。
Implements SkillProtocol from shared/protocols.py.

配置 / Configuration:
  通过构造函数传入 search_base_url，默认使用 DuckDuckGo JSON API。
  search_base_url passed via constructor, defaults to DuckDuckGo JSON API.
  测试时传入 mock URL 或通过 respx 拦截。
  For tests, pass a mock URL or intercept with respx.
"""

from __future__ import annotations

from typing import Any

import httpx

from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext


class WebSearchSkill:
    """
    Web 搜索 Skill（HTTP GET 请求）
    Web search skill (HTTP GET request).

    input:  {"query": str, "max_results": int = 5}
    output: {"results": [{"title": str, "url": str, "snippet": str}], "query": str}
    """

    skill_id = "web_search"
    description = "Search the web for information using a search API"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "default": 5, "description": "Max results to return"},
        },
        "required": ["query"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                },
            },
            "query": {"type": "string"},
        },
    }

    _DEFAULT_SEARCH_URL = "https://api.duckduckgo.com/"

    def __init__(
        self,
        search_base_url: str = _DEFAULT_SEARCH_URL,
        timeout: float = 10.0,
    ) -> None:
        self._search_base_url = search_base_url
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def execute(self, inputs: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        执行 Web 搜索，返回结果列表
        Execute web search, return results list.
        """
        query = inputs.get("query", "").strip()
        if not query:
            raise PluginError("query must not be empty", skill_id=self.skill_id)

        max_results = int(inputs.get("max_results", 5))

        try:
            response = await self._get_client().get(
                self._search_base_url,
                params={"q": query, "format": "json", "no_redirect": "1"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PluginError(
                f"Search API returned HTTP {exc.response.status_code}",
                skill_id=self.skill_id,
            ) from exc
        except httpx.RequestError as exc:
            raise PluginError(f"Search request failed: {exc}", skill_id=self.skill_id) from exc

        try:
            data = response.json()
        except Exception as exc:
            raise PluginError(f"Failed to parse search response: {exc}", skill_id=self.skill_id) from exc

        # 解析 DuckDuckGo JSON 格式 / Parse DuckDuckGo JSON format
        results = self._parse_ddg_response(data, max_results)

        return {"query": query, "results": results}

    def _parse_ddg_response(self, data: dict[str, Any], max_results: int) -> list[dict[str, Any]]:
        """
        解析 DuckDuckGo JSON 响应为统一格式
        Parse DuckDuckGo JSON response into unified format.
        """
        results: list[dict[str, Any]] = []

        # AbstractText (instant answer)
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", ""),
                "url": data.get("AbstractURL", ""),
                "snippet": data["AbstractText"],
            })

        # RelatedTopics
        for topic in data.get("RelatedTopics", []):
            if len(results) >= max_results:
                break
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:80],
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", ""),
                })

        return results[:max_results]

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
