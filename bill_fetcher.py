import re
import requests
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from cachetools import TTLCache, cached
from threading import RLock
from documentor_agent import log_action

load_dotenv()

CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

_session = requests.Session()

_bill_cache         = TTLCache(maxsize=256, ttl=3600)
_actions_cache      = TTLCache(maxsize=256, ttl=1800)
_text_cache         = TTLCache(maxsize=128, ttl=7200)
_related_cache      = TTLCache(maxsize=256, ttl=3600)
_amendments_cache   = TTLCache(maxsize=256, ttl=3600)
_cosponsors_cache   = TTLCache(maxsize=256, ttl=3600)

@cached(cache=_bill_cache, lock=RLock())
def fetch_bill(congress_number, bill_type, bill_number):
    url = f"https://api.congress.gov/v3/bill/{congress_number}/{bill_type}/{bill_number}"
    
    params = {
        "api_key": CONGRESS_API_KEY,
        "format": "json"
    }
    
    try:
        response = _session.get(url, params=params, timeout=10)
    except requests.exceptions.Timeout:
        print(f"[BILL FETCHER] Timeout fetching {bill_type}{bill_number}")
        return None
    except requests.exceptions.ConnectionError:
        print(f"[BILL FETCHER] Connection error fetching {bill_type}{bill_number}")
        return None
    except Exception as e:
        print(f"[BILL FETCHER] Unexpected error: {e}")
        return None
    
    if response.status_code == 429:
        print(f"[BILL FETCHER] Rate limited by Congress.gov")
        return None
    
    if response.status_code == 404:
        print(f"[BILL FETCHER] Bill not found: {bill_type}{bill_number}")
        return None
    
    if response.status_code != 200:
        print(f"[BILL FETCHER] Error {response.status_code} for {bill_type}{bill_number}")
        return None
    
    try:
        data = response.json()
    except Exception as e:
        print(f"[BILL FETCHER] Failed to parse JSON: {e}")
        return None
    
    if "bill" not in data:
        print(f"[BILL FETCHER] Unexpected response structure for {bill_type}{bill_number}")
        return None
    
    bill = data["bill"]
    
    # Safe extraction with fallbacks
    title = bill.get("title", "Unknown title")
    latest_action = (bill.get("latestAction") or {}).get("text", "No action recorded")
    
    log_action(
        agent_name="bill_fetcher",
        action="fetch_bill",
        input_data={
            "congress": congress_number,
            "type": bill_type,
            "number": bill_number
        },
        output_data={
            "title": title,
            "status": latest_action
        }
    )
    
    return data
def fetch_law(congress, law_number):
    """
    Fetches bill data by public law number.
    """
    url = f"https://api.congress.gov/v3/law/{congress}/pub/{law_number}"
    
    params = {
        "api_key": CONGRESS_API_KEY,
        "format": "json"
    }
    
    try:
        response = _session.get(url, params=params, timeout=10)
    except requests.exceptions.Timeout:
        print(f"[BILL FETCHER] Timeout fetching law {congress} pub {law_number}")
        return None
    except Exception as e:
        print(f"[BILL FETCHER] Error fetching law: {e}")
        return None

    if response.status_code == 429:
        print(f"[BILL FETCHER] Rate limited fetching law")
        return None
    if response.status_code == 404:
        print(f"[BILL FETCHER] Law {congress} pub {law_number} not in item endpoint — trying list fallback")
        fallback_url = f"https://api.congress.gov/v3/law/{congress}/pub"
        try:
            r2 = _session.get(fallback_url, params={**params, "limit": 250}, timeout=10)
            if r2.status_code == 200:
                for bill in r2.json().get("bills", []):
                    for law in (bill.get("laws") or []):
                        raw = str(law.get("number", ""))
                        # Normalise "119-98" → "98" before comparing
                        seq = raw.split("-")[-1] if "-" in raw else raw
                        if seq == str(law_number):
                            bill_type = (bill.get("type") or "").lower()
                            bill_number_val = bill.get("number")
                            if bill_type and bill_number_val:
                                return fetch_bill(congress, bill_type, int(bill_number_val))
        except Exception as e:
            print(f"[BILL FETCHER] Fallback error: {e}")
        return None
    if response.status_code != 200:
        print(f"[BILL FETCHER] Law not found: {congress} pub {law_number}")
        return None

    try:
        data = response.json()
    except Exception:
        return None

    bill = data.get("bill")
    
    if not bill:
        return None
    
    # Extract bill identifiers directly from the bill object
    bill_congress = bill.get("congress", congress)
    bill_type = bill.get("type", "").lower()
    bill_number = bill.get("number")
    
    if not bill_type or not bill_number:
        return None
    
    log_action(
        agent_name="bill_fetcher",
        action="fetch_law",
        input_data={"congress": congress, "law_number": law_number},
        output_data={"bill_type": bill_type, "bill_number": bill_number}
    )
    
    # Fetch full bill data using existing fetch_bill
    return fetch_bill(bill_congress, bill_type, int(bill_number))
