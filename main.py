import asyncio
import anthropic
import os
from dotenv import load_dotenv
from router_agent import route_query
from search_agent import search_bills, parse_package_id
from orchestrator import run_orchestrator

load_dotenv()

def print_results(results):
    for result in results:
        print()
        print("=" * 60)
        print(f"BILL: {result['bill'].upper()}")
        print("=" * 60)
        print()
        print("WHAT THIS BILL DOES:")
        print("-" * 40)
        print(result['translation'])
        print()
        print("HOW IT MOVED THROUGH CONGRESS:")
        print("-" * 40)
        print(result['timeline'])
        print()

async def main():
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    print()
    print("=" * 60)
    print("  NosPopuli - Law for the People")
    print("  Ask about any federal legislation in plain English")
    print("=" * 60)
    print()
    
    while True:
        try:
            question = input("What would you like to know? (or 'quit' to exit)\n> ").strip()
            
            if question.lower() in ["quit", "exit", "q"]:
                print("Goodbye.")
                break
            
            if not question:
                continue
            
            print()
            print("[CIVIC LENS] Understanding your question...")
            structured = route_query(question, client)
            print(f"[CIVIC LENS] Searching for: {structured['keywords']}")
            print(f"[CIVIC LENS] Time range: {structured['time_range']}")
            print()
            
            results_raw = search_bills(structured, max_results=3)
            
            if not results_raw:
                print("[CIVIC LENS] No bills found for that query. Try different keywords.")
                print()
                continue
            
            print(f"[CIVIC LENS] Found {len(results_raw)} bills. Processing...")
            print()
            
            # Convert search results to orchestrator format
            bills_to_process = [
                (bill["congress"], bill["type"], bill["number"])
                for bill in results_raw
                if bill["congress"] and bill["type"] and bill["number"]
            ]
            
            results = await run_orchestrator(bills_to_process)
            print_results(results)
            
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break

if __name__ == "__main__":
    asyncio.run(main())