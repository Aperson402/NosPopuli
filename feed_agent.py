import requests
import os
import json
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from threading import RLock
from cachetools import TTLCache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from documentor_agent import log_action
from state_search_agent import get_recent_state_bills, ENABLED_STATES
from correspondence.db import get_disk_cache, set_disk_cache

# ── Shared HTTP session ──────────────────────────────────────
# Single Session with HTTP keep-alive + a small connection pool eliminates
# the cold-TLS handshake on every Congress.gov call. Costs ~200ms per call
# without it.
_session = requests.Session()
_adapter = HTTPAdapter(
    pool_connections=10,
    pool_maxsize=20,
    max_retries=Retry(total=0, backoff_factor=0),
)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

# ── Curation patterns ─────────────────────────────────────────
# Ceremonial / procedural / honorary titles — never relevant to a citizen feed.
# Applied to rep bills, interest bills, and state bills before they enter the pool.
_CEREMONIAL_PATTERNS = (
    "celebrating the", "expressing support for the designation",
    "recognizing the", "honoring the", "congratulating",
    "acknowledging the", "commemorating", "proclaiming",
    "expressing the sense of", "to designate", "to redesignate",
    "to authorize the president to award", "to award a congressional gold medal",
    "to grant the congressional gold medal", "to name", "naming",
    "designating the week", "designating the month", "national day of",
    "national week of", "national month of",
)

# Appropriations bills — substantive but not front-page material.
# Allowed into the ranked list but excluded from the lede + 3-up slots
# by the frontend.
import re as _re
_APPROPRIATIONS_RE = _re.compile(
    r"(?:^|\s)(?:making\s+)?appropriations(?:\s+for|\s+act)|continuing\s+appropriations"
    r"|emergency\s+supplemental\s+appropriations|further\s+continuing\s+appropriations",
    _re.IGNORECASE,
)


def _is_ceremonial(title):
    t = (title or "").lower()
    return any(p in t for p in _CEREMONIAL_PATTERNS)


def _is_appropriations(title):
    return bool(_APPROPRIATIONS_RE.search(title or ""))


# Use the shared api.congress.gov breaker so a trip from any subsystem
# (feed, search, bill detail, member search) suspends every other call site.
from congress_breaker import is_tripped as _breaker_tripped, trip as _trip_breaker, clear as _clear_breaker


# Per-rep sponsored-legislation cache.
#   Fresh tier (in-memory TTLCache, 12h): full hit, no network
#   Stale tier (in-memory dict, no TTL): fallback when live call fails
#   Disk tier (correspondence.db disk_cache, 30d): survives server restarts
# In-flight set prevents concurrent warmers for the same bioguide.
_REP_FRESH_TTL = 12 * 3600
_REP_DISK_TTL  = 30 * 86400
_rep_fresh_cache = TTLCache(maxsize=512, ttl=_REP_FRESH_TTL)
_rep_stale_cache = {}
_rep_cache_lock = RLock()
_rep_inflight = set()
_rep_inflight_lock = RLock()


def _rep_disk_key(bioguide_id):
    return f"rep_bills:v1:{bioguide_id}"


def _load_rep_from_disk(bioguide_id):
    return get_disk_cache(_rep_disk_key(bioguide_id), max_age_seconds=_REP_DISK_TTL)


def _save_rep_to_disk(bioguide_id, bills):
    if bills:
        set_disk_cache(_rep_disk_key(bioguide_id), bills)

_FEED_TTL_SECONDS = 3600  # 1 hour

load_dotenv()

GOVINFO_API_KEY = os.getenv("GovInfo_API_KEY")
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

