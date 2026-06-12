import re
import requests
import os
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

GOVINFO_API_KEY = os.getenv("GovInfo_API_KEY")
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

def search_bills(structured_query, max_results=None):
    if max_results is None:
        max_results = structured_query.get("result_count", 5)
    max_results = min(max_results, 20)

    congress_numbers = structured_query["congress_numbers"]
    status = structured_query.get("status", "any")

    # Route enacted queries to Congress.gov law endpoint — not GovInfo
    if status == "enacted":
        keywords = structured_query.get("expanded_terms") or structured_query.get("keywords") or []
        return search_laws(keywords, congress_numbers, max_results)

    # Use expanded terms if available, fall back to original keywords
    expanded = structured_query.get("expanded_terms") or []
    keywords = structured_query.get("keywords") or []
    terms = expanded or keywords

    # Detect named act queries — use relevance scoring for precision
    original = (structured_query.get("original_question") or "").lower()
    keywords_str = " ".join(keywords).lower()
    is_named_act = "act" in original or "act" in keywords_str or "law" in original
    sort_field = "score" if is_named_act else "publishdate"

    if is_named_act and keywords:
        original_phrase = " ".join(keywords)
        if len(keywords) <= 3:
            all_terms = [original_phrase]
        else:
            all_terms = [original_phrase] + expanded[:2]
    else:
        all_terms = terms[:3]

    terms_query = " OR ".join(f'"{t}"' if " " in t else t for t in all_terms)
    congress_filter = " OR ".join([f"congress:{c}" for c in congress_numbers])

    keywords_lower = " ".join(terms).lower()

    if any(word in keywords_lower for word in ["act", "law", "stablecoin", "guiding"]):
        if terms_query:
            full_query = f"({terms_query}) (collection:BILLS OR collection:PLAW) ({congress_filter})"
        else:
            full_query = f"(collection:BILLS OR collection:PLAW) ({congress_filter})"
    else:
        if terms_query:
            full_query = f"({terms_query}) collection:BILLS ({congress_filter})"
        else:
            full_query = f"collection:BILLS ({congress_filter})"

    sort_order = "DESC"
    payload = {
        "query": full_query,
        "pageSize": max_results * 3,
        "offsetMark": "*",
        "sorts": [{"field": sort_field, "sortOrder": sort_order}]
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
        parsed = parse_package_id(package_id)
        if not parsed:
            continue
        results.append({
            "package_id": package_id,
            "title": item.get("title", "No title"),
            "date_issued": item.get("dateIssued", "Unknown"),
            "congress": parsed["congress"],
            "type": parsed.get("type"),
            "number": parsed.get("number"),
            "is_law": False,
            "law_number": None,
        })

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

def search_summaries(query, congress_numbers):
    """
    Search Congress.gov summaries for named acts.
    Better for finding specific legislation by nickname or popular name.
    """
    results = []

    for congress in congress_numbers[:2]:
        url = f"https://api.congress.gov/v3/summaries/{congress}"
        params = {
            "api_key": CONGRESS_API_KEY,
            "format": "json",
            "limit": 20,
        }

        try:
            r = requests.get(url, params=params, timeout=10)
        except Exception as e:
            print(f"[SEARCH] summaries error: {e}")
            continue

        if r.status_code != 200:
            continue

        try:
            summaries = r.json().get("summaries", [])
        except Exception:
            continue

        query_lower = query.lower()

        for s in summaries:
            text = (s.get("text") or "").lower()
            title = (s.get("bill", {}).get("title") or "").lower()

            if query_lower in text or query_lower in title:
                bill = s.get("bill", {})
                results.append({
                    "congress": bill.get("congress"),
                    "type": (bill.get("type") or "").lower(),
                    "number": bill.get("number"),
                    "title": bill.get("title", ""),
                    "date_issued": s.get("actionDate", ""),
                })

    return results

def search_laws(keywords, congress_numbers, max_results=5):
    """
    Search enacted public laws via Congress.gov law endpoint.
    Use this instead of GovInfo PLAW when status == 'enacted'.
    """
    META_WORDS = {
        "law", "laws", "enacted", "passed", "signed", "became",
        "trump", "biden", "obama", "bush", "clinton", "reagan", "carter",
        "under", "latest", "recent", "bills", "legislation",
    }
    results = []
    seen = set()
    keywords_lower = [k.lower() for k in keywords if k and k.lower() not in META_WORDS]

    for congress in congress_numbers:
        url = f"https://api.congress.gov/v3/law/{congress}/pub"
        params = {
            "api_key": CONGRESS_API_KEY,
            "format": "json",
            "limit": 250,
            "sort": "updateDate+desc"
        }

        try:
            r = requests.get(url, params=params, timeout=10)
        except Exception as e:
            print(f"[SEARCH] search_laws error for congress {congress}: {e}")
            continue

        if r.status_code != 200:
            print(f"[SEARCH] search_laws {congress}: status {r.status_code}")
            continue

        try:
            laws = r.json().get("bills", [])
        except Exception:
            continue

        for law in laws:
            title = (law.get("title") or "").lower()
            raw_law_num = str((law.get("laws") or [{}])[0].get("number", ""))
            # API returns "119-98" format — extract just the sequential number
            law_number = raw_law_num.split("-")[-1] if "-" in raw_law_num else raw_law_num

            if keywords_lower and not any(k in title for k in keywords_lower):
                continue

            bill_type = (law.get("type") or "").lower()
            bill_number = law.get("number")
            bill_congress = law.get("congress", congress)

            key = f"{bill_congress}{bill_type}{bill_number}"
            if key in seen or not bill_number:
                continue
            seen.add(key)

            results.append({
                "package_id": f"BILLS-{bill_congress}{bill_type}{bill_number}",
                "title": law.get("title", ""),
                "date_issued": (law.get("latestAction") or {}).get("actionDate", ""),
                "congress": bill_congress,
                "type": bill_type,
                "number": bill_number,
                "is_law": True,
                "law_number": law_number,
            })

            if len(results) >= max_results:
                return results

    if not results and keywords_lower:
        print(f"[SEARCH] search_laws: no title matches — falling back to GovInfo PLAW full-text")
        results = _govinfo_plaw_search(keywords_lower, congress_numbers, max_results)

    return results


def _govinfo_plaw_search(keywords_lower, congress_numbers, max_results=5):
    """
    GovInfo full-text fallback for enacted law searches when Congress.gov title
    matching returns nothing. Searches the PLAW collection by content keywords.
    """
    terms = [f'"{k}"' if " " in k else k for k in keywords_lower[:4]]
    terms_query = " OR ".join(terms)
    congress_filter = " OR ".join(f"congress:{c}" for c in congress_numbers)
    full_query = f"({terms_query}) collection:PLAW ({congress_filter})"

    payload = {
        "query": full_query,
        "pageSize": max_results * 3,
        "offsetMark": "*",
        "sorts": [{"field": "publishdate", "sortOrder": "DESC"}],
    }

    try:
        r = requests.post(
            "https://api.govinfo.gov/search",
            json=payload,
            params={"api_key": GOVINFO_API_KEY},
            timeout=15,
        )
    except Exception as e:
        print(f"[SEARCH] GovInfo PLAW fallback error: {e}")
        return []

    if r.status_code != 200:
        print(f"[SEARCH] GovInfo PLAW fallback: HTTP {r.status_code}")
        return []

    try:
        raw = r.json().get("results", [])
    except Exception:
        return []

    results = []
    seen = set()
    for item in raw:
        pkg = item.get("packageId", "")
        m = re.match(r"PLAW-(\d+)publ(\d+)", pkg)
        if not m:
            continue
        congress = int(m.group(1))
        law_number = int(m.group(2))
        key = f"{congress}pub{law_number}"
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "package_id": pkg,
            "title": item.get("title", ""),
            "date_issued": item.get("dateIssued", ""),
            "congress": congress,
            "type": None,
            "number": None,
            "is_law": True,
            "law_number": law_number,
        })
        if len(results) >= max_results:
            break

    return results


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