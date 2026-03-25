from __future__ import annotations

import re


def tokenize_query(query: str) -> list[str]:
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


def extract_key_phrases(text: str, max_phrases: int = 8) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []

    phrases: list[str] = []
    seen: set[str] = set()

    tech_patterns = [
        r"[A-Z][a-z]+(?:[A-Z][a-z]+)+",
        r"[A-Z]{2,}[0-9]*",
        r"[a-z]+_[a-z_]+",
        r"[a-z]+\.[a-z.]+",
        r"[A-Za-z]+\d+[A-Za-z]*",
        r"\b(?:CVE|CWE|GHSA|VD)-\d{4}-\d+\b",
        r"\b(?:https?://)?[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?\b",
    ]

    for pattern in tech_patterns:
        for match in re.findall(pattern, text):
            normalized = str(match).strip()
            if normalized and normalized.lower() not in seen and len(normalized) >= 2:
                seen.add(normalized.lower())
                phrases.append(normalized)

    chinese_phrases = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    for phrase in chinese_phrases:
        if phrase not in seen:
            seen.add(phrase)
            phrases.append(phrase)

    quoted = re.findall(r'["\'「」『』【】]([^"\s]{2,20})["\'「」『』【】]', text)
    for q in quoted:
        if q and q not in seen:
            seen.add(q)
            phrases.append(q)

    return phrases[:max_phrases]


def compute_bm25_score(
    content: str,
    terms: list[str],
    avg_doc_len: float = 400.0,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not content or not terms:
        return 0.0

    lowered = content.lower()
    doc_len = len(content)
    len_norm = 1 - b + b * (doc_len / max(1, avg_doc_len))

    score = 0.0
    for term in terms:
        term_lower = term.lower()
        tf = (
            lowered.count(term_lower)
            if re.fullmatch(r"[a-z0-9_]+", term_lower)
            else content.count(term)
        )
        if tf <= 0:
            continue
        tf_norm = tf / (tf + k1 * len_norm)
        score += tf_norm

    return score


def compute_rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def score_chunk(content: str, query: str, terms: list[str]) -> float:
    raw = str(content or "")
    if not raw:
        return 0.0

    bm25_score = compute_bm25_score(raw, terms)
    exact_match_bonus = 0.0

    lowered = raw.lower()
    normalized_query = str(query or "").strip().lower()
    if normalized_query and normalized_query in lowered:
        exact_match_bonus = 3.0

    return bm25_score + exact_match_bonus
