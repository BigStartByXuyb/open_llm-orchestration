"""
JWT 认证中间件
JWT authentication middleware.

Layer 1: Only imports from shared/.

职责 / Responsibilities:
  - 验证 Authorization: Bearer <token> 头
    Validate Authorization: Bearer <token> header
  - 将解码后的 payload 写入 request.state.jwt_payload
    Write decoded payload to request.state.jwt_payload
  - 提取 user_id 和 tenant_id 写入 request.state
    Extract user_id and tenant_id into request.state

跳过路径 / Skipped paths: /health, /docs, /openapi.json
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from orchestration.shared.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Paths that bypass authentication / 跳过认证的路径
_SKIP_PATHS = frozenset({"/health", "/healthz", "/readyz", "/metrics", "/docs", "/openapi.json", "/redoc", "/auth/register"})


class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWT Bearer token 认证中间件
    JWT Bearer token authentication middleware.
    """

    def __init__(self, app: Any, settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or get_settings()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip auth for known public paths
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid Authorization header", "code": "unauthorized"},
            )

        token = auth_header[len("Bearer "):]

        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._settings.JWT_SECRET_KEY,
                algorithms=[self._settings.JWT_ALGORITHM],
            )
        except JWTError as exc:
            logger.debug("JWT decode failed: %s", exc)
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or expired token", "code": "unauthorized"},
            )

        # Write decoded claims to request.state
        # 将解码后的声明写入 request.state
        request.state.jwt_payload = payload
        request.state.user_id = payload.get("sub", "")
        request.state.tenant_id = payload.get("tenant_id", "")

        return await call_next(request)


def create_access_token(
    subject: str,
    tenant_id: str,
    settings: Settings | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    创建 JWT 访问令牌（供测试和认证端点使用）
    Create a JWT access token (for tests and auth endpoints).
    """
    import datetime

    s = settings or get_settings()
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    expire = now + datetime.timedelta(minutes=s.JWT_EXPIRE_MINUTES)

    claims: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": expire,
    }
    if extra_claims:
        claims.update(extra_claims)

    return jwt.encode(claims, s.JWT_SECRET_KEY, algorithm=s.JWT_ALGORITHM)
