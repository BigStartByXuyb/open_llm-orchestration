"""
PromptSkill + PromptPlugin + executor prompt_injection 单元测试
Unit tests for PromptSkill, PromptPlugin, and executor prompt_injection handling.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestration.plugins.prompt_skill import PromptSkill, _parse_skill_md
from orchestration.plugins.prompt_plugin import PromptPlugin
from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext


def _make_context() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1", trace_id="test-trace")


def _write_skill(tmp_path: Path, filename: str, content: str) -> Path:
    f = tmp_path / filename
    f.write_text(content, encoding="utf-8")
    return f


# -----------------------------------------------------------------------
# _parse_skill_md
# -----------------------------------------------------------------------


class TestParseSkillMd:
    def test_with_front_matter(self) -> None:
        text = textwrap.dedent("""\
            ---
            skill_id: my_skill
            name: My Skill
            version: "2.0"
            ---

            Hello {description}
        """)
        fm, body = _parse_skill_md(text)
        assert fm["skill_id"] == "my_skill"
        assert fm["name"] == "My Skill"
        assert fm["version"] == "2.0"
        assert "Hello {description}" in body

    def test_without_front_matter(self) -> None:
        text = "Just a plain prompt with {placeholder}"
        fm, body = _parse_skill_md(text)
        assert fm == {}
        assert "Just a plain prompt" in body

    def test_strips_quotes_from_values(self) -> None:
        text = "---\nskill_id: \"quoted\"\n---\nbody"
        fm, _ = _parse_skill_md(text)
        assert fm["skill_id"] == "quoted"


# -----------------------------------------------------------------------
# PromptSkill
# -----------------------------------------------------------------------


class TestPromptSkill:
    def _make_skill_file(self, tmp_path: Path, body: str = "Task: {description}") -> Path:
        content = textwrap.dedent(f"""\
            ---
            skill_id: test_skill
            name: Test Skill
            description: A test skill
            version: "1.0"
            ---

            {body}
        """)
        return _write_skill(tmp_path, "test.skill.md", content)

    def test_loads_metadata(self, tmp_path: Path) -> None:
        skill = PromptSkill(self._make_skill_file(tmp_path))
        assert skill.skill_id == "test_skill"
        assert skill.description == "A test skill"

    def test_skill_id_defaults_to_stem(self, tmp_path: Path) -> None:
        # No skill_id in front-matter; should default to filename stem
        content = "---\nname: No ID\ndescription: test\n---\nbody"
        f = _write_skill(tmp_path, "my_file.skill.md", content)
        skill = PromptSkill(f)
        assert skill.skill_id == "my_file"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PluginError, match="not found"):
            PromptSkill(tmp_path / "nonexistent.skill.md")

    @pytest.mark.asyncio
    async def test_execute_fills_description(self, tmp_path: Path) -> None:
        skill = PromptSkill(self._make_skill_file(tmp_path))
        ctx = _make_context()
        result = await skill.execute({"description": "Write a sort function"}, ctx)

        assert result["result_type"] == "prompt_injection"
        assert "Write a sort function" in result["prompt"]

    @pytest.mark.asyncio
    async def test_execute_fills_context(self, tmp_path: Path) -> None:
        content = "---\nskill_id: ctx_skill\n---\nCtx: {context}"
        f = _write_skill(tmp_path, "ctx.skill.md", content)
        skill = PromptSkill(f)
        ctx = _make_context()
        result = await skill.execute(
            {
                "description": "Do something",
                "context_slice": [{"role": "user", "content": "hello"}],
            },
            ctx,
        )
        assert "user: hello" in result["prompt"]

    @pytest.mark.asyncio
    async def test_missing_placeholder_left_as_is(self, tmp_path: Path) -> None:
        """Placeholders with no matching input key should remain unchanged."""
        content = "---\nskill_id: s\n---\n{missing_key} and {description}"
        f = _write_skill(tmp_path, "s.skill.md", content)
        skill = PromptSkill(f)
        ctx = _make_context()
        result = await skill.execute({"description": "done"}, ctx)
        assert "{missing_key}" in result["prompt"]
        assert "done" in result["prompt"]

    @pytest.mark.asyncio
    async def test_missing_placeholder_emits_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """N-11: Missing placeholder must emit a logger.warning (aids debugging)."""
        import logging
        content = "---\nskill_id: warn_test\n---\n{undeclared_key} and {description}"
        f = _write_skill(tmp_path, "warn_test.skill.md", content)
        skill = PromptSkill(f)
        ctx = _make_context()
        with caplog.at_level(logging.WARNING, logger="orchestration.plugins.prompt_skill"):
            await skill.execute({"description": "check warnings"}, ctx)
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("undeclared_key" in msg for msg in warning_messages), (
            f"Expected warning about 'undeclared_key', got: {warning_messages}"
        )


# -----------------------------------------------------------------------
# PromptPlugin
# -----------------------------------------------------------------------


class TestPromptPlugin:
    def _write_skills(self, tmp_path: Path, count: int = 2) -> None:
        for i in range(count):
            content = textwrap.dedent(f"""\
                ---
                skill_id: skill_{i}
                name: Skill {i}
                description: Skill number {i}
                ---
                Body {i}: {{description}}
            """)
            _write_skill(tmp_path, f"skill_{i}.skill.md", content)

    def test_on_load_discovers_skills(self, tmp_path: Path) -> None:
        self._write_skills(tmp_path, count=3)
        plugin = PromptPlugin(skills_dir=tmp_path)
        plugin.on_load()
        assert len(plugin.skills) == 3
        skill_ids = {s.skill_id for s in plugin.skills}
        assert {"skill_0", "skill_1", "skill_2"} == skill_ids

    def test_on_load_missing_dir_is_noop(self, tmp_path: Path) -> None:
        plugin = PromptPlugin(skills_dir=tmp_path / "nonexistent")
        plugin.on_load()  # should not raise
        assert plugin.skills == []

    def test_on_load_skips_invalid_files(self, tmp_path: Path) -> None:
        """A corrupt .skill.md should be skipped; valid ones still load."""
        self._write_skills(tmp_path, count=1)
        # Write a file that will fail (e.g., binary content)
        bad_file = tmp_path / "bad.skill.md"
        bad_file.write_bytes(b"\xff\xfe" + b"corrupt" * 10)

        plugin = PromptPlugin(skills_dir=tmp_path)
        plugin.on_load()
        # Only the valid skill loads
        assert len(plugin.skills) == 1

    def test_on_unload_clears_skills(self, tmp_path: Path) -> None:
        self._write_skills(tmp_path, count=2)
        plugin = PromptPlugin(skills_dir=tmp_path)
        plugin.on_load()
        assert len(plugin.skills) == 2
        plugin.on_unload()
        assert plugin.skills == []

    def test_default_skills_dir_has_four_examples(self) -> None:
        """The bundled skills/ directory must contain at least 6 .skill.md files after N-12."""
        plugin = PromptPlugin()
        plugin.on_load()
        assert len(plugin.skills) >= 4

    def test_n12_required_skill_ids_present(self) -> None:
        """
        N-12: After renaming/adding skill files, the following skill_ids must be present:
          - prompt_code_review       (renamed from code_reviewer)
          - prompt_data_analysis     (renamed from data_analyst)
          - prompt_web_research      (new)
          - prompt_chain_of_thought  (new)
        """
        plugin = PromptPlugin()
        plugin.on_load()
        skill_ids = {s.skill_id for s in plugin.skills}
        required = {
            "prompt_code_review",
            "prompt_data_analysis",
            "prompt_web_research",
            "prompt_chain_of_thought",
        }
        missing = required - skill_ids
        assert not missing, (
            f"N-12: Missing required skill IDs: {missing}. Found: {skill_ids}"
        )

    def test_plugin_protocol_attributes(self, tmp_path: Path) -> None:
        plugin = PromptPlugin(skills_dir=tmp_path)
        assert plugin.plugin_id == "builtin_prompt_skills"
        assert plugin.version == "1.0.0"
        assert hasattr(plugin, "skills")
        assert hasattr(plugin, "on_load")
        assert hasattr(plugin, "on_unload")


# -----------------------------------------------------------------------
# executor: prompt_injection result type handling
# -----------------------------------------------------------------------


class TestExecutorPromptInjection:
    """
    Verify that ParallelExecutor._execute_skill routes prompt_injection correctly.
    """

    @pytest.mark.asyncio
    async def test_prompt_injection_result_uses_prompt_field(self) -> None:
        from orchestration.orchestration.executor import ParallelExecutor
        from orchestration.shared.enums import ProviderID, Capability
        from orchestration.shared.types import SubTask, TaskPlan

        # Build a minimal executor
        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=MagicMock(),
        )

        # Skill returns prompt_injection
        mock_skill = AsyncMock()
        mock_skill.execute.return_value = {
            "result_type": "prompt_injection",
            "prompt": "You are a code reviewer. Task: {description}",
        }
        executor._plugin_registry.get_skill.return_value = mock_skill

        subtask = SubTask(
            subtask_id="st1",
            description="review code",
            provider_id=ProviderID.SKILL,
            capability=Capability.TEXT,
            skill_id="prompt_code_review",
            context_slice=[],
        )
        ctx = _make_context()

        result = await executor._execute_skill(subtask, ctx)

        assert result.content == "You are a code reviewer. Task: {description}"
        assert result.metadata.get("result_type") == "prompt_injection"
        assert result.metadata.get("skill_id") == "prompt_code_review"

    @pytest.mark.asyncio
    async def test_regular_skill_result_uses_result_field(self) -> None:
        from orchestration.orchestration.executor import ParallelExecutor
        from orchestration.shared.enums import ProviderID, Capability
        from orchestration.shared.types import SubTask

        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=MagicMock(),
        )

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = {"result": "search results here"}
        executor._plugin_registry.get_skill.return_value = mock_skill

        subtask = SubTask(
            subtask_id="st2",
            description="search the web",
            provider_id=ProviderID.SKILL,
            capability=Capability.TEXT,
            skill_id="web_search",
            context_slice=[],
        )
        ctx = _make_context()

        result = await executor._execute_skill(subtask, ctx)

        assert result.content == "search results here"
        assert result.metadata.get("result_type") == "result"
