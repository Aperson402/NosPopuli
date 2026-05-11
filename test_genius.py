# test_genius.py
import requests
import os
from dotenv import load_dotenv
load_dotenv()

GOVINFO_API_KEY = os.getenv("GovInfo_API_KEY")

# Test 1: Search for GENIUS Act in BILLS
payload = {
    "query": "GENIUS Act stablecoin collection:BILLS congress:119",
    "pageSize": 10,
    "offsetMark": "*",
    "sorts": [{"field": "score", "sortOrder": "DESC"}]
}

r = requests.post(
    "https://api.govinfo.gov/search",
    json=payload,
    params={"api_key": GOVINFO_API_KEY}
)

print(f"BILLS search status: {r.status_code}")
data = r.json()
print(f"Total available: {data.get('count', 0)}")
for item in data.get("results", [])[:5]:
    print(f"  {item.get('packageId')} — {item.get('title', '')[:60]}")

print()

# Test 2: Search PLAW collection
payload2 = {
    "query": "GENIUS Act stablecoin collection:PLAW congress:119",
    "pageSize": 5,
    "offsetMark": "*",
    "sorts": [{"field": "score", "sortOrder": "DESC"}]
}

r2 = requests.post(
    "https://api.govinfo.gov/search",
    json=payload2,
    params={"api_key": GOVINFO_API_KEY}
)

print(f"PLAW search status: {r2.status_code}")
data2 = r2.json()
print(f"Total available: {data2.get('count', 0)}")
for item in data2.get("results", [])[:5]:
    print(f"  {item.get('packageId')} — {item.get('title', '')[:60]}")