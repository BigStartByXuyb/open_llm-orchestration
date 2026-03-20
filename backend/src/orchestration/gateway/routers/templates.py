"""
路由模板管理路由 — GET/POST/PUT/DELETE /templates
Template management router.

Layer 1: Uses deps for all external access.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orchestration.gateway.deps import RunContextDep, TemplateRepoDep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateCapabilities(BaseModel):
    text: str | None = None
    image: str | None = None
    video: str | None = None
    code: str | None = None
    search: str | None = None


class TemplateCreateRequest(BaseModel):
    name: str
    capabilities: dict


class TemplateUpdateRequest(BaseModel):
    name: str
    capabilities: dict


class TemplateResponse(BaseModel):
    id: str
    name: str
    capabilities: dict


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    context: RunContextDep,
    repo: TemplateRepoDep,
) -> list[TemplateResponse]:
    rows = await repo.list_all(context.tenant_id)
    return [TemplateResponse(id=str(r.id), name=r.name, capabilities=r.capabilities) for r in rows]


@router.post("", response_model=TemplateResponse, status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    context: RunContextDep,
    repo: TemplateRepoDep,
) -> TemplateResponse:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty")
    row = await repo.create(
        tenant_id=context.tenant_id,
        name=body.name.strip(),
        capabilities=body.capabilities,
    )
    logger.info("Template created: tenant_id=%s name=%s id=%s", context.tenant_id, row.name, row.id)
    return TemplateResponse(id=str(row.id), name=row.name, capabilities=row.capabilities)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: str,
    body: TemplateUpdateRequest,
    context: RunContextDep,
    repo: TemplateRepoDep,
) -> TemplateResponse:
    try:
        tid = uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid template_id")
    row = await repo.update(
        id=tid,
        tenant_id=context.tenant_id,
        name=body.name.strip(),
        capabilities=body.capabilities,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateResponse(id=str(row.id), name=row.name, capabilities=row.capabilities)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    context: RunContextDep,
    repo: TemplateRepoDep,
) -> None:
    try:
        tid = uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid template_id")
    deleted = await repo.delete(tid, context.tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    logger.info("Template deleted: tenant_id=%s id=%s", context.tenant_id, template_id)
