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
    Extract search keywords from this question: "{user_question}"
    
    Return ONLY this JSON, nothing else:
    {{
        "keywords": ["KEYWORD1", "KEYWORD2"],
        "topic": "one sentence description",
        "time_range": "last 5 years",
        "bill_type": "all"
    }}
    
    RULES FOR KEYWORDS:
    - Extract ONLY the subject matter nouns
    - "Show me bills about student loans" → ["student loans"]
    - "What has Congress done about housing affordability" → ["housing", "affordability"]
    - "Find everything related to veterans benefits" → ["veterans", "benefits"]
    - NEVER include: show, me, bills, find, everything, what, has, congress, done, about, related, to, from, the
    
    TIME RANGE RULES:
    - Mentions "last 2 years" or "recent" or "recently" → "last 2 years"
    - Mentions "last 5 years" → "last 5 years"  
    - Mentions "last 10 years" → "last 10 years"
    - No time mentioned → "last 5 years"
    
    User question: {user_question}
    
    Respond with ONLY this JSON structure:
    {{
        "keywords": ["keyword1", "keyword2"],
        "topic": "description",
        "time_range": "last 5 years",
        "bill_type": "all"
    }}
    """
    
    message = client.messages.create(
        model="claude-haiku-4-5",
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