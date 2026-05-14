import requests
import os
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

# Popular name → official bill mapping for cases where Congress.gov's search
# index doesn't surface the original by popular name (popular name ≠ official title).
POPULAR_NAMES = {
    "title ix":        {"congress": 92, "type": "s", "number": 659, "title": "Education Amendments of 1972"},
    "title 9":         {"congress": 92, "type": "s", "number": 659, "title": "Education Amendments of 1972"},
    "title vi":        {"congress": 88, "type": "hr", "number": 7152, "title": "Civil Rights Act of 1964"},
    "title vii":       {"congress": 88, "type": "hr", "number": 7152, "title": "Civil Rights Act of 1964"},
    "voting rights act": {"congress": 89, "type": "hr", "number": 6400, "title": "Voting Rights Act of 1965"},
    "civil rights act":  {"congress": 88, "type": "hr", "number": 7152, "title": "Civil Rights Act of 1964"},
    "equal pay act":   {"congress": 88, "type": "hr", "number": 6060, "title": "Equal Pay Act of 1963"},
}

def search_by_title(named_entity, max_recent=3):
    """
    Two-phase title search for named acts.
    Returns: [original_law, recent_1, recent_2, recent_3]
    """
    url = "https://api.congress.gov/v3/bill"
    entity_lower = named_entity.lower().strip()

    def bill_to_result(bill, is_original=False):
        return {
            "congress": bill.get("congress"),
            "type": (bill.get("type") or "").lower(),
            "number": bill.get("number"),
            "title": bill.get("title", ""),
            "date_issued": (bill.get("latestAction") or {}).get("actionDate", ""),
            "latest_action": (bill.get("latestAction") or {}).get("text", ""),
            "source": "title_search",
            "is_original": is_original,
            "is_law": False,
            "law_number": None,
        }

    # Phase 1 — check popular names table before hitting the API
    original = None
    if entity_lower in POPULAR_NAMES:
        entry = POPULAR_NAMES[entity_lower]
        original = {
            "congress": entry["congress"],
            "type": entry["type"].lower(),
            "number": entry["number"],
            "title": entry["title"],
            "date_issued": "",
            "latest_action": "",
            "source": "title_search",
            "is_original": True,
            "is_law": False,
            "law_number": None,
        }

    # Phase 1 fallback — relevance search when not in POPULAR_NAMES
    params_original = {
        "api_key": CONGRESS_API_KEY,
        "format": "json",
        "query": named_entity,
        "limit": 50,
    }

    if original is None:
        try:
            response = requests.get(url, params=params_original, timeout=10)
        except Exception as e:
            print(f"[TITLE SEARCH] Error: {e}")
            return []

        if response.status_code != 200:
            print(f"[TITLE SEARCH] Error {response.status_code}")
            return []

        try:
            bills = response.json().get("bills", [])
        except Exception:
            return []

        if not bills:
            return []

        for bill in bills[:10]:
            congress = bill.get("congress")
            if congress and int(congress) <= 100:
                original = bill_to_result(bill, is_original=True)
                break

        if not original:
            original = bill_to_result(bills[0], is_original=True)

    params = params_original

    # Phase 2 — recent: newest results, excluding original
    original_key = f"{original['congress']}{original['type']}{original['number']}" if original else None

    recent_params = {**params, "sort": "date+desc"}
    try:
        recent_response = requests.get(url, params=recent_params, timeout=10)
        recent_bills = recent_response.json().get("bills", []) if recent_response.status_code == 200 else []
    except Exception:
        recent_bills = []

    recent = []
    for bill in recent_bills:
        key = f"{bill.get('congress')}{(bill.get('type') or '').lower()}{bill.get('number')}"
        if key == original_key:
            continue
        if not bill.get("number") or not bill.get("type"):
            continue
        recent.append(bill_to_result(bill))
        if len(recent) >= max_recent:
            break

    results = ([original] if original else []) + recent

    log_action(
        agent_name="title_search",
        action="search_by_title",
        input_data={"named_entity": named_entity},
        output_data={"original_found": original is not None, "recent_count": len(recent)}
    )

    return results