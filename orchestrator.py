# NOTE: This orchestrator is used for batch processing and CLI testing.
# The production API uses FastAPI's async handlers directly.
# See api.py for the production implementation.
import asyncio
import anthropic
import os
from dotenv import load_dotenv
from bill_fetcher import fetch_bill
from translator_agent import translate_bill
from historian_agent import fetch_bill_actions, fetch_related_bills, summarize_history
from documentor_agent import log_action

load_dotenv()

# Semaphore limits simultaneous instances
# Prevents accidentally firing 10000 API calls at once
MAX_CONCURRENT = 5

async def process_single_bill(semaphore, client, congress, bill_type, number):
    async with semaphore:
        print(f"[ORCHESTRATOR] Spinning up instance for {bill_type}{number}")
        
        loop = asyncio.get_event_loop()
        
        # Fetch first - everything depends on this
        bill_data = await loop.run_in_executor(
            None, fetch_bill, congress, bill_type, number
        )
        
        if not bill_data:
            print(f"[ORCHESTRATOR] Failed to fetch {bill_type}{number}")
            return None
        
        # Translator and Historian run simultaneously
        translation, actions = await asyncio.gather(
            loop.run_in_executor(None, translate_bill, bill_data, client),
            loop.run_in_executor(None, fetch_bill_actions, congress, bill_type, number)
        )
        
        # Historian summarizes after actions are fetched
        timeline = await loop.run_in_executor(
            None, summarize_history, actions, client
        )
        
        log_action(
            agent_name="orchestrator",
            action="process_bill",
            input_data={"congress": congress, "type": bill_type, "number": number},
            output_data={"status": "complete"}
        )
        
        print(f"[ORCHESTRATOR] Instance complete for {bill_type}{number}")
        
        return {
            "bill": bill_type + str(number),
            "translation": translation,
            "timeline": timeline
        }

async def run_orchestrator(bills):
    """
    bills = list of tuples: [(congress, bill_type, number), ...]
    Orchestrator spins up one instance per bill, up to MAX_CONCURRENT at once
    """
    
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    
    print(f"[ORCHESTRATOR] Starting. Processing {len(bills)} bills.")
    print(f"[ORCHESTRATOR] Max concurrent instances: {MAX_CONCURRENT}")
    print("-" * 40)
    
    tasks = [
        process_single_bill(semaphore, client, congress, bill_type, number)
        for congress, bill_type, number in bills
    ]
    
    results = await asyncio.gather(*tasks)
    
    successful = [r for r in results if r is not None]
    
    print("-" * 40)
    print(f"[ORCHESTRATOR] Complete. {len(successful)}/{len(bills)} successful.")
    
    return successful

if __name__ == "__main__":
    # Test with multiple bills simultaneously
    bills_to_process = [
        (111, "hr", 3590),   # Affordable Care Act
        (107, "hr", 3162),   # USA PATRIOT Act
        (116, "hr", 133),    # Consolidated Appropriations Act 2021
    ]
    
    results = asyncio.run(run_orchestrator(bills_to_process))
    
    print()
    for result in results:
        print(f"BILL: {result['bill']}")
        print("-" * 40)
        print("PLAIN ENGLISH:")
        print(result['translation'][:300])
        print()
        print("TIMELINE:")
        print(result['timeline'][:300])
        print()
        print("=" * 60)
        print()