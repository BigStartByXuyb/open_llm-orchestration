"""
OpenTelemetry TracerProvider 初始化
OpenTelemetry TracerProvider initialization.

Layer 5: May import from all layers.

调用时机 / When to call:
  在 bootstrap.startup() 之前（bootstrap() 函数最开始）调用一次。
  Call once at the start of bootstrap() before container.startup().

导出策略 / Export policy:
  - OTEL_EXPORTER_OTLP_ENDPOINT 已配置
      → 尝试使用 OTLP HTTP 导出器（需安装 opentelemetry-exporter-otlp-proto-http）
      → Try OTLP HTTP exporter (requires opentelemetry-exporter-otlp-proto-http)
  - OTEL_EXPORTER_OTLP_ENDPOINT 未配置
      → 不导出（TracerProvider 仍然可用，trace_id 正常生成）
      → No export (TracerProvider still works, trace_id generation unaffected)
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from orchestration.shared.config import Settings

logger = logging.getLogger(__name__)


def configure_tracing(settings: Settings) -> None:
    """
    初始化全局 OpenTelemetry TracerProvider
    Initialize the global OpenTelemetry TracerProvider.

    幂等：重复调用会覆盖已有的全局 provider（测试中安全）。
    Idempotent: repeated calls override the existing global provider (safe in tests).
    """
    resource = Resource.create(
        {
            "service.name": "llm-orchestration",
            "service.version": "0.1.0",
        }
    )

    provider = TracerProvider(resource=resource)

    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        try:
            # Conditional import — package is optional
            # 条件导入 — 此包是可选依赖
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import]
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(
                "OTel OTLP exporter configured: %s",
                settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            )
        except ImportError:
            logger.warning(
                "opentelemetry-exporter-otlp-proto-http not installed; "
                "falling back to ConsoleSpanExporter. "
                "Install with: pip install opentelemetry-exporter-otlp-proto-http"
            )
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        # No span processor → spans created but silently dropped (no export overhead)
        # 无 span processor → span 创建但静默丢弃（无导出开销）
        logger.debug(
            "OTel: OTEL_EXPORTER_OTLP_ENDPOINT not set; spans will not be exported"
        )

    trace.set_tracer_provider(provider)
    logger.info("OpenTelemetry TracerProvider initialized (service=llm-orchestration)")
