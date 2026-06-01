import requests
import os
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

OPENSTATES_API_KEY = os.getenv("OPENSTATES_API_KEY")
OPENSTATES_BASE = "https://v3.openstates.org"

STATE_JURISDICTIONS = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming"
}

# Current sessions — update as sessions change
STATE_SESSIONS = {
    "VA": "2025",
    "CA": "20252026",
    "TX": "89",
    "NY": "2025",
    "FL": "2025",
}

SKIP_PATTERNS = [
    "celebrating the life", "commending", "recognizing the",
    "honoring the", "congratulating", "acknowledging",
    "commemorating", "proclaiming", "expressing support for the designation"
]

ENABLED_STATES = {"VA"}  # add as each state is built and tested

ENACTED_ACTION_KEYWORDS = [
    "signed by governor", "enacted", "chaptered", "became law",
    "approved by governor", "signed into law",
]


def get_jurisdiction(state_code):
    return STATE_JURISDICTIONS.get(state_code.upper())


def get_session(state_code):
    return STATE_SESSIONS.get(state_code.upper())


def filter_enacted(bills):
    """Keep only bills whose latest action indicates they were signed/enacted."""
    return [
        b for b in bills
        if any(kw in (b.get("latest_action") or "").lower() for kw in ENACTED_ACTION_KEYWORDS)
    ]


def fetch_state_bill_by_identifier(identifier, state_code, session=None):
    """
    Direct lookup of a state bill by its identifier (e.g. 'HB 1234').
    Returns a list (same shape as search_state_bills) with 0 or 1 result.
    """
    state_code = state_code.upper()
    jurisdiction = get_jurisdiction(state_code)
    if not jurisdiction:
        return []

    session = session or get_session(state_code)

    params = {
        "jurisdiction": jurisdiction,
        "identifier": identifier,
        "include": ["abstracts", "sponsorships"],
    }
    if session:
        params["session"] = session

    headers = {"X-API-KEY": OPENSTATES_API_KEY}

    try:
        r = requests.get(
            f"{OPENSTATES_BASE}/bills",
            params=params,
            headers=headers,
            timeout=10
        )
        if r.status_code != 200:
            print(f"[STATE SEARCH] Identifier lookup error {r.status_code}")
            return []

        results = []
        for bill in r.json().get("results", []):
            sponsor = None
            for s in bill.get("sponsorships", []):
                if s.get("primary"):
                    sponsor = s.get("name")
                    break
            results.append({
                "ocd_id": bill.get("id"),
                "identifier": bill.get("identifier", ""),
                "title": bill.get("title", ""),
                "state": state_code,
                "jurisdiction": jurisdiction,
                "session": bill.get("session", ""),
                "chamber": (bill.get("from_organization") or {}).get("classification", ""),
                "latest_action": bill.get("latest_action_description", ""),
                "latest_action_date": bill.get("latest_action_date", ""),
                "sponsor": sponsor,
                "openstates_url": bill.get("openstates_url", ""),
                "is_state_bill": True,
                "source": "openstates",
            })

        log_action(
            agent_name="state_search",
            action="fetch_state_bill_by_identifier",
            input_data={"identifier": identifier, "state": state_code},
            output_data={"found": len(results) > 0}
        )

        return results

    except Exception as e:
        print(f"[STATE SEARCH] Identifier lookup error: {e}")
        return []


def search_state_bills(query, state_code, session=None, limit=5):
    """
    Search OpenStates for bills in a given state.
    Returns normalized bill objects compatible with the frontend.
    """
    state_code = state_code.upper()

    if state_code not in ENABLED_STATES:
        print(f"[STATE SEARCH] State {state_code} not yet enabled")
        return []

    jurisdiction = get_jurisdiction(state_code)
    if not jurisdiction:
        print(f"[STATE SEARCH] Unknown state code: {state_code}")
        return []

    session = session or get_session(state_code)

    params = {
        "jurisdiction": jurisdiction,
        "q": query,
        "per_page": limit * 3,  # fetch extra to filter ceremonial
        "include": ["abstracts", "sponsorships"],
    }

    if session:
        params["session"] = session

    headers = {"X-API-KEY": OPENSTATES_API_KEY}

    try:
        r = requests.get(
            f"{OPENSTATES_BASE}/bills",
            params=params,
            headers=headers,
            timeout=10
        )
    except Exception as e:
        print(f"[STATE SEARCH] Request error: {e}")
        return []

    if r.status_code == 429:
        print(f"[STATE SEARCH] Rate limited")
        return []
    if r.status_code != 200:
        print(f"[STATE SEARCH] Error {r.status_code}: {r.text}")
        return []

    try:
        data = r.json()
    except Exception:
        return []

    results = []
    for bill in data.get("results", []):
        title = bill.get("title", "").lower()

        # Skip ceremonial
        if any(p in title for p in SKIP_PATTERNS):
            continue

        # Normalize to frontend-compatible shape
        sponsor = None
        for s in bill.get("sponsorships", []):
            if s.get("primary"):
                sponsor = s.get("name")
                break

        abstracts = bill.get("abstracts") or []
        abstract_text = abstracts[0].get("abstract", "") if abstracts else ""

        results.append({
            "ocd_id": bill.get("id"),
            "identifier": bill.get("identifier", ""),
            "title": bill.get("title", ""),
            "abstract": abstract_text,
            "subjects": bill.get("subject", []),
            "state": state_code,
            "jurisdiction": jurisdiction,
            "session": bill.get("session", ""),
            "chamber": (bill.get("from_organization") or {}).get("classification", ""),
            "latest_action": bill.get("latest_action_description", ""),
            "latest_action_date": bill.get("latest_action_date", ""),
            "sponsor": sponsor,
            "openstates_url": bill.get("openstates_url", ""),
            "is_state_bill": True,
            "source": "openstates",
        })

        if len(results) >= limit:
            break

    log_action(
        agent_name="state_search",
        action="search_state_bills",
        input_data={"query": query, "state": state_code, "session": session},
        output_data={"results_count": len(results)}
    )

    return results


def get_recent_state_bills(state_code, limit=10, session=None):
    """
    Fetch recent substantive bills for feed generation.
    No query — just latest activity.
    """
    state_code = state_code.upper()

    if state_code not in ENABLED_STATES:
        return []

    jurisdiction = get_jurisdiction(state_code)
    session = session or get_session(state_code)

    params = {
        "jurisdiction": jurisdiction,
        "classification": "bill",
        "per_page": limit * 3,
        "sort": "updated_desc",
    }

    if session:
        params["session"] = session

    headers = {"X-API-KEY": OPENSTATES_API_KEY}

    try:
        r = requests.get(
            f"{OPENSTATES_BASE}/bills",
            params=params,
            headers=headers,
            timeout=10
        )
        if r.status_code != 200:
            return []

        results = []
        for bill in r.json().get("results", []):
            title = bill.get("title", "").lower()
            if any(p in title for p in SKIP_PATTERNS):
                continue
            results.append({
                "ocd_id": bill.get("id"),
                "identifier": bill.get("identifier", ""),
                "title": bill.get("title", ""),
                "state": state_code,
                "session": bill.get("session", ""),
                "chamber": (bill.get("from_organization") or {}).get("classification", ""),
                "latest_action": bill.get("latest_action_description", ""),
                "latest_action_date": bill.get("latest_action_date", ""),
                "is_state_bill": True,
            })
            if len(results) >= limit:
                break

        return results

    except Exception as e:
        print(f"[STATE SEARCH] Recent bills error: {e}")
        return []