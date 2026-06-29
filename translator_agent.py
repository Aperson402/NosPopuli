import anthropic
import json
import os
from supabase import create_client
from dotenv import load_dotenv
from documentor_agent import log_action
from state_search_agent import STATE_JURISDICTIONS
from reference_resolver import resolve_references, REF_HARD_LIMIT

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_API_KEY")
)

def _cache_key(congress, bill_type, bill_number):
    # v3 prefix forces re-translation after the enacted-status fix. Old v2
    # rows could claim a not-yet-signed bill was law because the prompt
    # didn't have an authoritative is_law signal. Lazy invalidation on next
    # view; old v2 rows linger unused.
    return f"BILLS-v3-{congress}{bill_type}{bill_number}"

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

Explain in these four sections:
1. What this bill does in one sentence
2. Who it affects and how (specific groups: taxpayers, agencies, industries, individuals)
3. Costs, trade-offs, and obligations — what does this cost, who pays, what is required or restricted, and what is given up. If unknown, say so briefly.
4. What its current status means
"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
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


def _parse_translation_json(raw: str):
    """Parse Haiku's JSON output. Returns (translation_markdown, unknown_refs).

    Fail-open: malformed JSON falls back to using the raw text as the
    translation and an empty unknown_refs list. The user still gets the
    explanation; we just skip the Background section."""
    body = raw
    if body.startswith("```"):
        body = body.strip("`").lstrip("json").strip()
    try:
        parsed = json.loads(body)
        translation = (parsed.get("translation") or "").strip()
        unknown_refs = parsed.get("unknown_refs") or []
        if not isinstance(unknown_refs, list):
            unknown_refs = []
        unknown_refs = [str(t).strip() for t in unknown_refs if str(t).strip()]
        if not translation:
            return raw, []
        return translation, unknown_refs
    except json.JSONDecodeError:
        # Treat the whole response as the translation — better than nothing.
        return raw, []


def _format_background(resolutions: dict) -> str:
    """Render the Background section appended after the four-part explanation."""
    lines = ["## Background"]
    for term, body in resolutions.items():
        lines.append(f"**{term}** — {body}")
    return "\n\n".join(lines)


def translate_bill(bill_data, client, user_context=None, bill_text=None):
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

    # Authoritative enacted-status signal. The Congress.gov bill record only
    # populates `laws` once a Public Law number is actually assigned (signed
    # by the President or override of veto). Inferring "enacted" from action
    # text is unreliable — the model previously read procedural notations
    # like "Motion to reconsider laid on the table" as evidence of enactment.
    laws = bill.get("laws") or []
    is_law = bool(laws)
    law_number = laws[0].get("number") if laws else None

    status_signal = (
        f"ENACTED. Became Public Law {law_number}." if is_law
        else "NOT YET LAW. Use the latest action text below to describe the current stage in plain English (introduced, in committee, passed one chamber, passed both chambers awaiting presentment, sent to the President, etc.) — never state or imply the bill has been signed into law."
    )

    text_section = ""
    if bill_text and len(bill_text) > 200:
        text_section = f"\nActual bill text (excerpt):\n{bill_text[:8000]}"

    prompt = f"""
You are a plain English translator for legislation.
Your only job is to explain a bill clearly to an average person.
No legal jargon. No assumptions about their background.
Be concise but complete.
Base your explanation on the actual bill text when provided — do not infer or guess.

Bill Title: {title}
Sponsor: {sponsor}
Latest Action: {status}
Enacted Status: {status_signal}
Policy Area: {policy_area}
{text_section}

Return ONLY valid JSON, no markdown fences. Shape:
{{
  "translation": "<the plain-English explanation as markdown — see structure below>",
  "unknown_refs": ["<term>", ...]
}}

The translation field is markdown with these four sections, in order:
1. What this bill does in one sentence
2. Who it affects and how (specific groups: taxpayers, agencies, industries, individuals)
3. Costs, trade-offs, and obligations — what does this cost, who pays, what is required or restricted, and what is given up (e.g. federal spending, new mandates, regulatory burdens, loss of existing rights or programs). If costs or trade-offs are unknown or not specified in the bill, say so briefly.
4. What its current status means — the Enacted Status line above is authoritative. Procedural notations like "Motion to reconsider laid on the table", "Read twice", "Referred to Committee", or chamber-passage votes do NOT mean the bill is law. Only when Enacted Status begins with "ENACTED" may you describe the bill as law.

unknown_refs is a list of proper-noun programs, funds, statutes, offices, or
doctrines this bill references by name but does NOT itself define, AND that an
average reader would likely need explained. List at most {REF_HARD_LIMIT} terms;
omit common civics terms ("Congress", "Department of Justice") and anything you
yourself can adequately define in the translation body. Return [] when nothing
qualifies. Do NOT write "the bill does not explain X" in the translation body —
listed terms will be covered separately in a Background section.
"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    translation, unknown_refs = _parse_translation_json(raw)

    if unknown_refs:
        try:
            resolutions = resolve_references(unknown_refs, client)
        except Exception as e:
            print(f"[TRANSLATOR] Reference resolver error: {e}")
            resolutions = {}
        if resolutions:
            translation = translation.rstrip() + "\n\n" + _format_background(resolutions)

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