"""
CodeExec 内置插件包
CodeExec built-in plugin package.
"""

from __future__ import annotations

from orchestration.shared.protocols import SkillProtocol
from orchestration.plugins.builtin.code_exec.skill import CodeExecSkill


class CodeExecPlugin:
    """
    CodeExec 插件 — 将 CodeExecSkill 包装为 PluginProtocol
    CodeExec plugin — wraps CodeExecSkill as PluginProtocol.
    """

    plugin_id = "builtin_code_exec"
    version = "1.0.0"

    def __init__(self) -> None:
        self._skill = CodeExecSkill()
        self.skills: list[SkillProtocol] = [self._skill]  # type: ignore[list-item]

    def on_load(self) -> None:
        pass

    def on_unload(self) -> None:
        pass
