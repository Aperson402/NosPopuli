import requests
import os
from dotenv import load_dotenv
from documentor_agent import log_action
from state_search_agent import STATE_JURISDICTIONS, ENABLED_STATES

load_dotenv()

OPENSTATES_API_KEY = os.getenv("OPENSTATES_API_KEY")
OPENSTATES_BASE = "https://v3.openstates.org"


def search_state_member(name, state_code):
    """Search for a state legislator by name."""
    state_code = state_code.upper()
    jurisdiction = STATE_JURISDICTIONS.get(state_code)

    if not jurisdiction:
        return None

    params = {
        "name": name,
        "jurisdiction": jurisdiction,
        "include": ["other_names", "links"],
    }
    headers = {"X-API-KEY": OPENSTATES_API_KEY}

    try:
        r = requests.get(
            f"{OPENSTATES_BASE}/people",
            params=params,
            headers=headers,
            timeout=10
        )
        if r.status_code != 200:
            return None

        results = r.json().get("results", [])
        if not results:
            return None

        p = results[0]
        return normalize_state_member(p, state_code)

    except Exception as e:
        print(f"[STATE MEMBER] Search error: {e}")
        return None


def fetch_state_member_profile(ocd_person_id):
    """Fetch full profile for a state legislator."""
    person_id = ocd_person_id.replace("/", "%2F")
    url = f"{OPENSTATES_BASE}/people/{person_id}"
    params = {
        "include": ["other_names", "links", "sources"],
    }
    headers = {"X-API-KEY": OPENSTATES_API_KEY}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        return normalize_state_member(r.json(), None)
    except Exception as e:
        print(f"[STATE MEMBER] Profile error: {e}")
        return None


def fetch_state_member_bills(ocd_person_id, state_code, limit=10):
    """Fetch bills sponsored by a state legislator."""
    jurisdiction = STATE_JURISDICTIONS.get(state_code.upper(), "")
    session = None

    from state_search_agent import STATE_SESSIONS
    session = STATE_SESSIONS.get(state_code.upper())

    params = {
        "jurisdiction": jurisdiction,
        "sponsor": ocd_person_id,
        "pageSize": limit,
        "include": "sponsorships",
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

        bills = []
        for bill in r.json().get("results", []):
            bills.append({
                "ocd_id": bill.get("id"),
                "identifier": bill.get("identifier", ""),
                "title": bill.get("title", ""),
                "session": bill.get("session", ""),
                "latest_action": bill.get("latest_action_description", ""),
                "date": bill.get("latest_action_date", ""),
                "is_state_bill": True,
            })
        return bills

    except Exception as e:
        print(f"[STATE MEMBER] Bills error: {e}")
        return []


def normalize_state_member(p, state_code):
    """Normalize OpenStates person object to NosPopuli member shape."""
    current_role = {}
    roles = p.get("current_role") or {}

    return {
        "ocd_person_id": p.get("id"),
        "name": p.get("name", ""),
        "party": p.get("party", ""),
        "state": state_code or p.get("jurisdiction", {}).get("name", ""),
        "chamber": roles.get("org_classification", ""),
        "district": roles.get("district", ""),
        "title": roles.get("title", ""),
        "email": p.get("email", ""),
        "photo_url": p.get("image", ""),
        "links": [l.get("url") for l in p.get("links", [])],
        "current": True,
        "is_state_legislator": True,
        "source": "openstates",
    }