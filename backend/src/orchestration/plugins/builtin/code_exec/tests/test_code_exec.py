"""
CodeExecSkill 单元测试
Unit tests for CodeExecSkill.
"""

from __future__ import annotations

import pytest

from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext
from orchestration.plugins.builtin.code_exec.skill import CodeExecSkill


@pytest.fixture()
def skill() -> CodeExecSkill:
    return CodeExecSkill()


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


class TestExecute:
    @pytest.mark.asyncio
    async def test_prints_hello_world(self, skill: CodeExecSkill, ctx: RunContext) -> None:
        result = await skill.execute({"code": "print('hello world')"}, ctx)
        assert result["stdout"].strip() == "hello world"
        assert result["exit_code"] == 0
        assert result["timed_out"] is False

    @pytest.mark.asyncio
    async def test_captures_stderr(self, skill: CodeExecSkill, ctx: RunContext) -> None:
        result = await skill.execute({"code": "import sys; sys.stderr.write('err')"}, ctx)
        assert "err" in result["stderr"]

    @pytest.mark.asyncio
    async def test_nonzero_exit_on_error(self, skill: CodeExecSkill, ctx: RunContext) -> None:
        result = await skill.execute({"code": "raise ValueError('oops')"}, ctx)
        assert result["exit_code"] != 0
        assert "ValueError" in result["stderr"]

    @pytest.mark.asyncio
    async def test_timeout(self, ctx: RunContext) -> None:
        short_skill = CodeExecSkill(max_timeout=5.0)
        result = await short_skill.execute(
            {"code": "import time; time.sleep(30)", "timeout": 0.2}, ctx
        )
        assert result["timed_out"] is True
        assert result["exit_code"] == -1

    @pytest.mark.asyncio
    async def test_max_timeout_cap(self, ctx: RunContext) -> None:
        """请求的 timeout 超过上限时，应被截断到 max_timeout。"""
        small_skill = CodeExecSkill(max_timeout=1.0)
        # 请求 999 秒，但上限 1 秒；代码立即结束所以不会超时
        result = await small_skill.execute(
            {"code": "print('fast')", "timeout": 999}, ctx
        )
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_empty_code_raises(self, skill: CodeExecSkill, ctx: RunContext) -> None:
        with pytest.raises(PluginError, match="code"):
            await skill.execute({"code": ""}, ctx)

    @pytest.mark.asyncio
    async def test_multi_line_code(self, skill: CodeExecSkill, ctx: RunContext) -> None:
        code = "x = 1 + 1\nprint(f'result={x}')"
        result = await skill.execute({"code": code}, ctx)
        assert "result=2" in result["stdout"]


class TestSkillMetadata:
    def test_skill_id(self, skill: CodeExecSkill) -> None:
        assert skill.skill_id == "code_exec"

    def test_input_schema_has_code(self, skill: CodeExecSkill) -> None:
        assert "code" in skill.input_schema["properties"]