@cached(cache=_related_cache, lock=RLock())
def fetch_related_bills(congress, bill_type, bill_number, max_results=5):
    """
    Fetch related bills from Congress.gov, grouped by relationship type.
    Returns dict: {identical, related, superseded} — drops 'Procedurally related'.
    """
    url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}/relatedbills"
    params = {"api_key": CONGRESS_API_KEY, "format": "json", "limit": 50}

    try:
        r = _session.get(url, params=params, timeout=10)
    except Exception as e:
        print(f"[BILL FETCHER] Related bills error: {e}")
        return {"identical": [], "related": [], "superseded": []}

    if r.status_code != 200:
        print(f"[BILL FETCHER] Related bills: HTTP {r.status_code}")
        return {"identical": [], "related": [], "superseded": []}

    try:
        raw = r.json().get("relatedBills", [])
    except Exception:
        return {"identical": [], "related": [], "superseded": []}

    identical = []
    related = []
    superseded = []
    seen = set()

    for b in raw:
        details = b.get("relationshipDetails", [])
        rel_type = details[0].get("type", "") if details else ""
        if rel_type == "Procedurally related":
            continue

        key = f"{b.get('congress')}{(b.get('type') or '').lower()}{b.get('number')}"
        if key in seen:
            continue
        seen.add(key)

        entry = {
            "congress": b.get("congress"),
            "type": (b.get("type") or "").lower(),
            "number": b.get("number"),
            "title": b.get("title", "").strip(),
            "latest_action": (b.get("latestAction") or {}).get("text", ""),
            "latest_action_date": (b.get("latestAction") or {}).get("actionDate", ""),
        }

        if rel_type == "Identical bill":
            identical.append(entry)
        elif rel_type == "Superseded by":
            superseded.append(entry)
        else:
            related.append(entry)

    # Identical: keep only most recent by latest_action_date
    if len(identical) > 1:
        identical.sort(key=lambda x: x.get("latest_action_date") or "", reverse=True)
        identical = identical[:1]

    return {
        "identical": identical,
        "related": related[:max_results],
        "superseded": superseded[:1],
    }


@cached(cache=_amendments_cache, lock=RLock())
def fetch_amendments(congress, bill_type, bill_number, max_results=50):
    """
    Fetch amendments formally filed against this bill from Congress.gov.
    Returns list of amendment entries, capped at max_results.
    """
    url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}/amendments"
    params = {"api_key": CONGRESS_API_KEY, "format": "json", "limit": max_results}

    try:
        r = _session.get(url, params=params, timeout=10)
    except Exception as e:
        print(f"[BILL FETCHER] Amendments error: {e}")
        return []

    if r.status_code == 404:
        return []
    if r.status_code != 200:
        print(f"[BILL FETCHER] Amendments: HTTP {r.status_code}")
        return []

    try:
        raw = r.json().get("amendments", [])
    except Exception:
        return []

    results = []
    for a in raw:
        atype = (a.get("type") or "").upper()
        number = a.get("number")
        title = (a.get("description") or a.get("purpose") or "").strip()
        # Skip amendments with no real title — just the bare identifier repeated
        if not title or title.upper() == f"{atype} {number}":
            continue
        results.append({
            "congress": a.get("congress"),
            "type": atype.lower(),
            "number": number,
            "title": title,
            "latest_action": (a.get("latestAction") or {}).get("text", ""),
            "latest_action_date": (a.get("latestAction") or {}).get("actionDate", ""),
        })

    return results


_AMENDS_PATTERNS = [
    re.compile(r"[Tt]o\s+amend\s+(?:the\s+)?(.+?)\s+(?:of\s+\d{4})?(?:,|\.|to\b)", re.IGNORECASE),
    re.compile(r"[Tt]o\s+reauthorize\s+(?:the\s+)?(.+?)\s+(?:of\s+\d{4})?(?:,|\.|to\b)", re.IGNORECASE),
]
_REAUTH_PATTERN = re.compile(r"reauthorize", re.IGNORECASE)

