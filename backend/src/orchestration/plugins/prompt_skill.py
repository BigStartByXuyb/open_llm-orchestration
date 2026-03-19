"""
PromptSkill — 基于 Markdown 文件的可配置 LLM Prompt 注入 Skill
PromptSkill — configurable LLM prompt-injection skill backed by a .skill.md file.

Layer 4: Only imports from shared/ and stdlib.

功能 / Feature:
  - 解析 .skill.md 文件（YAML-like front-matter + Markdown prompt 模板）
    Parse .skill.md files (YAML-like front-matter + Markdown prompt template)
  - 将 inputs 中的占位符（{description}、{context}）填充到模板
    Fill template placeholders ({description}, {context}) from inputs
  - 返回 result_type="prompt_injection" 标记，供 ParallelExecutor 特殊处理
    Return result_type="prompt_injection" for special handling in ParallelExecutor

.skill.md 文件格式 / file format:
    ---
    skill_id: my_skill
    name: My Skill
    description: What this skill does
    version: "1.0"
    ---

    Prompt template body with {description} and {context} placeholders.
    The body is returned verbatim with placeholders filled.

可用占位符 / Available placeholders:
    {description} — subtask description (from SubTask.description)
    {context}     — joined context_slice as "role: content" lines
    All other keys from inputs are also available. Missing keys are left as-is.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from orchestration.shared.errors import PluginError

logger = logging.getLogger(__name__)
from orchestration.shared.types import RunContext

# ---------------------------------------------------------------------------
# Front-matter parsing helpers
# ---------------------------------------------------------------------------

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)
_KV_LINE_RE = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)


def _parse_skill_md(text: str) -> tuple[dict[str, str], str]:
    """
    从 .skill.md 文本解析 front-matter 和 prompt 模板。
    Parse front-matter and prompt template body from .skill.md text.

    Returns:
        (front_matter_dict, body_text)
        If no front-matter found, returns ({}, full_text).
    """
    match = _FRONT_MATTER_RE.match(text.lstrip())
    if not match:
        return {}, text.strip()

    fm_raw, body = match.group(1), match.group(2)
    # Parse key: value lines (strips surrounding quotes from values)
    fm: dict[str, str] = {
        k: v.strip().strip("\"'")
        for k, v in _KV_LINE_RE.findall(fm_raw)
    }
    return fm, body.strip()


class _SafeFormatMap(dict):  # type: ignore[type-arg]
    """
    dict 子类：missing key 时返回 '{key}' 原样，防止 KeyError。
    dict subclass: returns '{key}' literally for missing keys to avoid KeyError.
    """

    def __missing__(self, key: str) -> str:
        logger.warning("PromptSkill: placeholder '{%s}' not provided, left as-is", key)
        return "{" + key + "}"


# ---------------------------------------------------------------------------
# PromptSkill
# ---------------------------------------------------------------------------


class PromptSkill:
    """
    基于 .skill.md 文件的 Prompt 注入 Skill。
    Prompt-injection skill backed by a .skill.md file.

    执行时将 prompt 模板填充后作为 prompt_injection 结果返回，
    供 ParallelExecutor 或 Aggregator 后续注入 LLM 调用。
    At execution time, fills the prompt template and returns it as a
    prompt_injection result for downstream LLM injection.
    """

    def __init__(self, skill_file: Path) -> None:
        """
        从 .skill.md 文件构建 PromptSkill。
        Build a PromptSkill from a .skill.md file.

        Raises:
            PluginError: if file cannot be read or front-matter is invalid.
        """
        if not skill_file.exists():
            raise PluginError(f"Skill file not found: {skill_file}")

        try:
            raw_text = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"Cannot read skill file '{skill_file}': {exc}") from exc

        front_matter, self._template = _parse_skill_md(raw_text)

        # Strip ".skill.md" double-extension to get the bare stem.
        # e.g. "code_reviewer.skill.md" → stem "code_reviewer.skill" → bare "code_reviewer"
        bare_stem = skill_file.stem.removesuffix(".skill")
        self.skill_id: str = front_matter.get("skill_id", bare_stem)
        self.description: str = front_matter.get(
            "description", f"Prompt skill loaded from {skill_file.name}"
        )
        self._name: str = front_matter.get("name", self.skill_id)
        self._version: str = front_matter.get("version", "1.0")
        self._file: Path = skill_file

        if not self.skill_id:
            raise PluginError(f"skill_id must not be empty in '{skill_file}'")

    # ----------------------------------------------------------------
    # SkillProtocol implementation
    # ----------------------------------------------------------------

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "context_slice": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "required": ["description"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "result_type": {"type": "string", "const": "prompt_injection"},
                "prompt": {"type": "string"},
            },
        }

    async def execute(
        self,
        inputs: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        """
        填充 prompt 模板，返回 prompt_injection 类型结果。
        Fill the prompt template and return a prompt_injection result.

        Placeholders / 可用占位符:
            {description} — subtask description
            {context}     — context_slice formatted as "role: content" lines
            {skill_id}    — this skill's ID
            {name}        — this skill's name
            Any other key from inputs dict.

        Returns:
            {"result_type": "prompt_injection", "prompt": "<filled_template>"}
        """
        # Format context_slice as readable text
        # 将 context_slice 格式化为可读文本
        context_slice = inputs.get("context_slice", [])
        if isinstance(context_slice, list):
            context_lines: list[str] = []
            for item in context_slice:
                if isinstance(item, dict):
                    role = item.get("role", "")
                    content = item.get("content", item.get("char_count", ""))
                    context_lines.append(f"{role}: {content}")
            context_text = "\n".join(context_lines)
        else:
            context_text = str(context_slice)

        # Build format mapping: inputs + convenience keys + safe fallback
        # 构建格式化映射：inputs + 便捷键 + 安全回退
        fmt: dict[str, Any] = _SafeFormatMap({
            **inputs,
            "context": context_text,
            "skill_id": self.skill_id,
            "name": self._name,
        })

        try:
            filled = self._template.format_map(fmt)
        except (KeyError, ValueError) as exc:
            raise PluginError(
                f"PromptSkill '{self.skill_id}': template fill failed: {exc}",
                skill_id=self.skill_id,
            ) from exc

        return {
            "result_type": "prompt_injection",
            "prompt": filled,
        }

    def __repr__(self) -> str:
        return f"PromptSkill(skill_id={self.skill_id!r}, file={self._file.name!r})"
