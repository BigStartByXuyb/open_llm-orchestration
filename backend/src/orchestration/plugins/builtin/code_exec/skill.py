"""
CodeExecSkill — 内置 Python 代码执行 Skill
CodeExecSkill — Built-in Python code execution skill.

Layer 4: Only imports from shared/ and uses stdlib.

安全说明 / Security notes:
  - 使用 subprocess 隔离执行，避免污染主进程
    Uses subprocess isolation to avoid contaminating the main process
  - 强制超时，默认 10 秒 / Enforced timeout, default 10 seconds
  - 不做沙箱（生产环境应配合 Docker/seccomp）
    No sandboxing (production should combine with Docker/seccomp)
  - 仅执行 Python 代码（sys.executable），不执行 shell 命令
    Only executes Python code (sys.executable), NOT shell commands
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Any

from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext


class CodeExecSkill:
    """
    Python 代码执行 Skill
    Python code execution skill.

    input:  {"code": str, "timeout": float = 10.0}
    output: {"stdout": str, "stderr": str, "exit_code": int, "timed_out": bool}
    """

    skill_id = "code_exec"
    description = "Execute Python code and return stdout/stderr output"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {
                "type": "number",
                "default": 10.0,
                "description": "Execution timeout in seconds",
            },
        },
        "required": ["code"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
            "timed_out": {"type": "boolean"},
        },
    }

    _MAX_TIMEOUT = 60.0   # 硬上限 / Hard cap
    _MAX_OUTPUT = 32_768  # 输出最大字符数 / Max output chars

    def __init__(self, max_timeout: float = _MAX_TIMEOUT) -> None:
        self._max_timeout = max_timeout

    async def execute(self, inputs: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        在子进程中执行 Python 代码（异步，不阻塞事件循环）
        Execute Python code in subprocess (async, does not block event loop).
        """
        code = inputs.get("code", "").strip()
        if not code:
            raise PluginError("code must not be empty", skill_id=self.skill_id)

        timeout = min(float(inputs.get("timeout", 10.0)), self._max_timeout)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, self._run_sync, code, timeout)
        except Exception as exc:
            raise PluginError(f"Code execution failed: {exc}", skill_id=self.skill_id) from exc

        return result

    def _run_sync(self, code: str, timeout: float) -> dict[str, Any]:
        """
        同步执行（在线程池中运行）
        Synchronous execution (runs in thread pool).
        """
        timed_out = False
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = proc.stdout[: self._MAX_OUTPUT]
            stderr = proc.stderr[: self._MAX_OUTPUT]
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            stdout = ""
            stderr = f"Execution timed out after {timeout}s"
            exit_code = -1

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "timed_out": timed_out,
        }