def parse_amends_from_title(title: str, summary: str = "") -> dict | None:
    """
    Extract what law a bill amends or reauthorizes from its title, falling back
    to the first paragraph of the summary if the title yields nothing.
    Returns {"label": "Amends"|"Reauthorizes", "act_name": str} or None.
    """
    sources = [title or ""]
    if summary:
        first_para = (summary or "").split("\n")[0][:400]
        sources.append(first_para)

    for text in sources:
        for pattern in _AMENDS_PATTERNS:
            m = pattern.search(text)
            if m:
                act_name = m.group(1).strip().rstrip(",.")
                if len(act_name) < 5 or len(act_name) > 120:
                    continue
                label = "Reauthorizes" if _REAUTH_PATTERN.search(text[:m.start() + 15]) else "Amends"
                return {"label": label, "act_name": act_name}

    return None


@cached(cache=_text_cache, lock=RLock())
def fetch_bill_text(congress, bill_type, bill_number, max_chars=8000):
    """
    Fetch and strip actual bill text from GovInfo via Congress.gov text versions endpoint.
    Returns cleaned plain text capped at max_chars, or None if unavailable.
    """
    url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}/text"
    params = {"api_key": CONGRESS_API_KEY, "format": "json"}

    try:
        r = _session.get(url, params=params, timeout=10)
    except Exception as e:
        print(f"[BILL FETCHER] Text versions error: {e}")
        return None

    if r.status_code != 200:
        print(f"[BILL FETCHER] Text versions: HTTP {r.status_code}")
        return None

    try:
        versions = r.json().get("textVersions", [])
    except Exception:
        return None

    if not versions:
        return None

    # Pick most recent version; prefer Enrolled > Engrossed > Introduced
    FORMAT_PRIORITY = ["Enrolled Bill", "Engrossed in Senate", "Engrossed in House", "Introduced in Senate", "Introduced in House"]
    selected_url = None

    for priority in FORMAT_PRIORITY:
        for version in versions:
            if priority.lower() in (version.get("type") or "").lower():
                for fmt in version.get("formats", []):
                    if fmt.get("type") == "Formatted Text":
                        selected_url = fmt.get("url")
                        break
            if selected_url:
                break
        if selected_url:
            break

    # Fallback — first Formatted Text URL available
    if not selected_url:
        for version in versions:
            for fmt in version.get("formats", []):
                if fmt.get("type") == "Formatted Text":
                    selected_url = fmt.get("url")
                    break
            if selected_url:
                break

    if not selected_url:
        print(f"[BILL FETCHER] No formatted text URL found for {bill_type}{bill_number}")
        return None

    try:
        r = _session.get(selected_url, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator="\n")
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        text = text.strip()

        print(f"[BILL FETCHER] Fetched bill text: {len(text)} chars for {bill_type}{bill_number}")
        return text[:max_chars]

    except Exception as e:
        print(f"[BILL FETCHER] Text fetch error: {e}")
        return None


@cached(cache=_cosponsors_cache, lock=RLock())
def fetch_cosponsors(congress, bill_type, bill_number, limit=250):
    """
    Fetches cosponsors for a bill from Congress.gov.
    Returns list of cosponsor dicts with name, party, state, bioguide_id.
    """
    url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}/cosponsors"
    params = {"api_key": CONGRESS_API_KEY, "format": "json", "limit": limit}

    try:
        r = _session.get(url, params=params, timeout=10)
    except Exception as e:
        print(f"[BILL FETCHER] Cosponsors error: {e}")
        return []

    if r.status_code != 200:
        print(f"[BILL FETCHER] Cosponsors: HTTP {r.status_code}")
        return []

    try:
        raw = r.json().get("cosponsors", [])
    except Exception:
        return []

    result = []
    for c in raw:
        result.append({
            "name": c.get("fullName", ""),
            "first_name": c.get("firstName", ""),
            "last_name": c.get("lastName", ""),
            "party": c.get("party", ""),
            "state": c.get("state", ""),
            "bioguide_id": c.get("bioguideId", ""),
            "sponsorship_date": c.get("sponsorshipDate", ""),
            "is_original": c.get("isOriginalCosponsor", False),
        })
    return result


if __name__ == "__main__":
    import json
    
    url = f"https://api.congress.gov/v3/law/119/pub/87"
    params = {"api_key": CONGRESS_API_KEY, "format": "json"}
    response = requests.get(url, params=params, timeout=10)
    
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2)[:2000])
    
    