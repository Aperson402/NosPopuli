import requests
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

GOVINFO_API_KEY = os.getenv("GovInfo_API_KEY")
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

# Map user interest labels to legislative search terms
INTEREST_TERMS = {
   "healthcare": [
    "Medicaid", "Medicare", "health insurance", 
    "ACA", "prescription drug", "public health",
    "hospital", "patient", "healthcare coverage"
    ],
    "climate": ["climate", "greenhouse gas", "clean energy", "renewable", "carbon emissions", "EPA", "environment"],
    "housing": ["housing", "affordable housing", "rent", "mortgage", "homelessness", "HUD", "eviction"],
    "education": ["education", "student loan", "school", "university", "Pell Grant", "FAFSA", "teacher"],
    "veterans": ["veteran", "VA", "military service", "armed forces", "disability benefits", "PTSD", "GI Bill"],
    "economy": ["economy", "inflation", "jobs", "unemployment", "minimum wage", "tax", "small business"],
    "immigration": ["immigration", "border", "asylum", "DACA", "visa", "citizenship", "ICE"],
    "gun_policy": ["firearm", "gun violence", "background check", "Second Amendment", "ATF", "assault weapon"],
    "foreign_policy": ["foreign policy", "NATO", "sanctions", "diplomacy", "foreign aid", "defense"],
    "criminal_justice": ["criminal justice", "police", "incarceration", "sentencing", "prison reform", "law enforcement"],
    "small_business": ["small business", "SBA", "entrepreneur", "startup", "loan guarantee", "commerce"],
    "agriculture": ["agriculture", "farm", "rural", "USDA", "crop", "food security", "livestock"],
}

def fetch_feed(interests, senator_bioguides, rep_bioguide, days_back=30, max_per_interest=3):
    """
    Generates a personalized feed based on user interests and representatives.
    
    interests: list of interest keys e.g. ["healthcare", "climate"]
    senator_bioguides: list of senator bioguide IDs
    rep_bioguide: house rep bioguide ID
    """
    
    feed_items = []
    seen_bills = set()
    
    # ── Section 1: Bills from their representatives ──
    rep_bills = _fetch_rep_bills(
        senator_bioguides + ([rep_bioguide] if rep_bioguide else []),
        days_back
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
    
    log_action(
        agent_name="feed",
        action="fetch_feed",
        input_data={
            "interests": interests,
            "reps": senator_bioguides + ([rep_bioguide] if rep_bioguide else [])
        },
        output_data={"total_items": len(feed_items)}
    )
    
    return feed_items

def _fetch_rep_bills(bioguide_ids, days_back):
    """Fetch recently sponsored bills from the user's representatives."""
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
                date = (bill.get("latestAction") or {}).get("actionDate", "")
                if (date >= cutoff
                    and bill.get("title")
                    and bill.get("number")
                    and bill.get("type")):
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
    
    return bills

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
    for item in result[:5]:
        print(f"  [{item['feed_reason']}] {item.get('type','').upper()}{item.get('number','')} — {item.get('title','')[:60]}")
        print(f"  Date: {item.get('date','')}")
        print()