INTEREST_TERMS = {
    "healthcare": [
        "Medicaid", "Medicare", "health insurance coverage",
        "Affordable Care Act", "prescription drug pricing",
        "hospital reimbursement", "healthcare access",
        "public health emergency", "mental health parity",
        "health savings account"
    ],
    "climate": [
        "greenhouse gas emissions", "carbon emissions",
        "clean energy", "renewable energy", "decarbonization",
        "Paris Agreement", "carbon tax", "net zero",
        "climate resilience", "clean electricity"
    ],
    "housing": [
        "affordable housing", "housing assistance",
        "rent stabilization", "homelessness prevention",
        "HUD funding", "eviction moratorium",
        "first-time homebuyer", "housing voucher",
        "public housing", "mortgage relief"
    ],
    "education": [
        "student loan forgiveness", "Pell Grant",
        "higher education funding", "FAFSA",
        "K-12 education", "teacher shortage",
        "school funding", "early childhood education",
        "vocational training", "college affordability"
    ],
    "veterans": [
        "veteran benefits", "VA healthcare",
        "GI Bill", "veteran disability",
        "military service member", "PTSD treatment",
        "veteran homelessness", "veteran employment",
        "veteran mental health", "Medal of Honor"
    ],
    "economy": [
        "minimum wage", "unemployment insurance",
        "inflation reduction", "job creation",
        "small business loan", "economic growth",
        "Federal Reserve", "deficit reduction",
        "worker protections", "wage theft"
    ],
    "immigration": [
        "DACA", "asylum seeker", "border security",
        "immigration enforcement", "visa reform",
        "pathway to citizenship", "refugee resettlement",
        "immigration detention", "H-1B visa",
        "undocumented immigrant"
    ],
    "gun_policy": [
        "firearm background check", "assault weapon ban",
        "gun violence prevention", "Second Amendment",
        "concealed carry", "red flag law",
        "ghost gun", "bump stock",
        "school shooting", "ATF regulation"
    ],
    "foreign_policy": [
        "NATO alliance", "foreign military aid",
        "economic sanctions", "diplomatic relations",
        "foreign assistance", "defense authorization",
        "China competition", "Ukraine support",
        "arms control", "nuclear nonproliferation"
    ],
    "criminal_justice": [
        "criminal sentencing reform", "prison reform",
        "police accountability", "qualified immunity",
        "mass incarceration", "drug decriminalization",
        "juvenile justice", "reentry program",
        "mandatory minimum", "bail reform"
    ],
    "small_business": [
        "small business administration", "SBA loan",
        "small business tax", "entrepreneur support",
        "Main Street lending", "minority business",
        "small business relief", "startup funding",
        "small business regulation", "franchise"
    ],
    "agriculture": [
        "farm bill", "crop insurance", "USDA program",
        "agricultural subsidy", "rural development",
        "food security", "livestock regulation",
        "organic farming", "agricultural trade",
        "family farm"
    ],
}

def _feed_cache_key(interests, senator_bioguides, rep_bioguide, state_code):
    payload = json.dumps({
        "i": sorted(interests or []),
        "s": sorted(senator_bioguides or []),
        "r": rep_bioguide or "",
        "st": state_code or "",
    }, sort_keys=True)
    return "feed:v7:" + hashlib.sha1(payload.encode()).hexdigest()


def fetch_feed(interests, senator_bioguides, rep_bioguide, days_back=30, max_per_interest=3, state_code=None):
    """
    Generates a personalized feed based on user interests and representatives.

    interests: list of interest keys e.g. ["healthcare", "climate"]
    senator_bioguides: list of senator bioguide IDs
    rep_bioguide: house rep bioguide ID
    """
    db_key = _feed_cache_key(interests, senator_bioguides, rep_bioguide, state_code)
    cached = get_disk_cache(db_key, max_age_seconds=_FEED_TTL_SECONDS)
    if cached is not None:
        print(f"[FEED] Disk cache hit — {len(cached)} items")
        return cached

    feed_items = []
    seen_bills = set()

    # ── Run all three top-level fetches concurrently ──
    all_bioguides = senator_bioguides + ([rep_bioguide] if rep_bioguide else [])
    state_enabled = bool(state_code and state_code.upper() in ENABLED_STATES)

    with ThreadPoolExecutor(max_workers=8) as ex:
        rep_future = ex.submit(_fetch_rep_bills_parallel, all_bioguides, 90)
        interest_futures = [
            ex.submit(_search_interest_bills, INTEREST_TERMS.get(i, [i]), max_per_interest)
            for i in interests
        ]
        state_future = ex.submit(
            get_recent_state_bills, state_code.upper(), 5
        ) if state_enabled else None

        rep_bills = rep_future.result()
        interest_results = [f.result() for f in interest_futures]
        state_bills = state_future.result() if state_future else []

    # ── Build pools ──
    rep_pool = []
    for bill in rep_bills:
        if _is_ceremonial(bill.get("title")):
            continue
        key = f"{bill.get('type','')}{bill.get('number','')}"
        if key not in seen_bills:
            seen_bills.add(key)
            bill["feed_reason"] = "your_rep"
            if _is_appropriations(bill.get("title")):
                bill["is_appropriations"] = True
            rep_pool.append(bill)

    interest_pool = []
    for interest, bills in zip(interests, interest_results):
        for bill in bills:
            if _is_ceremonial(bill.get("title")):
                continue
            key = f"{bill.get('type','')}{bill.get('number','')}"
            if key not in seen_bills:
                seen_bills.add(key)
                bill["feed_reason"] = interest
                bill["feed_interest"] = interest
                if _is_appropriations(bill.get("title")):
                    bill["is_appropriations"] = True
                interest_pool.append(bill)

    # ── Single enrichment batch with a wall-clock budget ──
    _enrich_latest_actions(rep_pool + interest_pool)
    feed_items.extend(rep_pool)
    feed_items.extend(interest_pool)

    for bill in state_bills:
        if _is_ceremonial(bill.get("title")):
            continue
        key = f"state-{bill.get('identifier', '')}"
        if key not in seen_bills:
            seen_bills.add(key)
            bill["feed_reason"] = "state_legislature"
            bill["feed_interest"] = "state"
            if _is_appropriations(bill.get("title")):
                bill["is_appropriations"] = True
            feed_items.append(bill)

    log_action(
        agent_name="feed",
        action="fetch_feed",
        input_data={
            "interests": interests,
            "reps": senator_bioguides + ([rep_bioguide] if rep_bioguide else []),
            "state_code": state_code,
        },
        output_data={"total_items": len(feed_items)}
    )

    if feed_items:
        set_disk_cache(db_key, feed_items)

    return feed_items

