import re
import json
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from documentor_agent import log_action
from search_agent import parse_package_id

load_dotenv()

CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")
GOVINFO_API_KEY = os.getenv("GovInfo_API_KEY")

CACHE_PATH = os.path.join(os.path.dirname(__file__), "popular_names_cache.json")
CACHE_MAX_AGE_DAYS = 7
SCRAPE_COOLDOWN_HOURS = 6  # don't retry a failed scrape for this long
SCRAPE_FAILURE_SENTINEL = "__scrape_failed__"

# Small hardcoded table for acts where Congress.gov title search is unreliable
# (popular name differs significantly from official title, or the source bill is
# very old and poorly indexed)
POPULAR_NAMES = {
    # Education
    "title ix":                {"congress": 92,  "type": "s",  "number": 659,  "title": "Education Amendments of 1972"},
    "title 9":                 {"congress": 92,  "type": "s",  "number": 659,  "title": "Education Amendments of 1972"},
    # Civil Rights Act of 1964 titles
    "title vi":                {"congress": 88,  "type": "hr", "number": 7152, "title": "Civil Rights Act of 1964"},
    "title vii":               {"congress": 88,  "type": "hr", "number": 7152, "title": "Civil Rights Act of 1964"},
    "title 6":                 {"congress": 88,  "type": "hr", "number": 7152, "title": "Civil Rights Act of 1964"},
    "title 7":                 {"congress": 88,  "type": "hr", "number": 7152, "title": "Civil Rights Act of 1964"},
    # Fair Housing Act (Title VIII of Civil Rights Act of 1968)
    "title viii":              {"congress": 90,  "type": "hr", "number": 2516, "title": "Civil Rights Act of 1968 (Fair Housing Act)"},
    "title 8":                 {"congress": 90,  "type": "hr", "number": 2516, "title": "Civil Rights Act of 1968 (Fair Housing Act)"},
    "fair housing act":        {"congress": 90,  "type": "hr", "number": 2516, "title": "Civil Rights Act of 1968 (Fair Housing Act)"},
    # Other landmarks
    "voting rights act":       {"congress": 89,  "type": "hr", "number": 6400, "title": "Voting Rights Act of 1965"},
    "civil rights act":        {"congress": 88,  "type": "hr", "number": 7152, "title": "Civil Rights Act of 1964"},
    "civil rights act of 1968":{"congress": 90,  "type": "hr", "number": 2516, "title": "Civil Rights Act of 1968"},
    "equal pay act":           {"congress": 88,  "type": "hr", "number": 6060, "title": "Equal Pay Act of 1963"},
    "ada":                     {"congress": 101, "type": "s",  "number": 933,  "title": "Americans with Disabilities Act of 1990"},
    "americans with disabilities act": {"congress": 101, "type": "s", "number": 933, "title": "Americans with Disabilities Act of 1990"},
    # Recent acts where short popular names are too generic for relevance search
    "chips act":               {"congress": 117, "type": "hr", "number": 4346, "title": "CHIPS and Science Act"},
    "chips and science act":   {"congress": 117, "type": "hr", "number": 4346, "title": "CHIPS and Science Act"},
    "pact act":                {"congress": 117, "type": "hr", "number": 3967, "title": "Honoring our PACT Act of 2022"},
    "honoring our pact act":   {"congress": 117, "type": "hr", "number": 3967, "title": "Honoring our PACT Act of 2022"},
    "farm bill":               {"congress": 115, "type": "hr", "number": 2,    "title": "Agriculture Improvement Act of 2018"},
    "agriculture improvement act": {"congress": 115, "type": "hr", "number": 2, "title": "Agriculture Improvement Act of 2018"},
    # Landmark recent statutes
    "affordable care act":     {"congress": 111, "type": "hr", "number": 3590, "title": "Patient Protection and Affordable Care Act"},
    "obamacare":               {"congress": 111, "type": "hr", "number": 3590, "title": "Patient Protection and Affordable Care Act"},
    "dodd-frank":              {"congress": 111, "type": "hr", "number": 4173, "title": "Dodd-Frank Wall Street Reform and Consumer Protection Act"},
    "dodd frank":              {"congress": 111, "type": "hr", "number": 4173, "title": "Dodd-Frank Wall Street Reform and Consumer Protection Act"},
    # National security / surveillance landmarks
    "patriot act":             {"congress": 107, "type": "hr", "number": 3162, "title": "USA PATRIOT Act"},
    "usa patriot act":         {"congress": 107, "type": "hr", "number": 3162, "title": "USA PATRIOT Act"},
    "freedom act":             {"congress": 114, "type": "hr", "number": 2048, "title": "USA FREEDOM Act of 2015"},
    "usa freedom act":         {"congress": 114, "type": "hr", "number": 2048, "title": "USA FREEDOM Act of 2015"},
}

