from __future__ import annotations

import json
import math
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Integer, String, Text, create_engine, delete, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import load_project_env


_DASHSCOPE_API_V1_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
_DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-api/v1"
_DASHSCOPE_MULTIMODAL_EMBEDDING_MODEL_PREFIXES = (
    "tongyi-embedding-vision",
    "multimodal-embedding",
    "qwen3-vl-embedding",
)
_DASHSCOPE_NATIVE_RERANK_MODEL_PREFIXES = ("qwen3-vl-rerank", "gte-rerank")
_DASHSCOPE_COMPATIBLE_RERANK_MODEL_PREFIXES = ("qwen3-rerank",)
_MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_VULN_SECTION_PREFIXES = (
    "漏洞",
    "漏洞点",
    "漏洞成因",
    "根因",
    "触发条件",
    "利用条件",
    "影响范围",
    "影响",
    "复现",
    "验证",
    "证据",
    "修复",
    "缓解",
    "检测",
    "排查",
    "误报",
    "建议",
    "风险",
    "cwe",
    "cvss",
    "finding",
    "root cause",
    "trigger",
    "impact",
    "reproduce",
    "evidence",
    "fix",
    "mitigation",
    "detection",
)


@dataclass(slots=True)
class KnowledgeEmbeddingConfig:
    enabled: bool
    provider: str
    model_name: str
    api_key: str
    base_url: str
    timeout: float
    batch_size: int
    dimensions: int | None


@dataclass(slots=True)
class KnowledgeRerankConfig:
    enabled: bool
    provider: str
    model_name: str
    api_key: str
    base_url: str
    timeout: float
    max_input_chars: int


@dataclass(slots=True)
class KnowledgeChunkingConfig:
    max_chars: int
    overlap_chars: int
    min_chars: int


@dataclass(slots=True)
class KnowledgeChunkCandidate:
    chunk_id: str
    text: str


@dataclass(slots=True)
class KnowledgeSearchCandidate:
    score: float
    lexical_score: float
    vector_score: float
    knowledge_base_id: str
    knowledge_base_name: str
    document_id: str
    document_title: str
    chunk_id: str
    chunk_index: int
    content: str


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in {None, ""}:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _parse_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in {None, ""}:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _normalize_base_url(raw_url: str | None, *, default: str | None = None) -> str:
    return str(raw_url or default or "").strip().rstrip("/")


def _join_endpoint(base_url: str, suffix: str) -> str:
    normalized_suffix = str(suffix or "").lstrip("/")
    if base_url.endswith(normalized_suffix):
        return base_url
    return f"{base_url}/{normalized_suffix}"


def _request_headers(api_key: str | None, *, base_url: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    normalized_key = str(api_key or ("EMPTY" if base_url else ""))
    if normalized_key:
        headers["Authorization"] = f"Bearer {normalized_key}"
    return headers


def _batched(items: Sequence[str], batch_size: int) -> Iterable[list[str]]:
    step = max(1, int(batch_size or 1))
    for index in range(0, len(items), step):
        yield list(items[index : index + step])


def _model_matches(model_name: str | None, prefixes: Sequence[str]) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    return any(normalized.startswith(str(prefix).strip().lower()) for prefix in prefixes)


def _coerce_float_list(raw: Any) -> list[float]:
    if isinstance(raw, dict):
        for key in ("embedding", "vector", "dense", "values"):
            if key in raw:
                return _coerce_float_list(raw.get(key))
        return []
    if not isinstance(raw, (list, tuple)):
        return []
    values: list[float] = []
    for item in raw:
        try:
            values.append(float(item))
        except Exception:
            continue
    return values


def _vector_to_json(vector: list[float]) -> str | None:
    clean = _coerce_float_list(vector)
    if not clean:
        return None
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def _json_to_vector(raw: str | None) -> list[float]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    return _coerce_float_list(payload)


def _cosine_similarity(lhs: Sequence[float], rhs: Sequence[float]) -> float:
    if not lhs or not rhs:
        return 0.0
    size = min(len(lhs), len(rhs))
    if size <= 0:
        return 0.0
    dot = 0.0
    lhs_norm = 0.0
    rhs_norm = 0.0
    for index in range(size):
        lv = float(lhs[index])
        rv = float(rhs[index])
        dot += lv * rv
        lhs_norm += lv * lv
        rhs_norm += rv * rv
    if lhs_norm <= 0 or rhs_norm <= 0:
        return 0.0
    return dot / math.sqrt(lhs_norm * rhs_norm)


def _truncate_text(value: str, limit: int = 320) -> str:
    stripped = str(value or "").strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[: max(1, limit - 1)]}…"


