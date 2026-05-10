# test_error_handling.py
import os
from dotenv import load_dotenv
load_dotenv()

from bill_fetcher import fetch_bill
from historian_agent import fetch_bill_actions
from vote_fetcher_agent import fetch_house_votes, fetch_senate_votes
from member_search_agent import search_member, fetch_member_profile
from search_agent import search_bills

print("Testing error handling...")
print("-" * 40)

# Nonexistent bill
result = fetch_bill(999, "hr", 99999)
print(f"Nonexistent bill: {result} (should be None)")

# Nonexistent bill actions
result = fetch_bill_actions(999, "hr", 99999)
print(f"Nonexistent actions: {result} (should be None or [])")

# Nonexistent vote
result = fetch_house_votes({"roll": 99999, "session": 1, "year": 2020, "congress": 116, "url": None})
print(f"Nonexistent house vote: {result} (should be None)")

# Nonexistent member
result = search_member("Zzzzz Qqqqq Xxxxx")
print(f"Nonexistent member: {result} (should be None)")

# Empty search
result = search_bills({"keywords": [], "expanded_terms": [], "congress_numbers": [119], "status": "any", "result_count": 3})
print(f"Empty search: {type(result)} (should be list)")

print()
print("All tests complete — no crashes means error handling is working")