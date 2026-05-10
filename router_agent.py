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
# Add this near the CONGRESS_YEARS dict
PRESIDENT_TERMS = {
    "biden": [117, 118],
    "trump": [119, 116, 115],  # Current + first term
    "trump's first term": [115, 116],
    "first trump": [115, 116],
    "obama": [111, 112, 113, 114],
    "bush": [107, 108, 109, 110],
    "clinton": [103, 104, 105, 106],
    "reagan": [97, 98, 99, 100],
    "carter": [95, 96],
}

PRESIDENTIAL_CONTEXT = [
    "signed", "passed", "under", "era", "administration",
    "presidency", "president", "white house", "oval office"
]

CONGRESSIONAL_CONTEXT = [
    "voted", "sponsored", "senator", "representative", 
    "congress", "voting record", "cosponsored", "introduced"
]


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

def extract_president_congress(question):
    question_lower = question.lower()
    
    # More flexible matching
    PRESIDENT_PATTERNS = {
        "biden": [117, 118],
        "trump": [119, 115, 116],
        "obama": [111, 112, 113, 114],
        "bush": [107, 108, 109, 110],
        "clinton": [103, 104, 105, 106],
        "reagan": [97, 98, 99, 100],
    }
    
    for president, congresses in PRESIDENT_PATTERNS.items():
        if president in question_lower:
            # Avoid matching "trump" as a verb
            # Check it's used as a name by looking for context
            idx = question_lower.find(president)
            before = question_lower[max(0, idx-10):idx]
            # If preceded by "to " it's likely a verb
            if president == "trump" and before.strip().endswith("to"):
                continue
            return congresses
    
    return None
def route_query(user_question, client):
    """
    Takes a plain English question and returns a structured search query.
    This agent never fetches bills - it only extracts intent.
    """
    
    prompt = f"""
You are a query router for a legislative search system.
Extract search intent from a plain English question.
Return ONLY valid JSON, no markdown, no explanation.

CURRENT DATE CONTEXT (authoritative — do not use training-data assumptions):
- Today is 2026. Donald Trump is the current U.S. President (second term, began January 2025).
- The current Congress is the 119th (2025–2026).
- Biden served 2021–2025 (117th and 118th Congresses).
- Trump's first term was 2017–2021 (115th and 116th Congresses).
- When the user says "recently" or "now" in relation to Trump, they mean his CURRENT second term (119th Congress), not his first.

User question: {user_question}

Rules for query_type:
- A person's name, "Senator X", "Representative X", "what did X do", "X's record", "X's votes", "who is X" → "member"
- "X Committee", "committee on X", "House/Senate committee" → "committee"
- Everything else → "legislation"

Rules for confidence (0.0 to 1.0):
- 1.0 → completely unambiguous. "HR 3590", "Ted Kennedy", "Senate Judiciary Committee"
- 0.8 → clear intent with minor uncertainty. "healthcare bills", "Bernie Sanders record"
- 0.6 → some ambiguity. "Kennedy healthcare" could be member or legislation
- 0.4 → significant ambiguity. Mixed signals, unclear intent
- 0.2 → very unclear. Could mean many things
- Always explain low confidence (below 0.7) in ambiguity_reason

Rules for ambiguity_reason:
- null if confidence >= 0.7
- One sentence explaining the ambiguity if confidence < 0.7
- Example: "Kennedy could refer to a person or legislation named after Kennedy"

Rules for entity_name:
- For member queries: extract the person's name only
- For committee queries: extract the committee name
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
- Presidential terms handled separately

Examples:
"HR 3590" →
{{"query_type": "legislation", "confidence": 1.0, "ambiguity_reason": null, "entity_name": null, "keywords": [], "topic": "specific bill HR 3590", "time_range": "last 5 years", "bill_type": "hr", "result_count": 1, "specific_bill": {{"type": "hr", "number": 3590, "congress": null}}, "status": "any"}}

"Kennedy healthcare" →
{{"query_type": "legislation", "confidence": 0.5, "ambiguity_reason": "Kennedy could refer to Senator Ted Kennedy or legislation named after Kennedy", "entity_name": null, "keywords": ["healthcare"], "topic": "Kennedy healthcare legislation", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

"Ted Kennedy" →
{{"query_type": "member", "confidence": 0.95, "ambiguity_reason": null, "entity_name": "Ted Kennedy", "keywords": [], "topic": "", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

"Senate Judiciary Committee" →
{{"query_type": "committee", "confidence": 1.0, "ambiguity_reason": null, "entity_name": "Senate Judiciary Committee", "keywords": [], "topic": "", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

Return ONLY this JSON structure:
{{
    "query_type": "legislation",
    "confidence": 0.9,
    "ambiguity_reason": null,
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

    # Override congress_numbers if a president was mentioned
    president_congresses = extract_president_congress(user_question)
    if president_congresses:
        structured["congress_numbers"] = president_congresses
        structured["time_range"] = "presidential term"
        # Don't force enacted status just because they said "passed"
        # Let it search all bills from that term
        if structured.get("status") == "enacted":
            structured["status"] = "any"

    PRESIDENTS = ["trump", "biden", "obama", "bush", "clinton", "reagan", "carter"]

    question_lower = user_question.lower()

    presidential_signals = ["signed", "passed", "under", "era",
                            "administration", "presidency", "president",
                            "white house"]

    congressional_signals = ["voted", "sponsored", "senator",
                             "representative", "voting record",
                             "cosponsored", "introduced"]

    entity = (structured.get("entity_name") or "").lower()

    if structured.get("query_type") == "member":
        if any(p in entity for p in PRESIDENTS):
            has_presidential = any(s in question_lower for s in presidential_signals)
            has_congressional = any(s in question_lower for s in congressional_signals)

            if has_presidential and not has_congressional:
                structured["query_type"] = "legislation"
                structured["entity_name"] = None

                stop_words = {"what", "are", "the", "latest", "bills", "that",
                              "has", "passed", "signed", "under", "laws", "legislation",
                              "trump", "biden", "obama", "bush", "clinton", "reagan"}

                words = user_question.lower().split()
                meaningful = [w for w in words if w not in stop_words and len(w) > 3]

                if meaningful:
                    structured["keywords"] = meaningful
                else:
                    structured["keywords"] = ["enacted", "signed"]
            elif has_congressional and not has_presidential:
                pass  # Keep as member — they were in Congress
            else:
                # Ambiguous — Trump defaults to legislation; Biden/Obama stay as member
                if "trump" in entity:
                    structured["query_type"] = "legislation"
                    structured["entity_name"] = None

    log_action(
    agent_name="router",
    action="route_query",
    input_data={"question": user_question},
    output_data={
        "query_type": structured.get("query_type"),
        "confidence": structured.get("confidence"),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "keywords": structured.get("keywords"),
        "entity_name": structured.get("entity_name"),
    }
)
    
    return structured

if __name__ == "__main__":
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    result = route_query("senate judiciary committee", client)
    print(result['query_type'])
    print(result['entity_name'])