import requests
import os
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

GOVINFO_API_KEY = os.getenv("GovInfo_API_KEY")

def search_bills(structured_query, max_results=None):
    if max_results is None:
        max_results = structured_query.get("result_count", 5)
    max_results = min(max_results, 20)

    congress_numbers = structured_query["congress_numbers"]
    status = structured_query.get("status", "any")

    # Use expanded terms if available, fall back to original keywords
    terms = structured_query.get("expanded_terms") or structured_query.get("keywords", [])

    # Build OR query — quote multi-word terms, leave single words bare
    terms_query = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    congress_filter = " OR ".join([f"congress:{c}" for c in congress_numbers])

    if status == "enacted":
        collection = "PLAW"
        if terms_query:
            full_query = f"({terms_query}) collection:PLAW ({congress_filter})"
        else:
            full_query = f"collection:PLAW ({congress_filter})"
    else:
        collection = "BILLS"
        if terms_query:
            full_query = f"({terms_query}) collection:BILLS ({congress_filter})"
        else:
            full_query = f"collection:BILLS ({congress_filter})"

    payload = {
        "query": full_query,
        "pageSize": max_results,
        "offsetMark": "*",
        "sorts": [{"field": "score", "sortOrder": "DESC"}]
    }

    try:
        response = requests.post(
            "https://api.govinfo.gov/search",
            json=payload,
            params={"api_key": GOVINFO_API_KEY},
            timeout=15
        )
    except requests.exceptions.Timeout:
        print(f"[SEARCH] Timeout")
        return []
    except Exception as e:
        print(f"[SEARCH] Error: {e}")
        return []

    if response.status_code == 429:
        print(f"[SEARCH] Rate limited")
        return []
    if response.status_code != 200:
        print(f"[SEARCH] Error: {response.status_code}")
        return []

    try:
        data = response.json()
    except Exception:
        return []
    raw_results = data.get("results", [])

    results = []
    for item in raw_results:
        package_id = item.get("packageId", "")

        # PLAW package IDs look like PLAW-118publ234
        # BILLS package IDs look like BILLS-118hr1234ih
        if status == "enacted":
            parsed = parse_plaw_package_id(package_id)
        else:
            parsed = parse_package_id(package_id)

        results.append({
            "package_id": package_id,
            "title": item.get("title", "No title"),
            "date_issued": item.get("dateIssued", "Unknown"),
            "congress": parsed["congress"] if parsed else None,
            "type": parsed.get("type"),
            "number": parsed.get("number"),
            "is_law": status == "enacted",
            "law_number": parsed.get("law_number") if status == "enacted" else None,
        })

    # Deduplicate by congress + type + number
    seen = set()
    deduplicated = []
    for r in results:
        key = f"{r.get('congress')}{r.get('type')}{r.get('number')}"
        if key not in seen and r.get('number'):
            seen.add(key)
            deduplicated.append(r)

    log_action(
        agent_name="search",
        action="search_bills",
        input_data={"keywords": terms, "result_count": max_results, "status": status},
        output_data={"total_available": data.get("count", 0), "results_returned": len(deduplicated)}
    )

    return deduplicated[:max_results]

def parse_package_id(package_id):
    """
    Converts BILLS-118hr1211ih → {congress: 118, type: hr, number: 1211}
    """
    import re
    
    # Remove BILLS- prefix
    raw = package_id.replace("BILLS-", "")
    
    # Extract congress number, bill type, bill number
    match = re.match(r"(\d+)([a-z]+)(\d+)", raw)
    
    if match:
        return {
            "congress": int(match.group(1)),
            "type": match.group(2),
            "number": int(match.group(3))
        }
    
    return None
def parse_plaw_package_id(package_id):
    """
    Converts PLAW-118publ234 → {congress: 118, law_number: 234, type: "hr", number: None}
    We won't have bill type/number from this — just the law number.
    """
    import re
    match = re.match(r"PLAW-(\d+)publ(\d+)", package_id)
    if match:
        return {
            "congress": int(match.group(1)),
            "law_number": int(match.group(2)),
            "type": None,
            "number": None,
        }
    return None
if __name__ == "__main__":
    test_query = {
        "keywords": ["student", "loans"],
        "topic": "Bills related to student loans",
        "time_range": "last 5 years",
        "bill_type": "all",
        "congress_numbers": [119, 118, 117]
    }
    
    print("SEARCH AGENT TEST - GovInfo")
    print("-" * 40)
    print(f"Searching for: {test_query['keywords']}")
    print()
    
    results = search_bills(test_query, max_results=5)
    
    print(f"Found {len(results)} bills:")
    print()
    for bill in results:
        print(f"  {bill['package_id']}")
        print(f"  {bill['title'][:80]}")
        print(f"  Date: {bill['date_issued']}")
        print(f"  Parsed: congress={bill['congress']}, type={bill['type']}, number={bill['number']}")
        print()