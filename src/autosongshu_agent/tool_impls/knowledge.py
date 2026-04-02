from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse

from ..runtime import PentestRuntime
from .registry import registry
from .utils import _error_response, _parse_json_list, _tool_response

registry.create_group(
    "knowledge-rag",
    description="Search reusable internal knowledge and past experience snippets.",
    active=True,
    notes="Use this only when retrieval is truly helpful. Compose a concise query based on the current task.",
)

@registry.register("knowledge-rag")
def knowledge_search(
    runtime: PentestRuntime,
    query: str,
    knowledge_base_ids_json: str = "[]",
    limit: int = 6,
) -> ToolResponse:
    """Search knowledge-base chunks when prior experience may help. query should be concise and retrieval-oriented."""
    try:
        requested_ids = _parse_json_list(knowledge_base_ids_json)
        result = runtime.search_knowledge(
            query=query,
            knowledge_base_ids=requested_ids,
            limit=limit,
        )
        hits = result.get("hits") if isinstance(result, dict) else []
        return _tool_response(
            {
                "query": str(query or "").strip(),
                "requested_knowledge_base_ids": requested_ids,
                **(result if isinstance(result, dict) else {"hits": []}),
                "hit_count": len(hits) if isinstance(hits, list) else 0,
            },
        )
    except Exception as exc:
        return _error_response(exc)
