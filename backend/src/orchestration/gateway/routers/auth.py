"""
认证路由 — POST /auth/register
Auth router — POST /auth/register.

Layer 1: Uses deps for all external access.

为新租户签发 JWT，无需已有凭证。
Issues a JWT for a new tenant without requiring existing credentials.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from orchestration.gateway.deps import DBSessionDep, ContainerDep
from orchestration.gateway.middleware.auth import create_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str = "default"


class RegisterResponse(BaseModel):
    access_token: str
    tenant_id: str
    token_type: str = "bearer"


@router.post("/register", response_model=RegisterResponse)
async def register(
    body: RegisterRequest,
    db: DBSessionDep,
    container: ContainerDep,
) -> RegisterResponse:
    """
    创建新租户并签发 JWT / Create a new tenant and issue a JWT.

    无需 Authorization header（_SKIP_PATHS 中已豁免）。
    No Authorization header required (path is in _SKIP_PATHS).
    """
    tenant_repo = container.make_tenant_repo(db)
    row = await tenant_repo.create(name=body.name)
    await db.commit()

    tenant_id = str(row.tenant_id)
    token = create_access_token(subject=tenant_id, tenant_id=tenant_id)

    logger.info("New tenant registered: %s (name=%s)", tenant_id, body.name)
    return RegisterResponse(access_token=token, tenant_id=tenant_id)