# ---------------------------------------------------------------------------
# Popular names cache — scraped from congress.gov/popular-names weekly
# ---------------------------------------------------------------------------

def _cache_is_stale():
    if not os.path.exists(CACHE_PATH):
        return True
    age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(CACHE_PATH))
    return age > timedelta(days=CACHE_MAX_AGE_DAYS)

def _scrape_popular_names():
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = requests.get(
            "https://www.congress.gov/popular-names",
            headers=headers,
            timeout=20,
        )
        if response.status_code != 200:
            print(f"[POPULAR NAMES] Scrape failed: HTTP {response.status_code}")
            return {}
    except Exception as e:
        print(f"[POPULAR NAMES] Scrape error: {e}")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    cache = {}

    # The page renders a table where each row has: popular name | citation(s)
    # Citations look like "118 H.R. 1234" or "89 S. 456"
    bill_pattern = re.compile(
        r"(\d{2,3})\s+(H\.R\.|S\.|H\.J\.Res\.|S\.J\.Res\.|H\.Con\.Res\.|S\.Con\.Res\.|H\.Res\.|S\.Res\.)\s*(\d+)",
        re.IGNORECASE,
    )
    type_map = {
        "h.r.": "hr", "s.": "s", "h.j.res.": "hjres", "s.j.res.": "sjres",
        "h.con.res.": "hconres", "s.con.res.": "sconres", "h.res.": "hres", "s.res.": "sres",
    }

    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        name = cells[0].get_text(separator=" ", strip=True).lower()
        citation_text = cells[1].get_text(separator=" ", strip=True)

        match = bill_pattern.search(citation_text)
        if not match or not name:
            continue

        congress = int(match.group(1))
        bill_type = type_map.get(match.group(2).lower().replace(" ", ""), match.group(2).lower())
        number = int(match.group(3))

        cache[name] = {"congress": congress, "type": bill_type, "number": number}

    print(f"[POPULAR NAMES] Scraped {len(cache)} entries")
    return cache

def _load_popular_names_cache():
    if _cache_is_stale():
        # Check if we recently failed — avoid hammering a 403 source
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH) as f:
                    existing = json.load(f)
                if existing.get(SCRAPE_FAILURE_SENTINEL):
                    failed_at = existing[SCRAPE_FAILURE_SENTINEL]
                    age_hours = (datetime.now() - datetime.fromisoformat(failed_at)).total_seconds() / 3600
                    if age_hours < SCRAPE_COOLDOWN_HOURS:
                        print(f"[POPULAR NAMES] Scrape failed {age_hours:.1f}h ago — skipping retry")
                        return {}
            except Exception:
                pass

        print("[POPULAR NAMES] Cache stale or missing — refreshing")
        data = _scrape_popular_names()
        if data:
            try:
                with open(CACHE_PATH, "w") as f:
                    json.dump(data, f)
            except Exception as e:
                print(f"[POPULAR NAMES] Failed to write cache: {e}")
        else:
            # Write a failure sentinel so we don't retry for SCRAPE_COOLDOWN_HOURS
            try:
                with open(CACHE_PATH, "w") as f:
                    json.dump({SCRAPE_FAILURE_SENTINEL: datetime.now().isoformat()}, f)
            except Exception:
                pass
            return {}

    if not os.path.exists(CACHE_PATH):
        return {}

    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        # Don't expose the sentinel key as real cache entries
        return {k: v for k, v in data.items() if k != SCRAPE_FAILURE_SENTINEL}
    except Exception:
        return {}

