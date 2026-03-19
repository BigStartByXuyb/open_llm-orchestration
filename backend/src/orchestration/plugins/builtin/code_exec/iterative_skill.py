"""
CodeIterativeSkill — 自动纠错代码执行 Skill
CodeIterativeSkill — Auto-correcting code execution skill.

Layer 4: Only imports from shared/ and plugins/builtin/code_exec/skill.py.

执行流程 / Execution flow:
  1. 用 CodeExecSkill 执行代码
     Execute code with CodeExecSkill
  2. 若 exit_code != 0 且未达最大轮次，调 LLM 修复代码
     If exit_code != 0 and under max_iterations, call LLM to fix code
  3. 重复直到成功或达到最大轮次
     Repeat until success or max_iterations reached

架构注意 / Architecture note:
  fixer_adapter / fixer_transformer 是 Protocol 类型（shared/protocols.py），
  由 wiring/container.py（Layer 5）注入协调者 LLM 实例。
  fixer_adapter / fixer_transformer are Protocol types (shared/protocols.py),
  injected with the coordinator LLM instance by wiring/container.py (Layer 5).
"""

from __future__ import annotations

import re
from typing import Any

from orchestration.shared.errors import PluginError
from orchestration.shared.enums import Role
from orchestration.shared.protocols import InstructionTransformer, ProviderAdapter
from orchestration.shared.types import CanonicalMessage, RunContext, TextPart
from orchestration.plugins.builtin.code_exec.skill import CodeExecSkill

# Regex to extract fenced code blocks from LLM output
_CODE_FENCE_RE = re.compile(r"```(?:python)?\n?([\s\S]*?)```", re.MULTILINE)

_FIX_PROMPT_TEMPLATE = """\
Fix the following Python code that produced an error.

Code:
```python
{code}
```

Error output:
{error}

Return ONLY the corrected Python code with NO explanation, NO markdown fencing, NO preamble.
"""


def _extract_code(text: str) -> str:
    """
    从 LLM 输出中提取纯代码（去除 markdown 代码块包裹）
    Extract plain code from LLM output (strip markdown code fence if present).
    """
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


class CodeIterativeSkill:
    """
    自动纠错代码执行 Skill
    Auto-correcting code execution skill.

    input:  {
        "code": str,               # 待执行代码 / Code to execute
        "max_iterations": int,     # 最大纠错轮次（默认 3）/ Max fix iterations (default 3)
        "timeout_per_run": float,  # 每次执行超时（秒，默认 10.0）/ Per-run timeout in seconds
    }
    output: {
        "final_code": str,    # 最终（已修正）代码 / Final (corrected) code
        "stdout": str,        # 最后一次成功执行的 stdout / stdout from last execution
        "stderr": str,        # 最后一次执行的 stderr / stderr from last execution
        "iterations": int,    # 实际迭代次数 / Actual iteration count
        "success": bool,      # 是否成功（exit_code == 0）/ Whether succeeded (exit_code == 0)
    }
    """

    skill_id = "code_exec_iterative"
    description = (
        "Execute Python code with automatic LLM-based error correction. "
        "Retries up to max_iterations times if the code fails."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "max_iterations": {
                "type": "integer",
                "default": 3,
                "minimum": 1,
                "maximum": 10,
                "description": "Maximum number of fix-and-retry iterations",
            },
            "timeout_per_run": {
                "type": "number",
                "default": 10.0,
                "description": "Execution timeout per attempt in seconds",
            },
        },
        "required": ["code"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "final_code": {"type": "string"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "iterations": {"type": "integer"},
            "success": {"type": "boolean"},
        },
    }

    def __init__(
        self,
        exec_skill: CodeExecSkill,
        fixer_adapter: ProviderAdapter,
        fixer_transformer: InstructionTransformer,
        coordinator_model: str,
    ) -> None:
        """
        参数 / Parameters:
          exec_skill:          代码执行后端（subprocess 或 Docker）/ Code execution backend
          fixer_adapter:       LLM 适配器（用于生成修复代码）/ LLM adapter for fix generation
          fixer_transformer:   LLM Transformer（构建 API 请求格式）/ LLM transformer for request format
          coordinator_model:   协调者模型 ID（如 'claude-sonnet-4-6'）/ Coordinator model ID
        """
        self._exec_skill = exec_skill
        self._fixer_adapter = fixer_adapter
        self._fixer_transformer = fixer_transformer
        self._coordinator_model = coordinator_model

    async def execute(self, inputs: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        执行代码，若失败则循环调 LLM 修复直到成功或达到最大轮次
        Execute code; on failure, loop calling LLM to fix until success or max_iterations.
        """
        code = inputs.get("code", "").strip()
        if not code:
            raise PluginError("code must not be empty", skill_id=self.skill_id)

        max_iter: int = int(inputs.get("max_iterations", 3))
        timeout: float = float(inputs.get("timeout_per_run", 10.0))

        exec_result: dict[str, Any] = {}

        for iteration in range(1, max_iter + 1):
            exec_result = await self._exec_skill.execute(
                {"code": code, "timeout": timeout}, context
            )

            if exec_result["exit_code"] == 0:
                return {
                    "final_code": code,
                    "stdout": exec_result["stdout"],
                    "stderr": exec_result["stderr"],
                    "iterations": iteration,
                    "success": True,
                }

            # Not the last iteration — ask LLM to fix
            # 未达最大轮次 — 请求 LLM 修复
            if iteration < max_iter:
                code = await self._fix_code(code, exec_result["stderr"], context)

        return {
            "final_code": code,
            "stdout": exec_result.get("stdout", ""),
            "stderr": exec_result.get("stderr", ""),
            "iterations": max_iter,
            "success": False,
        }

    async def _fix_code(self, code: str, error: str, context: RunContext) -> str:
        """
        调 LLM 修复报错代码，返回修复后的纯代码字符串
        Call LLM to fix broken code, return corrected plain code string.
        """
        prompt = _FIX_PROMPT_TEMPLATE.format(code=code, error=error[:2000])
        messages = [
            CanonicalMessage(
                role=Role.USER,
                content=[TextPart(text=prompt)],
            )
        ]
        payload = self._fixer_transformer.transform(messages)
        # Ensure model is set (transformer may not inject it automatically)
        # 确保 model 字段被设置（transformer 可能不自动注入）
        payload = {**payload, "model": self._coordinator_model}

        raw = await self._fixer_adapter.call(payload, context)
        result = self._fixer_transformer.parse_response(raw)

        fixed = _extract_code(result.content)
        return fixed if fixed else code
