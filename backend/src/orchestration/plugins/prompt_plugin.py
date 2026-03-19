"""
PromptPlugin — 自动扫描目录中的 .skill.md 文件并批量注册为 PromptSkill
PromptPlugin — auto-scans a directory for .skill.md files and registers them as PromptSkills.

Layer 4: Only imports from shared/ and plugins/prompt_skill.py.

功能 / Feature:
  - 扫描指定目录（默认 plugins/skills/）中所有 *.skill.md 文件
    Scan a directory (default: plugins/skills/) for all *.skill.md files
  - 为每个文件构建一个 PromptSkill 并作为 PluginProtocol 整体对外暴露
    Build a PromptSkill per file and expose them as a group via PluginProtocol
  - 加载失败的 skill 文件以 WARNING 跳过，不影响其他文件
    Failed skill files are skipped with a WARNING, leaving others unaffected

用法 / Usage:
    # Default: scans <plugins_package>/skills/
    plugin = PromptPlugin()

    # Custom directory:
    plugin = PromptPlugin(skills_dir="/path/to/my/skills")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from orchestration.plugins.prompt_skill import PromptSkill

logger = logging.getLogger(__name__)

# Default skills directory: plugins/skills/ relative to this file
# 默认 skills 目录：相对于本文件的 plugins/skills/
_DEFAULT_SKILLS_DIR = Path(__file__).parent / "skills"


class PromptPlugin:
    """
    Prompt Skill 插件 — 批量管理 .skill.md 文件
    Prompt skill plugin — manages a collection of .skill.md files.

    实现 PluginProtocol（duck-typing）。
    Implements PluginProtocol (duck-typing).
    """

    plugin_id = "builtin_prompt_skills"
    version = "1.0.0"

    def __init__(self, skills_dir: str | Path | None = None) -> None:
        """
        初始化 PromptPlugin。
        Initialize PromptPlugin.

        skills_dir: 扫描 .skill.md 文件的目录。None → 使用默认目录（plugins/skills/）。
                    Directory to scan. None → use default (plugins/skills/).
        """
        self._skills_dir: Path = (
            Path(skills_dir) if skills_dir is not None else _DEFAULT_SKILLS_DIR
        )
        self.skills: list[Any] = []  # populated in on_load()

    def on_load(self) -> None:
        """
        扫描 skills_dir，为每个 .skill.md 文件创建 PromptSkill。
        Scan skills_dir and create PromptSkill for each .skill.md file.

        跳过无效文件（仅记录 WARNING）。
        Skips invalid files (logs WARNING only).
        """
        self.skills = []

        if not self._skills_dir.is_dir():
            logger.info(
                "PromptPlugin: skills directory not found (%s) — no prompt skills loaded",
                self._skills_dir,
            )
            return

        for skill_file in sorted(self._skills_dir.glob("*.skill.md")):
            try:
                skill = PromptSkill(skill_file)
                self.skills.append(skill)
                logger.info(
                    "PromptSkill loaded: %s (from %s)", skill.skill_id, skill_file.name
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load PromptSkill from '%s': %s — skipping",
                    skill_file, exc,
                )

        logger.info(
            "PromptPlugin: loaded %d prompt skill(s) from '%s'",
            len(self.skills),
            self._skills_dir,
        )

    def on_unload(self) -> None:
        """清理 skills 列表 / Clear skills list."""
        self.skills = []

    def __repr__(self) -> str:
        return (
            f"PromptPlugin(skills_dir={self._skills_dir!r}, "
            f"skills={[s.skill_id for s in self.skills]})"
        )
