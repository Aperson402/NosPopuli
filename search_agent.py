import requests
import os
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

GOVINFO_API_KEY = os.getenv("GovInfo_API_KEY")

def search_bills(structured_query, max_results=5):
    """
    Uses GovInfo search API - real full text search across all congressional bills.
    This is a POST request unlike the Congress.gov API.
    """
    
    keywords = " ".join(structured_query["keywords"])
    congress_numbers = structured_query["congress_numbers"]
    
    # Build congress filter - search across all relevant congresses
    congress_filter = " OR ".join([f"congress:{c}" for c in congress_numbers])
    
    # Full query: keywords + collection filter + congress filter
    full_query = f"{keywords} collection:BILLS ({congress_filter})"
    
    payload = {
        "query": full_query,
        "pageSize": max_results,
        "offsetMark": "*",
        "sorts": [
            {
                "field": "score",
                "sortOrder": "DESC"
            }
        ]
    }
    
    response = requests.post(
        "https://api.govinfo.gov/search",
        json=payload,
        params={"api_key": GOVINFO_API_KEY}
    )
    
    if response.status_code != 200:
        print(f"[SEARCH] Error: {response.status_code} - {response.text[:200]}")
        return []
    
    data = response.json()
    raw_results = data.get("results", [])
    
    results = []
    for item in raw_results:
        package_id = item.get("packageId", "")
        
        # Extract bill type and number from packageId
        # Format is BILLS-119hr1234ih → congress=119, type=hr, number=1234
        parts = package_id.replace("BILLS-", "")
        parsed = parse_package_id(package_id)
        results.append({
            "package_id": package_id,
            "title": item.get("title", "No title"),
            "date_issued": item.get("dateIssued", "Unknown"),
            "congress": parsed["congress"] if parsed else None,
            "type": parsed["type"] if parsed else None,
            "number": parsed["number"] if parsed else None,
        })
    
    log_action(
        agent_name="search",
        action="search_bills",
        input_data={
            "keywords": keywords,
            "congress_numbers": congress_numbers,
            "full_query": full_query
        },
        output_data={
            "total_available": data.get("count", 0),
            "results_returned": len(results)
        }
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