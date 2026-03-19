"""
导入边界验证测试 — 通过 AST 解析确保各层不越级导入
Import boundary validation — AST-based enforcement of layer dependency rules.

This test runs in CI to catch architectural violations early.
此测试在 CI 中运行，尽早捕获架构违规。

Layer rules / 层级规则:
  Layer 0: shared/     → no internal imports
  Layer 1: gateway/    → may import shared only
  Layer 2: orchestration/ → may import shared only (not concrete providers)
  Layer 3: transformer/   → may import shared only (not providers)
  Layer 4: providers/, plugins/, storage/, scheduler/
                       → may import shared only; providers don't cross-import
  Layer 5: wiring/     → may import anything (it's the DI root)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path setup / 路径配置
# ---------------------------------------------------------------------------

BACKEND_SRC = Path(__file__).parent.parent / "backend" / "src" / "orchestration"


def _collect_python_files(directory: Path) -> list[Path]:
    """递归收集目录下所有 .py 文件，排除 tests/ 子目录和 __pycache__"""
    if not directory.exists():
        return []
    return [
        p for p in directory.rglob("*.py")
        if "tests" not in p.parts and "__pycache__" not in str(p)
    ]


def _extract_imports(filepath: Path) -> list[str]:
    """
    使用 AST 解析提取文件中所有 orchestration.* 内部导入
    Extract all orchestration.* internal imports from a file using AST.
    """
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("orchestration."):
                    imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("orchestration."):
                imports.append(node.module)
    return imports


def _module_layer(module_path: str) -> str:
    """
    从模块路径推断所属层 / Infer the layer from a module path.
    e.g., 'orchestration.shared.types' → 'shared'
    """
    parts = module_path.split(".")
    if len(parts) >= 2:
        return parts[1]  # orchestration.<layer>.*
    return ""


# ---------------------------------------------------------------------------
# Layer 0: shared/ must have zero internal imports
# Layer 0: shared/ 必须零内部导入
# ---------------------------------------------------------------------------


class TestSharedLayerBoundary:
    """shared/ 只能导入标准库和第三方包，不能导入任何 orchestration.* 内部模块"""

    def test_shared_has_no_internal_imports(self) -> None:
        shared_dir = BACKEND_SRC / "shared"
        if not shared_dir.exists():
            pytest.skip("shared/ not yet created")

        violations: list[str] = []
        for filepath in _collect_python_files(shared_dir):
            imports = _extract_imports(filepath)
            # shared/ files may only import from orchestration.shared itself
            for imp in imports:
                layer = _module_layer(imp)
                if layer != "shared":
                    violations.append(f"{filepath.name}: imports {imp}")

        assert not violations, (
            "shared/ (Layer 0) must not import from other layers:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Layer 1: gateway/ may only import shared
# Layer 1: gateway/ 只能导入 shared
# ---------------------------------------------------------------------------


class TestGatewayLayerBoundary:
    """
    gateway/ 只能导入 shared，不能导入 orchestration、transformer、providers 等具体层。
    例外：app.py、deps.py、ws.py 是 DI 接线入口，被允许访问 wiring/storage/orchestration。
    Exception: app.py, deps.py, ws.py are DI wiring entry-points; they may import any layer
    (they ARE the gateway's connection to the DI container — equivalent to wiring code).
    All other gateway files (middleware/, routers/, schemas/) must obey Layer 1 strictly.
    """

    ALLOWED_FROM_GATEWAY = {"shared"}

    # These files are application entry-points that must wire layers together.
    # 这些文件是应用入口，需要接线各层，豁免于 Layer 1 约束。
    _ENTRY_POINTS = frozenset({"app.py", "deps.py", "ws.py"})

    def test_gateway_only_imports_shared(self) -> None:
        gateway_dir = BACKEND_SRC / "gateway"
        if not gateway_dir.exists():
            pytest.skip("gateway/ not yet created")

        violations: list[str] = []
        for filepath in _collect_python_files(gateway_dir):
            # Skip entry-point files — they are the DI wiring layer for the gateway
            # 跳过入口文件 — 它们是 gateway 的 DI 接线层
            if filepath.name in self._ENTRY_POINTS:
                continue
            imports = _extract_imports(filepath)
            for imp in imports:
                layer = _module_layer(imp)
                if layer not in self.ALLOWED_FROM_GATEWAY and layer != "gateway":
                    violations.append(f"{filepath.name}: imports {imp}")

        assert not violations, (
            "gateway/ non-entry-point files (Layer 1) may only import from shared/:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Layer 2: orchestration/ may only import shared (no concrete implementations)
# Layer 2: orchestration/ 只能导入 shared（不知道任何具体实现）
# ---------------------------------------------------------------------------


class TestOrchestrationLayerBoundary:
    """orchestration/ 只能导入 shared，不能直接导入 transformer/providers/plugins 的具体类"""

    ALLOWED_FROM_ORCHESTRATION = {"shared"}

    def test_orchestration_only_imports_shared(self) -> None:
        orch_dir = BACKEND_SRC / "orchestration"
        if not orch_dir.exists():
            pytest.skip("orchestration/ not yet created")

        violations: list[str] = []
        for filepath in _collect_python_files(orch_dir):
            imports = _extract_imports(filepath)
            for imp in imports:
                layer = _module_layer(imp)
                if layer not in self.ALLOWED_FROM_ORCHESTRATION and layer != "orchestration":
                    violations.append(f"{filepath.name}: imports {imp}")

        assert not violations, (
            "orchestration/ (Layer 2) may only import from shared/:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Layer 3: transformer/ may only import shared (not providers)
# Layer 3: transformer/ 只能导入 shared（不知道 providers）
# ---------------------------------------------------------------------------


class TestTransformerLayerBoundary:
    """transformer/ 只能导入 shared，不能导入 providers/"""

    ALLOWED_FROM_TRANSFORMER = {"shared"}

    def test_transformer_only_imports_shared(self) -> None:
        transformer_dir = BACKEND_SRC / "transformer"
        if not transformer_dir.exists():
            pytest.skip("transformer/ not yet created")

        violations: list[str] = []
        for filepath in _collect_python_files(transformer_dir):
            imports = _extract_imports(filepath)
            for imp in imports:
                layer = _module_layer(imp)
                if layer not in self.ALLOWED_FROM_TRANSFORMER and layer != "transformer":
                    violations.append(f"{filepath.name}: imports {imp}")

        assert not violations, (
            "transformer/ (Layer 3) may only import from shared/:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Layer 4: providers/ — each provider must not cross-import other providers
# Layer 4: providers/ — 各 provider 之间绝不互相导入
# ---------------------------------------------------------------------------


class TestProviderCrossImportBoundary:
    """
    providers/ 各 provider 子包之间绝不互相导入
    Providers must be completely independent of each other.
    """

    KNOWN_PROVIDERS = {"anthropic", "openai", "deepseek", "gemini", "jimeng", "kling"}

    def test_providers_do_not_cross_import(self) -> None:
        providers_dir = BACKEND_SRC / "providers"
        if not providers_dir.exists():
            pytest.skip("providers/ not yet created")

        violations: list[str] = []
        for provider_subdir in providers_dir.iterdir():
            if not provider_subdir.is_dir():
                continue
            current_provider = provider_subdir.name
            other_providers = self.KNOWN_PROVIDERS - {current_provider}

            for filepath in _collect_python_files(provider_subdir):
                imports = _extract_imports(filepath)
                for imp in imports:
                    # Check if this import reaches into another provider's subpackage
                    # e.g., orchestration.providers.openai.* from anthropic/
                    imp_parts = imp.split(".")
                    if (
                        len(imp_parts) >= 3
                        and imp_parts[1] == "providers"
                        and imp_parts[2] in other_providers
                    ):
                        violations.append(
                            f"providers/{current_provider}/{filepath.name}: "
                            f"cross-imports {imp}"
                        )

        assert not violations, (
            "providers/ (Layer 4) must not cross-import between providers:\n"
            + "\n".join(violations)
        )

    def test_providers_only_import_shared(self) -> None:
        providers_dir = BACKEND_SRC / "providers"
        if not providers_dir.exists():
            pytest.skip("providers/ not yet created")

        violations: list[str] = []
        for filepath in _collect_python_files(providers_dir):
            imports = _extract_imports(filepath)
            for imp in imports:
                layer = _module_layer(imp)
                if layer not in {"shared", "providers"}:
                    violations.append(f"{filepath.relative_to(providers_dir)}: imports {imp}")

        assert not violations, (
            "providers/ (Layer 4) may only import from shared/:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Layer 4: plugins/ may only import shared
# ---------------------------------------------------------------------------


class TestPluginsLayerBoundary:
    def test_plugins_only_import_shared(self) -> None:
        plugins_dir = BACKEND_SRC / "plugins"
        if not plugins_dir.exists():
            pytest.skip("plugins/ not yet created")

        violations: list[str] = []
        for filepath in _collect_python_files(plugins_dir):
            imports = _extract_imports(filepath)
            for imp in imports:
                layer = _module_layer(imp)
                if layer not in {"shared", "plugins"}:
                    violations.append(f"{filepath.name}: imports {imp}")

        assert not violations, (
            "plugins/ (Layer 4) may only import from shared/:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Layer 4: storage/ may only import shared
# ---------------------------------------------------------------------------


class TestStorageLayerBoundary:
    def test_storage_only_imports_shared(self) -> None:
        storage_dir = BACKEND_SRC / "storage"
        if not storage_dir.exists():
            pytest.skip("storage/ not yet created")

        violations: list[str] = []
        for filepath in _collect_python_files(storage_dir):
            imports = _extract_imports(filepath)
            for imp in imports:
                layer = _module_layer(imp)
                if layer not in {"shared", "storage"}:
                    violations.append(f"{filepath.name}: imports {imp}")

        assert not violations, (
            "storage/ (Layer 4) may only import from shared/:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Layer 5: wiring/ is exempt (it's the DI root, allowed to import everything)
# Layer 5: wiring/ 豁免（DI 根，允许导入所有具体类）
# ---------------------------------------------------------------------------


class TestWiringIsExempt:
    """wiring/ 是系统接线层，允许导入所有具体类，不受约束"""

    def test_wiring_exists_as_exemption_note(self) -> None:
        # This test just documents that wiring/ is intentionally exempt.
        # No violations to check — wiring/ is the only layer allowed to
        # import everything. 此测试仅文档记录 wiring/ 的豁免状态。
        assert True, "wiring/ is intentionally exempt from boundary checks"


# ---------------------------------------------------------------------------
# Smoke test: all current Layer 0 files are importable
# 冒烟测试：确保当前 Layer 0 文件可正常导入
# ---------------------------------------------------------------------------


class TestSharedModulesImportable:
    """确保 shared/ 所有模块可以正常导入，没有语法错误"""

    def test_enums_importable(self) -> None:
        from orchestration.shared import enums  # noqa: F401

    def test_types_importable(self) -> None:
        from orchestration.shared import types  # noqa: F401

    def test_errors_importable(self) -> None:
        from orchestration.shared import errors  # noqa: F401

    def test_protocols_importable(self) -> None:
        from orchestration.shared import protocols  # noqa: F401

    def test_config_importable(self) -> None:
        from orchestration.shared import config  # noqa: F401