def _fetch_bill_detail(congress, bill_type, number, timeout=8):
    url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{number}"
    try:
        r = requests.get(url, params={"api_key": CONGRESS_API_KEY, "format": "json"}, timeout=timeout)
        if r.status_code == 200:
            return r.json().get("bill") or {}
        return {"_error": r.status_code}
    except Exception as e:
        return {"_error": str(e.__class__.__name__)}


def _fetch_bill_detail_resilient(congress, bill_type, number):
    """Two attempts: fast first, equally short retry. A 15s second try rarely
    succeeds when the first 8s call already failed; it just inflates the tail."""
    detail = _fetch_bill_detail(congress, bill_type, number, timeout=6)
    if detail and "_error" not in detail:
        return detail
    detail = _fetch_bill_detail(congress, bill_type, number, timeout=6)
    if detail and "_error" not in detail:
        return detail
    return None


_ENRICH_BUDGET_SECONDS = 10


def _enrich_latest_actions(bills):
    """Populate latest_action, latest_action_date, is_law, law_number in parallel.

    Wall-clock budgeted: any future that hasn't returned by the deadline
    falls back to "Recently introduced" rather than blocking the whole feed.
    """
    if not bills:
        return
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {
            ex.submit(_fetch_bill_detail_resilient, b.get("congress"), b.get("type"), b.get("number")): b
            for b in bills
        }
        done, not_done = wait(futures.keys(), timeout=_ENRICH_BUDGET_SECONDS)
        for fut in not_done:
            bill = futures[fut]
            if not bill.get("latest_action"):
                bill["latest_action"] = "Recently introduced."
                if not bill.get("latest_action_date") and bill.get("date"):
                    bill["latest_action_date"] = bill["date"]
            fut.cancel()
        for fut in done:
            bill = futures[fut]
            detail = fut.result()
            if not detail:
                if not bill.get("latest_action"):
                    bill["latest_action"] = "Recently introduced."
                    if not bill.get("latest_action_date") and bill.get("date"):
                        bill["latest_action_date"] = bill["date"]
                continue
            la = detail.get("latestAction") or {}
            bill["latest_action"] = la.get("text", "") or bill.get("latest_action", "")
            bill["latest_action_date"] = la.get("actionDate", "") or bill.get("latest_action_date", "")
            laws = detail.get("laws") or []
            if laws:
                bill["is_law"] = True
                law_num = (laws[0].get("number") or "").split("-")[-1]
                if law_num:
                    bill["law_number"] = law_num
            sponsors = detail.get("sponsors") or []
            if sponsors and not bill.get("sponsor_name"):
                s = sponsors[0]
                name = s.get("fullName") or s.get("directOrderName") or ""
                party = s.get("party") or ""
                state = s.get("state") or ""
                tag = f" ({party}-{state})" if party and state else ""
                bill["sponsor_name"] = f"{name}{tag}".strip()
                bill["sponsor_bioguide"] = s.get("bioguideId") or bill.get("sponsor_bioguide")
            # Defensive: even if we got a 200 with no latestAction (rare), fall back
            if not bill.get("latest_action"):
                bill["latest_action"] = "Recently introduced."
                if not bill.get("latest_action_date") and bill.get("date"):
                    bill["latest_action_date"] = bill["date"]


