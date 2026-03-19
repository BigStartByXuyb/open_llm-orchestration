"""
文档摄入路由 — POST /documents, GET /documents, DELETE /documents/{doc_id}
Document ingestion router — POST /documents, GET /documents, DELETE /documents/{doc_id}.

Layer 1: Uses deps for all external access.
第 1 层：通过 deps 访问所有外部资源。

用途 / Purpose:
  允许外部系统将文本文档（含调用方预计算的向量嵌入）摄入平台的向量存储，
  供 RAG 检索流程使用。
  Allow external systems to ingest text documents (with caller-precomputed embeddings)
  into the platform's vector store for RAG retrieval workflows.

向量嵌入由调用方提供 / Embeddings are provided by the caller:
  平台不内置 embedding 模型 — 调用方使用任意 embedding API（OpenAI、Anthropic 等）
  将文本转为向量，再提交本接口存储。维度须在同一租户内保持一致。
  The platform has no built-in embedding model. Callers use any embedding API
  (OpenAI, Anthropic, etc.) to convert text to vectors before submitting.
  Dimensions must be consistent within a tenant.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orchestration.gateway.deps import (
    EmbeddingRepoDep,
    RunContextDep,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# Request / Response schemas / 请求/响应模型
# ---------------------------------------------------------------------------


class DocumentIngestRequest(BaseModel):
    doc_id: str | None = Field(
        default=None,
        description="文档唯一标识符（省略时自动生成）/ Unique document ID (auto-generated if omitted)",
    )
    content: str = Field(description="文档文本内容 / Document text content")
    embedding: list[float] = Field(
        description="调用方预计算的浮点向量 / Caller-precomputed float vector"
    )
    metadata: dict = Field(
        default_factory=dict,
        description="任意元数据（来源、标签等）/ Arbitrary metadata (source, tags, etc.)",
    )


class DocumentIngestResponse(BaseModel):
    doc_id: str
    tenant_id: str
    content_length: int


class DocumentInfo(BaseModel):
    doc_id: str
    content_preview: str   # first 200 chars
    embedding_dim: int
    metadata: dict


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


class DocumentDeleteResponse(BaseModel):
    doc_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Endpoints / 端点
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=DocumentIngestResponse,
    status_code=201,
    responses={400: {"description": "Invalid request body"}},
)
async def ingest_document(
    body: DocumentIngestRequest,
    context: RunContextDep,
    embedding_repo: EmbeddingRepoDep,
) -> DocumentIngestResponse:
    """
    摄入单个文档（含预计算向量嵌入）
    Ingest a single document with a pre-computed vector embedding.

    doc_id: 省略时自动生成 UUID / Auto-generates a UUID if omitted.
    content: 文档原文，存储后可随搜索结果一起返回 / Raw document text, returned with search results.
    embedding: 浮点向量列表，维度须与该租户已有文档一致 /
               Float vector; dimensionality must be consistent with existing tenant documents.
    """
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")
    if not body.embedding:
        raise HTTPException(status_code=400, detail="embedding must not be empty")

    doc_id = body.doc_id or str(uuid.uuid4())
    row = await embedding_repo.upsert_document(
        tenant_id=context.tenant_id,
        doc_id=doc_id,
        content=body.content,
        embedding=body.embedding,
        metadata=body.metadata,
    )

    logger.info(
        "Document ingested: doc_id=%s tenant_id=%s dim=%d",
        doc_id, context.tenant_id, len(body.embedding),
    )

    return DocumentIngestResponse(
        doc_id=doc_id,
        tenant_id=context.tenant_id,
        content_length=len(body.content),
    )


@router.get(
    "",
    response_model=DocumentListResponse,
)
async def list_documents(
    context: RunContextDep,
    embedding_repo: EmbeddingRepoDep,
) -> DocumentListResponse:
    """
    列出当前租户的所有文档（含内容预览和向量维度）
    List all documents for the current tenant (with content preview and embedding dimension).
    """
    tenant_id = context.tenant_id
    # Reuse the search method with a dummy vector to list all docs
    # (top_k large enough to retrieve all for small datasets)
    # For a proper implementation, a dedicated list() method would be more efficient.
    # Use count() + raw select would be ideal; for now reuse existing repo methods.
    count = await embedding_repo.count(tenant_id)
    if count == 0:
        return DocumentListResponse(documents=[], total=0)

    # Use a zero-vector search to retrieve all docs (min_score=-2.0 passes all)
    # This is acceptable for the list endpoint on small-medium datasets.
    dummy_vector = [0.0]
    results = await embedding_repo.search(
        tenant_id=tenant_id,
        query_embedding=dummy_vector,
        top_k=count,
        min_score=-2.0,
    )

    docs = [
        DocumentInfo(
            doc_id=row.doc_id,
            content_preview=row.content[:200],
            embedding_dim=len(row.embedding) if row.embedding else 0,
            metadata=row.doc_metadata or {},
        )
        for row, _ in results
    ]

    return DocumentListResponse(documents=docs, total=len(docs))


@router.delete(
    "/{doc_id}",
    response_model=DocumentDeleteResponse,
)
async def delete_document(
    doc_id: str,
    context: RunContextDep,
    embedding_repo: EmbeddingRepoDep,
) -> DocumentDeleteResponse:
    """
    删除指定文档（不存在时返回 deleted=false，不报错）
    Delete the specified document (returns deleted=false if not found, no error).
    """
    deleted = await embedding_repo.delete_document(context.tenant_id, doc_id)

    logger.info(
        "Document delete: doc_id=%s tenant_id=%s deleted=%s",
        doc_id, context.tenant_id, deleted,
    )

    return DocumentDeleteResponse(doc_id=doc_id, deleted=deleted)
