import anthropic
import os
import json
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

# Static knowledge - never changes
CONGRESS_YEARS = {
    119: (2025, 2026),
    118: (2023, 2024),
    117: (2021, 2022),
    116: (2019, 2020),
    115: (2017, 2018),
    114: (2015, 2016),
    113: (2013, 2014),
    112: (2011, 2012),
    111: (2009, 2010),
    110: (2007, 2008),
}

def years_to_congress_numbers(year_range_str):
    """Convert a year range like 'last 5 years' to congress numbers"""
    import datetime
    current_year = datetime.datetime.now().year
    
    if "last 5 years" in year_range_str.lower():
        start_year = current_year - 5
    elif "last 10 years" in year_range_str.lower():
        start_year = current_year - 10
    elif "last 2 years" in year_range_str.lower():
        start_year = current_year - 2
    else:
        start_year = current_year - 5  # Default to last 5 years
    
    matching = []
    for congress, (start, end) in CONGRESS_YEARS.items():
        if end >= start_year:
            matching.append(congress)
    
    return sorted(matching, reverse=True)

def route_query(user_question, client):
    """
    Takes a plain English question and returns a structured search query.
    This agent never fetches bills - it only extracts intent.
    """
    
    prompt = f"""
    You are a query router for a legislative search system.
    Extract search intent from a plain English question.
    Return ONLY valid JSON, no markdown, no explanation.

    User question: {user_question}

    Rules for query_type:
    - A person's name, "Senator X", "Representative X", "what did X do", "X's record", "X's votes", "who is X" → "member"
    - "X Committee", "committee on X", "House/Senate committee" → "committee"
    - Everything else → "legislation"

    Rules for entity_name:
    - For member queries: extract the person's name only. "What did Ted Kennedy do" → "Ted Kennedy"
    - For committee queries: extract the committee name. "Senate Judiciary Committee" → "Senate Judiciary Committee"
    - For legislation queries: null

    Rules for result_count:
    - "a bill", "one bill", "a law", "an example" → 1
    - "a few", "some" → 3
    - No quantity mentioned → 5
    - "many", "lots", explicit number → that number
    - Maximum: 20

    Rules for specific_bill:
    - If user mentions a bill number like "HR 3590", "S 1234" → extract it
    - Otherwise → null

    Rules for status:
    - "passed", "became law", "signed", "enacted", "a law" → "enacted"
    - "failed", "rejected" → "failed"
    - No status mentioned → "any"

    Rules for keywords (legislation only):
    - Extract ONLY subject matter nouns
    - NEVER include: show, me, bills, find, a, one, some, what, has, done, about, related, to, from, the, give, senator, representative

    Rules for time_range:
    - "recent", "recently" → "last 2 years"
    - "last 5 years" or nothing → "last 5 years"
    - "last 10 years" → "last 10 years"

    Examples:
    "What did Ted Kennedy do in Congress?" →
    {{"query_type": "member", "entity_name": "Ted Kennedy", "keywords": [], "topic": "", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

    "Show me the Senate Judiciary Committee" →
    {{"query_type": "committee", "entity_name": "Senate Judiciary Committee", "keywords": [], "topic": "", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

    "Find bills about climate change" →
    {{"query_type": "legislation", "entity_name": null, "keywords": ["climate", "change"], "topic": "climate change legislation", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

    Return ONLY this JSON structure:
    {{
        "query_type": "legislation",
        "entity_name": null,
        "keywords": ["keyword1"],
        "topic": "description",
        "time_range": "last 5 years",
        "bill_type": "all",
        "result_count": 5,
        "specific_bill": null,
        "status": "any"
    }}
    """
    
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    
    try:
        structured = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback if AI returns malformed JSON
        structured = {
            "keywords": user_question.split()[:3],
            "topic": user_question,
            "time_range": "last 5 years",
            "bill_type": "all"
        }
    
    # Add congress numbers based on time range
    structured["congress_numbers"] = years_to_congress_numbers(structured["time_range"])
    
    log_action(
        agent_name="router",
        action="route_query",
        input_data={"question": user_question},
        output_data=structured
    )
    
    return structured

if __name__ == "__main__":
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    test_questions = [
        "Show me bills about student loans from the last 5 years",
        "What has Congress done about housing affordability?",
        "Find everything related to veterans benefits recently"
    ]
    
    print("ROUTER AGENT TEST")
    print("-" * 40)
    
    for question in test_questions:
        print(f"Question: {question}")
        result = route_query(question, client)
        print(f"Structured: {json.dumps(result, indent=2)}")
        print()