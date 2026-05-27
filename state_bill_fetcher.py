import requests
import re
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

OPENSTATES_API_KEY = os.getenv("OPENSTATES_API_KEY")
OPENSTATES_BASE = "https://v3.openstates.org"


def fetch_state_bill(ocd_id):
    """
    Fetch full bill detail from OpenStates by OCD ID.
    Includes actions, versions, sponsorships.
    """
    # OCD IDs look like ocd-bill/uuid — encode the slash
    bill_id = ocd_id.replace("/", "%2F") if "/" in ocd_id else ocd_id

    url = f"{OPENSTATES_BASE}/bills/{bill_id}"
    params = {
        "include": ["actions", "versions", "sponsorships", "votes", "abstracts"],
    }
    headers = {"X-API-KEY": OPENSTATES_API_KEY}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
    except Exception as e:
        print(f"[STATE FETCHER] Request error: {e}")
        return None

    if r.status_code != 200:
        print(f"[STATE FETCHER] Error {r.status_code} for {ocd_id}")
        return None

    try:
        return r.json()
    except Exception:
        return None


def fetch_state_bill_text(bill_data):
    """
    Fetch HTML text of the bill from the version links.
    Prefers: Chaptered > Enrolled > Engrossed > Introduced
    """
    if not bill_data:
        return None

    versions = bill_data.get("versions", [])
    if not versions:
        return None

    # Priority order for version selection
    VERSION_PRIORITY = [
        "chaptered", "enacted", "enrolled", "reenrolled",
        "engrossed", "introduced"
    ]

    selected_url = None

    for priority in VERSION_PRIORITY:
        for version in versions:
            note = (version.get("note") or "").lower()
            if priority in note:
                for link in version.get("links", []):
                    if link.get("media_type") == "text/html":
                        selected_url = link["url"]
                        break
            if selected_url:
                break
        if selected_url:
            break

    # Fallback — first HTML link available
    if not selected_url:
        for version in versions:
            for link in version.get("links", []):
                if link.get("media_type") == "text/html":
                    selected_url = link["url"]
                    break
            if selected_url:
                break

    if not selected_url:
        print(f"[STATE FETCHER] No HTML version found")
        return None

    try:
        r = requests.get(selected_url, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator="\n")

        # Clean whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        return text.strip()

    except Exception as e:
        print(f"[STATE FETCHER] Text fetch error: {e}")
        return None


def structure_state_actions(bill_data):
    """
    Convert OpenStates actions to the same structure as federal timeline.
    """
    if not bill_data:
        return []

    actions = bill_data.get("actions", [])
    if not actions:
        return []

    seen = set()
    structured = []

    for a in sorted(actions, key=lambda x: (x.get("order", 0))):
        text = a.get("description", "").strip()
        date = a.get("date", "")
        key = f"{date}:{text[:80]}"

        if key in seen or not text:
            continue
        seen.add(key)

        classifications = a.get("classification", [])
        org = (a.get("organization") or {})
        org_class = org.get("classification", "")
        chamber = "House" if org_class == "lower" else \
                  "Senate" if org_class == "upper" else \
                  org.get("name", "")

        # Detect event type from classifications
        if "became-law" in classifications or "executive-signature" in classifications:
            event_type = "signed"
        elif "executive-veto" in classifications:
            event_type = "vetoed"
        elif "passage" in classifications and "reading-3" in classifications:
            event_type = "passed"
        elif "committee-passage" in classifications:
            event_type = "committee"
        elif "referral-committee" in classifications:
            event_type = "referred"
        elif "introduction" in classifications:
            event_type = "introduced"
        else:
            event_type = "action"

        # Extract vote counts from description
        yea = nay = None
        vote_match = re.search(r'\((\d+)-Y\s+(\d+)-N\)', text)
        if vote_match:
            yea = int(vote_match.group(1))
            nay = int(vote_match.group(2))

        structured.append({
            "date": date,
            "text": make_state_event_title(text, event_type),
            "detail": text if len(text) > 80 else None,
            "chamber": chamber,
            "event_type": event_type,
            "yea": yea,
            "nay": nay,
        })

    return structured


def make_state_event_title(text, event_type):
    """Clean action text into a short readable title."""
    # Truncate at natural breakpoints
    for sep in [' (', '; ', ' - fiscal']:
        if sep in text:
            text = text[:text.index(sep)]

    text = text.rstrip('.,;').strip()

    if len(text) > 100:
        text = text[:100].rsplit(' ', 1)[0] + '…'

    return text


