"""
PluginLoader 单元测试
Unit tests for PluginLoader.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestration.shared.errors import PluginError
from orchestration.plugins.loader import PluginLoader, _split_class_path
from orchestration.plugins.registry import PluginRegistry


def make_plugin_mock(plugin_id: str = "test_plugin") -> MagicMock:
    plugin = MagicMock()
    plugin.plugin_id = plugin_id
    plugin.version = "1.0"
    plugin.skills = []
    return plugin


# -----------------------------------------------------------------------
# _split_class_path
# -----------------------------------------------------------------------


class TestSplitClassPath:
    def test_splits_correctly(self) -> None:
        mod, cls = _split_class_path("a.b.c.MyClass")
        assert mod == "a.b.c"
        assert cls == "MyClass"

    def test_no_dot_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid class_path"):
            _split_class_path("NoModule")

    def test_single_separator(self) -> None:
        mod, cls = _split_class_path("mymodule.MyClass")
        assert mod == "mymodule"
        assert cls == "MyClass"


# -----------------------------------------------------------------------
# load_from_module
# -----------------------------------------------------------------------


class TestLoadFromModule:
    def test_load_valid_plugin(self) -> None:
        registry = PluginRegistry()
        loader = PluginLoader(registry)

        plugin = loader.load_from_module(
            "orchestration.plugins.builtin.web_search",
            "WebSearchPlugin",
        )
        assert plugin.plugin_id == "builtin_web_search"
        assert "web_search" in registry.list_skills()

    def test_load_unknown_module_raises(self) -> None:
        loader = PluginLoader(PluginRegistry())
        with pytest.raises(PluginError, match="Cannot import"):
            loader.load_from_module("no.such.module", "SomeClass")

    def test_load_unknown_class_raises(self) -> None:
        loader = PluginLoader(PluginRegistry())
        with pytest.raises(PluginError, match="not found"):
            loader.load_from_module("orchestration.plugins.registry", "NoSuchClass")

    def test_on_load_failure_raises_plugin_error(self) -> None:
        plugin = make_plugin_mock()
        plugin.on_load.side_effect = RuntimeError("init failed")

        loader = PluginLoader(PluginRegistry())
        with pytest.raises(PluginError, match="on_load"):
            loader.load_plugin_instance(plugin)


# -----------------------------------------------------------------------
# load_plugin_instance
# -----------------------------------------------------------------------


class TestLoadPluginInstance:
    def test_registers_in_registry(self) -> None:
        registry = PluginRegistry()
        loader = PluginLoader(registry)

        plugin = make_plugin_mock("ext_plugin")
        skill = MagicMock()
        skill.skill_id = "ext_skill"
        plugin.skills = [skill]

        loader.load_plugin_instance(plugin)
        assert "ext_skill" in registry.list_skills()

    def test_non_protocol_raises(self) -> None:
        loader = PluginLoader(PluginRegistry())
        with pytest.raises(PluginError, match="PluginProtocol"):
            loader.load_plugin_instance("not_a_plugin")  # type: ignore[arg-type]


# -----------------------------------------------------------------------
# load_builtin_plugins (auto-discovery)
# -----------------------------------------------------------------------


class TestLoadBuiltinPlugins:
    def test_loads_three_builtin_plugins(self) -> None:
        """Auto-discovery should find web_search, code_exec, browser manifests."""
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        loaded = loader.load_builtin_plugins()

        plugin_ids = {p.plugin_id for p in loaded}
        assert "builtin_web_search" in plugin_ids
        assert "builtin_code_exec" in plugin_ids
        assert "builtin_browser" in plugin_ids

    def test_bad_manifest_skipped_gracefully(self, tmp_path: Path) -> None:
        """A corrupt plugin.toml in a subdir should be skipped, not crash."""
        bad_dir = tmp_path / "bad_plugin"
        bad_dir.mkdir()
        (bad_dir / "plugin.toml").write_text("[plugin]\n# missing class_path\n")

        registry = PluginRegistry()
        loader = PluginLoader(registry)

        # Patch _BUILTIN_DIR to our tmp directory
        with patch("orchestration.plugins.loader._BUILTIN_DIR", tmp_path):
            loaded = loader.load_builtin_plugins()

        assert loaded == []

    def test_missing_builtin_dir_returns_empty(self, tmp_path: Path) -> None:
        """If the builtin directory doesn't exist, return empty list without crash."""
        non_existent = tmp_path / "no_such_dir"
        registry = PluginRegistry()
        loader = PluginLoader(registry)

        with patch("orchestration.plugins.loader._BUILTIN_DIR", non_existent):
            loaded = loader.load_builtin_plugins()

        assert loaded == []

    def test_manifest_loads_correct_class(self, tmp_path: Path) -> None:
        """A valid plugin.toml pointing at a real class should load successfully."""
        plugin_dir = tmp_path / "web_search_copy"
        plugin_dir.mkdir()
        manifest = textwrap.dedent("""\
            [plugin]
            name       = "Web Search Copy"
            class_path = "orchestration.plugins.builtin.web_search.WebSearchPlugin"
            version    = "1.0.0"
        """)
        (plugin_dir / "plugin.toml").write_text(manifest)

        registry = PluginRegistry()
        loader = PluginLoader(registry)

        with patch("orchestration.plugins.loader._BUILTIN_DIR", tmp_path):
            loaded = loader.load_builtin_plugins()

        assert len(loaded) == 1
        assert loaded[0].plugin_id == "builtin_web_search"


