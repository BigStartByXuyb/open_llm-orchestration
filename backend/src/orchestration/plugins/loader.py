"""
PluginLoader — 插件动态加载器
PluginLoader — Dynamic plugin loader.

Layer 4: Only imports from shared/ and plugins/registry.py.

职责 / Responsibilities:
  - 通过 importlib 从模块路径加载 Python 插件类
    Load Python plugin classes from module paths via importlib
  - 扫描 builtin/ 子目录中的 plugin.toml manifest 自动发现并加载内置插件
    Auto-discover and load built-in plugins by scanning plugin.toml manifests
  - 支持通过 Python entry_points 接入外部包插件
    Support external-package plugins via Python entry_points
  - 校验插件实现了 PluginProtocol
    Validate plugins implement PluginProtocol
  - 调用插件生命周期钩子（on_load / on_unload）
    Call plugin lifecycle hooks (on_load / on_unload)
  - 提供 load_plugin_instance() 供外部注入预构建插件（MCP 插件由 wiring 层构建后注入）
    Provide load_plugin_instance() for externally-built plugins (MCP plugins built in wiring layer)

plugin.toml schema / manifest 格式:
    [plugin]
    name       = "My Plugin"
    class_path = "my.module.path.MyPluginClass"   # full dotted path
    version    = "1.0.0"
    description = "..."

entry_points:
    External packages expose plugins via:
        [project.entry-points."orchestration.plugins"]
        my_plugin = "my.module.path:MyPluginClass"

MCP 支持 / MCP support:
  MCP 插件（MCPPlugin）在 wiring/container.py（Layer 5）中构建后，
  通过 load_plugin_instance() 注入，保持本模块对 mcp/ 的零依赖。
  MCP plugins (MCPPlugin) are built in wiring/container.py (Layer 5) and
  injected via load_plugin_instance(), keeping this module zero-dependency on mcp/.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import tomllib
from pathlib import Path

from orchestration.shared.errors import PluginError
from orchestration.shared.protocols import PluginProtocol
from orchestration.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

# Path to the builtin plugins directory, relative to this file.
# builtin 插件目录路径（相对于本文件）。
_BUILTIN_DIR = Path(__file__).parent / "builtin"

# Entry-point group name for external package plugins.
# 外部包插件的 entry_points 组名。
_ENTRY_POINT_GROUP = "orchestration.plugins"


def _split_class_path(class_path: str) -> tuple[str, str]:
    """
    将 "a.b.c.ClassName" 拆分为 ("a.b.c", "ClassName")。
    Split "a.b.c.ClassName" into ("a.b.c", "ClassName").

    Raises ValueError if class_path has no dot (invalid).
    """
    if "." not in class_path:
        raise ValueError(f"Invalid class_path (no module separator): '{class_path}'")
    module_path, _, class_name = class_path.rpartition(".")
    return module_path, class_name


class PluginLoader:
    """
    插件加载器 — 动态加载并注册插件
    Plugin loader — dynamically loads and registers plugins.
    """

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry
        self._loaded: dict[str, PluginProtocol] = {}  # plugin_id → instance

    # ------------------------------------------------------------------
    # Auto-discovery / 自动发现
    # ------------------------------------------------------------------

    def load_builtin_plugins(self) -> list[PluginProtocol]:
        """
        扫描 builtin/ 下所有子目录的 plugin.toml，自动加载插件。
        Scan all subdirectories of builtin/ for plugin.toml and auto-load.

        每个含有 plugin.toml 的子目录都会被尝试加载；加载失败只记录
        WARNING，不中断整个启动流程（防止单插件故障影响全局）。
        Each subdir with a plugin.toml is attempted; failures are logged as
        WARNING without aborting startup (single-plugin fault isolation).

        Returns:
            List of successfully loaded plugin instances.
        """
        loaded: list[PluginProtocol] = []

        if not _BUILTIN_DIR.is_dir():
            logger.warning("builtin plugin directory not found: %s", _BUILTIN_DIR)
            return loaded

        for subdir in sorted(_BUILTIN_DIR.iterdir()):
            manifest_path = subdir / "plugin.toml"
            if not subdir.is_dir() or not manifest_path.exists():
                continue
            try:
                plugin = self._load_from_manifest(manifest_path)
                loaded.append(plugin)
            except Exception as exc:
                logger.warning(
                    "Failed to auto-load plugin from '%s': %s — skipping",
                    manifest_path, exc,
                )

        logger.info(
            "Auto-loaded %d builtin plugin(s): %s",
            len(loaded),
            [p.plugin_id for p in loaded],
        )
        return loaded

    def load_from_entry_points(self) -> list[PluginProtocol]:
        """
        通过 Python entry_points 加载外部包插件。
        Load external-package plugins via Python entry_points.

        External packages must declare:
            [project.entry-points."orchestration.plugins"]
            my_plugin = "my.module:MyPluginClass"

        Returns:
            List of successfully loaded plugin instances.
        """
        loaded: list[PluginProtocol] = []
        eps = importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP)

        for ep in eps:
            try:
                cls = ep.load()
                instance = cls()
                self.load_plugin_instance(instance)
                loaded.append(instance)
                logger.info("entry_point plugin loaded: %s → %s", ep.name, ep.value)
            except Exception as exc:
                logger.warning(
                    "Failed to load entry_point plugin '%s': %s — skipping",
                    ep.name, exc,
                )

        return loaded

    # ------------------------------------------------------------------
    # Single-plugin loading
    # ------------------------------------------------------------------

    def _load_from_manifest(self, manifest_path: Path) -> PluginProtocol:
        """
        从单个 plugin.toml manifest 文件加载插件。
        Load a plugin from a single plugin.toml manifest file.

        Raises:
            PluginError | ValueError | ImportError: on any failure.
        """
        with manifest_path.open("rb") as fh:
            data = tomllib.load(fh)

        plugin_section = data.get("plugin")
        if not isinstance(plugin_section, dict):
            raise ValueError(f"manifest missing [plugin] section: {manifest_path}")

        class_path = plugin_section.get("class_path", "")
        if not class_path:
            raise ValueError(f"manifest missing 'class_path': {manifest_path}")

        module_path, class_name = _split_class_path(class_path)
        return self.load_from_module(module_path, class_name)

    def load_from_module(self, module_path: str, class_name: str) -> PluginProtocol:
        """
        从 Python 模块路径加载插件类并实例化注册
        Load a plugin class from a Python module path, instantiate, and register.

        Args / 参数:
            module_path: 模块路径，如 "orchestration.plugins.builtin.web_search"
            class_name:  插件类名，如 "WebSearchPlugin"

        Raises / 抛出:
            PluginError: 类不存在、不满足 PluginProtocol 或 on_load 失败
        """
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise PluginError(f"Cannot import module '{module_path}': {exc}") from exc

        cls = getattr(module, class_name, None)
        if cls is None:
            raise PluginError(f"Class '{class_name}' not found in module '{module_path}'")

        try:
            instance = cls()
        except Exception as exc:
            raise PluginError(f"Failed to instantiate '{class_name}': {exc}") from exc

        return self.load_plugin_instance(instance)

    def load_plugin_instance(self, plugin: PluginProtocol) -> PluginProtocol:
        """
        注册预构建的插件实例（适用于 MCP 插件、内置插件等）
        Register a pre-built plugin instance (for MCP plugins, built-ins, etc.).

        调用 on_load()，然后注册到 PluginRegistry。
        Calls on_load(), then registers with PluginRegistry.

        Raises / 抛出:
            PluginError: on_load() 失败
        """
        # Duck-typing check: avoid runtime Protocol isinstance issues in Python 3.12+
        # where non-method attribute checks on @runtime_checkable Protocols were changed.
        _required = ("plugin_id", "version", "skills", "on_load", "on_unload")
        _missing = [a for a in _required if not hasattr(plugin, a)]
        if _missing:
            raise PluginError(
                f"Object of type {type(plugin).__name__} does not implement PluginProtocol "
                f"(missing: {', '.join(_missing)})"
            )

        try:
            plugin.on_load()
        except Exception as exc:
            raise PluginError(
                f"Plugin '{plugin.plugin_id}' on_load() failed: {exc}",
                skill_id=plugin.plugin_id,
            ) from exc

        self._registry.register_plugin(plugin)
        self._loaded[plugin.plugin_id] = plugin
        logger.info("Plugin loaded: %s (v%s, skills=%s)", plugin.plugin_id, plugin.version,
                    [s.skill_id for s in plugin.skills])
        return plugin

    # ------------------------------------------------------------------
    # Unload
    # ------------------------------------------------------------------

    def unload(self, plugin_id: str) -> None:
        """
        卸载插件：调用 on_unload()，从注册表移除
        Unload plugin: call on_unload(), remove from registry.
        """
        plugin = self._loaded.pop(plugin_id, None)
        if plugin is None:
            logger.warning("Attempted to unload unknown plugin: %s", plugin_id)
            return
        try:
            plugin.on_unload()
        except Exception as exc:
            logger.warning("Plugin '%s' on_unload() raised: %s", plugin_id, exc)
        self._registry.unregister_plugin(plugin_id)
        logger.info("Plugin unloaded: %s", plugin_id)

    def unload_all(self) -> None:
        """卸载所有插件 / Unload all plugins."""
        for plugin_id in list(self._loaded.keys()):
            self.unload(plugin_id)

    @property
    def loaded_plugin_ids(self) -> list[str]:
        """已加载插件 ID 列表 / List of loaded plugin IDs."""
        return list(self._loaded.keys())
