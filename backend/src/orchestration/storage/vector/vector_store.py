"""
EmbeddingRepository — 文档向量嵌入仓库（RAG 支持）
EmbeddingRepository — document vector embedding repository (RAG support).

Layer 4: Only imports from shared/ and storage/postgres/.
第 4 层：只导入 shared/ 和 storage/postgres/。

职责 / Responsibilities:
  - 存储文档的文本内容和向量嵌入（upsert 语义）
    Store document text content and vector embeddings (upsert semantics)
  - 余弦相似度搜索：给定查询向量，返回最相似的 Top-K 文档
    Cosine similarity search: given a query vector, return top-K most similar documents
  - 按 tenant_id 完全隔离（配合 RLS 双重保障）
    Full isolation by tenant_id (combined with RLS for defense in depth)

生产环境升级路径 / Production upgrade path:
  当前实现在 Python 中计算余弦相似度（全表扫描）。
  Current implementation computes cosine similarity in Python (full table scan).
  生产环境可将 embedding 列改为 pgvector VECTOR 类型，并启用 IVFFlat/HNSW 索引，
  无需修改接口。
  In production, migrate the embedding column to pgvector VECTOR type and enable
  IVFFlat/HNSW index without changing this interface.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestration.storage.postgres.models import DocumentEmbeddingRow, PGVECTOR_AVAILABLE


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    计算两个向量的余弦相似度
    Compute cosine similarity between two vectors.

    返回值范围 [−1, 1]；向量为零时返回 0.0。
    Return range [−1, 1]; returns 0.0 for zero vectors.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingRepository:
    """
    文档向量嵌入仓库 — 每次请求新建实例（session 由调用方注入）
    Document embedding repository — new instance per request (session injected by caller).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_document(
        self,
        tenant_id: Any,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict | None = None,
    ) -> DocumentEmbeddingRow:
        """
        插入或更新文档向量（已存在则更新内容和向量）
        Insert or update a document embedding (update content and vector if exists).

        doc_id: 调用方提供的文档标识符，同一租户内唯一
                Caller-provided document identifier, unique within a tenant.
        embedding: 向量浮点列表（维度由调用方决定，须一致）
                   Float vector list (dimensionality decided by caller, must be consistent).
        """
        stmt = select(DocumentEmbeddingRow).where(
            DocumentEmbeddingRow.tenant_id == tenant_id,
            DocumentEmbeddingRow.doc_id == doc_id,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is not None:
            row.content = content
            row.embedding = list(embedding)
            row.doc_metadata = metadata or {}
        else:
            row = DocumentEmbeddingRow(
                tenant_id=tenant_id,
                doc_id=doc_id,
                content=content,
                embedding=list(embedding),
                doc_metadata=metadata or {},
            )
            self._session.add(row)

        await self._session.flush()
        return row

    async def search(
        self,
        tenant_id: Any,
        query_embedding: list[float],
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[tuple[DocumentEmbeddingRow, float]]:
        """
        余弦相似度向量搜索，返回按相似度降序排列的 Top-K 文档
        Cosine similarity vector search, returning top-K documents in descending score order.

        min_score: 最低相似度阈值（含），低于此值的结果被过滤
                   Minimum similarity threshold (inclusive); results below this are filtered out.

        当 pgvector 可用时使用 HNSW 索引加速（<= 运算符）；否则退回到 Python 全表扫描。
        Uses pgvector HNSW index when available (<=> operator); falls back to Python full scan.
        """
        if PGVECTOR_AVAILABLE:
            try:
                return await self._search_pgvector(tenant_id, query_embedding, top_k, min_score)
            except Exception:
                pass  # fall through to Python fallback
        return await self._search_python(tenant_id, query_embedding, top_k, min_score)

    async def _search_pgvector(
        self,
        tenant_id: Any,
        query_embedding: list[float],
        top_k: int,
        min_score: float,
    ) -> list[tuple[DocumentEmbeddingRow, float]]:
        """
        使用 pgvector <=> 运算符（余弦距离）的 ANN 向量搜索
        ANN vector search using pgvector <=> operator (cosine distance).

        余弦相似度 = 1 - 余弦距离（<=> 返回余弦距离）。
        Cosine similarity = 1 - cosine distance (<=> returns cosine distance).
        """
        vec_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
        sql = text("""
            SELECT id, tenant_id, doc_id, content, metadata, created_at,
                   1.0 - (embedding <=> CAST(:qvec AS vector)) AS score
            FROM document_embeddings
            WHERE tenant_id = CAST(:tid AS uuid)
              AND 1.0 - (embedding <=> CAST(:qvec AS vector)) >= :min_score
            ORDER BY embedding <=> CAST(:qvec AS vector)
            LIMIT :lim
        """)
        result = await self._session.execute(sql, {
            "qvec": vec_literal,
            "tid": str(tenant_id),
            "min_score": min_score,
            "lim": top_k,
        })
        rows_raw = result.mappings().all()

        output: list[tuple[DocumentEmbeddingRow, float]] = []
        for r in rows_raw:
            row = DocumentEmbeddingRow()
            row.id = r["id"]
            row.tenant_id = r["tenant_id"]
            row.doc_id = r["doc_id"]
            row.content = r["content"]
            row.doc_metadata = r.get("metadata") or {}
            row.created_at = r["created_at"]
            row.embedding = []
            output.append((row, float(r["score"])))
        return output

    async def _search_python(
        self,
        tenant_id: Any,
        query_embedding: list[float],
        top_k: int,
        min_score: float,
    ) -> list[tuple[DocumentEmbeddingRow, float]]:
        """
        Python 全表扫描余弦相似度搜索（无 pgvector 时的兜底实现）
        Python full-table-scan cosine similarity search (fallback when pgvector unavailable).

        适合中小型数据集（< 10k 文档）。
        Suitable for small-medium datasets (< 10k documents).
        """
        stmt = select(DocumentEmbeddingRow).where(
            DocumentEmbeddingRow.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())

        scored: list[tuple[DocumentEmbeddingRow, float]] = []
        for row in rows:
            score = _cosine_similarity(query_embedding, list(row.embedding))
            if score >= min_score:
                scored.append((row, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    async def delete_document(
        self,
        tenant_id: Any,
        doc_id: str,
    ) -> bool:
        """
        删除文档（不存在时返回 False）
        Delete a document (returns False if not found).
        """
        stmt = delete(DocumentEmbeddingRow).where(
            DocumentEmbeddingRow.tenant_id == tenant_id,
            DocumentEmbeddingRow.doc_id == doc_id,
        )
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0

    async def get_document(
        self,
        tenant_id: Any,
        doc_id: str,
    ) -> DocumentEmbeddingRow | None:
        """
        按 doc_id 获取单个文档（含向量）
        Get a single document by doc_id (including embedding).
        """
        stmt = select(DocumentEmbeddingRow).where(
            DocumentEmbeddingRow.tenant_id == tenant_id,
            DocumentEmbeddingRow.doc_id == doc_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count(self, tenant_id: Any) -> int:
        """
        返回租户的文档总数
        Return total document count for a tenant.
        """
        stmt = select(DocumentEmbeddingRow).where(
            DocumentEmbeddingRow.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        return len(result.scalars().all())

    async def retrieve_relevant(
        self,
        tenant_id: Any,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[str, str]]:
        """
        按文本关键词检索相关文档（大小写不敏感 ILIKE 匹配），实现 DocumentRetrieverProtocol
        Retrieve relevant documents by text keyword (case-insensitive ILIKE), implements
        DocumentRetrieverProtocol.

        返回 (doc_id, content) 元组列表，按创建时间降序
        Returns (doc_id, content) tuples ordered by creation time (newest first).
        """
        if not query or not query.strip():
            return []
        stmt = (
            select(DocumentEmbeddingRow)
            .where(
                DocumentEmbeddingRow.tenant_id == tenant_id,
                DocumentEmbeddingRow.content.ilike(f"%{query.strip()}%"),
            )
            .order_by(DocumentEmbeddingRow.created_at.desc())
            .limit(top_k)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        return [(row.doc_id, row.content) for row in rows]


class RAGRetriever:
    """
    工厂模式 RAG 检索器 — 持有 session_factory，按需创建 DB session 执行检索
    Factory-pattern RAG retriever — holds session_factory, creates DB session on demand.

    用于 OrchestrationEngine 中跨越多个 DB 事务的 RAG 检索。
    Used in OrchestrationEngine for RAG retrieval spanning multiple DB transactions.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def retrieve_relevant(
        self,
        tenant_id: Any,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[str, str]]:
        """
        按文本关键词检索相关文档（每次调用创建独立 DB session）
        Retrieve relevant documents by keyword (creates an independent DB session per call).
        """
        async with self._factory() as session:
            repo = EmbeddingRepository(session)
            return await repo.retrieve_relevant(tenant_id, query, top_k)
