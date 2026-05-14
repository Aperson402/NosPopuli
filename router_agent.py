import anthropic
import os
import json
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

# Static knowledge - never changes
def year_to_congress(year):
    if year < 1789:
        return None
    return ((year - 1789) // 2) + 1

def congress_to_years(congress):
    start = 1789 + (congress - 1) * 2
    return (start, start + 1)


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


def years_to_congress_numbers(year_range_str, all_congresses=False):
    import datetime
    import re

    current_year = datetime.datetime.now().year
    current_congress = year_to_congress(current_year)

    # Specific year always wins — even over full_history
    year_match = re.match(r"year:(\d{4})", year_range_str or "")
    if year_match:
        year = int(year_match.group(1))
        congress = year_to_congress(year)
        return [congress] if congress else [current_congress]

    if all_congresses:
        return list(range(current_congress, 0, -1))

    if "last 2 years" in (year_range_str or "").lower():
        start_year = current_year - 2
    elif "last 10 years" in (year_range_str or "").lower():
        start_year = current_year - 10
    else:
        start_year = current_year - 3

    start_congress = year_to_congress(start_year)
    return list(range(current_congress, start_congress - 1, -1))

KNOWN_BILLS = {
    # Current major legislation
    "genius act": {"congress": 119, "type": "s", "number": 1582},
    "genius": {"congress": 119, "type": "s", "number": 1582},
    "inflation reduction act": {"congress": 117, "type": "hr", "number": 5376},
    "chips act": {"congress": 117, "type": "hr", "number": 4346},
    "infrastructure investment": {"congress": 117, "type": "hr", "number": 3684},
    "bipartisan infrastructure": {"congress": 117, "type": "hr", "number": 3684},

    # Healthcare
    "affordable care act": {"congress": 111, "type": "hr", "number": 3590},
    "aca": {"congress": 111, "type": "hr", "number": 3590},
    "obamacare": {"congress": 111, "type": "hr", "number": 3590},

    # Historical major acts
    "patriot act": {"congress": 107, "type": "hr", "number": 3162},
    "usa patriot": {"congress": 107, "type": "hr", "number": 3162},
    "cara": {"congress": 114, "type": "s", "number": 524},
    "dodd frank": {"congress": 111, "type": "hr", "number": 4173},
    "dodd-frank": {"congress": 111, "type": "hr", "number": 4173},
    "citizens united": {"congress": 111, "type": "hr", "number": 2517},

    # Defense
    "ndaa": {"congress": 118, "type": "hr", "number": 2670},
    "national defense authorization": {"congress": 118, "type": "hr", "number": 2670},

    # Education
    "higher education act": {"congress": 89, "type": "hr", "number": 9567},

    # Civil rights
    "voting rights act": {"congress": 89, "type": "hr", "number": 6400},
    "civil rights act": {"congress": 88, "type": "hr", "number": 7152},
}

def check_known_bills(question):
    question_lower = question.lower()
    for name, bill in KNOWN_BILLS.items():
        if name in question_lower:
            return bill
    return None

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
def route_query(user_question, client, full_history=False):
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

Rules for query_subtype (legislation queries only):
- Proper noun law name, named act, roman numerals, known acronym → "named_entity"
- Proper noun law name + specific year, president, or era → "named_entity_with_date"
- General topic + specific year, president, or era → "concept_with_date"
- "give me a bill", "show me something", "any bill", no specific topic → "browse"
- "laws", "enacted", "signed into law", "passed into law", "became law" → "enacted"
- Everything else → "concept"

Rules for time_filter:
- true if query contains: specific year, president name, era, "recent", "latest", "oldest"
- false otherwise

Rules for named_entity:
- If query_subtype is named_entity or named_entity_with_date: extract the law name exactly as written
- Otherwise: null

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
- "passed", "became law", "signed", "enacted", "a law", "laws" → "enacted"
- "failed", "rejected" → "failed"
- No status mentioned → "any"

Rules for keywords (legislation only):
- Extract ONLY subject matter nouns
- NEVER include: show, me, bills, find, a, one, some, what, has, done, about, related, to, from, the, give, senator, representative, laws, passed, signed, enacted

Rules for time_range:
- "in [year]", "from [year]", "[year] bill" → "year:YYYY"
- "recent", "recently" → "last 2 years"
- "last 5 years" or nothing → "last 5 years"
- "last 10 years" → "last 10 years"
- Presidential terms handled separately

Examples:
"Title IX" →
{{"query_type": "legislation", "query_subtype": "named_entity", "named_entity": "Title IX", "time_filter": false, "confidence": 0.95, "ambiguity_reason": null, "entity_name": null, "keywords": ["Title IX"], "topic": "Title IX education legislation", "time_range": "last 5 years", "bill_type": "all", "result_count": 4, "specific_bill": null, "status": "any"}}

"Title IX in 1972" →
{{"query_type": "legislation", "query_subtype": "named_entity_with_date", "named_entity": "Title IX", "time_filter": true, "confidence": 0.95, "ambiguity_reason": null, "entity_name": null, "keywords": ["Title IX"], "topic": "Title IX 1972", "time_range": "year:1972", "bill_type": "all", "result_count": 4, "specific_bill": null, "status": "any"}}

"healthcare bills from 2017" →
{{"query_type": "legislation", "query_subtype": "concept_with_date", "named_entity": null, "time_filter": true, "confidence": 0.9, "ambiguity_reason": null, "entity_name": null, "keywords": ["healthcare"], "topic": "healthcare legislation 2017", "time_range": "year:2017", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

"give me a bill" →
{{"query_type": "legislation", "query_subtype": "browse", "named_entity": null, "time_filter": false, "confidence": 0.8, "ambiguity_reason": null, "entity_name": null, "keywords": [], "topic": "recent legislation", "time_range": "last 2 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

"laws passed under trump" →
{{"query_type": "legislation", "query_subtype": "enacted", "named_entity": null, "time_filter": true, "confidence": 0.9, "ambiguity_reason": null, "entity_name": null, "keywords": [], "topic": "enacted legislation trump", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "enacted"}}

"gun control bills" →
{{"query_type": "legislation", "query_subtype": "concept", "named_entity": null, "time_filter": false, "confidence": 0.9, "ambiguity_reason": null, "entity_name": null, "keywords": ["gun", "control"], "topic": "gun control legislation", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

"HR 3590" →
{{"query_type": "legislation", "query_subtype": "concept", "named_entity": null, "time_filter": false, "confidence": 1.0, "ambiguity_reason": null, "entity_name": null, "keywords": [], "topic": "specific bill HR 3590", "time_range": "last 5 years", "bill_type": "hr", "result_count": 1, "specific_bill": {{"type": "hr", "number": 3590, "congress": null}}, "status": "any"}}

"Kennedy healthcare" →
{{"query_type": "legislation", "query_subtype": "concept", "named_entity": null, "time_filter": false, "confidence": 0.5, "ambiguity_reason": "Kennedy could refer to Senator Ted Kennedy or legislation named after Kennedy", "entity_name": null, "keywords": ["healthcare"], "topic": "Kennedy healthcare legislation", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

"Ted Kennedy" →
{{"query_type": "member", "query_subtype": "concept", "named_entity": null, "time_filter": false, "confidence": 0.95, "ambiguity_reason": null, "entity_name": "Ted Kennedy", "keywords": [], "topic": "", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

"Senate Judiciary Committee" →
{{"query_type": "committee", "query_subtype": "concept", "named_entity": null, "time_filter": false, "confidence": 1.0, "ambiguity_reason": null, "entity_name": "Senate Judiciary Committee", "keywords": [], "topic": "", "time_range": "last 5 years", "bill_type": "all", "result_count": 5, "specific_bill": null, "status": "any"}}

Return ONLY this JSON structure:
{{
    "query_type": "legislation",
    "query_subtype": "concept",
    "named_entity": null,
    "time_filter": false,
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
            "bill_type": "all",
            "query_subtype": "concept",
            "named_entity": None,
        }
    
    # Check for known bills before anything else
    known = check_known_bills(user_question)
    if known:
        structured["specific_bill"] = known
        structured["query_type"] = "legislation"
        structured["result_count"] = 1

    # Add congress numbers based on time range
    structured["congress_numbers"] = years_to_congress_numbers(structured.get("time_range", "last 5 years"), all_congresses=full_history)

    # Override congress_numbers if a president was mentioned
    president_congresses = extract_president_congress(user_question)
    if president_congresses:
        structured["congress_numbers"] = president_congresses
        structured["time_range"] = "presidential term"

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