from __future__ import annotations

from dataclasses import dataclass


_DASHSCOPE_API_V1_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
_DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-api/v1"
_DASHSCOPE_MULTIMODAL_EMBEDDING_MODEL_PREFIXES = (
    "tongyi-embedding-vision",
    "multimodal-embedding",
    "qwen3-vl-embedding",
)
_DASHSCOPE_NATIVE_RERANK_MODEL_PREFIXES = ("qwen3-vl-rerank", "gte-rerank")
_DASHSCOPE_COMPATIBLE_RERANK_MODEL_PREFIXES = ("qwen3-rerank",)


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
class KnowledgeSearchConfig:
    min_rerank_score: float
    min_vector_score: float
    rrf_k: int
    candidate_multiplier: int


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
