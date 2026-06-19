from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi import Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import json
import re
import secrets
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from vote_parser_agent import parse_vote_references
from vote_fetcher_agent import fetch_house_votes, fetch_senate_votes
from vote_mapper_agent import map_house_votes, map_senate_votes
from bill_fetcher import fetch_bill, fetch_law, fetch_bill_text, fetch_related_bills, fetch_amendments, parse_amends_from_title, fetch_cosponsors
from member_search_agent import (
    search_member,
    fetch_member_profile,
    fetch_member_legislation,
)
from query_expander_agent import expand_query
from search_logger import log_search, log_bill_opened, log_member_opened
from analyst_agent import analyze
from flag_logger import log_search_flag, log_bill_flag, get_flags
from feed_agent import fetch_feed
from civic_resolver import resolve_zip
import search_cache
import httpx
import asyncio
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

from router_agent import route_query, extract_president_congress
from search_agent import search_bills, search_summaries
from title_search_agent import search_by_title
from bill_fetcher import fetch_bill
from translator_agent import translate_bill, translate_state_bill
from historian_agent import (
    fetch_bill_actions,
    fetch_related_bills as historian_fetch_related_bills,
    summarize_history,
    structure_history,
)
from documentor_agent import log_action
from result_validator_agent import validate_results, validate_results_batch
from state_search_agent import (
    search_state_bills,
    get_recent_state_bills,
    ENABLED_STATES,
    fetch_state_bill_by_identifier,
    filter_enacted,
)
from state_bill_fetcher import (
    fetch_state_bill,
    fetch_state_bill_text,
    structure_state_actions,
)
from state_vote_mapper import map_state_votes
from state_member_search_agent import (
    search_state_member,
    fetch_state_member_profile,
    fetch_state_member_bills,
)

from correspondence.router import router as correspondence_router
from correspondence.db import (
    list_known_elections as db_list_known_elections,
    add_known_election as db_add_known_election,
    delete_known_election as db_delete_known_election,
)
from elections_agent import fetch_elections, fetch_election_detail, fetch_election_polling

app = FastAPI(title="NosPopuli API")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"[VALIDATION ERROR] {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[API] Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Something went wrong on our end.",
            "path": str(request.url.path),
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(correspondence_router)

class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

app.mount("/static", CachedStaticFiles(directory="frontend"), name="static")

client = None


def get_client():
    global client
    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return client


_MONITOR_SECRET = os.getenv("MONITOR_SECRET", "")

