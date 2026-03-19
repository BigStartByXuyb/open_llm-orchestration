"""
0002_pgvector_embedding

Migrate document_embeddings.embedding from ARRAY(Float) to pgvector VECTOR(1536),
and create an HNSW index for ANN search.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str = "0001"
branch_labels = None
depends_on = None

# Embedding dimension (must match EMBEDDING_DIM in models.py)
EMBEDDING_DIM: int = 1536


def upgrade() -> None:
    conn = op.get_bind()

    # Enable pgvector extension (idempotent)
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # Change embedding column type from float[] to vector(1536)
    # The USING clause converts existing float[] data to the vector type.
    conn.execute(sa.text(
        f"ALTER TABLE document_embeddings "
        f"ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM}) "
        f"USING embedding::text::vector({EMBEDDING_DIM})"
    ))

    # Create HNSW index for fast approximate nearest-neighbor search
    # m=16: max connections per layer; ef_construction=128: build quality vs speed trade-off
    conn.execute(sa.text(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_document_embeddings_embedding_hnsw "
        "ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    ))


def downgrade() -> None:
    conn = op.get_bind()

    # Drop HNSW index first
    conn.execute(sa.text(
        "DROP INDEX IF EXISTS ix_document_embeddings_embedding_hnsw"
    ))

    # Revert embedding column back to float[]
    conn.execute(sa.text(
        "ALTER TABLE document_embeddings "
        "ALTER COLUMN embedding TYPE float[] "
        "USING embedding::text::float[]"
    ))

    # Note: We intentionally do NOT drop the vector extension on downgrade,
    # as other tables or users may depend on it.
