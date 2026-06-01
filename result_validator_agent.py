import json
from documentor_agent import log_action

def validate_results(query, results, client, min_score=5, fail_open=True):
    """
    Scores each result for relevance to the query.
    Returns filtered list with obviously wrong results removed.

    min_score: keep results scoring >= this (0-10). Use 7 for state bill searches.
    fail_open: if True, return original results when nothing passes. If False, return [].
    """
    print(f"[VALIDATOR] Running on {len(results)} results for: {query}")
    if not results:
        return results

    entries = []
    for i, r in enumerate(results):
        entry = {
            "index": i,
            "id": r.get("identifier") or f"{(r.get('type') or '').upper()}{r.get('number', '')}",
            "title": r.get("title", ""),
        }
        if r.get("abstract"):
            entry["abstract"] = r["abstract"][:250]
        if r.get("subjects"):
            entry["subjects"] = r["subjects"][:6]
        if r.get("latest_action"):
            entry["latest_action"] = r["latest_action"][:120]
        entries.append(entry)

    prompt = f"""
You are a search result validator for a legislative search engine.
The user searched for: "{query}"

Rate each result's relevance. Return ONLY valid JSON, no markdown.

Results:
{json.dumps(entries, indent=2)}

For each result, return a relevance score 0-10.
- 8-10: Directly relevant — bill is primarily about the searched topic
- 5-7: Somewhat related — bill touches the topic but isn't primarily about it
- 0-4: Not relevant — wrong topic, only mentions the term in passing, or unrelated

Return ONLY this JSON:
{{
    "scores": [
        {{"index": 0, "score": 8, "reason": "brief reason"}},
        ...
    ]
}}
"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip().replace("```json", "").replace("```", "")
        scored = json.loads(raw)

        keep = {s["index"] for s in scored["scores"] if s["score"] >= min_score}
        filtered = [r for i, r in enumerate(results) if i in keep]

        log_action(
            agent_name="result_validator",
            action="validate_results",
            input_data={"query": query, "result_count": len(results), "min_score": min_score},
            output_data={"kept": len(filtered), "dropped": len(results) - len(filtered)}
        )

        if filtered:
            return filtered
        return results if fail_open else []

    except Exception as e:
        print(f"[VALIDATOR] Error: {e}")
        return results  # always fail open on error