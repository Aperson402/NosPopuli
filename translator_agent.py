import anthropic
import os
from supabase import create_client
from dotenv import load_dotenv
from documentor_agent import log_action
from state_search_agent import STATE_JURISDICTIONS

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_API_KEY")
)

def _cache_key(congress, bill_type, bill_number):
    return f"BILLS-{congress}{bill_type}{bill_number}"

def _get_cached(congress, bill_type, bill_number):
    try:
        package_id = _cache_key(congress, bill_type, bill_number)
        result = supabase.table("bill_translations") \
            .select("translation") \
            .eq("package_id", package_id) \
            .execute()
        if result.data:
            print(f"[TRANSLATOR] Cache hit: {package_id}")
            return result.data[0]["translation"]
        return None
    except Exception as e:
        print(f"[TRANSLATOR] Cache read error: {e}")
        return None

def _store_cached(congress, bill_type, bill_number, translation):
    try:
        package_id = _cache_key(congress, bill_type, bill_number)
        print(f"[TRANSLATOR] Attempting cache write: {package_id}")
        result = supabase.table("bill_translations").upsert({
            "package_id": package_id,
            "congress": int(congress),
            "bill_type": str(bill_type),
            "bill_number": int(bill_number),
            "translation": translation,
            "jurisdiction": "federal",
            "state_code": None,
        }).execute()
        print(f"[TRANSLATOR] Cache write result: {result.data}")
    except Exception as e:
        print(f"[TRANSLATOR] Cache write error: {e}")

def _get_cached_by_key(key):
    try:
        result = supabase.table("bill_translations") \
            .select("translation") \
            .eq("package_id", key) \
            .execute()
        if result.data:
            print(f"[TRANSLATOR] Cache hit: {key}")
            return result.data[0]["translation"]
        return None
    except Exception as e:
        print(f"[TRANSLATOR] Cache read error: {e}")
        return None


def _store_cached_by_key(key, translation, jurisdiction='federal', state_code=None):
    try:
        supabase.table("bill_translations").upsert({
            "package_id": key,
            "congress": 0,
            "bill_type": "state",
            "bill_number": 0,
            "translation": translation,
            "jurisdiction": jurisdiction,
            "state_code": state_code,
        }).execute()
        print(f"[TRANSLATOR] Cached: {key}")
    except Exception as e:
        print(f"[TRANSLATOR] Cache write error: {e}")


def translate_state_bill(bill_data, bill_text, client):
    """
    Translate a state bill. Uses actual bill text if available,
    falls back to metadata only.
    """
    bill = bill_data.get("bill", {})

    state_code = bill.get("type", "")
    identifier = bill.get("number", "")
    title = bill.get("title", "Unknown")
    sponsors = bill.get("sponsors", [{}])
    sponsor = sponsors[0].get("fullName", "Unknown") if sponsors else "Unknown"
    status = (bill.get("latestAction") or {}).get("text", "Unknown")

    cache_key = f"STATE-{state_code}-{identifier}"
    cached = _get_cached_by_key(cache_key)
    if cached:
        return cached

    if bill_text and len(bill_text) > 200:
        text_section = f"\nActual bill text (first 3000 characters):\n{bill_text[:3000]}"
    else:
        text_section = ""

    state_name = STATE_JURISDICTIONS.get(state_code, "state")
    prompt = f"""
You are a plain English translator for state legislation.
Explain this bill clearly to a {state_name} resident with no legal background.
Be concise but complete. No jargon.

Bill: {identifier} — {title}
Sponsor: {sponsor}
Current Status: {status}
{text_section}

Explain:
1. What this bill does in one sentence
2. Who it affects and how
3. What its current status means
"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    translation = message.content[0].text
    _store_cached_by_key(cache_key, translation, jurisdiction='state', state_code=state_code)

    log_action(
        agent_name="translator",
        action="translate_state_bill",
        input_data={"state": state_code, "identifier": identifier},
        output_data={"translation_preview": translation[:100]}
    )

    return translation


def translate_bill(bill_data, client, user_context=None):
    bill = bill_data["bill"]

    congress = bill.get("congress")
    bill_type = (bill.get("type") or "").lower()
    bill_number = bill.get("number")

    # Check cache first
    cached = _get_cached(congress, bill_type, bill_number)
    if cached:
        log_action(
            agent_name="translator",
            action="translate_bill_cached",
            input_data={"congress": congress, "type": bill_type, "number": bill_number},
            output_data={"source": "cache"}
        )
        return cached

    # Not cached — translate
    title = bill.get("title", "Unknown")
    sponsors = bill.get("sponsors", [{}])
    sponsor = sponsors[0].get("fullName", "Unknown") if sponsors else "Unknown"
    status = bill.get("latestAction", {}).get("text", "Unknown")
    policy_area = bill.get("policyArea", {}).get("name", "")

    prompt = f"""
You are a plain English translator for legislation.
Your only job is to explain a bill clearly to an average person.
No legal jargon. No assumptions about their background.
Be concise but complete.

Bill Title: {title}
Sponsor: {sponsor}
Current Status: {status}
Policy Area: {policy_area}

Explain:
1. What this bill does in one sentence
2. Who it affects and how
3. What its current status means
"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    translation = message.content[0].text

    # Store in cache
    _store_cached(congress, bill_type, bill_number, translation)

    log_action(
        agent_name="translator",
        action="translate_bill",
        input_data={
            "congress": congress,
            "type": bill_type,
            "number": bill_number,
            "title": title,
        },
        output_data={"translation_preview": translation[:100], "source": "api"}
    )

    return translation