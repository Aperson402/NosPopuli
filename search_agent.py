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

    keywords = " ".join(structured_query["keywords"])
    congress_numbers = structured_query["congress_numbers"]
    status = structured_query.get("status", "any")

    congress_filter = " OR ".join([f"congress:{c}" for c in congress_numbers])

    # If user wants enacted laws, search PLAW collection instead of BILLS
    if status == "enacted":
        collection = "PLAW"
        full_query = f"{keywords} collection:PLAW ({congress_filter})"
    else:
        collection = "BILLS"
        full_query = f"{keywords} collection:BILLS ({congress_filter})"

    payload = {
        "query": full_query,
        "pageSize": max_results,
        "offsetMark": "*",
        "sorts": [{"field": "score", "sortOrder": "DESC"}]
    }

    response = requests.post(
        "https://api.govinfo.gov/search",
        json=payload,
        params={"api_key": GOVINFO_API_KEY}
    )

    if response.status_code != 200:
        print(f"[SEARCH] Error: {response.status_code}")
        return []

    data = response.json()
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

    log_action(
        agent_name="search",
        action="search_bills",
        input_data={"keywords": keywords, "result_count": max_results, "status": status},
        output_data={"total_available": data.get("count", 0), "results_returned": len(results)}
    )

    return results

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