def _require_monitor_auth(request: Request):
    """Raises 403 if the request lacks a valid monitor secret."""
    if not _MONITOR_SECRET:
        raise HTTPException(status_code=503, detail="Monitor not configured — set MONITOR_SECRET in .env")
    provided = (
        request.query_params.get("secret") or
        request.headers.get("X-Monitor-Secret", "")
    )
    if not secrets.compare_digest(provided, _MONITOR_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")


def _build_connections(related: dict, amendments: list, bill_title: str, translation: str) -> dict:
    amends = parse_amends_from_title(bill_title, translation or "")
    return {
        "amends":     amends,
        "identical":  related.get("identical", []),
        "amended_by": amendments,
        "related":    related.get("related", []),
        "superseded": related.get("superseded", []),
    }


class SearchRequest(BaseModel):
    question: str
    max_results: int = 10
    full_history: bool = False
    state_code: Optional[str] = None
    before_congress: Optional[int] = None  # history starts before this congress number
    fresh: bool = False  # debug: bypass search cache for this request


class BillRequest(BaseModel):
    congress: int
    bill_type: str
    number: int
    user_context: Optional[dict] = None


class LawRequest(BaseModel):
    congress: int
    law_number: int
    user_context: dict = None


class MemberSearchRequest(BaseModel):
    name: str


class FeedRequest(BaseModel):
    interests: list
    senator_bioguides: list
    rep_bioguide: str = None
    state_code: str = None


class ZipRequest(BaseModel):
    zip_code: str


class StateBillRequest(BaseModel):
    ocd_id: str
    state_code: str
    user_context: Optional[dict] = None


class StateSearchRequest(BaseModel):
    question: str
    state_code: str
    max_results: int = 5


class StateMemberSearchRequest(BaseModel):
    name: str
    state_code: str


class KnownElectionRequest(BaseModel):
    state_code: str
    name: str
    date: str
    type: Optional[str] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None


class SearchFlagRequest(BaseModel):
    query: str
    results_shown: list
    expanded_terms: list = []
    congress_numbers: list = []
    confidence: float = 1.0
    reason: str
    notes: str = ""


class BillFlagRequest(BaseModel):
    bill_id: str
    congress: int
    bill_type: str
    reason: str
    notes: str = ""
    flagged_section: str = "translation"


# ── Search handlers ──


async def handle_member_search(structured, question, loop):
    member = await loop.run_in_executor(None, search_member, structured["entity_name"])

    if not member:
        log_search(
            query=question,
            query_type="member",
            expanded_terms=[],
            results_count=0,
            result_ids=[],
            confidence=structured.get("confidence", 1.0),
        )
        return {
            "query_type": "member",
            "found": False,
            "confidence": structured.get("confidence"),
            "ambiguity_reason": structured.get("ambiguity_reason"),
        }

    profile, legislation = await asyncio.gather(
        loop.run_in_executor(None, fetch_member_profile, member["bioguide_id"]),
        loop.run_in_executor(None, fetch_member_legislation, member["bioguide_id"], 10),
    )

    log_search(
        query=question,
        query_type="member",
        expanded_terms=[],
        results_count=1,
        result_ids=[member.get("bioguide_id", "")],
        confidence=structured.get("confidence", 1.0),
    )

    return {
        "query_type": "member",
        "found": True,
        "confidence": structured.get("confidence"),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "member": {**member, **(profile or {})},
        "legislation": legislation,
    }


async def handle_committee_search(structured, question, loop):
    entity = structured.get("entity_name", "")

    def fetch():
        import requests

        all_committees = []

        for chamber in ["senate", "house"]:
            url = "https://api.congress.gov/v3/committee"
            params = {
                "api_key": os.getenv("CONGRESS_API_KEY"),
                "format": "json",
                "limit": 250,
                "chamber": chamber,
            }
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                all_committees.extend(r.json().get("committees", []))

        name_lower = entity.lower()
        distinctive_words = [
            w
            for w in name_lower.split()
            if len(w) > 4
            and w
            not in {
                "committee",
                "senate",
                "house",
                "joint",
                "select",
                "special",
                "standing",
            }
        ]

        best = None
        best_score = 0

        for c in all_committees:
            cname = (c.get("name") or "").lower()
            score = sum(len(w) for w in distinctive_words if w in cname)
            if score > best_score:
                best_score = score
                best = c

        if not best:
            return None, []

        committee_name = best.get("name", "")
        search_payload = {
            "query": f'"{committee_name}" collection:BILLS congress:119 OR congress:118',
            "pageSize": 10,
            "offsetMark": "*",
            "sorts": [{"field": "publishdate", "sortOrder": "DESC"}],
        }

        import re

        search_r = requests.post(
            "https://api.govinfo.gov/search",
            json=search_payload,
            params={"api_key": os.getenv("GovInfo_API_KEY")},
            timeout=10,
        )

        bills = []
        if search_r.status_code == 200:
            for item in search_r.json().get("results", []):
                package_id = item.get("packageId", "")
                raw = package_id.replace("BILLS-", "")
                m = re.match(r"(\d+)([a-z]+)(\d+)", raw)
                if m:
                    bills.append(
                        {
                            "congress": int(m.group(1)),
                            "type": m.group(2),
                            "number": int(m.group(3)),
                            "title": item.get("title", ""),
                            "latest_action": "",
                            "date": item.get("dateIssued", "")[:10],
                        }
                    )

        return best, bills

    committee, bills = await loop.run_in_executor(None, fetch)

    if not committee:
        return {
            "query_type": "committee",
            "found": False,
            "confidence": structured.get("confidence"),
            "ambiguity_reason": structured.get("ambiguity_reason"),
        }

    return {
        "query_type": "committee",
        "found": True,
        "confidence": structured.get("confidence"),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "committee": {
            "name": committee.get("name"),
            "chamber": committee.get("chamber"),
            "system_code": committee.get("systemCode"),
            "url": committee.get("url"),
        },
        "bills": [b for b in bills if b.get("number")],
    }


async def handle_specific_bill(structured, question):
    specific = structured["specific_bill"]
    bill_type = specific["type"].lower()
    number = specific["number"]
    congress = specific.get("congress") or structured["congress_numbers"][0]

    return {
        "query_type": "legislation",
        "confidence": structured.get("confidence", 1.0),
        "ambiguity_reason": None,
        "query": structured,
        "results": [
            {
                "package_id": f"BILLS-{congress}{bill_type}{number}",
                "title": f"{bill_type.upper()} {number}",
                "date_issued": "",
                "congress": congress,
                "type": bill_type,
                "number": number,
            }
        ],
    }


async def handle_named_entity_search(structured, question, loop):
    named_entity = structured.get("named_entity") or question

    sc_key = None
    if not (structured.get("_bypass_search_cache") or search_cache.is_freshness_query(structured, question)):
        sc_key = search_cache.cache_key(
            {**structured, "keywords": [named_entity]},
            question,
            structured.get("result_count", 5),
        )
        cached = search_cache.get(sc_key)
        if cached:
            results = await loop.run_in_executor(None, search_cache.rehydrate, cached)
            log_search(
                query=question,
                query_type="named_entity",
                expanded_terms=[],
                results_count=len(results),
                result_ids=[f"{r.get('type', '')}{r.get('number', '')}" for r in results],
                confidence=structured.get("confidence", 1.0),
            )
            return {
                "query_type": "legislation",
                "confidence": structured.get("confidence", 1.0),
                "ambiguity_reason": structured.get("ambiguity_reason"),
                "query": structured,
                "results": results,
                "cached": True,
            }

    title_results = await loop.run_in_executor(None, search_by_title, named_entity, 3)

    if len(title_results) < 2:
        structured["expanded_terms"] = [named_entity]
        structured["original_question"] = question
        govinfo_results = await loop.run_in_executor(None, search_bills, structured)
        seen = {f"{r['congress']}{r['type']}{r['number']}" for r in title_results}
        for r in govinfo_results:
            key = f"{r['congress']}{r['type']}{r['number']}"
            if key not in seen:
                title_results.append(r)
                seen.add(key)
                if len(title_results) >= 4:
                    break

    validated = await loop.run_in_executor(
        None, validate_results, question, title_results, get_client()
    )
    final = validated if validated else title_results

    # Common-name disambiguation: when the same act name exists across 3+ different
    # congresses, surface the ambiguity rather than silently leading with the most recent.
    distinct_congresses = list({r.get("congress") for r in final if r.get("congress")})
    confidence = structured.get("confidence", 1.0)
    ambiguity_reason = structured.get("ambiguity_reason")
    if len(distinct_congresses) >= 3:
        from router_agent import congress_to_years
        years = sorted(
            [congress_to_years(c)[0] for c in distinct_congresses if c],
            reverse=True
        )[:4]
        year_list = ", ".join(str(y) for y in years)
        ambiguity_reason = (
            f"Multiple bills share this name across different Congresses "
            f"({year_list}). Showing the most relevant — add a year to your "
            f"search (e.g. \"{named_entity} {years[0]}\") to target a specific version."
        )
        confidence = min(confidence, 0.55)

    log_search(
        query=question,
        query_type="named_entity",
        expanded_terms=[],
        results_count=len(final),
        result_ids=[f"{r.get('type', '')}{r.get('number', '')}" for r in final],
        confidence=confidence,
    )

    if sc_key and final:
        await loop.run_in_executor(None, search_cache.store, sc_key, final)

    return {
        "query_type": "legislation",
        "confidence": confidence,
        "ambiguity_reason": ambiguity_reason,
        "query": structured,
        "results": final,
        "cached": False,
    }


async def handle_legislation_search(structured, question, loop):
    full_history = structured.get("full_history", False)
    max_results_override = structured.get("max_results_override")

    # Tier-1 cache: skip the expander + fetch + validator if we've seen this
    # query recently and it's not freshness-sensitive.
    cache_target = structured.get("result_count", 5)
    bypass = (
        full_history
        or structured.get("_bypass_search_cache")
        or search_cache.is_freshness_query(structured, question)
    )
    sc_key = None
    if not bypass:
        sc_key = search_cache.cache_key(structured, question, cache_target)
        cached = search_cache.get(sc_key)
        if cached:
            results = await loop.run_in_executor(None, search_cache.rehydrate, cached)
            log_search(
                query=question,
                query_type="legislation",
                expanded_terms=[],
                results_count=len(results),
                result_ids=[f"{r.get('type', '')}{r.get('number', '')}" for r in results],
                confidence=structured.get("confidence", 1.0),
            )
            return {
                "query_type": "legislation",
                "confidence": structured.get("confidence", 1.0),
                "ambiguity_reason": structured.get("ambiguity_reason"),
                "query": structured,
                "results": results,
                "cached": True,
            }

    expanded = await loop.run_in_executor(
        None,
        expand_query,
        structured.get("keywords", []),
        structured.get("topic", ""),
        get_client(),
    )
    structured["expanded_terms"] = expanded or []
    structured["original_question"] = question

    if full_history:
        max_results = max_results_override or 50
        govinfo_results = await loop.run_in_executor(
            None, search_bills, structured, max_results
        )
        summary_results = []
    elif structured.get("status") == "enacted":
        govinfo_results = await loop.run_in_executor(None, search_bills, structured)
        summary_results = []
    else:
        # Fetch 2× target so the validator has enough headroom without dropping below target
        fetch_count = min(structured.get("result_count", 5) * 2, 20)
        # Run a second keyword pass using the original (pre-expansion) keywords so that
        # explicitly named terms (like "340B") can't be lost if the expander drifts.
        orig_keywords = structured.get("keywords", [])
        keyword_structured = {**structured, "expanded_terms": orig_keywords}
        govinfo_results, govinfo_keyword, summary_results = await asyncio.gather(
            loop.run_in_executor(None, search_bills, structured, fetch_count),
            loop.run_in_executor(None, search_bills, keyword_structured, fetch_count // 2 or 3),
            loop.run_in_executor(
                None,
                search_summaries,
                " ".join(orig_keywords),
                structured.get("congress_numbers", [119, 118]),
            ),
        )
        # merge keyword pass into govinfo_results
        govinfo_results = govinfo_results + govinfo_keyword

    seen = set()
    merged = []
    for r in summary_results:
        key = f"{r.get('congress')}{r.get('type')}{r.get('number')}"
        if key not in seen and r.get("number"):
            seen.add(key)
            r["source"] = "summary"
            merged.append(r)
    for r in govinfo_results:
        key = f"{r.get('congress')}{r.get('type')}{r.get('number')}"
        if key not in seen and r.get("number"):
            seen.add(key)
            r["source"] = "govinfo"
            merged.append(r)

    # If a known-bill hint exists, prepend it to candidates so the validator
    # ranks it fairly — it gets a head start but can still lose to a better match.
    hint = structured.get("known_bill_hint")
    if hint and not full_history:
        hint_key = f"{hint.get('congress')}{hint.get('type')}{hint.get('number')}"
        if hint_key not in seen:
            hint_candidate = {
                "package_id": f"BILLS-{hint['congress']}{hint['type']}{hint['number']}",
                "title": f"{hint['type'].upper()} {hint['number']}",
                "date_issued": "",
                "congress": hint["congress"],
                "type": hint["type"],
                "number": hint["number"],
                "source": "hint",
            }
            merged.insert(0, hint_candidate)

    if full_history:
        # Run validator on history batch too — relaxed threshold (4 vs 5) so
        # "somewhat related" older bills pass, but tuna acts and impeachment
        # resolutions don't. Batched in groups of 20 to stay within token limits.
        raw_results = await loop.run_in_executor(
            None, validate_results_batch, question, merged, get_client(), 4
        )
    else:
        target = structured.get("result_count", 5)
        # Feed more candidates to the validator so filtering doesn't drop us below target
        candidates = merged[: target * 2]
        validated = await loop.run_in_executor(
            None, validate_results, question, candidates, get_client()
        )
        raw_results = validated[:target]

    log_search(
        query=question,
        query_type="legislation",
        expanded_terms=expanded,
        results_count=len(raw_results),
        result_ids=[f"{r.get('type', '')}{r.get('number', '')}" for r in raw_results],
        confidence=structured.get("confidence", 1.0),
    )

    log_action(
        agent_name="api",
        action="search",
        input_data={"question": question},
        output_data={"results_count": len(raw_results)},
    )

    if sc_key and raw_results:
        await loop.run_in_executor(None, search_cache.store, sc_key, raw_results)

    return {
        "query_type": "legislation",
        "confidence": structured.get("confidence", 1.0),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "query": structured,
        "results": raw_results,
        "cached": False,
    }


async def handle_named_entity_with_date(structured, question, loop):
    named_entity = structured.get("named_entity") or question
    congress_numbers = structured.get("congress_numbers", [119])

    all_results = await loop.run_in_executor(None, search_by_title, named_entity, 3)

    filtered = [r for r in all_results if r.get("congress") in congress_numbers]
    final = filtered if filtered else all_results

    validated = await loop.run_in_executor(
        None, validate_results, question, final, get_client()
    )
    final = validated if validated else final

    log_search(
        query=question,
        query_type="named_entity_with_date",
        expanded_terms=[],
        results_count=len(final),
        result_ids=[f"{r.get('type', '')}{r.get('number', '')}" for r in final],
        confidence=structured.get("confidence", 1.0),
    )

    return {
        "query_type": "legislation",
        "confidence": structured.get("confidence", 1.0),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "query": structured,
        "results": final,
    }


async def handle_concept_with_date(structured, question, loop):
    expanded = await loop.run_in_executor(
        None,
        expand_query,
        structured.get("keywords", []),
        structured.get("topic", ""),
        get_client(),
    )
    structured["expanded_terms"] = expanded or []
    structured["original_question"] = question

    govinfo_results = await loop.run_in_executor(None, search_bills, structured)

    raw_results = [r for r in govinfo_results if r.get("number") or r.get("law_number")][
        : structured.get("result_count", 5)
    ]

    validated = await loop.run_in_executor(
        None, validate_results, question, raw_results, get_client()
    )
    raw_results = validated if validated else raw_results

    log_search(
        query=question,
        query_type="concept_with_date",
        expanded_terms=expanded,
        results_count=len(raw_results),
        result_ids=[f"{r.get('type', '')}{r.get('number', '')}" for r in raw_results],
        confidence=structured.get("confidence", 1.0),
    )

    return {
        "query_type": "legislation",
        "confidence": structured.get("confidence", 1.0),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "query": structured,
        "results": raw_results,
    }


async def handle_law_search(structured, question, loop):
    structured["original_question"] = question
    structured["expanded_terms"] = structured.get("keywords", [])

    govinfo_results = await loop.run_in_executor(None, search_bills, structured)

    raw_results = [r for r in govinfo_results if r.get("number") or r.get("law_number")][
        : structured.get("result_count", 5)
    ]

    log_search(
        query=question,
        query_type="enacted",
        expanded_terms=structured.get("keywords", []),
        results_count=len(raw_results),
        result_ids=[f"{r.get('type', '')}{r.get('number', '')}" for r in raw_results],
        confidence=structured.get("confidence", 1.0),
    )

    return {
        "query_type": "legislation",
        "confidence": structured.get("confidence", 1.0),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "query": structured,
        "results": raw_results,
    }


async def handle_browse(structured, question, loop):
    structured["expanded_terms"] = []
    structured["keywords"] = []
    structured["original_question"] = question

    govinfo_results = await loop.run_in_executor(None, search_bills, structured)

    raw_results = [r for r in govinfo_results if r.get("number") or r.get("law_number")][
        : structured.get("result_count", 5)
    ]

    log_search(
        query=question,
        query_type="browse",
        expanded_terms=[],
        results_count=len(raw_results),
        result_ids=[f"{r.get('type', '')}{r.get('number', '')}" for r in raw_results],
        confidence=structured.get("confidence", 1.0),
    )

    return {
        "query_type": "legislation",
        "confidence": structured.get("confidence", 1.0),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "query": structured,
        "results": raw_results,
    }


async def handle_state_search(structured, question, loop):
    state_code = structured["state_code"]

    # ── Member query: route to legislator search instead of bill search ──
    if structured.get("query_type") == "member" and structured.get("entity_name"):
        member = await loop.run_in_executor(
            None, search_state_member, structured["entity_name"], state_code
        )
        if member:
            bills = await loop.run_in_executor(
                None, fetch_state_member_bills, member["ocd_person_id"], state_code, 10
            )
        else:
            bills = []
        return {
            "query_type": "state_member",
            "state_code": state_code,
            "confidence": structured.get("confidence", 1.0),
            "ambiguity_reason": structured.get("ambiguity_reason"),
            "member": member,
            "sponsored_bills": bills,
        }

    # ── Bill-number direct lookup (e.g. "HB 1234", "SB 45") ──
    bill_id_match = re.search(r"\b([HS][BJCR]?\s*\d+)\b", question, re.IGNORECASE)
    if bill_id_match:
        identifier = re.sub(r"\s+", " ", bill_id_match.group(1).upper().strip())
        direct = await loop.run_in_executor(
            None, fetch_state_bill_by_identifier, identifier, state_code
        )
        if direct:
            return {
                "query_type": "state_legislation",
                "state_code": state_code,
                "confidence": 1.0,
                "ambiguity_reason": None,
                "query": structured,
                "results": direct,
            }
        # fall through to text search if identifier not found

    keywords = structured.get("keywords", [])
    expanded = await loop.run_in_executor(
        None, expand_query, keywords, structured.get("topic", ""), get_client()
    )

    # Build search terms from clean keywords, not the full conversational question.
    # OpenStates does full-text search on bill titles so conversational phrasing hurts recall.
    primary_term = " ".join(keywords) if keywords else question
    seen = set()
    results = []
    search_terms = [primary_term] + (expanded[:2] if expanded else [])
    target_count = max(structured.get("result_count", 5), 10)

    for term in search_terms:
        term_results = await loop.run_in_executor(
            None, search_state_bills, term, state_code, None, 20
        )
        for r in term_results:
            key = r.get("ocd_id")
            if key not in seen:
                seen.add(key)
                results.append(r)
        if len(results) >= target_count:
            break

    results = results[:target_count]

    # ── Enacted filter ──
    if structured.get("status") == "enacted":
        enacted = filter_enacted(results)
        if enacted:
            results = enacted

    results = await loop.run_in_executor(
        None, validate_results, question, results, get_client(), 7, False
    )

    log_search(
        query=question,
        query_type="state_legislation",
        expanded_terms=expanded or [],
        results_count=len(results),
        result_ids=[r.get("identifier", "") for r in results],
        confidence=structured.get("confidence", 1.0),
    )

    return {
        "query_type": "state_legislation",
        "state_code": state_code,
        "confidence": structured.get("confidence", 1.0),
        "ambiguity_reason": None,
        "query": structured,
        "results": results,
    }


@app.post("/resolve-zip")
@limiter.limit("10/minute")
async def resolve_zip_endpoint(request: Request, body: ZipRequest):
    """Takes a zip code, returns state and representatives."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, resolve_zip, body.zip_code)

    if not result:
        raise HTTPException(status_code=404, detail="Could not resolve zip code")

    return result


@app.post("/feed")
@limiter.limit("10/minute")
async def get_feed(request: Request, body: FeedRequest):
    """Returns personalized feed based on interests and representatives."""
    try:
        loop = asyncio.get_event_loop()
        items = await loop.run_in_executor(
            None,
            fetch_feed,
            body.interests,
            body.senator_bioguides,
            body.rep_bioguide,
            30,
            3,
            body.state_code,
        )
        return {"items": items, "count": len(items)}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error generating feed: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to generate feed. Please try again."
        )


@app.post("/search")
@limiter.limit("20/minute")
async def search(request: Request, body: SearchRequest):
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        structured = route_query(
            body.question, get_client(), full_history=body.full_history
        )
        structured["full_history"] = body.full_history
        structured["max_results_override"] = body.max_results if body.full_history else None
        structured["_bypass_search_cache"] = bool(body.fresh)
        if body.full_history and body.before_congress:
            structured["before_congress"] = body.before_congress
        loop = asyncio.get_event_loop()
        question = body.question

        # ── Presidential override ──
        president_congresses = extract_president_congress(question)
        if president_congresses:
            structured["congress_numbers"] = president_congresses
            structured["time_range"] = "presidential term"

        # ── Dispatcher ──
        query_type = structured.get("query_type", "legislation")

        PRESIDENTS = ["trump", "biden", "obama", "bush", "clinton", "reagan"]
        entity = (structured.get("entity_name") or "").lower()
        question_lower = question.lower()

        presidential_signals = [
            "signed",
            "passed",
            "under",
            "era",
            "administration",
            "presidency",
            "white house",
        ]
        congressional_signals = [
            "voted",
            "sponsored",
            "senator",
            "representative",
            "voting record",
            "cosponsored",
        ]

        if query_type == "member" and any(p in entity for p in PRESIDENTS):
            has_presidential = any(s in question_lower for s in presidential_signals)
            has_congressional = any(s in question_lower for s in congressional_signals)
            if has_presidential and not has_congressional:
                query_type = "legislation"
                structured["query_type"] = "legislation"
                structured["entity_name"] = None
            elif not has_congressional and "trump" in entity:
                query_type = "legislation"
                structured["query_type"] = "legislation"
                structured["entity_name"] = None

        # ── State jurisdiction short-circuit ──
        if body.state_code:
            structured["jurisdiction"] = "state"
            structured["state_code"] = body.state_code.upper()
        if structured.get("jurisdiction") == "state" and structured.get("state_code"):
            state_code = structured["state_code"]
            if state_code in ENABLED_STATES:
                return await handle_state_search(structured, question, loop)
            else:
                return {
                    "query_type": "legislation",
                    "confidence": 1.0,
                    "ambiguity_reason": f"{state_code} state legislation is not yet available.",
                    "query": structured,
                    "results": [],
                }

        # ── Route ──
        if query_type == "member" and structured.get("entity_name"):
            return await handle_member_search(structured, question, loop)

        if query_type == "committee" and structured.get("entity_name"):
            return await handle_committee_search(structured, question, loop)

        specific = structured.get("specific_bill")
        if specific and specific.get("number") and specific.get("type"):
            return await handle_specific_bill(structured, question)

        # ── Legislation subtypes ──
        subtype = structured.get("query_subtype", "concept")
        log_action(
            agent_name="dispatcher",
            action=subtype,
            input_data={
                "question": question,
                "congress": structured.get("congress_numbers"),
            },
            output_data={},
        )

        # Full-history show-more bypasses specialized handlers — they don't support it
        if structured.get("full_history"):
            return await handle_legislation_search(structured, question, loop)

        if subtype == "named_entity":
            return await handle_named_entity_search(structured, question, loop)

        if subtype == "named_entity_with_date":
            return await handle_named_entity_with_date(structured, question, loop)

        if subtype == "concept_with_date":
            return await handle_concept_with_date(structured, question, loop)

        if subtype == "enacted" or structured.get("status") == "enacted":
            return await handle_law_search(structured, question, loop)

        if subtype == "browse":
            return await handle_browse(structured, question, loop)

        return await handle_legislation_search(structured, question, loop)

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        print(f"[API] Full error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Search failed. Please try again.")


@app.post("/bill")
@limiter.limit("30/minute")
async def get_bill(request: Request, body: BillRequest):
    try:
        loop = asyncio.get_event_loop()

        bill_data = await loop.run_in_executor(
            None, fetch_bill, body.congress, body.bill_type, body.number
        )

        if not bill_data:
            raise HTTPException(
                status_code=404, detail="Bill not found or unavailable."
            )

        bill_text, related, amendments, cosponsors = await asyncio.gather(
            loop.run_in_executor(None, fetch_bill_text, body.congress, body.bill_type, body.number),
            loop.run_in_executor(None, fetch_related_bills, body.congress, body.bill_type, body.number),
            loop.run_in_executor(None, fetch_amendments, body.congress, body.bill_type, body.number),
            loop.run_in_executor(None, fetch_cosponsors, body.congress, body.bill_type, body.number),
        )

        translation, actions = await asyncio.gather(
            loop.run_in_executor(
                None,
                translate_bill,
                bill_data,
                get_client(),
                body.user_context,
                bill_text,
            ),
            loop.run_in_executor(
                None, fetch_bill_actions, body.congress, body.bill_type, body.number
            ),
        )

        translation = translation or "Translation unavailable for this bill."
        actions = actions or []

        timeline, vote_refs = await asyncio.gather(
            loop.run_in_executor(None, summarize_history, actions, get_client()),
            loop.run_in_executor(None, parse_vote_references, actions),
        )

        timeline = timeline or "Timeline unavailable for this bill."
        vote_refs = vote_refs or {}

        house_raw, senate_raw = await asyncio.gather(
            loop.run_in_executor(None, fetch_house_votes, vote_refs.get("house")),
            loop.run_in_executor(None, fetch_senate_votes, vote_refs.get("senate")),
        )

        house_mapped = map_house_votes(house_raw)
        senate_mapped = map_senate_votes(senate_raw)

        bill_title = bill_data.get("bill", {}).get("title", "")
        connections = _build_connections(related or {}, amendments or [], bill_title, translation)

        log_action(
            agent_name="api",
            action="get_bill",
            input_data={
                "congress": body.congress,
                "type": body.bill_type,
                "number": body.number,
            },
            output_data={"status": "complete"},
        )

        log_bill_opened(
            bill_id=f"{body.bill_type}{body.number}",
            title=bill_title,
            from_query="",
        )

        laws = bill_data.get("bill", {}).get("laws") or []
        became_law = laws[0] if laws else None

        raw_sponsors = bill_data.get("bill", {}).get("sponsors") or []
        sponsors = [
            {
                "name": s.get("fullName", ""),
                "first_name": s.get("firstName", ""),
                "last_name": s.get("lastName", ""),
                "party": s.get("party", ""),
                "state": s.get("state", ""),
                "bioguide_id": s.get("bioguideId", ""),
                "is_by_request": s.get("isByRequest", "N") == "Y",
            }
            for s in raw_sponsors
        ]

        return {
            "congress": body.congress,
            "type": body.bill_type,
            "number": body.number,
            "translation": translation,
            "timeline": timeline,
            "timeline_events": structure_history(actions),
            "votes": {"house": house_mapped, "senate": senate_mapped},
            "bill_text": bill_text or None,
            "connections": connections,
            "became_law": became_law,
            "sponsors": sponsors,
            "cosponsors": cosponsors or [],
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error processing bill {body.bill_type}{body.number}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to process bill. Please try again."
        )


@app.post("/law")
@limiter.limit("30/minute")
async def get_law(request: Request, body: LawRequest):
    try:
        loop = asyncio.get_event_loop()

        bill_data = await loop.run_in_executor(
            None, fetch_law, body.congress, body.law_number
        )

        if not bill_data:
            return {
                "congress": body.congress,
                "law_number": body.law_number,
                "translation": "This law was recently enacted and its full details are not yet available in Congress.gov. Check back soon.",
                "timeline": "Timeline unavailable — law not yet indexed.",
                "votes": {"house": None, "senate": None},
            }

        bill = bill_data.get("bill", {})
        bill_congress = bill.get("congress", body.congress)
        bill_type = bill.get("type", "").lower()
        bill_number = int(bill.get("number", 0))

        bill_text, related, amendments = await asyncio.gather(
            loop.run_in_executor(None, fetch_bill_text, bill_congress, bill_type, bill_number),
            loop.run_in_executor(None, fetch_related_bills, bill_congress, bill_type, bill_number),
            loop.run_in_executor(None, fetch_amendments, bill_congress, bill_type, bill_number),
        )

        translation, actions = await asyncio.gather(
            loop.run_in_executor(
                None,
                translate_bill,
                bill_data,
                get_client(),
                body.user_context,
                bill_text,
            ),
            loop.run_in_executor(
                None, fetch_bill_actions, bill_congress, bill_type, bill_number
            ),
        )

        translation = translation or "Translation unavailable for this law."
        actions = actions or []

        timeline, vote_refs = await asyncio.gather(
            loop.run_in_executor(None, summarize_history, actions, get_client()),
            loop.run_in_executor(None, parse_vote_references, actions),
        )

        timeline = timeline or "Timeline unavailable for this law."
        vote_refs = vote_refs or {}

        house_raw, senate_raw = await asyncio.gather(
            loop.run_in_executor(None, fetch_house_votes, vote_refs.get("house")),
            loop.run_in_executor(None, fetch_senate_votes, vote_refs.get("senate")),
        )

        house_mapped = map_house_votes(house_raw)
        senate_mapped = map_senate_votes(senate_raw)

        bill_title = bill_data.get("bill", {}).get("title", "")
        connections = _build_connections(related or {}, amendments or [], bill_title, translation)

        log_action(
            agent_name="api",
            action="get_law",
            input_data={"congress": body.congress, "law_number": body.law_number},
            output_data={"status": "complete"},
        )

        return {
            "congress": body.congress,
            "law_number": body.law_number,
            "translation": translation,
            "timeline": timeline,
            "timeline_events": structure_history(actions),
            "votes": {"house": house_mapped, "senate": senate_mapped},
            "bill_text": bill_text or None,
            "connections": connections,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error processing law {body.congress} pub {body.law_number}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to process law. Please try again."
        )


@app.post("/state/search")
@limiter.limit("20/minute")
async def state_search(request: Request, body: StateSearchRequest):
    if body.state_code.upper() not in ENABLED_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"{body.state_code} is not yet available. Check back soon.",
        )
    try:
        loop = asyncio.get_event_loop()
        # Strip natural language filler — OpenStates needs keywords not a sentence
        FILLER = {"show", "me", "a", "an", "the", "bill", "bills", "about",
                  "related", "to", "regarding", "find", "give", "some", "legislation",
                  "laws", "law", "any", "that", "which", "have", "has", "been"}
        keywords = [w for w in body.question.lower().split() if w not in FILLER and len(w) > 2]
        search_query = " ".join(keywords) if keywords else body.question
        print(f"[STATE SEARCH] Cleaned query: '{body.question}' → '{search_query}'")
        results = await loop.run_in_executor(
            None,
            search_state_bills,
            search_query,
            body.state_code,
            None,
            body.max_results,
        )
        if results:
            results = await loop.run_in_executor(
                None, validate_results, body.question, results, get_client(), 3, True
            )
        return {
            "query_type": "state_legislation",
            "state_code": body.state_code,
            "results": results,
        }
    except Exception as e:
        print(f"[API] State search error: {e}")
        raise HTTPException(status_code=500, detail="State search failed.")


@app.post("/state/bill")
@limiter.limit("30/minute")
async def get_state_bill(request: Request, body: StateBillRequest):
    try:
        loop = asyncio.get_event_loop()

        bill_data = await loop.run_in_executor(None, fetch_state_bill, body.ocd_id)

        if not bill_data:
            raise HTTPException(status_code=404, detail="State bill not found.")

        bill_text  = await loop.run_in_executor(None, fetch_state_bill_text, bill_data)
        votes_raw  = bill_data.get("votes", [])
        house_vote  = map_state_votes(votes_raw, body.state_code, "lower")
        senate_vote = map_state_votes(votes_raw, body.state_code, "upper")

        synthetic_bill_data = {
            "bill": {
                "congress": None,
                "type": body.state_code,
                "number": bill_data.get("identifier", ""),
                "title": bill_data.get("title", ""),
                "sponsors": [
                    {"fullName": s.get("name", "")}
                    for s in bill_data.get("sponsorships", [])
                    if s.get("primary")
                ],
                "latestAction": {
                    "text": bill_data.get("latest_action_description", "")
                },
                "policyArea": {"name": ""},
            }
        }

        translation = await loop.run_in_executor(
            None, translate_state_bill, synthetic_bill_data, bill_text, get_client()
        )

        timeline_events = structure_state_actions(bill_data)

        log_action(
            agent_name="api",
            action="get_state_bill",
            input_data={"ocd_id": body.ocd_id, "state": body.state_code},
            output_data={"status": "complete"},
        )

        return {
            "ocd_id": body.ocd_id,
            "state_code": body.state_code,
            "identifier": bill_data.get("identifier", ""),
            "title": bill_data.get("title", ""),
            "translation": translation,
            "timeline": "",
            "timeline_events": timeline_events,
            "votes": {"house": house_vote, "senate": senate_vote},
            "is_state_bill": True,
            "bill_text": bill_text or None,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] State bill error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load state bill.")


@app.post("/state/member/search")
async def state_member_search(request: Request, body: StateMemberSearchRequest):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name required")

    loop = asyncio.get_event_loop()
    member = await loop.run_in_executor(
        None, search_state_member, body.name, body.state_code
    )

    if not member:
        return {"found": False, "member": None}

    bills = await loop.run_in_executor(
        None, fetch_state_member_bills, member["ocd_person_id"], body.state_code, 10
    )

    return {
        "found": True,
        "member": member,
        "legislation": {
            "sponsored": bills,
            "sponsored_count": len(bills),
            "cosponsored_count": 0,
            "policy_areas": {},
        },
    }


@app.post("/member/search")
async def member_search(request: MemberSearchRequest):
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Name required")

    loop = asyncio.get_event_loop()

    member = await loop.run_in_executor(None, search_member, request.name)
    if not member:
        return {"found": False, "member": None}

    profile, legislation = await asyncio.gather(
        loop.run_in_executor(None, fetch_member_profile, member["bioguide_id"]),
        loop.run_in_executor(None, fetch_member_legislation, member["bioguide_id"], 10),
    )

    return {
        "found": True,
        "member": {**member, **profile} if profile else member,
        "legislation": legislation,
    }


@app.get("/member/photo/{bioguide_id}")
async def member_photo(bioguide_id: str):
    from fastapi.responses import Response

    url = f"https://www.congress.gov/img/member/{bioguide_id.lower()}_200.jpg"

    async with httpx.AsyncClient() as client_http:
        response = await client_http.get(
            url,
            headers={
                "Referer": "https://www.congress.gov/",
                "User-Agent": "Mozilla/5.0",
            },
        )

    if response.status_code == 200:
        return Response(content=response.content, media_type="image/jpeg")
    else:
        raise HTTPException(status_code=404, detail="Photo not found")


@app.get("/api/elections")
@limiter.limit("10/minute")
async def elections_endpoint(request: Request, zip: Optional[str] = None, state: Optional[str] = None):
    """Returns upcoming and recent elections, optionally personalized by zip/state."""
    try:
        data = await fetch_elections(zip_code=zip, state_code=state)
        return data
    except Exception as e:
        print(f"[API] Elections error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch elections data.")


@app.get("/elections")
async def elections_page():
    return FileResponse("frontend/elections.html")


@app.get("/api/elections/{election_id}")
@limiter.limit("20/minute")
async def election_detail_endpoint(
    request: Request,
    election_id: str,
    zip: Optional[str] = None,
    state: Optional[str] = None,
):
    try:
        detail = await fetch_election_detail(election_id, zip_code=zip, state_code=state)
        if not detail:
            raise HTTPException(status_code=404, detail="Election not found.")
        return detail
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Election detail error for {election_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch election detail.")


@app.get("/api/elections/{election_id}/polling")
@limiter.limit("10/minute")
async def election_polling_endpoint(
    request: Request,
    election_id: str,
    state: Optional[str] = None,
):
    try:
        data = await fetch_election_polling(election_id, state_code=state)
        return data
    except Exception as e:
        print(f"[API] Polling error for {election_id}: {e}")
        return {}


@app.get("/elections/{election_id}")
async def election_detail_page(election_id: str):
    return FileResponse("frontend/election_detail.html")


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/test")
async def test_home():
    return FileResponse("frontend/test.html")


@app.post("/flag/search")
async def flag_search(request: SearchFlagRequest):
    try:
        log_search_flag(
            query=request.query,
            results_shown=request.results_shown,
            reason=request.reason,
            notes=request.notes,
        )
        return {"status": "flagged", "message": "Thank you for the feedback."}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to log flag")


@app.post("/flag/bill")
async def flag_bill(request: BillFlagRequest):
    try:
        log_bill_flag(
            bill_id=request.bill_id,
            congress=request.congress,
            bill_type=request.bill_type,
            reason=request.reason,
            notes=request.notes,
            flagged_section=request.flagged_section,
        )
        return {"status": "flagged", "message": "Thank you for the feedback."}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to log flag")


@app.get("/monitor/flags")
async def get_all_flags(request: Request):
    _require_monitor_auth(request)
    return get_flags()


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Event watcher ──

WATCHER_SECRET = os.getenv("WATCHER_SECRET", "")


@app.post("/watcher/run")
async def watcher_run(request: Request):
    secret = request.headers.get("X-Watcher-Secret", "")
    if not WATCHER_SECRET or secret != WATCHER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    from event_watcher import run_watcher
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_watcher)
    return result


@app.get("/correspondence/unsubscribe-link")
async def unsubscribe_link(email: str, bill_id: str):
    """One-click unsubscribe from email notifications."""
    from correspondence.db import deactivate_subscription
    deactivate_subscription(email, bill_id)
    return HTMLResponse(
        "<html><body style='font-family:Georgia,serif;max-width:480px;margin:4rem auto;"
        "color:#0e0e0e;padding:2rem'>"
        f"<p style='color:#6b6355;font-size:0.75rem;text-transform:uppercase;"
        "letter-spacing:0.08em'>NosPopuli</p>"
        f"<h2>Unsubscribed</h2>"
        f"<p>You'll no longer receive updates on <strong>{bill_id}</strong>.</p>"
        "<p><a href='/' style='color:#8b1a1a'>Return to NosPopuli</a></p>"
        "</body></html>"
    )


@app.get("/admin/elections")
async def admin_list_elections(request: Request, state: Optional[str] = None):
    _require_monitor_auth(request)
    return {"elections": db_list_known_elections(state)}


@app.post("/admin/elections")
async def admin_add_election(request: Request, body: KnownElectionRequest):
    _require_monitor_auth(request)
    try:
        new_id = db_add_known_election(
            state_code=body.state_code,
            name=body.name,
            date=body.date,
            election_type=body.type,
            source_url=body.source_url,
            notes=body.notes,
        )
        return {"id": new_id, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/admin/elections/{election_id}")
async def admin_delete_election(request: Request, election_id: int):
    _require_monitor_auth(request)
    db_delete_known_election(election_id)
    return {"status": "deleted"}


@app.get("/admin/elections/ui", response_class=HTMLResponse)
async def admin_elections_ui(request: Request):
    _require_monitor_auth(request)
    return FileResponse("frontend/admin_elections.html")


@app.get("/monitor", response_class=HTMLResponse)
async def monitor(request: Request):
    _require_monitor_auth(request)
    return FileResponse("frontend/monitor.html")


@app.get("/monitor/stream")
async def monitor_stream(request: Request):
    _require_monitor_auth(request)
    try:
        with open("agent_log.json", "r") as f:
            log = json.load(f)
        return log
    except:
        return []


@app.post("/monitor/clear-search-log")
async def clear_search_log(request: Request):
    _require_monitor_auth(request)
    with open("search_log.json", "w") as f:
        json.dump([], f)
    return {"status": "cleared"}


@app.post("/monitor/clear-search-cache")
async def clear_search_cache_endpoint(request: Request):
    _require_monitor_auth(request)
    n = search_cache.clear()
    return {"status": "cleared", "entries_removed": n}


@app.get("/monitor/analysis")
async def get_analysis(request: Request):
    _require_monitor_auth(request)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, analyze, get_client())
    return result
