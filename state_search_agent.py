import requests
import os
from threading import RLock
from dotenv import load_dotenv
from cachetools import TTLCache
from documentor_agent import log_action

load_dotenv()

OPENSTATES_API_KEY = os.getenv("OPENSTATES_API_KEY")
OPENSTATES_BASE = "https://v3.openstates.org"
_session = requests.Session()

_session_lookup_cache = TTLCache(maxsize=60, ttl=86400)  # 24hr — sessions rarely change mid-year
_session_lookup_lock = RLock()

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
    "TX": "891",
    "CA": "20252026",
    "NY": "2025-2026",
    "FL": "2026F",
    "PA": "2025-2026",
    "IL": "104th",
    "OH": "136",
    "GA": "2025_26",
    "NC": "2025",
    "MI": "2025-2026",
    "NJ": "222",
    "VA": "2026",
    "WA": "2025-2026",
    "AZ": "57th-2nd-regular",
    "TN": "114",
    "MA": "194th",
    "IN": "2026",
    # Remaining states — session lookup was rate-limited; will search across all sessions
}

SKIP_PATTERNS = [
    "celebrating the life", "commending", "recognizing the",
    "honoring the", "congratulating", "acknowledging",
    "commemorating", "proclaiming", "expressing support for the designation"
]

ENABLED_STATES = set(STATE_JURISDICTIONS.keys())

ENACTED_ACTION_KEYWORDS = [
    "signed by governor", "enacted", "chaptered", "became law",
    "approved by governor", "signed into law",
]


def get_jurisdiction(state_code):
    return STATE_JURISDICTIONS.get(state_code.upper())


def _lookup_current_session_from_api(state_code):
    """Query OpenStates jurisdictions API for the current session identifier."""
    ocd_id = f"ocd-jurisdiction/country:us/state:{state_code.lower()}/government"
    try:
        r = _session.get(
            f"{OPENSTATES_BASE}/jurisdictions/{ocd_id}",
            headers={"X-API-KEY": OPENSTATES_API_KEY},
            params={"include": ["legislative_sessions"]},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"[STATE SEARCH] Session lookup {r.status_code} for {state_code}")
            return None
        sessions = r.json().get("legislative_sessions", [])
        in_progress = [s for s in sessions if s.get("status") == "in_progress"]
        candidates = in_progress or sessions
        if candidates:
            latest = max(candidates, key=lambda s: s.get("start_date", ""))
            print(f"[STATE SEARCH] Resolved session for {state_code}: {latest['identifier']}")
            return latest["identifier"]
    except Exception as e:
        print(f"[STATE SEARCH] Session lookup error for {state_code}: {e}")
    return None


def get_session(state_code):
    code = state_code.upper()
    if code in STATE_SESSIONS:
        return STATE_SESSIONS[code]
    with _session_lookup_lock:
        if code in _session_lookup_cache:
            return _session_lookup_cache[code]
        session_id = _lookup_current_session_from_api(code)
        _session_lookup_cache[code] = session_id
        return session_id


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
        r = _session.get(
            f"{OPENSTATES_BASE}/bills",
            params=params,
            headers=headers,
            timeout=30
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


def search_state_bills(query, state_code, session=None, limit=10):
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
        "per_page": 20,  # Always fetch max; caller slices
        "sort": "updated_desc",
        "include": ["abstracts", "sponsorships"],
    }

    if session:
        params["session"] = session
    else:
        # No session found — restrict to recent bills so we don't surface stale results
        params["updated_since"] = "2025-01-01"

    headers = {"X-API-KEY": OPENSTATES_API_KEY}

    try:
        r = _session.get(
            f"{OPENSTATES_BASE}/bills",
            params=params,
            headers=headers,
            timeout=30
        )
    except Exception as e:
        print(f"[STATE SEARCH] Request error: {e}")
        return []

    if r.status_code == 429:
        print(f"[STATE SEARCH] Rate limited")
        return []
    if r.status_code != 200:
        print(f"[STATE SEARCH] Error {r.status_code}: {r.text[:300]}")
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
        "per_page": min(limit * 3, 20),  # OpenStates max is 20
        "sort": "updated_desc",
    }

    if session:
        params["session"] = session

    headers = {"X-API-KEY": OPENSTATES_API_KEY}

    try:
        r = _session.get(
            f"{OPENSTATES_BASE}/bills",
            params=params,
            headers=headers,
            timeout=30
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