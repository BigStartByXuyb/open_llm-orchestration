"""Initial schema — all 6 tables + RLS policies

初始 Schema 迁移 — 包含 6 张表及 RLS 策略。
Creates: tenants, sessions, tasks, usage_records, document_embeddings, tenant_api_keys
RLS:     sessions, tasks, usage_records, document_embeddings, tenant_api_keys

Revision ID: 0001
Revises: (none — initial migration)
Create Date: 2026-03-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----------------------------------------------------------------
    # tenants — 租户主表（无 RLS）
    # ----------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ----------------------------------------------------------------
    # sessions — 对话会话（RLS）
    # ----------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "messages",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])
    op.create_index(
        "ix_sessions_tenant_updated", "sessions", ["tenant_id", "updated_at"]
    )

    # ----------------------------------------------------------------
    # tasks — 任务记录（RLS）
    # ----------------------------------------------------------------
    op.create_table(
        "tasks",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column(
            "input_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("task_plan", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_tasks_tenant_id", "tasks", ["tenant_id"])
    op.create_index("ix_tasks_session_id", "tasks", ["session_id"])
    op.create_index("ix_tasks_tenant_status", "tasks", ["tenant_id", "status"])
    op.create_index("ix_tasks_tenant_session", "tasks", ["tenant_id", "session_id"])

    # ----------------------------------------------------------------
    # usage_records — 用量计费（RLS）
    # ----------------------------------------------------------------
    op.create_table(
        "usage_records",
        sa.Column("record_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_id", sa.String(50), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_usage_records_tenant_id", "usage_records", ["tenant_id"])
    op.create_index("ix_usage_records_task_id", "usage_records", ["task_id"])
    op.create_index(
        "ix_usage_records_tenant_created", "usage_records", ["tenant_id", "created_at"]
    )
    op.create_index(
        "ix_usage_records_tenant_provider",
        "usage_records",
        ["tenant_id", "provider_id"],
    )

    # ----------------------------------------------------------------
    # document_embeddings — 向量嵌入（RLS）
    # ----------------------------------------------------------------
    op.create_table(
        "document_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_id", sa.String(256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.ARRAY(sa.Float()), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "doc_id", name="uq_document_embeddings_tenant_doc"
        ),
    )
    op.create_index(
        "ix_document_embeddings_tenant", "document_embeddings", ["tenant_id"]
    )

    # ----------------------------------------------------------------
    # tenant_api_keys — 租户 API 密钥（RLS）
    # ----------------------------------------------------------------
    op.create_table(
        "tenant_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("api_key", sa.String(1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "provider_id", name="uq_tenant_api_keys"),
    )
    op.create_index("ix_tenant_api_keys_tenant_id", "tenant_api_keys", ["tenant_id"])

    # ----------------------------------------------------------------
    # RLS policies
    # PostgreSQL 行级安全策略 / Row-Level Security policies
    # ----------------------------------------------------------------
    conn = op.get_bind()
    rls_statements = [
        # sessions
        "ALTER TABLE sessions ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE sessions FORCE ROW LEVEL SECURITY",
        "CREATE POLICY deny_by_default ON sessions USING (false)",
        (
            "CREATE POLICY tenant_isolation ON sessions "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        ),
        # tasks
        "ALTER TABLE tasks ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE tasks FORCE ROW LEVEL SECURITY",
        "CREATE POLICY deny_by_default ON tasks USING (false)",
        (
            "CREATE POLICY tenant_isolation ON tasks "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        ),
        # usage_records
        "ALTER TABLE usage_records ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE usage_records FORCE ROW LEVEL SECURITY",
        "CREATE POLICY deny_by_default ON usage_records USING (false)",
        (
            "CREATE POLICY tenant_isolation ON usage_records "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        ),
        # document_embeddings
        "ALTER TABLE document_embeddings ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE document_embeddings FORCE ROW LEVEL SECURITY",
        "CREATE POLICY deny_by_default ON document_embeddings USING (false)",
        (
            "CREATE POLICY tenant_isolation ON document_embeddings "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        ),
        # tenant_api_keys
        "ALTER TABLE tenant_api_keys ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE tenant_api_keys FORCE ROW LEVEL SECURITY",
        "CREATE POLICY deny_by_default ON tenant_api_keys USING (false)",
        (
            "CREATE POLICY tenant_isolation ON tenant_api_keys "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        ),
    ]
    for stmt in rls_statements:
        conn.execute(sa.text(stmt))


def downgrade() -> None:
    # Remove tables in reverse dependency order.
    # 按反向依赖顺序删除表。
    op.drop_table("tenant_api_keys")
    op.drop_table("document_embeddings")
    op.drop_table("usage_records")
    op.drop_table("tasks")
    op.drop_table("sessions")
    op.drop_table("tenants")
