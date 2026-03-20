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

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

from orchestration.gateway.deps import (
    EmbeddingRepoDep,
    RunContextDep,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DocumentInfo(BaseModel):
    document_id: str
    title: str
    content_type: str
    chunk_count: int
    char_count: int
    created_at: str | None


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


class DocumentUploadResponse(BaseModel):
    document_id: str
    title: str
    chunk_count: int
    message: str


class DocumentDeleteResponse(BaseModel):
    doc_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=201,
)
async def upload_document(
    context: RunContextDep,
    embedding_repo: EmbeddingRepoDep,
    file: UploadFile,
    title: str = Form(...),
) -> DocumentUploadResponse:
    """
    上传文档文件（.txt 等），自动存入向量库
    Upload a document file and store it in the vector store.
    """
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    if not content.strip():
        raise HTTPException(status_code=400, detail="File content must not be empty")

    doc_id = str(uuid.uuid4())
    content_type = file.content_type or "text/plain"
    char_count = len(content)

    await embedding_repo.upsert_document(
        tenant_id=context.tenant_id,
        doc_id=doc_id,
        content=content,
        embedding=[0.0],
        metadata={"title": title, "content_type": content_type, "char_count": char_count},
    )

    logger.info("Document uploaded: doc_id=%s title=%s tenant_id=%s", doc_id, title, context.tenant_id)

    return DocumentUploadResponse(
        document_id=doc_id,
        title=title,
        chunk_count=1,
        message="Document uploaded successfully",
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
        meta: dict[str, Any] = row.doc_metadata or {}
        created = row.created_at.isoformat() if row.created_at else None
        docs.append(DocumentInfo(
            document_id=row.doc_id,
            title=meta.get("title", row.doc_id),
            content_type=meta.get("content_type", "text/plain"),
            chunk_count=1,
            char_count=meta.get("char_count", len(row.content or "")),
            created_at=created,
        ))

    return DocumentListResponse(documents=docs, total=len(docs))


@router.get(
    "/{doc_id}",
    response_model=DocumentInfo,
)
async def get_document(
    doc_id: str,
    context: RunContextDep,
    embedding_repo: EmbeddingRepoDep,
) -> DocumentInfo:
    """
    获取单个文档详情
    Get a single document by ID.
    """
    row = await embedding_repo.get_document(context.tenant_id, doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    meta: dict[str, Any] = row.doc_metadata or {}
    created = row.created_at.isoformat() if row.created_at else None
    return DocumentInfo(
        document_id=row.doc_id,
        title=meta.get("title", row.doc_id),
        content_type=meta.get("content_type", "text/plain"),
        chunk_count=1,
        char_count=meta.get("char_count", len(row.content or "")),
        created_at=created,
    )


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
