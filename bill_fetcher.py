import requests
import os
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

def fetch_bill(congress_number, bill_type, bill_number):
    url = f"https://api.congress.gov/v3/bill/{congress_number}/{bill_type}/{bill_number}"
    
    params = {
        "api_key": CONGRESS_API_KEY,
        "format": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
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
        response = requests.get(url, params=params, timeout=10)
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
            r2 = requests.get(fallback_url, params={**params, "limit": 250}, timeout=10)
            if r2.status_code == 200:
                for bill in r2.json().get("bills", []):
                    for law in (bill.get("laws") or []):
                        if str(law.get("number")) == str(law_number):
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
if __name__ == "__main__":
    import json
    
    url = f"https://api.congress.gov/v3/law/119/pub/87"
    params = {"api_key": CONGRESS_API_KEY, "format": "json"}
    response = requests.get(url, params=params, timeout=10)
    
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2)[:2000])
    
    