def _live_fetch_rep(bioguide_id, timeout):
    """Single live call against Congress.gov. Returns list or raises."""
    url = f"https://api.congress.gov/v3/member/{bioguide_id}/sponsored-legislation"
    params = {"api_key": CONGRESS_API_KEY, "format": "json", "limit": 5}
    r = _session.get(url, params=params, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"status {r.status_code}")
    out = []
    for bill in r.json().get("sponsoredLegislation", []):
        if not (bill.get("title") and bill.get("number") and bill.get("type")):
            continue
        date = (bill.get("latestAction") or {}).get("actionDate", "")
        out.append({
            "congress": bill.get("congress"),
            "type": (bill.get("type") or "").lower(),
            "number": bill.get("number"),
            "title": bill.get("title", ""),
            "date": date,
            "sponsor_bioguide": bioguide_id,
            "latest_action": (bill.get("latestAction") or {}).get("text", ""),
        })
    return out


def _store_rep(bioguide_id, bills):
    with _rep_cache_lock:
        _rep_fresh_cache[bioguide_id] = bills
        _rep_stale_cache[bioguide_id] = bills
    _save_rep_to_disk(bioguide_id, bills)


def _live_fetch_rep_no_limit(bioguide_id, timeout):
    """Fallback live call without limit param — in case the server-side
    'limit' handling is what's actually slow. Trims to 5 client-side."""
    url = f"https://api.congress.gov/v3/member/{bioguide_id}/sponsored-legislation"
    params = {"api_key": CONGRESS_API_KEY}
    r = _session.get(url, params=params, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"status {r.status_code}")
    out = []
    for bill in r.json().get("sponsoredLegislation", [])[:5]:
        if not (bill.get("title") and bill.get("number") and bill.get("type")):
            continue
        date = (bill.get("latestAction") or {}).get("actionDate", "")
        out.append({
            "congress": bill.get("congress"),
            "type": (bill.get("type") or "").lower(),
            "number": bill.get("number"),
            "title": bill.get("title", ""),
            "date": date,
            "sponsor_bioguide": bioguide_id,
            "latest_action": (bill.get("latestAction") or {}).get("text", ""),
        })
    return out


def _warm_rep_in_background(bioguide_id):
    """One-shot warmer: tries canonical + no-limit variants with short
    timeouts, trips the breaker on full failure, then exits. No spammy
    retry loops — the breaker keeps the next feed request from re-dispatching
    until the cooldown clears. Most outages clear within the 15-min window;
    if not, the user's next refresh after that dispatches a single fresh try."""
    if _breaker_tripped():
        return
    with _rep_inflight_lock:
        if bioguide_id in _rep_inflight:
            return
        _rep_inflight.add(bioguide_id)

    def attempt(label, fn, timeout):
        try:
            bills = fn(bioguide_id, timeout=timeout)
            _store_rep(bioguide_id, bills)
            _clear_breaker()
            print(f"[FEED] Warmer SUCCEEDED for {bioguide_id} via {label} ({len(bills)} bills)")
            return True
        except Exception as e:
            print(f"[FEED] Warmer {label} for {bioguide_id} failed: {type(e).__name__}")
            return False

    def runner():
        try:
            for to in (15, 30):
                if attempt(f"canonical t={to}s", _live_fetch_rep, to):
                    return
                if _breaker_tripped():
                    return
            for to in (15, 30):
                if attempt(f"no-limit t={to}s", _live_fetch_rep_no_limit, to):
                    return
                if _breaker_tripped():
                    return
            _trip_breaker()
        finally:
            with _rep_inflight_lock:
                _rep_inflight.discard(bioguide_id)

    t = threading.Thread(target=runner, daemon=True, name=f"rep-warm-{bioguide_id}")
    t.start()


