"""
WebSearchSkill 单元测试（respx mock HTTP）
Unit tests for WebSearchSkill (respx mock HTTP).
"""

from __future__ import annotations

import pytest
import respx
import httpx

from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext
from orchestration.plugins.builtin.web_search.skill import WebSearchSkill


_MOCK_URL = "http://mock-search.test/"


@pytest.fixture()
def skill() -> WebSearchSkill:
    return WebSearchSkill(search_base_url=_MOCK_URL)


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


_DDG_RESPONSE = {
    "Heading": "LLM",
    "AbstractText": "Large Language Model",
    "AbstractURL": "https://en.wikipedia.org/wiki/LLM",
    "RelatedTopics": [
        {"Text": "GPT-4 is a large language model", "FirstURL": "https://example.com/gpt4"},
    ],
}


class TestExecute:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_search(self, skill: WebSearchSkill, ctx: RunContext) -> None:
        respx.get(_MOCK_URL).mock(return_value=httpx.Response(200, json=_DDG_RESPONSE))

        result = await skill.execute({"query": "LLM"}, ctx)
        assert result["query"] == "LLM"
        assert isinstance(result["results"], list)
        assert len(result["results"]) >= 1
        assert result["results"][0]["snippet"] == "Large Language Model"

    @pytest.mark.asyncio
    @respx.mock
    async def test_max_results_respected(self, skill: WebSearchSkill, ctx: RunContext) -> None:
        big_response = {
            "AbstractText": "",
            "RelatedTopics": [
                {"Text": f"Topic {i}", "FirstURL": f"https://example.com/{i}"}
                for i in range(10)
            ],
        }
        respx.get(_MOCK_URL).mock(return_value=httpx.Response(200, json=big_response))

        result = await skill.execute({"query": "test", "max_results": 3}, ctx)
        assert len(result["results"]) <= 3

    @pytest.mark.asyncio
    async def test_empty_query_raises(self, skill: WebSearchSkill, ctx: RunContext) -> None:
        with pytest.raises(PluginError, match="query"):
            await skill.execute({"query": ""}, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error_raises_plugin_error(self, skill: WebSearchSkill, ctx: RunContext) -> None:
        respx.get(_MOCK_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(PluginError, match="500"):
            await skill.execute({"query": "test"}, ctx)

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_ddg_response_returns_empty(self, skill: WebSearchSkill, ctx: RunContext) -> None:
        respx.get(_MOCK_URL).mock(return_value=httpx.Response(200, json={}))
        result = await skill.execute({"query": "obscure"}, ctx)
        assert result["results"] == []


class TestSkillMetadata:
    def test_skill_id(self, skill: WebSearchSkill) -> None:
        assert skill.skill_id == "web_search"

    def test_input_schema_has_query(self, skill: WebSearchSkill) -> None:
        assert "query" in skill.input_schema["properties"]
