from __future__ import annotations

import json
import math
from typing import Any, Iterable, Sequence

from .config import (
    _DASHSCOPE_API_V1_BASE_URL,
    _DASHSCOPE_COMPATIBLE_BASE_URL,
    _DASHSCOPE_MULTIMODAL_EMBEDDING_MODEL_PREFIXES,
)


def normalize_base_url(raw_url: str | None, *, default: str | None = None) -> str:
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


def batched(items: Sequence[str], batch_size: int) -> Iterable[list[str]]:
    step = max(1, int(batch_size or 1))
    for index in range(0, len(items), step):
        yield list(items[index : index + step])


def _model_matches(model_name: str | None, prefixes: Sequence[str]) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    return any(
        normalized.startswith(str(prefix).strip().lower()) for prefix in prefixes
    )


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


def vector_to_json(vector: list[float]) -> str | None:
    clean = _coerce_float_list(vector)
    if not clean:
        return None
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def json_to_vector(raw: str | None) -> list[float]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    return _coerce_float_list(payload)


def cosine_similarity(lhs: Sequence[float], rhs: Sequence[float]) -> float:
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