def _fetch_one_rep(bioguide_id, cutoff):
    # Tier 1: in-memory fresh cache
    with _rep_cache_lock:
        cached = _rep_fresh_cache.get(bioguide_id)
    if cached is not None:
        return [b for b in cached if b.get("date", "") >= cutoff]

    # Tier 2: disk cache (survives restarts)
    disk_cached = _load_rep_from_disk(bioguide_id)
    if disk_cached is not None:
        with _rep_cache_lock:
            _rep_fresh_cache[bioguide_id] = disk_cached
            _rep_stale_cache[bioguide_id] = disk_cached
        # Disk hit — refresh in background so the next call has fresher data
        _warm_rep_in_background(bioguide_id)
        return [b for b in disk_cached if b.get("date", "") >= cutoff]

    # Tier 3: breaker check — if Congress.gov is in cooldown, don't try
    if _breaker_tripped():
        with _rep_cache_lock:
            stale = _rep_stale_cache.get(bioguide_id)
        if stale is not None:
            return [b for b in stale if b.get("date", "") >= cutoff]
        return []

    # Tier 4: try a short live call so first-ever loads have a shot
    try:
        bills = _live_fetch_rep(bioguide_id, timeout=8)
        _store_rep(bioguide_id, bills)
        _clear_breaker()
        return [b for b in bills if b.get("date", "") >= cutoff]
    except Exception as e:
        with _rep_cache_lock:
            stale = _rep_stale_cache.get(bioguide_id)
        _warm_rep_in_background(bioguide_id)
        if stale is not None:
            print(f"[FEED] Live rep fetch failed for {bioguide_id} ({type(e).__name__}); serving stale ({len(stale)} bills)")
            return [b for b in stale if b.get("date", "") >= cutoff]
        print(f"[FEED] Rep cold-load failed for {bioguide_id} ({type(e).__name__}); background warmer dispatched")
        return []


def _fetch_rep_bills_parallel(bioguide_ids, days_back=180):
    if not bioguide_ids:
        return []
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    bills = []
    with ThreadPoolExecutor(max_workers=min(8, len(bioguide_ids))) as ex:
        futures = [ex.submit(_fetch_one_rep, bg, cutoff) for bg in bioguide_ids]
        done, not_done = wait(futures, timeout=8)
        for f in not_done:
            f.cancel()
        for f in done:
            bills.extend(f.result())
    bills.sort(key=lambda b: b.get("date", ""), reverse=True)
    return bills[:3]


def _fetch_rep_bills(bioguide_ids, days_back=180):
    """Backwards-compatible wrapper for external callers."""
    return _fetch_rep_bills_parallel(bioguide_ids, days_back)

def _search_interest_bills(terms, max_results):
    """Search GovInfo for recent bills matching interest terms."""
    terms_query = " OR ".join(f'"{t}"' if " " in t else t for t in terms[:5])
    
    # Current and last congress
    congress_filter = "congress:119 OR congress:118"
    full_query = f"({terms_query}) collection:BILLS ({congress_filter})"
    
    payload = {
        "query": full_query,
        "pageSize": max_results,
        "offsetMark": "*",
        "sorts": [{"field": "publishdate", "sortOrder": "DESC"}]
    }
    
    try:
        response = requests.post(
            "https://api.govinfo.gov/search",
            json=payload,
            params={"api_key": GOVINFO_API_KEY},
            timeout=10
        )
        
        if response.status_code != 200:
            return []
        
        results = []
        for item in response.json().get("results", []):
            package_id = item.get("packageId", "")
            import re
            match = re.match(r"BILLS-(\d+)([a-z]+)(\d+)", package_id.replace("BILLS-", "BILLS-"))
            if match:
                raw = package_id.replace("BILLS-", "")
                m = re.match(r"(\d+)([a-z]+)(\d+)", raw)
                if m:
                    results.append({
                        "congress": int(m.group(1)),
                        "type": m.group(2),
                        "number": int(m.group(3)),
                        "title": item.get("title", ""),
                        "date": item.get("dateIssued", ""),
                        "latest_action": "",
                    })
        
        return [r for r in results if not _is_ceremonial(r.get("title"))]

    except Exception as e:
        print(f"[FEED] Search error: {e}")
        return []

if __name__ == "__main__":
    print("FEED AGENT TEST")
    print("-" * 40)
    
    # Simulate a Vermont user who cares about healthcare and climate
    result = fetch_feed(
        interests=["healthcare", "climate"],
        senator_bioguides=["S000033", "W000800"],  # Sanders, Welch
        rep_bioguide="B001311",                     # Balint
        days_back=60
    )
    
    print(f"Feed items: {len(result)}")
    print()
    for item in result:
        print(f"  [{item['feed_reason']}] {item.get('type','').upper()}{item.get('number','')} — {item.get('title','')[:60]}")
        print(f"  Date: {item.get('date','')}")
        print()