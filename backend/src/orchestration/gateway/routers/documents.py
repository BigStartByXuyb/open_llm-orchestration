"""
文档摄入路由 — POST /documents, GET /documents, GET /documents/{doc_id}, DELETE /documents/{doc_id}
Document ingestion router.

Layer 1: Uses deps for all external access.
第 1 层：通过 deps 访问所有外部资源。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orchestration.gateway.deps import (
    EmbeddingRepoDep,
    RunContextDep,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class IngestDocumentRequest(BaseModel):
    content: str
    embedding: list[float]
    doc_id: str | None = None
    metadata: dict[str, Any] | None = None


class IngestDocumentResponse(BaseModel):
    doc_id: str
    content_length: int


class DocumentInfo(BaseModel):
    doc_id: str
    content_length: int
    created_at: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


class DocumentDeleteResponse(BaseModel):
    doc_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=IngestDocumentResponse,
    status_code=201,
)
async def ingest_document(
    body: IngestDocumentRequest,
    context: RunContextDep,
    embedding_repo: EmbeddingRepoDep,
) -> IngestDocumentResponse:
    """
    摄入文档（JSON body，含预计算 embedding）
    Ingest a document with a pre-computed embedding vector.
    """
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")
    if not body.embedding:
        raise HTTPException(status_code=400, detail="embedding must not be empty")

    doc_id = body.doc_id or str(uuid.uuid4())

    await embedding_repo.upsert_document(
        tenant_id=context.tenant_id,
        doc_id=doc_id,
        content=body.content,
        embedding=body.embedding,
        metadata=body.metadata or {},
    )

    logger.info("Document ingested: doc_id=%s tenant_id=%s", doc_id, context.tenant_id)

    return IngestDocumentResponse(doc_id=doc_id, content_length=len(body.content))


@router.get(
    "",
    response_model=DocumentListResponse,
)
async def list_documents(
    context: RunContextDep,
    embedding_repo: EmbeddingRepoDep,
) -> DocumentListResponse:
    """
    列出当前租户的所有文档
    List all documents for the current tenant.
    """
    tenant_id = context.tenant_id
    count = await embedding_repo.count(tenant_id)
    if count == 0:
        return DocumentListResponse(documents=[], total=0)

    results = await embedding_repo.search(
        tenant_id=tenant_id,
        query_embedding=[0.0],
        top_k=count,
        min_score=-2.0,
    )

    docs = []
    for row, _ in results:
        created = row.created_at.isoformat() if row.created_at else None
        docs.append(DocumentInfo(
            doc_id=row.doc_id,
            content_length=len(row.content or ""),
            created_at=created,
        ))

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

    logger.info("Document delete: doc_id=%s tenant_id=%s deleted=%s", doc_id, context.tenant_id, deleted)

    return DocumentDeleteResponse(doc_id=doc_id, deleted=deleted)
