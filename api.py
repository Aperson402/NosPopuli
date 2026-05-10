from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi import Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import json
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from vote_parser_agent import parse_vote_references
from vote_fetcher_agent import fetch_house_votes, fetch_senate_votes
from vote_mapper_agent import map_house_votes, map_senate_votes
from bill_fetcher import fetch_bill, fetch_law
from member_search_agent import search_member, fetch_member_profile, fetch_member_legislation
from query_expander_agent import expand_query
from search_logger import log_search, log_bill_opened, log_member_opened
from analyst_agent import analyze
from feed_agent import fetch_feed
from civic_resolver import resolve_zip
import httpx
import asyncio
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

from router_agent import route_query, extract_president_congress
from search_agent import search_bills
from bill_fetcher import fetch_bill
from translator_agent import translate_bill
from historian_agent import fetch_bill_actions, fetch_related_bills, summarize_history
from documentor_agent import log_action

app = FastAPI(title="NosPopuli API")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[API] Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Something went wrong on our end.",
            "path": str(request.url.path)
        }
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")

client = None

def get_client():
    global client
    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return client

class SearchRequest(BaseModel):
    question: str
    max_results: int = 10

class BillRequest(BaseModel):
    congress: int
    bill_type: str
    number: int
    user_context: dict = None

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

class ZipRequest(BaseModel):
    zip_code: str

# ── Search handlers ──

async def handle_member_search(structured, question, loop):
    member = await loop.run_in_executor(None, search_member, structured["entity_name"])

    if not member:
        log_search(query=question, query_type="member", expanded_terms=[],
                   results_count=0, result_ids=[], confidence=structured.get("confidence", 1.0))
        return {"query_type": "member", "found": False,
                "confidence": structured.get("confidence"),
                "ambiguity_reason": structured.get("ambiguity_reason")}

    profile, legislation = await asyncio.gather(
        loop.run_in_executor(None, fetch_member_profile, member["bioguide_id"]),
        loop.run_in_executor(None, fetch_member_legislation, member["bioguide_id"], 10)
    )

    log_search(query=question, query_type="member", expanded_terms=[],
               results_count=1, result_ids=[member.get("bioguide_id", "")],
               confidence=structured.get("confidence", 1.0))

    return {
        "query_type": "member",
        "found": True,
        "confidence": structured.get("confidence"),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "member": {**member, **(profile or {})},
        "legislation": legislation
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
                "chamber": chamber
            }
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                all_committees.extend(r.json().get("committees", []))

        name_lower = entity.lower()
        distinctive_words = [w for w in name_lower.split() if len(w) > 4
                             and w not in {"committee", "senate", "house", "joint", "select", "special", "standing"}]

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
            "sorts": [{"field": "publishdate", "sortOrder": "DESC"}]
        }

        import re
        search_r = requests.post(
            "https://api.govinfo.gov/search",
            json=search_payload,
            params={"api_key": os.getenv("GovInfo_API_KEY")},
            timeout=10
        )

        bills = []
        if search_r.status_code == 200:
            for item in search_r.json().get("results", []):
                package_id = item.get("packageId", "")
                raw = package_id.replace("BILLS-", "")
                m = re.match(r"(\d+)([a-z]+)(\d+)", raw)
                if m:
                    bills.append({
                        "congress": int(m.group(1)),
                        "type": m.group(2),
                        "number": int(m.group(3)),
                        "title": item.get("title", ""),
                        "latest_action": "",
                        "date": item.get("dateIssued", "")[:10],
                    })

        return best, bills

    committee, bills = await loop.run_in_executor(None, fetch)

    if not committee:
        return {"query_type": "committee", "found": False,
                "confidence": structured.get("confidence"),
                "ambiguity_reason": structured.get("ambiguity_reason")}

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
        "bills": [b for b in bills if b.get("number")]
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
        "results": [{
            "package_id": f"BILLS-{congress}{bill_type}{number}",
            "title": f"{bill_type.upper()} {number}",
            "date_issued": "",
            "congress": congress,
            "type": bill_type,
            "number": number,
        }]
    }