# ---------------------------------------------------------------------------
# GovInfo phrase search — matches "may be cited as" preamble text
# ---------------------------------------------------------------------------

def _govinfo_phrase_search(act_name):
    payload = {
        "query": f'"{act_name}" collection:BILLS',
        "pageSize": 5,
        "offsetMark": "*",
        "sorts": [{"field": "score", "sortOrder": "DESC"}],
    }
    try:
        response = requests.post(
            "https://api.govinfo.gov/search",
            json=payload,
            params={"api_key": GOVINFO_API_KEY},
            timeout=15,
        )
        if response.status_code != 200:
            print(f"[TITLE SEARCH] GovInfo phrase search: HTTP {response.status_code}")
            return None
        results = response.json().get("results", [])
        if not results:
            return None

        item = results[0]
        parsed = parse_package_id(item.get("packageId", ""))
        if not parsed:
            return None

        return {
            "congress": parsed["congress"],
            "type": parsed["type"],
            "number": parsed["number"],
            "title": item.get("title", ""),
            "date_issued": item.get("dateIssued", ""),
            "latest_action": "",
            "source": "govinfo_phrase",
            "is_original": True,
            "is_law": False,
            "law_number": None,
        }
    except Exception as e:
        print(f"[TITLE SEARCH] GovInfo phrase search error: {e}")
        return None

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def search_by_title(named_entity, max_recent=3):
    """
    Multi-phase title search for named acts.

    Phase 0: hardcoded POPULAR_NAMES table (historical acts with divergent titles)
    Phase 1: scraped congress.gov popular names cache (auto-refreshed weekly)
    Phase 2: Congress.gov relevance search
    Phase 3: GovInfo full-text phrase search ("may be cited as" preamble)
    """
    url = "https://api.congress.gov/v3/bill"
    entity_lower = named_entity.lower().strip()

    def bill_to_result(bill, is_original=False, source="title_search"):
        return {
            "congress": bill.get("congress"),
            "type": (bill.get("type") or "").lower(),
            "number": bill.get("number"),
            "title": bill.get("title", ""),
            "date_issued": (bill.get("latestAction") or {}).get("actionDate", "") if source == "title_search" else bill.get("date_issued", ""),
            "latest_action": (bill.get("latestAction") or {}).get("text", "") if source == "title_search" else "",
            "source": source,
            "is_original": is_original,
            "is_law": False,
            "law_number": None,
        }

    original = None

    # Phase 0 — hardcoded table.
    # Try the literal key first, then a year-stripped variant ("act of 2022" → "act"),
    # since the router often appends an official year that the table omits.
    _lookup_keys = [entity_lower]
    _year_stripped = re.sub(r"\s+of\s+\d{4}\s*$", "", entity_lower).strip()
    if _year_stripped and _year_stripped != entity_lower:
        _lookup_keys.append(_year_stripped)

    _hit_key = next((k for k in _lookup_keys if k in POPULAR_NAMES), None)
    if _hit_key:
        entry = POPULAR_NAMES[_hit_key]
        original = {
            "congress": entry["congress"],
            "type": entry["type"].lower(),
            "number": entry["number"],
            "title": entry["title"],
            "date_issued": "",
            "latest_action": "",
            "source": "popular_names_hardcoded",
            "is_original": True,
            "is_law": False,
            "law_number": None,
        }

    # Phase 1 — scraped popular names cache
    if original is None:
        cache = _load_popular_names_cache()
        if entity_lower in cache:
            entry = cache[entity_lower]
            original = {
                "congress": entry["congress"],
                "type": entry["type"],
                "number": entry["number"],
                "title": named_entity,
                "date_issued": "",
                "latest_action": "",
                "source": "popular_names_cache",
                "is_original": True,
                "is_law": False,
                "law_number": None,
            }

    # Phase 2 — Congress.gov relevance search
    STOP_WORDS = {"act", "the", "of", "and", "for", "to", "a", "an", "in", "on", "with", "law"}
    query_keywords = {w for w in entity_lower.split() if w not in STOP_WORDS and len(w) > 2}

    # Detect acronym-style queries: any ALL-CAPS word 2+ chars (e.g. "SAVE Act", "CHIPS Act")
    _acronym_match = re.search(r'\b([A-Z]{2,})\b', named_entity)
    acronym = _acronym_match.group(1) if _acronym_match else None

    def title_has_parenthetical_acronym(title):
        """True if the acronym appears in parentheses in the official title, e.g. '(SAVE)'."""
        return bool(re.search(rf'\({re.escape(acronym)}\)', title, re.IGNORECASE))

    def title_matches_query(title):
        title_lower = title.lower()
        return any(kw in title_lower for kw in query_keywords)

    params_original = {
        "api_key": CONGRESS_API_KEY,
        "format": "json",
        "query": named_entity,
        "limit": 50,
    }

    if original is None:
        try:
            response = requests.get(url, params=params_original, timeout=10)
        except Exception as e:
            print(f"[TITLE SEARCH] Congress.gov error: {e}")
            response = None

        if response is not None and response.status_code == 200:
            try:
                bills = response.json().get("bills", [])
            except Exception:
                bills = []

            # Pass 1: prefer titles where the acronym appears in parentheses — "Safeguard ... (SAVE) Act"
            if acronym:
                for bill in bills:
                    if title_has_parenthetical_acronym(bill.get("title", "")):
                        original = bill_to_result(bill, is_original=True)
                        print(f"[TITLE SEARCH] Parenthetical acronym match for ({acronym}): {bill.get('title', '')[:80]}")
                        break

            # Pass 2: fall back to keyword match in first 10 results
            if original is None:
                for bill in bills[:10]:
                    if title_matches_query(bill.get("title", "")):
                        original = bill_to_result(bill, is_original=True)
                        break

            if original is None:
                print(f"[TITLE SEARCH] Congress.gov returned no title-matched results — falling through to GovInfo")

    # Phase 3 — GovInfo full-text phrase search
    if original is None:
        print(f"[TITLE SEARCH] Falling back to GovInfo phrase search for: {named_entity}")
        original = _govinfo_phrase_search(named_entity)

    if original is None:
        log_action(
            agent_name="title_search",
            action="search_by_title",
            input_data={"named_entity": named_entity},
            output_data={"original_found": False, "recent_count": 0}
        )
        return []

    # Fetch recent related bills, excluding original
    original_key = f"{original['congress']}{original['type']}{original['number']}"
    recent_params = {**params_original, "sort": "date+desc"}
    try:
        recent_response = requests.get(url, params=recent_params, timeout=10)
        recent_bills = recent_response.json().get("bills", []) if recent_response.status_code == 200 else []
    except Exception:
        recent_bills = []

    recent = []
    for bill in recent_bills:
        key = f"{bill.get('congress')}{(bill.get('type') or '').lower()}{bill.get('number')}"
        if key == original_key:
            continue
        if not bill.get("number") or not bill.get("type"):
            continue
        recent.append(bill_to_result(bill))
        if len(recent) >= max_recent:
            break

    results = [original] + recent

    log_action(
        agent_name="title_search",
        action="search_by_title",
        input_data={"named_entity": named_entity},
        output_data={
            "original_found": True,
            "original_source": original.get("source"),
            "recent_count": len(recent),
        }
    )

    return results
