"""
插件路由 — GET /plugins, GET /plugins/{plugin_id}/skills
Plugin router — GET /plugins, GET /plugins/{plugin_id}/skills.

Layer 1: Uses deps for all external access.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from orchestration.gateway.deps import ContainerDep
from orchestration.gateway.schemas.task_request import (
    PluginInfo,
    PluginListResponse,
    SkillInfo,
    ErrorResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.get(
    "",
    response_model=PluginListResponse,
)
async def list_plugins(container: ContainerDep) -> PluginListResponse:
    """
    列出所有已加载的插件及其 Skill
    List all loaded plugins and their skills.
    """
    plugin_loader = container.plugin_loader
    plugin_registry = container.plugin_registry

    plugins: list[PluginInfo] = []
    for plugin_id in plugin_loader.loaded_plugin_ids:
        skill_ids = [
            s for s in plugin_registry.list_skills()
            if s.startswith(plugin_id.replace("mcp::", "")) or True
        ]
        # Get skills directly from loader's loaded set
        # 直接从 loader 已加载集合获取技能
        loaded = plugin_loader._loaded  # noqa: SLF001
        plugin_obj = loaded.get(plugin_id)
        skills = [s.skill_id for s in plugin_obj.skills] if plugin_obj else []
        plugins.append(PluginInfo(
            plugin_id=plugin_id,
            version=plugin_obj.version if plugin_obj else "unknown",
            skills=skills,
        ))

    return PluginListResponse(plugins=plugins, total=len(plugins))


@router.get(
    "/{plugin_id}/skills",
    response_model=list[SkillInfo],
    responses={404: {"model": ErrorResponse}},
)
async def list_plugin_skills(
    plugin_id: str,
    container: ContainerDep,
) -> list[SkillInfo]:
    """
    列出指定插件的所有 Skill 详情
    List all skill details for a specific plugin.
    """
    loader = container.plugin_loader
    plugin_obj = loader._loaded.get(plugin_id)  # noqa: SLF001
    if plugin_obj is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    return [
        SkillInfo(
            skill_id=s.skill_id,
            description=s.description,
            input_schema=s.input_schema,
            output_schema=s.output_schema,
        )
        for s in plugin_obj.skills
    ]