async def handle_legislation_search(structured, question, loop):
    expanded = await loop.run_in_executor(
        None, expand_query,
        structured.get("keywords", []),
        structured.get("topic", ""),
        get_client()
    )
    structured["expanded_terms"] = expanded
    structured["original_question"] = question

    raw_results = await loop.run_in_executor(None, search_bills, structured)

    log_search(
        query=question,
        query_type="legislation",
        expanded_terms=expanded,
        results_count=len(raw_results),
        result_ids=[f"{r.get('type','')}{r.get('number','')}" for r in raw_results],
        confidence=structured.get("confidence", 1.0)
    )

    log_action(
        agent_name="api",
        action="search",
        input_data={"question": question},
        output_data={"results_count": len(raw_results)}
    )

    return {
        "query_type": "legislation",
        "confidence": structured.get("confidence", 1.0),
        "ambiguity_reason": structured.get("ambiguity_reason"),
        "query": structured,
        "results": raw_results
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
            3
        )
        return {"items": items, "count": len(items)}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error generating feed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate feed. Please try again.")

@app.post("/search")
@limiter.limit("20/minute")
async def search(request: Request, body: SearchRequest):
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        structured = route_query(body.question, get_client())
        loop = asyncio.get_event_loop()
        question = body.question

        # ── Presidential override ──
        president_congresses = extract_president_congress(question)
        if president_congresses:
            structured["congress_numbers"] = president_congresses
            structured["time_range"] = "presidential term"
            if structured.get("status") == "enacted":
                structured["status"] = "any"

        # ── Dispatcher ──
        query_type = structured.get("query_type", "legislation")

        PRESIDENTS = ["trump", "biden", "obama", "bush", "clinton", "reagan"]
        entity = (structured.get("entity_name") or "").lower()
        question_lower = question.lower()

        presidential_signals = ["signed", "passed", "under", "era", "administration", "presidency", "white house"]
        congressional_signals = ["voted", "sponsored", "senator", "representative", "voting record", "cosponsored"]

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

        # ── Route ──
        if query_type == "member" and structured.get("entity_name"):
            return await handle_member_search(structured, question, loop)

        if query_type == "committee" and structured.get("entity_name"):
            return await handle_committee_search(structured, question, loop)

        specific = structured.get("specific_bill")
        if specific and specific.get("number") and specific.get("type"):
            return await handle_specific_bill(structured, question)

        return await handle_legislation_search(structured, question, loop)

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error processing search '{body.question}': {e}")
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
            raise HTTPException(status_code=404, detail="Bill not found or unavailable.")

        translation, actions = await asyncio.gather(
            loop.run_in_executor(None, translate_bill, bill_data, get_client(), body.user_context),
            loop.run_in_executor(None, fetch_bill_actions, body.congress, body.bill_type, body.number)
        )

        translation = translation or "Translation unavailable for this bill."
        actions = actions or []

        timeline, vote_refs = await asyncio.gather(
            loop.run_in_executor(None, summarize_history, actions, get_client()),
            loop.run_in_executor(None, parse_vote_references, actions)
        )

        timeline = timeline or "Timeline unavailable for this bill."
        vote_refs = vote_refs or {}

        house_raw, senate_raw = await asyncio.gather(
            loop.run_in_executor(None, fetch_house_votes, vote_refs.get("house")),
            loop.run_in_executor(None, fetch_senate_votes, vote_refs.get("senate"))
        )

        house_mapped = map_house_votes(house_raw)
        senate_mapped = map_senate_votes(senate_raw)

        log_action(
            agent_name="api",
            action="get_bill",
            input_data={"congress": body.congress, "type": body.bill_type, "number": body.number},
            output_data={"status": "complete"}
        )

        log_bill_opened(
            bill_id=f"{body.bill_type}{body.number}",
            title=bill_data.get("bill", {}).get("title", ""),
            from_query=""
        )

        return {
            "congress": body.congress,
            "type": body.bill_type,
            "number": body.number,
            "translation": translation,
            "timeline": timeline,
            "votes": {"house": house_mapped, "senate": senate_mapped}
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error processing bill {body.bill_type}{body.number}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process bill. Please try again.")

@app.post("/law")
@limiter.limit("30/minute")
async def get_law(request: Request, body: LawRequest):
    try:
        loop = asyncio.get_event_loop()

        bill_data = await loop.run_in_executor(
            None, fetch_law, body.congress, body.law_number
        )

        if not bill_data:
            raise HTTPException(status_code=404, detail="Law not found")

        bill = bill_data.get("bill", {})
        bill_congress = bill.get("congress", body.congress)
        bill_type = bill.get("type", "").lower()
        bill_number = int(bill.get("number", 0))

        translation, actions = await asyncio.gather(
            loop.run_in_executor(None, translate_bill, bill_data, get_client(), body.user_context),
            loop.run_in_executor(None, fetch_bill_actions, bill_congress, bill_type, bill_number)
        )

        translation = translation or "Translation unavailable for this law."
        actions = actions or []

        timeline, vote_refs = await asyncio.gather(
            loop.run_in_executor(None, summarize_history, actions, get_client()),
            loop.run_in_executor(None, parse_vote_references, actions)
        )

        timeline = timeline or "Timeline unavailable for this law."
        vote_refs = vote_refs or {}

        house_raw, senate_raw = await asyncio.gather(
            loop.run_in_executor(None, fetch_house_votes, vote_refs.get("house")),
            loop.run_in_executor(None, fetch_senate_votes, vote_refs.get("senate"))
        )

        house_mapped = map_house_votes(house_raw)
        senate_mapped = map_senate_votes(senate_raw)

        log_action(
            agent_name="api",
            action="get_law",
            input_data={"congress": body.congress, "law_number": body.law_number},
            output_data={"status": "complete"}
        )

        return {
            "congress": body.congress,
            "law_number": body.law_number,
            "translation": translation,
            "timeline": timeline,
            "votes": {"house": house_mapped, "senate": senate_mapped}
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error processing law {body.congress} pub {body.law_number}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process law. Please try again.")

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
        loop.run_in_executor(None, fetch_member_legislation, member["bioguide_id"], 10)
    )
    
    return {
        "found": True,
        "member": {**member, **profile} if profile else member,
        "legislation": legislation
    }

@app.get("/member/photo/{bioguide_id}")
async def member_photo(bioguide_id: str):
    from fastapi.responses import Response
    
    url = f"https://www.congress.gov/img/member/{bioguide_id.lower()}_200.jpg"
    
    async with httpx.AsyncClient() as client_http:
        response = await client_http.get(url, headers={
            "Referer": "https://www.congress.gov/",
            "User-Agent": "Mozilla/5.0"
        })
    
    if response.status_code == 200:
        return Response(
            content=response.content,
            media_type="image/jpeg"
        )
    else:
        raise HTTPException(status_code=404, detail="Photo not found")
    
@app.get("/")
async def root():
    return FileResponse("frontend/index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "NosPopuli"}

@app.get("/monitor", response_class=HTMLResponse)
async def monitor():
    return FileResponse("frontend/monitor.html")

@app.get("/monitor/stream")
async def monitor_stream():
    """Returns current log as JSON"""
    try:
        with open("agent_log.json", "r") as f:
            log = json.load(f)
        return log
    except:
        return []

@app.post("/monitor/clear-search-log")
async def clear_search_log():
    with open("search_log.json", "w") as f:
        json.dump([], f)
    return {"status": "cleared"}

@app.get("/monitor/analysis")
async def get_analysis():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, analyze, get_client())
    return result

