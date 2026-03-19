"""
TransformerRegistry — 版本化 Transformer 查找注册表
TransformerRegistry — versioned transformer lookup registry.

Layer 3: Only imports from shared/. No knowledge of concrete providers.
第 3 层：仅从 shared/ 导入，不知道具体 provider 实现。

Versioning strategy / 版本化策略:
  - Each provider+version = one entry, keyed by (provider_id, api_version)
    每个 provider+版本 = 一条记录，以 (provider_id, api_version) 为键
  - Deprecating a version: remove its register() call from wiring/container.py
    废弃版本：仅从 wiring/container.py 移除对应的 register() 调用
  - Multiple versions co-exist in the registry simultaneously
    多个版本在注册表中同时共存
"""

from __future__ import annotations

from orchestration.shared.enums import ProviderID
from orchestration.shared.protocols import InstructionTransformer


class TransformerRegistry:
    """
    Transformer 注册表 — 线程安全（asyncio 单线程模型下）
    Transformer registry — thread-safe under asyncio's single-thread model.

    Lifecycle / 生命周期:
      1. Instantiated by wiring/container.py (Layer 5)
         由 wiring/container.py（第 5 层）实例化
      2. All transformers registered via register() at startup
         启动时通过 register() 注册所有 transformer
      3. Injected into OrchestrationEngine via DI
         通过 DI 注入 OrchestrationEngine
    """

    def __init__(self) -> None:
        # Key: (provider_id, api_version), Value: transformer instance
        # 键：(provider_id, api_version)，值：transformer 实例
        self._registry: dict[tuple[ProviderID, str], InstructionTransformer] = {}

    def register(self, transformer: InstructionTransformer) -> None:
        """
        注册一个 Transformer 实例
        Register a transformer instance.

        Overwrites silently if the same (provider_id, api_version) is registered twice.
        同一 (provider_id, api_version) 重复注册时静默覆盖。
        This allows hot-swap in tests. 允许测试中热替换。
        """
        key = (transformer.provider_id, transformer.api_version)
        self._registry[key] = transformer

    def get(self, provider_id: ProviderID, version: str) -> InstructionTransformer:
        """
        按 provider_id + version 查找 Transformer
        Look up transformer by provider_id + version.

        Raises / 抛出:
            KeyError: If no transformer is registered for the given combination.
                     如果指定组合未注册。
        """
        key = (provider_id, version)
        transformer = self._registry.get(key)
        if transformer is None:
            registered = [f"{p}/{v}" for p, v in self._registry]
            raise KeyError(
                f"No transformer registered for {provider_id}/{version}. "
                f"Registered: {registered}"
            )
        return transformer

    def list_versions(self, provider_id: ProviderID) -> list[str]:
        """
        列出指定 provider 的所有已注册版本（按字母顺序）
        List all registered versions for a provider (sorted).
        Returns empty list if provider has no registered transformers.
        如果 provider 无已注册 transformer，返回空列表。
        """
        return sorted(
            version
            for pid, version in self._registry
            if pid == provider_id
        )

    def list_all(self) -> list[tuple[ProviderID, str]]:
        """
        列出所有已注册的 (provider_id, version) 组合
        List all registered (provider_id, version) combinations.
        """
        return list(self._registry.keys())

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:
        entries = ", ".join(f"{p}/{v}" for p, v in self._registry)
        return f"TransformerRegistry([{entries}])"
