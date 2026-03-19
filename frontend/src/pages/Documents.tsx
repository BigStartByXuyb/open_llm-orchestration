import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useT } from "../hooks/useT";
import type { DocumentInfo, DocumentListResponse, DocumentUploadResponse } from "../types/api";

// ---------------------------------------------------------------------------
// Document list item
// ---------------------------------------------------------------------------

function DocumentCard({
  doc,
  onDelete,
}: {
  doc: DocumentInfo;
  onDelete: (id: string) => void;
}) {
  const t = useT();
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!confirm(t("docs.confirm_delete"))) return;
    setDeleting(true);
    try {
      await api.delete(`/documents/${doc.document_id}`);
      onDelete(doc.document_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      alert(t("docs.delete_failed") + ": " + msg);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="px-4 py-3 rounded-xl border border-bg-border bg-bg-surface flex items-start justify-between gap-4">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-text-primary truncate">{doc.title}</p>
        <p className="text-xs text-text-secondary mt-0.5">
          {doc.chunk_count} {t("docs.chunks")} · {(doc.char_count / 1000).toFixed(1)}k{" "}
          {t("docs.chars")}
          {doc.content_type && (
            <span className="ml-2 bg-bg-elevated rounded px-1.5 py-0.5 text-text-tertiary">
              {doc.content_type}
            </span>
          )}
        </p>
        {doc.created_at && (
          <p className="text-xs text-text-tertiary mt-1">
            {new Date(doc.created_at).toLocaleString()}
          </p>
        )}
      </div>
      <button
        onClick={handleDelete}
        disabled={deleting}
        className="shrink-0 text-xs text-red-400 hover:text-red-300 disabled:opacity-50 transition-colors"
        aria-label={t("docs.delete")}
      >
        {deleting ? t("docs.deleting") : t("docs.delete")}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload dropzone
// ---------------------------------------------------------------------------

function UploadZone({ onUploaded }: { onUploaded: (doc: DocumentInfo) => void }) {
  const t = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const upload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError(null);
      try {
        const form = new FormData();
        form.append("file", file);
        form.append("title", file.name);
        const resp = await api.postForm<DocumentUploadResponse>("/documents", form);
        // Refresh the uploaded doc info
        const info = await api.get<DocumentInfo>(`/documents/${resp.document_id}`);
        onUploaded(info);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
      } finally {
        setUploading(false);
      }
    },
    [onUploaded]
  );

  const handleFiles = (files: FileList | null) => {
    if (!files?.length) return;
    upload(files[0]);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        handleFiles(e.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer border-2 border-dashed rounded-xl p-8 flex flex-col items-center gap-2 transition-colors ${
        dragOver
          ? "border-primary bg-primary/5"
          : "border-bg-border hover:border-primary/50"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept=".txt,.md,.pdf,.docx,.html"
        onChange={(e) => handleFiles(e.target.files)}
      />
      {uploading ? (
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      ) : (
        <svg
          className="w-8 h-8 text-text-tertiary"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
          />
        </svg>
      )}
      <p className="text-sm text-text-secondary text-center">
        {uploading ? t("docs.uploading") : t("docs.drop_hint")}
      </p>
      {error && <p className="text-xs text-red-400 text-center">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Documents page
// ---------------------------------------------------------------------------

export function Documents() {
  const t = useT();
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<DocumentListResponse>("/documents")
      .then((r) => setDocs(r.documents))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleUploaded = (doc: DocumentInfo) => {
    setDocs((prev) => [doc, ...prev]);
  };

  const handleDelete = (id: string) => {
    setDocs((prev) => prev.filter((d) => d.document_id !== id));
  };

  return (
    <div className="flex flex-col flex-1 px-6 py-6 gap-5 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">{t("docs.title")}</h1>
        <span className="text-sm text-text-tertiary">
          {docs.length} {t("docs.count")}
        </span>
      </div>

      <UploadZone onUploaded={handleUploaded} />

      {loading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-bg-elevated rounded-xl animate-pulse" />
          ))}
        </div>
      )}

      {error && (
        <div className="px-4 py-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          {error}
        </div>
      )}

      {!loading && docs.length === 0 && !error && (
        <p className="text-sm text-text-tertiary text-center py-8">{t("docs.empty")}</p>
      )}

      <div className="flex flex-col gap-3">
        {docs.map((doc) => (
          <DocumentCard key={doc.document_id} doc={doc} onDelete={handleDelete} />
        ))}
      </div>
    </div>
  );
}
