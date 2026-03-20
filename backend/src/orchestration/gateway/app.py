"""
FastAPI 应用工厂函数
FastAPI application factory function.

Layer 1: Imports from gateway/ and wiring/ (via bootstrap).

Usage / 使用方式:
  # ASGI entry point / ASGI 入口
  uvicorn orchestration.gateway.app:create_app --factory

  # Programmatic / 程序化
  app = create_app()
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from orchestration.shared.config import Settings, get_settings
from orchestration.wiring.bootstrap import bootstrap, teardown
from orchestration.gateway.middleware.auth import AuthMiddleware
from orchestration.gateway.middleware.rate_limit import RateLimitMiddleware
from orchestration.gateway.middleware.tenant import TenantMiddleware
from orchestration.gateway.middleware.tracing import TracingMiddleware
from orchestration.gateway.routers import tasks, sessions, plugins, ws, webhooks, usage, documents, tenant_keys, auth as auth_router_module, templates as templates_router_module
from orchestration.gateway.middleware.metrics import MetricsMiddleware, metrics_endpoint

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    创建并配置 FastAPI 应用
    Create and configure the FastAPI application.

    Middleware order (LIFO — last added = outermost):
    中间件顺序（后添加 = 最外层）:
      CORSMiddleware → AuthMiddleware → RateLimitMiddleware → TenantMiddleware → routes

    Lifespan:
      startup  — bootstrap AppContainer (DB, Redis, plugins, engine)
      shutdown — teardown AppContainer (close connections)
    """
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """
        FastAPI lifespan context manager — startup / shutdown
        FastAPI lifespan 上下文管理器 — 启动 / 关闭
        """
        container = await bootstrap(s)
        app.state.container = container
        logger.info("Application startup complete")
        try:
            yield
        finally:
            await teardown()
            logger.info("Application shutdown complete")

    app = FastAPI(
        title="LLM Orchestration Platform",
        description="SaaS-grade multi-tenant LLM orchestration platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # -----------------------------------------------------------------------
    # Middleware (added in reverse order of execution)
    # 中间件（按执行顺序反向添加）
    # -----------------------------------------------------------------------

    # Tenant context (innermost — runs last)
    # 租户上下文（最内层 — 最后运行）
    app.add_middleware(TenantMiddleware)

    # Prometheus metrics (just inside tracing — records all request outcomes)
    # Prometheus 指标（TracingMiddleware 内侧 — 记录所有请求结果）
    app.add_middleware(MetricsMiddleware)

    # Rate limiting (before tenant, after auth)
    # 限流（在租户之前，在认证之后）
    app.add_middleware(RateLimitMiddleware, settings=s)

    # Authentication (outermost among custom middleware)
    # 认证（自定义中间件中最外层）
    app.add_middleware(AuthMiddleware, settings=s)

    # Tracing (runs just inside CORS — captures auth outcomes too)
    # 追踪（运行在 CORS 内侧 — 也能捕获认证结果）
    app.add_middleware(TracingMiddleware)

    # CORS (absolute outermost)
    # CORS（绝对最外层）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Routers / 路由
    # -----------------------------------------------------------------------
    app.include_router(auth_router_module.router)
    app.include_router(tasks.router)
    app.include_router(sessions.router)
    app.include_router(plugins.router)
    app.include_router(ws.router)
    app.include_router(webhooks.router)
    app.include_router(usage.router)
    app.include_router(documents.router)
    app.include_router(tenant_keys.router)
    app.include_router(templates_router_module.router)

    # -----------------------------------------------------------------------
    # Prometheus metrics endpoint
    # Prometheus 指标端点
    # -----------------------------------------------------------------------
    @app.get("/metrics", tags=["observability"], include_in_schema=False)
    async def prometheus_metrics() -> Response:
        """
        Prometheus 指标端点（文本格式，供 Prometheus scrape）。
        Prometheus metrics endpoint (text format, for Prometheus scraping).
        跳过认证，仅限内网访问（通过网络策略控制）。
        Auth skipped; restrict to internal network via network policy.
        """
        return metrics_endpoint()

    # -----------------------------------------------------------------------
    # Health / Readiness endpoints
    # 健康检查 / 就绪检查端点
    # -----------------------------------------------------------------------

    @app.get("/health", tags=["health"])
    @app.get("/healthz", tags=["health"])
    async def liveness() -> dict[str, str]:
        """
        Liveness probe — 检查进程存活（跳过认证，不检查依赖）。
        Liveness probe — checks process is alive (auth skipped, no dependency check).
        Used by: Docker HEALTHCHECK, K8s livenessProbe.
        """
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readiness() -> JSONResponse:
        """
        Readiness probe — 检查 DB + Redis 是否可达，不可达时返回 503。
        Readiness probe — checks DB + Redis reachability, returns 503 if unavailable.
        Used by: K8s readinessProbe, load-balancer health check.
        Failing this probe removes the instance from the rotation until it recovers.
        失败时从轮询中摘除该实例，直至恢复。
        """
        container = getattr(app.state, "container", None)
        if container is None:
            return JSONResponse(
                {"status": "starting", "detail": "container not initialized"},
                status_code=503,
            )

        # Sprint 17: detailed per-component health status
        # Sprint 17：每个组件的详细健康状态
        components: dict[str, str] = {}

        # Check PostgreSQL
        try:
            from sqlalchemy import text  # noqa: PLC0415
            async with container.db_session_factory() as db_session:
                await db_session.execute(text("SELECT 1"))
            components["db"] = "ok"
        except Exception as exc:
            components["db"] = f"error: {exc}"

        # Check Redis
        try:
            await container.redis.ping()
            components["redis"] = "ok"
        except Exception as exc:
            components["redis"] = f"error: {exc}"

        # Report executor circuit breaker states (if engine available)
        try:
            executor = getattr(container, "_executor", None)
            if executor is not None and hasattr(executor, "_circuit_breakers"):
                cb_states = {
                    provider: cb.state
                    for provider, cb in executor._circuit_breakers.items()
                }
                components["circuit_breakers"] = cb_states  # type: ignore[assignment]
        except Exception:
            pass

        has_error = any(
            isinstance(v, str) and v.startswith("error:")
            for v in components.values()
        )

        if has_error:
            return JSONResponse(
                {"status": "unavailable", "components": components},
                status_code=503,
            )

        return JSONResponse({"status": "ok", "components": components})

    return app
