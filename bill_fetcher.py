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

if __name__ == "__main__":
    bill = fetch_bill(111, "hr", 3590)
    
    if bill:
        print("SUCCESS - Raw data received:")
        print(f"Title: {bill['bill']['title']}")
        print(f"Sponsor: {bill['bill']['sponsors'][0]['fullName']}")
        print(f"Status: {bill['bill']['latestAction']['text']}")