# -----------------------------------------------------------------------
# load_from_entry_points
# -----------------------------------------------------------------------


class TestLoadFromEntryPoints:
    def test_no_entry_points_returns_empty(self) -> None:
        """When no packages declare entry_points, returns empty list."""
        registry = PluginRegistry()
        loader = PluginLoader(registry)

        with patch("importlib.metadata.entry_points", return_value=[]):
            loaded = loader.load_from_entry_points()

        assert loaded == []

    def test_valid_entry_point_loaded(self) -> None:
        """A valid entry_point referencing a real plugin class is loaded."""
        from orchestration.plugins.builtin.web_search import WebSearchPlugin

        mock_ep = MagicMock()
        mock_ep.name = "test_ep"
        mock_ep.value = "orchestration.plugins.builtin.web_search:WebSearchPlugin"
        mock_ep.load.return_value = WebSearchPlugin

        registry = PluginRegistry()
        loader = PluginLoader(registry)

        with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
            loaded = loader.load_from_entry_points()

        assert len(loaded) == 1
        assert loaded[0].plugin_id == "builtin_web_search"

    def test_broken_entry_point_skipped(self) -> None:
        """A failing entry_point is skipped; does not crash the whole startup."""
        mock_ep = MagicMock()
        mock_ep.name = "broken_ep"
        mock_ep.load.side_effect = ImportError("package missing")

        registry = PluginRegistry()
        loader = PluginLoader(registry)

        with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
            loaded = loader.load_from_entry_points()

        assert loaded == []


# -----------------------------------------------------------------------
# Unload
# -----------------------------------------------------------------------


class TestUnload:
    def test_unload_calls_on_unload(self) -> None:
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        plugin = make_plugin_mock("p_to_unload")

        loader.load_plugin_instance(plugin)
        loader.unload("p_to_unload")

        plugin.on_unload.assert_called_once()
        assert "p_to_unload" not in loader.loaded_plugin_ids

    def test_unload_unknown_is_noop(self) -> None:
        loader = PluginLoader(PluginRegistry())
        loader.unload("ghost")  # should not raise

    def test_unload_all(self) -> None:
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        for i in range(3):
            loader.load_plugin_instance(make_plugin_mock(f"p{i}"))

        loader.unload_all()
        assert loader.loaded_plugin_ids == []
