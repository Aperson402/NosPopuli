import json
from documentor_agent import log_action

def validate_results(query, results, client):
    """
    Scores each result for relevance to the query.
    Returns filtered list with obviously wrong results removed.
    """
    print(f"[VALIDATOR] Running on {len(results)} results for: {query}")
    if not results:
        return results

    titles = [
        {"index": i, "title": r.get("title", ""), "id": f"{(r.get('type','') or '').upper()}{r.get('number','')}"}
        for i, r in enumerate(results)
    ]

    prompt = f"""
You are a search result validator for a legislative search engine.
The user searched for: "{query}"

Rate each result's relevance. Return ONLY valid JSON, no markdown.

Results:
{json.dumps(titles, indent=2)}

For each result, return a relevance score 0-10.
- 8-10: Directly relevant to the query
- 5-7: Somewhat related
- 0-4: Not relevant (wrong topic, generic, unrelated)

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

        # Filter out low scores, keep order
        keep = {s["index"] for s in scored["scores"] if s["score"] >= 5}
        filtered = [r for i, r in enumerate(results) if i in keep]

        log_action(
            agent_name="result_validator",
            action="validate_results",
            input_data={"query": query, "result_count": len(results)},
            output_data={"kept": len(filtered), "dropped": len(results) - len(filtered)}
        )

        return filtered if filtered else results  # never return empty if we had results

    except Exception as e:
        print(f"[VALIDATOR] Error: {e}")
        return results  # fail open