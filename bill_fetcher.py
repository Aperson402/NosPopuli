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
    
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        
        log_action(
            agent_name="bill_fetcher",
            action="fetch_bill",
            input_data={
                "congress": congress_number,
                "type": bill_type,
                "number": bill_number
            },
            output_data={
                "title": data["bill"]["title"],
                "status": data["bill"]["latestAction"]["text"]
            }
        )
        
        return data
    else:
        print(f"Error: {response.status_code}")
        return None
def fetch_law(congress, law_number):
    """
    Fetches bill data by public law number.
    """
    url = f"https://api.congress.gov/v3/law/{congress}/pub/{law_number}"
    
    params = {
        "api_key": CONGRESS_API_KEY,
        "format": "json"
    }
    
    response = requests.get(url, params=params, timeout=10)
    
    if response.status_code != 200:
        print(f"[BILL FETCHER] Law not found: {congress} pub {law_number}")
        return None
    
    data = response.json()
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
    
    