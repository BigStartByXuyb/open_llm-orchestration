"""
CodeIterativeSkill 单元测试
Unit tests for CodeIterativeSkill.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestration.shared.errors import PluginError
from orchestration.shared.types import ProviderResult, RunContext
from orchestration.shared.enums import ProviderID
from orchestration.plugins.builtin.code_exec.iterative_skill import (
    CodeIterativeSkill,
    _extract_code,
)
from orchestration.plugins.builtin.code_exec.skill import CodeExecSkill


# ---------------------------------------------------------------------------
# Helpers / 辅助函数
# ---------------------------------------------------------------------------


def _make_context() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


def _make_exec_result(exit_code: int, stdout: str = "", stderr: str = "") -> dict:
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": False,
    }


def _make_provider_result(content: str) -> ProviderResult:
    return ProviderResult(
        subtask_id="fix",
        provider_id=ProviderID.ANTHROPIC,
        content=content,
        tokens_used=100,
    )


def _make_skill(
    exec_results: list[dict],
    fix_content: str = "print('fixed')",
) -> CodeIterativeSkill:
    """Build a CodeIterativeSkill with mocked exec + fixer."""
    exec_skill = MagicMock(spec=CodeExecSkill)
    exec_skill.execute = AsyncMock(side_effect=exec_results)

    fixer_adapter = AsyncMock()
    fixer_adapter.call = AsyncMock(return_value={})

    fixer_transformer = MagicMock()
    fixer_transformer.transform = MagicMock(return_value={"messages": []})
    fixer_transformer.parse_response = MagicMock(
        return_value=_make_provider_result(fix_content)
    )

    return CodeIterativeSkill(
        exec_skill=exec_skill,
        fixer_adapter=fixer_adapter,
        fixer_transformer=fixer_transformer,
        coordinator_model="claude-sonnet-4-6",
    )


# ---------------------------------------------------------------------------
# Tests: _extract_code helper
# ---------------------------------------------------------------------------


class TestExtractCode:
    def test_plain_code_unchanged(self) -> None:
        code = "print('hello')"
        assert _extract_code(code) == code

    def test_strips_python_fence(self) -> None:
        text = "```python\nprint('hello')\n```"
        assert _extract_code(text) == "print('hello')"

    def test_strips_generic_fence(self) -> None:
        text = "```\nprint('hello')\n```"
        assert _extract_code(text) == "print('hello')"

    def test_extracts_first_block(self) -> None:
        text = "Here is the fix:\n```python\nx = 1\nprint(x)\n```\n"
        assert _extract_code(text) == "x = 1\nprint(x)"

    def test_strips_whitespace(self) -> None:
        assert _extract_code("   print('hi')   ") == "print('hi')"


# ---------------------------------------------------------------------------
# Tests: CodeIterativeSkill.execute
# ---------------------------------------------------------------------------


class TestExecuteSuccess:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self) -> None:
        skill = _make_skill(exec_results=[_make_exec_result(0, stdout="ok")])
        result = await skill.execute({"code": "print('ok')"}, _make_context())

        assert result["success"] is True
        assert result["iterations"] == 1
        assert result["stdout"] == "ok"
        assert result["final_code"] == "print('ok')"

    @pytest.mark.asyncio
    async def test_success_on_second_try(self) -> None:
        skill = _make_skill(
            exec_results=[
                _make_exec_result(1, stderr="NameError: name 'x' is not defined"),
                _make_exec_result(0, stdout="fixed"),
            ],
            fix_content="x = 1\nprint(x)",
        )
        result = await skill.execute(
            {"code": "print(x)", "max_iterations": 3}, _make_context()
        )

        assert result["success"] is True
        assert result["iterations"] == 2
        assert result["final_code"] == "x = 1\nprint(x)"

    @pytest.mark.asyncio
    async def test_success_on_third_try(self) -> None:
        skill = _make_skill(
            exec_results=[
                _make_exec_result(1, stderr="err1"),
                _make_exec_result(1, stderr="err2"),
                _make_exec_result(0, stdout="done"),
            ],
        )
        result = await skill.execute(
            {"code": "bad()", "max_iterations": 3}, _make_context()
        )

        assert result["success"] is True
        assert result["iterations"] == 3


class TestExecuteFailure:
    @pytest.mark.asyncio
    async def test_failure_after_max_iterations(self) -> None:
        skill = _make_skill(
            exec_results=[
                _make_exec_result(1, stderr="err"),
                _make_exec_result(1, stderr="err"),
                _make_exec_result(1, stderr="err"),
            ],
        )
        result = await skill.execute(
            {"code": "bad()", "max_iterations": 3}, _make_context()
        )

        assert result["success"] is False
        assert result["iterations"] == 3

    @pytest.mark.asyncio
    async def test_max_iterations_one_no_fix_called(self) -> None:
        skill = _make_skill(
            exec_results=[_make_exec_result(1, stderr="err")],
        )
        result = await skill.execute(
            {"code": "bad()", "max_iterations": 1}, _make_context()
        )

        assert result["success"] is False
        assert result["iterations"] == 1
        # fixer_adapter should NOT have been called (no fix attempt when max_iter=1)
        skill._fixer_adapter.call.assert_not_awaited()  # type: ignore[attr-defined]


class TestExecuteValidation:
    @pytest.mark.asyncio
    async def test_empty_code_raises(self) -> None:
        skill = _make_skill(exec_results=[])
        with pytest.raises(PluginError, match="code"):
            await skill.execute({"code": ""}, _make_context())

    @pytest.mark.asyncio
    async def test_whitespace_code_raises(self) -> None:
        skill = _make_skill(exec_results=[])
        with pytest.raises(PluginError, match="code"):
            await skill.execute({"code": "   "}, _make_context())


class TestFixerIntegration:
    @pytest.mark.asyncio
    async def test_fixer_transformer_receives_model(self) -> None:
        """确保 _fix_code 将 coordinator_model 注入 payload / Verify coordinator_model injected."""
        exec_skill = MagicMock(spec=CodeExecSkill)
        exec_skill.execute = AsyncMock(
            side_effect=[
                _make_exec_result(1, stderr="err"),
                _make_exec_result(0),
            ]
        )
        fixer_adapter = AsyncMock()
        captured_payload: dict = {}

        async def _capture_call(payload: dict, context):  # type: ignore[type-arg]
            nonlocal captured_payload
            captured_payload = payload
            return {}

        fixer_adapter.call = _capture_call
        fixer_transformer = MagicMock()
        fixer_transformer.transform = MagicMock(return_value={"messages": []})
        fixer_transformer.parse_response = MagicMock(
            return_value=_make_provider_result("print('ok')")
        )

        skill = CodeIterativeSkill(
            exec_skill=exec_skill,
            fixer_adapter=fixer_adapter,
            fixer_transformer=fixer_transformer,
            coordinator_model="claude-opus-4-6",
        )
        await skill.execute({"code": "bad()", "max_iterations": 2}, _make_context())

        assert captured_payload.get("model") == "claude-opus-4-6"


class TestSkillMetadata:
    def test_skill_id(self) -> None:
        skill = _make_skill(exec_results=[])
        assert skill.skill_id == "code_exec_iterative"

    def test_input_schema_has_required_fields(self) -> None:
        skill = _make_skill(exec_results=[])
        assert "code" in skill.input_schema["properties"]
        assert "max_iterations" in skill.input_schema["properties"]
        assert "timeout_per_run" in skill.input_schema["properties"]

    def test_output_schema_has_all_fields(self) -> None:
        skill = _make_skill(exec_results=[])
        for field in ("final_code", "stdout", "stderr", "iterations", "success"):
            assert field in skill.output_schema["properties"]
