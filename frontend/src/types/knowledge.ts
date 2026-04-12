// ── Knowledge Base Types ─────────────────────────────────────────

// ── Knowledge Base Summary (list item) ──────────────────────────

export interface KnowledgeBaseSummary {
  id: string;
  name: string;
  description?: string;
  document_count: number;
  chunk_count: number;
  created_at?: string;
  updated_at?: string;
}

// ── Knowledge Base Detail ───────────────────────────────────────

export interface KnowledgeBaseDetail extends KnowledgeBaseSummary {
  documents: KnowledgeDocument[];
}

// ── Knowledge Document ──────────────────────────────────────────

export interface KnowledgeDocument {
  id: string;
  knowledge_base_id: string;
  title: string;
  source?: string;
  source_type?: string;
  content?: string;
  content_preview?: string;
  content_length?: number;
  word_count?: number;
  chunk_count?: number;
  created_at?: string;
  updated_at?: string;
}

// ── Hit Testing ─────────────────────────────────────────────────

export interface HitTestResult {
  document_id: string;
  document_title?: string;
  knowledge_base_name?: string;
  chunk_index: number;
  content: string;
  score: number;
}

// ── Create / Update Requests ────────────────────────────────────

export interface CreateKnowledgeBasePayload {
  name: string;
  description?: string | null;
}

export interface UpdateKnowledgeBasePayload {
  name?: string;
  description?: string | null;
}

export interface CreateDocumentPayload {
  title: string;
  source?: string | null;
  source_type?: string;
  content?: string;
}

export interface UploadDocumentPayload {
  title?: string;
  source?: string;
  file: File;
}

export interface HitTestingPayload {
  knowledge_base_id: string;
  query: string;
  limit?: number;
}