def _rough_word_count(text: str) -> int:
    english_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return english_words + cjk_chars


def _normalize_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return normalized.strip()


def _split_long_line(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        chunks.append(text[cursor : cursor + max_chars].strip())
        cursor += max_chars
    return [item for item in chunks if item]


def _normalize_heading_title(raw_line: str) -> str:
    line = str(raw_line or "").strip()
    if not line:
        return ""
    markdown_match = _MARKDOWN_HEADING_PATTERN.match(line)
    if markdown_match:
        line = markdown_match.group(1).strip()
    line = re.sub(r"^[\-\*\d\.\)\(、\s]+", "", line).strip()
    line = re.sub(r"[:：]\s*$", "", line).strip()
    return line


def _looks_like_vuln_section_heading(raw_line: str) -> bool:
    raw_text = str(raw_line or "").strip()
    title = _normalize_heading_title(raw_text)
    if not title:
        return False
    lowered = title.lower()
    if any(lowered.startswith(prefix) for prefix in _VULN_SECTION_PREFIXES):
        return True
    if len(raw_text) <= 24 and raw_text.endswith((":", "：")):
        return True
    return False


def _split_document_sections(body: str) -> list[tuple[str, str]]:
    lines = str(body or "").split("\n")
    sections: list[tuple[str, str]] = []
    current_title = ""
    current_lines: list[str] = []

    for raw_line in lines:
        if _MARKDOWN_HEADING_PATTERN.match(raw_line) or _looks_like_vuln_section_heading(raw_line):
            if current_lines:
                chunk_body = _normalize_text("\n".join(current_lines))
                if chunk_body:
                    sections.append((current_title, chunk_body))
                current_lines = []
            current_title = _normalize_heading_title(raw_line)
            continue
        current_lines.append(raw_line)

    if current_lines:
        chunk_body = _normalize_text("\n".join(current_lines))
        if chunk_body:
            sections.append((current_title, chunk_body))

    if not sections:
        return [("", _normalize_text(body))]
    return sections


def _find_split_position(text: str, start: int, max_chars: int) -> int:
    hard_end = min(len(text), start + max_chars)
    if hard_end >= len(text):
        return len(text)

    soft_start = start + int(max_chars * 0.55)
    best = -1
    for token in ("\n\n", "\n", "。", "！", "？", "；", ". ", "; ", "，", "、", ", "):
        pos = text.rfind(token, soft_start, hard_end)
        if pos > best:
            best = pos + len(token)

    if best <= start + int(max_chars * 0.35):
        return hard_end
    return best


def _split_with_overlap(text: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    cursor = 0
    guard = 0
    safe_overlap = max(0, min(overlap_chars, max_chars // 2))

    while cursor < len(normalized):
        guard += 1
        if guard > 2000:
            break
        split_at = _find_split_position(normalized, cursor, max_chars)
        piece = normalized[cursor:split_at].strip()
        if piece:
            chunks.append(piece)
        if split_at >= len(normalized):
            break
        next_cursor = max(cursor + 1, split_at - safe_overlap)
        if next_cursor <= cursor:
            next_cursor = split_at
        cursor = next_cursor

    return chunks


def _chunk_document(
    text: str,
    *,
    max_chars: int = 680,
    overlap_chars: int = 120,
    min_chars: int = 120,
) -> list[str]:
    body = _normalize_text(text)
    if not body:
        return []

    sections = _split_document_sections(body)
    normalized_max_chars = max(220, int(max_chars or 680))
    normalized_min_chars = max(40, min(int(min_chars or 120), normalized_max_chars))
    normalized_overlap = max(0, min(int(overlap_chars or 120), normalized_max_chars // 2))

    chunks: list[str] = []
    seen: set[str] = set()
    for title, section_body in sections:
        section_text = _normalize_text(section_body)
        if not section_text:
            continue

        pieces = _split_with_overlap(
            section_text,
            max_chars=normalized_max_chars,
            overlap_chars=normalized_overlap,
        )
        if not pieces:
            continue

        for piece in pieces:
            chunk = f"{title}\n{piece}".strip() if title else piece.strip()
            if not chunk:
                continue

            key = chunk.lower()
            if key in seen:
                continue

            if chunks and len(chunk) < normalized_min_chars:
                merged = f"{chunks[-1]}\n{chunk}".strip()
                if len(merged) <= normalized_max_chars + max(12, normalized_overlap // 2):
                    chunks[-1] = merged
                    seen.add(merged.lower())
                    continue

            chunks.append(chunk)
            seen.add(key)

    return chunks


def _tokenize_query(query: str) -> list[str]:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return []

    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9_]{2,}", lowered):
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)

    for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", str(query or "")):
        phrase = phrase.strip()
        if not phrase:
            continue
        if len(phrase) <= 4:
            if phrase not in seen:
                seen.add(phrase)
                terms.append(phrase)
            continue
        for index in range(0, len(phrase) - 1):
            token = phrase[index : index + 2]
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
    return terms


def _score_chunk(content: str, query: str, terms: list[str]) -> float:
    raw = str(content or "")
    if not raw:
        return 0.0
    lowered = raw.lower()
    score = 0.0
    normalized_query = str(query or "").strip().lower()
    if normalized_query and normalized_query in lowered:
        score += 8.0
    for term in terms:
        count = lowered.count(term.lower()) if re.fullmatch(r"[a-z0-9_]+", term) else raw.count(term)
        if count <= 0:
            continue
        score += 1.0 + min(count, 5) * 0.4
    if score <= 0:
        return 0.0
    length_factor = max(0.4, min(1.8, 220 / max(80, len(raw))))
    return score * length_factor


class KnowledgeBaseDraft(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None

    @model_validator(mode="after")
    def normalize_fields(self) -> "KnowledgeBaseDraft":
        self.name = self.name.strip()
        self.description = self.description.strip() if isinstance(self.description, str) else self.description
        return self


class KnowledgeBaseUpdateDraft(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None

    @model_validator(mode="after")
    def normalize_fields(self) -> "KnowledgeBaseUpdateDraft":
        if isinstance(self.name, str):
            self.name = self.name.strip()
        if isinstance(self.description, str):
            self.description = self.description.strip()
        return self


class KnowledgeDocumentDraft(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source_type: str = Field(default="text")
    source: str | None = None

    @model_validator(mode="after")
    def normalize_fields(self) -> "KnowledgeDocumentDraft":
        self.title = self.title.strip()
        self.content = _normalize_text(self.content)
        self.source_type = (self.source_type or "text").strip().lower() or "text"
        self.source = self.source.strip() if isinstance(self.source, str) else self.source
        return self


class Base(DeclarativeBase):
    pass


class KnowledgeBaseRow(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class KnowledgeDocumentRow(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(48), default="text")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str] = mapped_column(Text)
    content_preview: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content_text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_dim: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32))


class KnowledgeStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        load_project_env(self.project_root)

        self.lock = threading.RLock()
        self.database_url = self._resolve_database_url()
        self.engine = self._create_engine()
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        self.embedding_config = self._resolve_embedding_config()
        self.rerank_config = self._resolve_rerank_config()
        self.chunking_config = self._resolve_chunking_config()

        self.embedding_client: httpx.Client | None = None
        self.rerank_client: httpx.Client | None = None
        self.embedding_available = self.embedding_config.enabled
        self.rerank_available = self.rerank_config.enabled

        if self.embedding_config.enabled:
            self.embedding_client = httpx.Client(timeout=max(3.0, self.embedding_config.timeout))
        if self.rerank_config.enabled:
            self.rerank_client = httpx.Client(timeout=max(3.0, self.rerank_config.timeout))

        Base.metadata.create_all(self.engine)
        self._ensure_schema()

    def _resolve_database_url(self) -> str:
        raw_url = (
            os.getenv("AUTOSONGSHU_KNOWLEDGE_DATABASE_URL")
            or os.getenv("AUTOSONGSHU_DATABASE_URL")
            or f"sqlite:///{(self.project_root / 'data' / 'autosongshu.db').resolve().as_posix()}"
        )
        url = make_url(raw_url)
        if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
            database_path = Path(url.database)
            if not database_path.is_absolute():
                database_path = (self.project_root / database_path).resolve()
            database_path.parent.mkdir(parents=True, exist_ok=True)
            url = url.set(database=str(database_path))
            return url.render_as_string(hide_password=False)
        return raw_url

    def _create_engine(self) -> Engine:
        connect_args: dict[str, object] = {}
        if self.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        return create_engine(self.database_url, connect_args=connect_args)

    def _ensure_schema(self) -> None:
        inspector = inspect(self.engine)
        if not inspector.has_table("knowledge_chunks"):
            return
        columns = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
        statements: list[str] = []
        if "embedding_json" not in columns:
            statements.append("ALTER TABLE knowledge_chunks ADD COLUMN embedding_json TEXT")
        if "embedding_dim" not in columns:
            statements.append("ALTER TABLE knowledge_chunks ADD COLUMN embedding_dim INTEGER DEFAULT 0")
        if not statements:
            return
        with self.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

    def _resolve_embedding_config(self) -> KnowledgeEmbeddingConfig:
        provider = str(os.getenv("AUTOSONGSHU_KB_EMBEDDING_PROVIDER") or "online").strip().lower()
        enabled = _parse_bool_env("AUTOSONGSHU_KB_EMBEDDING_ENABLED", provider != "none")
        model_name = str(
            os.getenv("AUTOSONGSHU_KB_EMBEDDING_MODEL_NAME")
            or "tongyi-embedding-vision-flash-2026-03-06"
        ).strip()
        api_key = str(
            os.getenv("AUTOSONGSHU_KB_EMBEDDING_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or ""
        ).strip()
        base_url = _normalize_base_url(
            os.getenv("AUTOSONGSHU_KB_EMBEDDING_BASE_URL"),
            default=_DASHSCOPE_API_V1_BASE_URL,
        )
        batch_size = max(1, _parse_int_env("AUTOSONGSHU_KB_EMBEDDING_BATCH_SIZE", 8))
        dimensions_raw = str(os.getenv("AUTOSONGSHU_KB_EMBEDDING_DIMENSIONS") or "").strip()
        dimensions = int(dimensions_raw) if dimensions_raw.isdigit() else None
        timeout = max(2.0, _parse_float_env("AUTOSONGSHU_KB_EMBEDDING_TIMEOUT", 15.0))
        if not enabled or provider not in {"online", "aliyun", "dashscope", "bailian"}:
            enabled = False
        if enabled and (not model_name or not api_key):
            enabled = False
        return KnowledgeEmbeddingConfig(
            enabled=enabled,
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            batch_size=batch_size,
            dimensions=dimensions,
        )

    def _resolve_rerank_config(self) -> KnowledgeRerankConfig:
        provider = str(os.getenv("AUTOSONGSHU_KB_RERANK_PROVIDER") or "online").strip().lower()
        enabled = _parse_bool_env("AUTOSONGSHU_KB_RERANK_ENABLED", provider != "none")
        model_name = str(os.getenv("AUTOSONGSHU_KB_RERANK_MODEL_NAME") or "qwen3-vl-rerank").strip()
        api_key = str(
            os.getenv("AUTOSONGSHU_KB_RERANK_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or ""
        ).strip()
        base_url = _normalize_base_url(
            os.getenv("AUTOSONGSHU_KB_RERANK_BASE_URL"),
            default=_DASHSCOPE_API_V1_BASE_URL,
        )
        timeout = max(2.0, _parse_float_env("AUTOSONGSHU_KB_RERANK_TIMEOUT", 15.0))
        max_input_chars = max(256, _parse_int_env("AUTOSONGSHU_KB_RERANK_MAX_INPUT_CHARS", 1600))
        if not enabled or provider not in {"online", "aliyun", "dashscope", "bailian"}:
            enabled = False
        if enabled and (not model_name or not api_key):
            enabled = False
        return KnowledgeRerankConfig(
            enabled=enabled,
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_input_chars=max_input_chars,
        )

    def _resolve_chunking_config(self) -> KnowledgeChunkingConfig:
        max_chars = max(220, _parse_int_env("AUTOSONGSHU_KB_CHUNK_MAX_CHARS", 680))
        overlap_chars = max(0, _parse_int_env("AUTOSONGSHU_KB_CHUNK_OVERLAP_CHARS", 120))
        overlap_chars = min(overlap_chars, max_chars // 2)
        min_chars = max(40, _parse_int_env("AUTOSONGSHU_KB_CHUNK_MIN_CHARS", 120))
        min_chars = min(min_chars, max_chars)
        return KnowledgeChunkingConfig(
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            min_chars=min_chars,
        )

    def _assert_base_exists(self, session, knowledge_base_id: str) -> KnowledgeBaseRow:
        row = session.get(KnowledgeBaseRow, knowledge_base_id)
        if row is None:
            raise KeyError(knowledge_base_id)
        return row

    def _base_summary_with_counts(self, session, row: KnowledgeBaseRow) -> dict[str, Any]:
        document_count = int(
            session.scalar(
                select(func.count()).select_from(KnowledgeDocumentRow).where(
                    KnowledgeDocumentRow.knowledge_base_id == row.id,
                ),
            )
            or 0
        )
        chunk_count = int(
            session.scalar(
                select(func.count()).select_from(KnowledgeChunkRow).where(
                    KnowledgeChunkRow.knowledge_base_id == row.id,
                ),
            )
            or 0
        )
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "document_count": document_count,
            "chunk_count": chunk_count,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _document_payload(self, row: KnowledgeDocumentRow, *, include_content: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": row.id,
            "knowledge_base_id": row.knowledge_base_id,
            "title": row.title,
            "source_type": row.source_type,
            "source": row.source,
            "content_preview": row.content_preview,
            "word_count": row.word_count,
            "chunk_count": row.chunk_count,
            "content_length": len(str(row.content_text or "")),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        if include_content:
            payload["content"] = row.content_text
        return payload

    def _use_dashscope_multimodal_embedding(self) -> bool:
        return _model_matches(self.embedding_config.model_name, _DASHSCOPE_MULTIMODAL_EMBEDDING_MODEL_PREFIXES)

    def _use_dashscope_native_rerank(self) -> bool:
        return _model_matches(self.rerank_config.model_name, _DASHSCOPE_NATIVE_RERANK_MODEL_PREFIXES)

    def _use_dashscope_compatible_rerank(self) -> bool:
        return _model_matches(self.rerank_config.model_name, _DASHSCOPE_COMPATIBLE_RERANK_MODEL_PREFIXES)

    def _embed_texts_openai_compatible(self, texts: Sequence[str]) -> list[list[float]]:
        if self.embedding_client is None:
            return []
        base_url = _normalize_base_url(self.embedding_config.base_url)
        if not base_url:
            raise ValueError("knowledge_base.embedding.base_url is required for online embeddings.")
        headers = _request_headers(self.embedding_config.api_key, base_url=base_url)
        endpoint = _join_endpoint(base_url, "/embeddings")
        vectors: list[list[float]] = []
        for batch in _batched(list(texts), self.embedding_config.batch_size):
            payload: dict[str, Any] = {
                "model": self.embedding_config.model_name,
                "input": batch,
            }
            if self.embedding_config.dimensions is not None:
                payload["dimensions"] = self.embedding_config.dimensions
            response = self.embedding_client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            rows = sorted((data.get("data") or []), key=lambda item: int(item.get("index", 0)))
            vectors.extend(_coerce_float_list(item.get("embedding") or []) for item in rows)
        return vectors

    def _embed_texts_dashscope_multimodal(self, texts: Sequence[str]) -> list[list[float]]:
        if self.embedding_client is None:
            return []
        base_url = _normalize_base_url(self.embedding_config.base_url, default=_DASHSCOPE_API_V1_BASE_URL)
        if not base_url:
            raise ValueError("knowledge_base.embedding.base_url is required for DashScope embeddings.")
        headers = _request_headers(self.embedding_config.api_key, base_url=base_url)
        endpoint = _join_endpoint(base_url, "/services/embeddings/multimodal-embedding/multimodal-embedding")

        vectors: list[list[float]] = []
        for batch in _batched(list(texts), self.embedding_config.batch_size):
            payload: dict[str, Any] = {
                "model": self.embedding_config.model_name,
                "input": {
                    "contents": [{"text": text} for text in batch],
                },
            }
            if self.embedding_config.dimensions is not None:
                payload["parameters"] = {"dimension": int(self.embedding_config.dimensions)}
            response = self.embedding_client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            output = data.get("output") or {}
            rows = sorted(
                (output.get("embeddings") or []),
                key=lambda item: int(item.get("text_index", item.get("index", 0)) or 0),
            )
            vectors.extend(_coerce_float_list(item.get("embedding") or []) for item in rows)
        return vectors

    def _embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.embedding_config.enabled or not self.embedding_available:
            return []
        try:
            if self._use_dashscope_multimodal_embedding():
                return self._embed_texts_dashscope_multimodal(texts)
            return self._embed_texts_openai_compatible(texts)
        except Exception:
            self.embedding_available = False
            return []

    def _normalize_indexed_results(
        self,
        rows: Sequence[Any],
        candidates: Sequence[KnowledgeChunkCandidate],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate: KnowledgeChunkCandidate | None = None
            chunk_id = str(row.get("id") or "").strip()
            if chunk_id:
                candidate = next((item for item in candidates if item.chunk_id == chunk_id), None)
            elif "index" in row:
                try:
                    candidate = candidates[int(row.get("index") or 0)]
                except (TypeError, ValueError, IndexError):
                    candidate = None
            if candidate is None:
                continue
            normalized.append(
                {
                    "id": candidate.chunk_id,
                    "score": float(row.get("relevance_score", row.get("score", 0.0)) or 0.0),
                    "reason": str(row.get("reason") or "").strip(),
                },
            )
        normalized.sort(key=lambda item: item["score"], reverse=True)
        return normalized[:top_k]

    def _rerank_dashscope_native(
        self,
        query: str,
        candidates: Sequence[KnowledgeChunkCandidate],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if self.rerank_client is None:
            return []
        base_url = _normalize_base_url(self.rerank_config.base_url, default=_DASHSCOPE_API_V1_BASE_URL)
        if not base_url:
            raise ValueError("knowledge_base.rerank.base_url is required for online rerank.")
        headers = _request_headers(self.rerank_config.api_key, base_url=base_url)
        endpoint = _join_endpoint(base_url, "/services/rerank/text-rerank/text-rerank")

        response = self.rerank_client.post(
            endpoint,
            headers=headers,
            json={
                "model": self.rerank_config.model_name,
                "input": {
                    "query": {"text": query},
                    "documents": [
                        {"text": _truncate_text(item.text, self.rerank_config.max_input_chars)}
                        for item in candidates
                    ],
                },
                "parameters": {
                    "top_n": min(max(1, int(top_k or 1)), len(candidates)),
                    "return_documents": False,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        results = (payload.get("output") or {}).get("results") or payload.get("results") or []
        return self._normalize_indexed_results(results, candidates, top_k=max(1, int(top_k or 1)))

    def _rerank_dashscope_compatible(
        self,
        query: str,
        candidates: Sequence[KnowledgeChunkCandidate],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if self.rerank_client is None:
            return []
        base_url = _normalize_base_url(self.rerank_config.base_url, default=_DASHSCOPE_COMPATIBLE_BASE_URL)
        if not base_url:
            raise ValueError("knowledge_base.rerank.base_url is required for online rerank.")
        headers = _request_headers(self.rerank_config.api_key, base_url=base_url)
        endpoint = _join_endpoint(base_url, "/reranks")

        response = self.rerank_client.post(
            endpoint,
            headers=headers,
            json={
                "model": self.rerank_config.model_name,
                "query": query,
                "documents": [_truncate_text(item.text, self.rerank_config.max_input_chars) for item in candidates],
                "top_n": min(max(1, int(top_k or 1)), len(candidates)),
                "return_documents": False,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return self._normalize_indexed_results(
            payload.get("results") or [],
            candidates,
            top_k=max(1, int(top_k or 1)),
        )

    def _rerank(
        self,
        query: str,
        candidates: Sequence[KnowledgeChunkCandidate],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        if not self.rerank_config.enabled or not self.rerank_available:
            return []

        try:
            if self._use_dashscope_native_rerank():
                return self._rerank_dashscope_native(query, candidates, top_k=top_k)
            if self._use_dashscope_compatible_rerank():
                return self._rerank_dashscope_compatible(query, candidates, top_k=top_k)

            native = self._rerank_dashscope_native(query, candidates, top_k=top_k)
            if native:
                return native
            return self._rerank_dashscope_compatible(query, candidates, top_k=top_k)
        except Exception:
            self.rerank_available = False
            return []

    def filter_existing_base_ids(self, ids: list[str]) -> list[str]:
        normalized = [str(item or "").strip() for item in ids if str(item or "").strip()]
        if not normalized:
            return []
        with self.lock, self.session_factory() as session:
            rows = session.scalars(select(KnowledgeBaseRow.id).where(KnowledgeBaseRow.id.in_(normalized))).all()
        existing = {str(item) for item in rows}
        return [item for item in normalized if item in existing]

    def get_base_name_map(self, ids: list[str]) -> dict[str, str]:
        normalized = [str(item or "").strip() for item in ids if str(item or "").strip()]
        if not normalized:
            return {}
        with self.lock, self.session_factory() as session:
            rows = session.scalars(select(KnowledgeBaseRow).where(KnowledgeBaseRow.id.in_(normalized))).all()
        return {row.id: row.name for row in rows}

    def list_bases(self) -> list[dict[str, Any]]:
        with self.lock, self.session_factory() as session:
            rows = session.scalars(select(KnowledgeBaseRow).order_by(KnowledgeBaseRow.updated_at.desc())).all()
            return [self._base_summary_with_counts(session, row) for row in rows]

    def create_base(self, payload: KnowledgeBaseDraft) -> dict[str, Any]:
        timestamp = now_iso()
        base_id = uuid4().hex
        with self.lock, self.session_factory() as session:
            row = KnowledgeBaseRow(
                id=base_id,
                name=payload.name,
                description=payload.description,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)
            session.commit()
            return self._base_summary_with_counts(session, row)

    def update_base(self, knowledge_base_id: str, payload: KnowledgeBaseUpdateDraft) -> dict[str, Any]:
        with self.lock, self.session_factory() as session:
            row = self._assert_base_exists(session, knowledge_base_id)
            if payload.name is not None:
                row.name = payload.name
            if "description" in payload.model_fields_set:
                row.description = payload.description
            row.updated_at = now_iso()
            session.commit()
            return self._base_summary_with_counts(session, row)

    def delete_base(self, knowledge_base_id: str) -> None:
        with self.lock, self.session_factory() as session:
            row = self._assert_base_exists(session, knowledge_base_id)
            session.execute(delete(KnowledgeChunkRow).where(KnowledgeChunkRow.knowledge_base_id == row.id))
            session.execute(delete(KnowledgeDocumentRow).where(KnowledgeDocumentRow.knowledge_base_id == row.id))
            session.execute(delete(KnowledgeBaseRow).where(KnowledgeBaseRow.id == row.id))
            session.commit()

    def list_documents(self, knowledge_base_id: str) -> list[dict[str, Any]]:
        with self.lock, self.session_factory() as session:
            self._assert_base_exists(session, knowledge_base_id)
            rows = session.scalars(
                select(KnowledgeDocumentRow)
                .where(KnowledgeDocumentRow.knowledge_base_id == knowledge_base_id)
                .order_by(KnowledgeDocumentRow.updated_at.desc()),
            ).all()
            return [self._document_payload(row) for row in rows]

    def get_base(self, knowledge_base_id: str) -> dict[str, Any]:
        with self.lock, self.session_factory() as session:
            row = self._assert_base_exists(session, knowledge_base_id)
            documents = session.scalars(
                select(KnowledgeDocumentRow)
                .where(KnowledgeDocumentRow.knowledge_base_id == knowledge_base_id)
                .order_by(KnowledgeDocumentRow.updated_at.desc()),
            ).all()
            payload = self._base_summary_with_counts(session, row)
            payload["documents"] = [self._document_payload(item) for item in documents]
            return payload

    def get_document(self, knowledge_base_id: str, document_id: str) -> dict[str, Any]:
        with self.lock, self.session_factory() as session:
            self._assert_base_exists(session, knowledge_base_id)
            row = session.get(KnowledgeDocumentRow, document_id)
            if row is None or row.knowledge_base_id != knowledge_base_id:
                raise KeyError(document_id)
            return self._document_payload(row, include_content=True)

    def _touch_base(self, session, knowledge_base_id: str) -> None:
        row = self._assert_base_exists(session, knowledge_base_id)
        row.updated_at = now_iso()

    def create_document(self, knowledge_base_id: str, payload: KnowledgeDocumentDraft) -> dict[str, Any]:
        content = _normalize_text(payload.content)
        if not content:
            raise ValueError("Document content cannot be empty.")
        chunks = _chunk_document(
            content,
            max_chars=self.chunking_config.max_chars,
            overlap_chars=self.chunking_config.overlap_chars,
            min_chars=self.chunking_config.min_chars,
        )
        if not chunks:
            raise ValueError("Document content cannot be empty.")

        embeddings = self._embed_texts(chunks)
        if len(embeddings) != len(chunks):
            embeddings = []

        timestamp = now_iso()
        document_id = uuid4().hex
        with self.lock, self.session_factory() as session:
            self._assert_base_exists(session, knowledge_base_id)
            row = KnowledgeDocumentRow(
                id=document_id,
                knowledge_base_id=knowledge_base_id,
                title=payload.title,
                source_type=payload.source_type,
                source=payload.source,
                content_text=content,
                content_preview=(content[:240] + "...") if len(content) > 240 else content,
                word_count=_rough_word_count(content),
                chunk_count=len(chunks),
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)

            for index, chunk in enumerate(chunks, start=1):
                vector = embeddings[index - 1] if embeddings else []
                clean_vector = _coerce_float_list(vector)
                session.add(
                    KnowledgeChunkRow(
                        id=uuid4().hex,
                        knowledge_base_id=knowledge_base_id,
                        document_id=document_id,
                        chunk_index=index,
                        content_text=chunk,
                        token_count=_rough_word_count(chunk),
                        embedding_json=_vector_to_json(clean_vector),
                        embedding_dim=len(clean_vector) if clean_vector else 0,
                        created_at=timestamp,
                    ),
                )
            self._touch_base(session, knowledge_base_id)
            session.commit()
            return self._document_payload(row)

    def delete_document(self, knowledge_base_id: str, document_id: str) -> None:
        with self.lock, self.session_factory() as session:
            self._assert_base_exists(session, knowledge_base_id)
            row = session.get(KnowledgeDocumentRow, document_id)
            if row is None or row.knowledge_base_id != knowledge_base_id:
                raise KeyError(document_id)
            session.execute(delete(KnowledgeChunkRow).where(KnowledgeChunkRow.document_id == document_id))
            session.execute(delete(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id == document_id))
            self._touch_base(session, knowledge_base_id)
            session.commit()

    def _format_search_payload(self, item: KnowledgeSearchCandidate, *, rerank_reason: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "score": round(float(item.score), 4),
            "knowledge_base_id": item.knowledge_base_id,
            "knowledge_base_name": item.knowledge_base_name,
            "document_id": item.document_id,
            "document_title": item.document_title,
            "chunk_id": item.chunk_id,
            "chunk_index": item.chunk_index,
            "content": item.content,
        }
        if rerank_reason:
            payload["rerank_reason"] = rerank_reason
        return payload

    def search_chunks(
        self,
        knowledge_base_ids: list[str],
        query: str,
        *,
        limit: int = 4,
        max_scan_chunks: int = 2500,
    ) -> list[dict[str, Any]]:
        normalized_ids = [str(item or "").strip() for item in knowledge_base_ids if str(item or "").strip()]
        if not normalized_ids:
            return []
        query_text = str(query or "").strip()
        if not query_text:
            return []

        terms = _tokenize_query(query_text)
        if not terms and len(query_text) < 2:
            return []

        query_vectors = self._embed_texts([query_text])
        query_vector = query_vectors[0] if query_vectors else []

        with self.lock, self.session_factory() as session:
            chunks = session.scalars(
                select(KnowledgeChunkRow)
                .where(KnowledgeChunkRow.knowledge_base_id.in_(normalized_ids))
                .order_by(KnowledgeChunkRow.created_at.desc())
                .limit(max_scan_chunks),
            ).all()
            if not chunks:
                return []

            document_ids = {item.document_id for item in chunks}
            documents = session.scalars(
                select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.id.in_(document_ids)),
            ).all()
            document_map = {item.id: item for item in documents}

            base_ids = {item.knowledge_base_id for item in chunks}
            bases = session.scalars(select(KnowledgeBaseRow).where(KnowledgeBaseRow.id.in_(base_ids))).all()
            base_map = {item.id: item for item in bases}

            scored: list[KnowledgeSearchCandidate] = []
            for chunk in chunks:
                lexical_score = _score_chunk(chunk.content_text, query_text, terms)
                vector_score = 0.0
                if query_vector:
                    vector_score = max(0.0, _cosine_similarity(query_vector, _json_to_vector(chunk.embedding_json)))

                combined_score = lexical_score + vector_score * 8.0
                if combined_score <= 0 and vector_score < 0.24:
                    continue

                document = document_map.get(chunk.document_id)
                base = base_map.get(chunk.knowledge_base_id)
                scored.append(
                    KnowledgeSearchCandidate(
                        score=float(combined_score),
                        lexical_score=float(lexical_score),
                        vector_score=float(vector_score),
                        knowledge_base_id=chunk.knowledge_base_id,
                        knowledge_base_name=base.name if base else chunk.knowledge_base_id,
                        document_id=chunk.document_id,
                        document_title=document.title if document else chunk.document_id,
                        chunk_id=chunk.id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content_text,
                    ),
                )

        if not scored:
            return []

        scored.sort(
            key=lambda item: (item.score, item.vector_score, item.lexical_score, -int(item.chunk_index)),
            reverse=True,
        )

        safe_limit = max(1, int(limit))
        candidate_pool = scored[: max(safe_limit * 4, 12)]
        rerank_candidates = [KnowledgeChunkCandidate(chunk_id=item.chunk_id, text=item.content) for item in candidate_pool]
        rerank_results = self._rerank(query_text, rerank_candidates, top_k=safe_limit)
        if rerank_results:
            by_chunk_id = {str(item.get("id") or ""): item for item in rerank_results}
            reranked_payloads: list[dict[str, Any]] = []
            for item in candidate_pool:
                rerank_row = by_chunk_id.get(item.chunk_id)
                if rerank_row is None:
                    continue
                reason = _truncate_text(str(rerank_row.get("reason") or "").strip(), 240)
                payload = self._format_search_payload(item, rerank_reason=reason or None)
                payload["retrieval_score"] = round(float(item.score), 4)
                payload["score"] = round(float(rerank_row.get("score") or 0.0), 4)
                reranked_payloads.append(payload)
            reranked_payloads.sort(key=lambda item: (float(item.get("score") or 0.0)), reverse=True)
            if reranked_payloads:
                return reranked_payloads[:safe_limit]

        return [self._format_search_payload(item) for item in candidate_pool[:safe_limit]]

    def close(self) -> None:
        clients: list[httpx.Client] = []
        if self.embedding_client is not None:
            clients.append(self.embedding_client)
        if self.rerank_client is not None and self.rerank_client is not self.embedding_client:
            clients.append(self.rerank_client)
        for client in clients:
            try:
                client.close()
            except Exception:
                continue
        self.engine.dispose()
