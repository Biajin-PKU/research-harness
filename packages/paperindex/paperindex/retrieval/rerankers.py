from __future__ import annotations

import json
import re
from typing import Any, Literal

from ..llm.client import LLMClient, ResolvedLLMConfig
from ..types import SearchResult

RerankMode = Literal["none", "heuristic", "llm"]


def rerank_search_results(
    query: str,
    results: list[SearchResult],
    mode: RerankMode = "heuristic",
    llm_config: dict[str, Any] | None = None,
) -> list[SearchResult]:
    if mode == "none":
        return results
    if mode == "heuristic":
        return _heuristic_rerank(results)
    if mode == "llm":
        return _llm_rerank(query, results, llm_config=llm_config)
    raise ValueError(f"Unsupported rerank mode: {mode}")


def _heuristic_rerank(results: list[SearchResult]) -> list[SearchResult]:
    reranked: list[SearchResult] = []
    for result in results:
        bonus = 0.0
        reason = result.rerank_reason
        if result.structure_matches:
            bonus += result.structure_matches[0].score * 0.5
            reason = "Top structure match boosted by heuristic reranker"
            if result.structure_matches[0].summary:
                bonus += 1.0
                reason = "Top structure match summary increased heuristic confidence"
        reranked.append(
            SearchResult(
                paper_id=result.paper_id,
                title=result.title,
                score=result.score + bonus,
                matched_fields=result.matched_fields,
                snippet=result.snippet,
                structure_matches=result.structure_matches,
                rerank_reason=reason,
            )
        )
    return sorted(reranked, key=lambda item: (-item.score, item.title.lower()))


def _llm_rerank(
    query: str,
    results: list[SearchResult],
    llm_config: dict[str, Any] | None = None,
) -> list[SearchResult]:
    config = llm_config or {}
    model = config.get("model")
    if not model:
        raise ValueError("LLM rerank requires llm_config['model']")

    client = LLMClient(ResolvedLLMConfig(
        provider=config.get("provider", "openai"),
        model=model,
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", ""),
    ))
    prompt = _build_rerank_prompt(query, results)
    response = client.chat(prompt=prompt, temperature=0.0)
    ranked_items = _extract_ranked_items(response)
    if not ranked_items:
        return _heuristic_rerank(results)

    by_id = {result.paper_id: result for result in results}
    reranked: list[SearchResult] = []
    seen: set[str] = set()
    total = len(ranked_items)
    for index, item in enumerate(ranked_items):
        paper_id = item["paper_id"]
        result = by_id.get(paper_id)
        if result is None:
            continue
        seen.add(paper_id)
        bonus = float(max(total - index, 1))
        reranked.append(
            SearchResult(
                paper_id=result.paper_id,
                title=result.title,
                score=result.score + bonus,
                matched_fields=result.matched_fields,
                snippet=result.snippet,
                structure_matches=result.structure_matches,
                rerank_reason=item.get("reason", ""),
            )
        )
    for result in results:
        if result.paper_id in seen:
            continue
        reranked.append(result)
    return reranked


def _build_rerank_prompt(query: str, results: list[SearchResult]) -> str:
    candidates = []
    for result in results:
        candidates.append(
            {
                "paper_id": result.paper_id,
                "title": result.title,
                "snippet": result.snippet,
                "structure_matches": [
                    {
                        "node_id": item.node_id,
                        "title": item.title,
                        "summary": item.summary,
                        "score": item.score,
                    }
                    for item in result.structure_matches[:3]
                ],
            }
        )
    return (
        "You are reranking paper retrieval candidates for a user query. "
        "Return only JSON with a single key 'ranked_results'. "
        "Each item must contain 'paper_id' and a short 'reason' explaining the ranking. "
        "Order best to worst.\n\n"
        f"Query:\n{query}\n\nCandidates:\n{json.dumps(candidates, ensure_ascii=False, indent=2)}"
    )


def _extract_ranked_items(text: str) -> list[dict[str, str]]:
    data = _extract_json_object(text)
    if not isinstance(data, dict):
        return []

    ranked_results = data.get("ranked_results")
    if isinstance(ranked_results, list):
        items: list[dict[str, str]] = []
        for item in ranked_results:
            if not isinstance(item, dict):
                continue
            paper_id = str(item.get("paper_id", "")).strip()
            if not paper_id:
                continue
            items.append({
                "paper_id": paper_id,
                "reason": str(item.get("reason", "")).strip(),
            })
        if items:
            return items

    ranked_ids = data.get("ranked_paper_ids")
    if isinstance(ranked_ids, list):
        return [{"paper_id": str(item).strip(), "reason": ""} for item in ranked_ids if str(item).strip()]
    return []


def _extract_json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
