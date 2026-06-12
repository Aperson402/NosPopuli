import requests
import re
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from cachetools import TTLCache, cached
from threading import RLock
from documentor_agent import log_action

load_dotenv()

OPENSTATES_API_KEY = os.getenv("OPENSTATES_API_KEY")
OPENSTATES_BASE = "https://v3.openstates.org"

_session = requests.Session()
_bill_cache = TTLCache(maxsize=256, ttl=1800)   # 30 min — state bills update more frequently
_text_cache = TTLCache(maxsize=128, ttl=7200)   # 2 hours — bill text is stable
_text_lock  = RLock()


@cached(cache=_bill_cache, lock=RLock())
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
        r = _session.get(url, params=params, headers=headers, timeout=30)
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


def _normalize_bill_text(text):
    """
    Clean and reformat raw legislative bill text for readable display.

    Formatting rules:
    1. Strip unicode whitespace artifacts (non-breaking spaces, etc.)
    2. Remove lines that are purely whitespace
    3. Join structural fragment lines — bare parentheticals "(2)" and section
       labels "Sec." that were split into their own elements by the HTML source
    4. Join prose lines that were wrapped at ~60 chars in the source HTML
    5. Preserve intentional structure: SECTION N, Sec., (N), (a) always start
       their own line; ALL-CAPS headers that end with . or : are treated as complete
    6. Add a single blank line before each major SECTION to aid scanning
    """
    # 1. Normalize unicode whitespace artifacts
    text = text.replace('\xa0', ' ').replace(' ', ' ').replace(' ', ' ')

    # 2. Strip each line; drop lines that are pure whitespace after stripping
    lines = [l.strip() for l in text.split('\n')]
    lines = [l for l in lines if l]

    # 3. Join structural fragment lines with the line that follows them.
    #    Fragments: bare parentheticals "(2)", bare "Sec.", bare section numbers "240.912."
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt  = lines[i + 1] if i + 1 < len(lines) else None

        is_bare_paren = bool(re.match(r'^\([0-9a-zA-Z]+\)$', line))
        is_bare_sec   = bool(re.match(r'^Sec\.$', line, re.IGNORECASE))
        is_bare_num   = bool(re.match(r'^\d+\.\d[\d\.]*\.$', line))

        if nxt and (is_bare_paren or is_bare_sec or is_bare_num):
            merged.append(line + '  ' + nxt)
            i += 2
        else:
            merged.append(line)
            i += 1
    lines = merged

    # Patterns for structure detection
    SECTION_START = re.compile(
        r'^(SECTION\s+\d|SEC\.\s+\d|BE IT\s|AN ACT|A BILL\s|By:|'
        r'H\.[BCJ-SJ]\.(\s+No\.)?|S\.[BCJ]\.(\s+No\.)?|'
        r'TITLE\s+[IVX\d]|SUBTITLE\s+[A-Z]|'
        r'CHAPTER\s+\d|SUBCHAPTER\s+[A-Z]|ARTICLE\s+\d)',
        re.IGNORECASE
    )
    SUBSEC_START = re.compile(r'^\([0-9a-zA-Z]+\)\s')
    TERMINAL     = re.compile(r'[.;:?!]$')
    # All-caps header that is itself a complete line (ends with . or :)
    CAPS_HEADER  = re.compile(r'^[A-Z][A-Z0-9\s\-\.]+[.:]$')

    # 4. Join prose lines that were wrapped at the source
    result = []
    for line in lines:
        if not result:
            result.append(line)
            continue

        prev = result[-1]
        prev_complete  = bool(TERMINAL.search(prev)) or bool(CAPS_HEADER.match(prev))
        line_new_block = bool(SECTION_START.match(line)) or bool(SUBSEC_START.match(line))

        if not prev_complete and not line_new_block:
            result[-1] = prev + ' ' + line
        else:
            result.append(line)

    # 5. Add a blank line before each major SECTION N for visual separation
    MAJOR_SECTION = re.compile(r'^SECTION\s+\d', re.IGNORECASE)
    spaced = []
    for i, line in enumerate(result):
        if i > 0 and MAJOR_SECTION.match(line):
            spaced.append('')
        spaced.append(line)

    return '\n'.join(spaced).strip()


def fetch_state_bill_text(bill_data):
    """
    Fetch HTML text of the bill from the version links.
    Prefers: Chaptered > Enrolled > Engrossed > Introduced
    """
    if not bill_data:
        return None

    ocd_id = bill_data.get("id")
    if ocd_id:
        with _text_lock:
            if ocd_id in _text_cache:
                return _text_cache[ocd_id]

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
        r = _session.get(selected_url, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        raw  = soup.get_text(separator="\n")
        result = _normalize_bill_text(raw)

        if ocd_id and result:
            with _text_lock:
                _text_cache[ocd_id] = result
        return result

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


