import requests
import os
import json
import hashlib
from datetime import datetime, timedelta
from dotenv import load_dotenv
from documentor_agent import log_action
from state_search_agent import get_recent_state_bills, ENABLED_STATES
from correspondence.db import get_disk_cache, set_disk_cache

_FEED_TTL_SECONDS = 21600  # 6 hours

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
    return "feed:" + hashlib.sha1(payload.encode()).hexdigest()


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
    
    # ── Section 1: Bills from their representatives ──
    rep_bills = _fetch_rep_bills(
        senator_bioguides + ([rep_bioguide] if rep_bioguide else []),
        days_back=90
    )
    
    for bill in rep_bills:
        key = f"{bill.get('type','')}{bill.get('number','')}"
        if key not in seen_bills:
            seen_bills.add(key)
            bill["feed_reason"] = "your_rep"
            feed_items.append(bill)
    
    # ── Section 2: Bills matching user interests ──
    for interest in interests:
        terms = INTEREST_TERMS.get(interest, [interest])
        interest_bills = _search_interest_bills(terms, max_per_interest)
        
        for bill in interest_bills:
            key = f"{bill.get('type','')}{bill.get('number','')}"
            if key not in seen_bills:
                seen_bills.add(key)
                bill["feed_reason"] = interest
                bill["feed_interest"] = interest
                feed_items.append(bill)
    
    # ── Section 3: State bills if state is enabled ──
    if state_code and state_code.upper() in ENABLED_STATES:
        state_bills = get_recent_state_bills(state_code.upper(), limit=5)
        for bill in state_bills:
            key = f"state-{bill.get('identifier', '')}"
            if key not in seen_bills:
                seen_bills.add(key)
                bill["feed_reason"] = "state_legislature"
                bill["feed_interest"] = "state"
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

def _fetch_rep_bills(bioguide_ids, days_back=180):
    bills = []
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    for bioguide_id in bioguide_ids:
        url = f"https://api.congress.gov/v3/member/{bioguide_id}/sponsored-legislation"
        params = {
            "api_key": CONGRESS_API_KEY,
            "format": "json",
            "limit": 5,
        }

        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                continue

            data = r.json()
            for bill in data.get("sponsoredLegislation", []):
                if (bill.get("title")
                        and bill.get("number")
                        and bill.get("type")):
                    date = (bill.get("latestAction") or {}).get("actionDate", "")
                    if date >= cutoff:
                        bills.append({
                            "congress": bill.get("congress"),
                            "type": (bill.get("type") or "").lower(),
                            "number": bill.get("number"),
                            "title": bill.get("title", ""),
                            "date": date,
                            "sponsor_bioguide": bioguide_id,
                            "latest_action": (bill.get("latestAction") or {}).get("text", ""),
                        })
        except Exception as e:
            print(f"[FEED] Error fetching rep bills for {bioguide_id}: {e}")

    bills.sort(key=lambda b: b.get("date", ""), reverse=True)
    return bills[:3]

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
        
        SKIP_PATTERNS = [
            "celebrating the", "expressing support for the designation",
            "recognizing the", "honoring the", "congratulating",
            "acknowledging the", "commemorating", "proclaiming"
        ]
        results = [r for r in results
                   if not any(p in r.get("title", "").lower() for p in SKIP_PATTERNS)]

        return results

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