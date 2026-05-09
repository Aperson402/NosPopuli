from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi import Response
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
import httpx
import asyncio
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

from router_agent import route_query
from search_agent import search_bills
from bill_fetcher import fetch_bill
from translator_agent import translate_bill
from historian_agent import fetch_bill_actions, fetch_related_bills, summarize_history
from documentor_agent import log_action

app = FastAPI(title="NosPopuli API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

class SearchRequest(BaseModel):
    question: str
    max_results: int = 10

class BillRequest(BaseModel):
    congress: int
    bill_type: str
    number: int

class LawRequest(BaseModel):
    congress: int
    law_number: int

class MemberSearchRequest(BaseModel):
    name: str

@app.post("/search")
async def search(request: SearchRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    structured = route_query(request.question, client)

    # ── Member search ──
    if structured.get("query_type") == "member" and structured.get("entity_name"):
        loop = asyncio.get_event_loop()
        member = await loop.run_in_executor(None, search_member, structured["entity_name"])

        if not member:
            log_search(
                query=request.question,
                query_type="member",
                expanded_terms=[],
                results_count=0,
                result_ids=[]
            )
            return {"query_type": "member", "found": False}

        profile, legislation = await asyncio.gather(
            loop.run_in_executor(None, fetch_member_profile, member["bioguide_id"]),
            loop.run_in_executor(None, fetch_member_legislation, member["bioguide_id"], 10)
        )

        log_search(
            query=request.question,
            query_type="member",
            expanded_terms=[],
            results_count=1,
            result_ids=[member.get("bioguide_id", "")]
        )
        return {
            "query_type": "member",
            "found": True,
            "member": {**member, **(profile or {})},
            "legislation": legislation
        }

    # ── Specific bill lookup ──
    specific = structured.get("specific_bill")
    if specific and specific.get("number") and specific.get("type"):
        bill_type = specific["type"].lower()
        number = specific["number"]
        congress = specific.get("congress") or structured["congress_numbers"][0]
        return {
            "query_type": "legislation",
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
    if structured.get("query_type") == "legislation":
        expanded = expand_query(
            structured.get("keywords", []),
            structured.get("topic", ""),
            client
    )
    structured["expanded_terms"] = expanded

    raw_results = search_bills(structured)

    if not raw_results:
        return {"query_type": "legislation", "query": structured, "results": [], "message": "No bills found."}

    log_action(
        agent_name="api",
        action="search",
        input_data={"question": request.question},
        output_data={"results_count": len(raw_results)}
    )

    log_search(
        query=request.question,
        query_type="legislation",
        expanded_terms=structured.get("expanded_terms", []),
        results_count=len(raw_results),
        result_ids=[f"{r.get('type','')}{r.get('number','')}" for r in raw_results]
    )
    return {"query_type": "legislation", "query": structured, "results": raw_results}
@app.post("/bill")
async def get_bill(request: BillRequest):
    loop = asyncio.get_event_loop()

    # Fetch bill data
    bill_data = await loop.run_in_executor(
        None, fetch_bill, request.congress, request.bill_type, request.number
    )

    if not bill_data:
        raise HTTPException(status_code=404, detail="Bill not found")

    # Run translation and actions in parallel
    translation, actions = await asyncio.gather(
        loop.run_in_executor(None, translate_bill, bill_data, client),
        loop.run_in_executor(None, fetch_bill_actions, request.congress, request.bill_type, request.number)
    )

    # Timeline and vote parsing both need actions — run in parallel
    timeline, vote_refs = await asyncio.gather(
        loop.run_in_executor(None, summarize_history, actions, client),
        loop.run_in_executor(None, parse_vote_references, actions)
    )

    # Fetch both chamber votes in parallel
    house_raw, senate_raw = await asyncio.gather(
        loop.run_in_executor(None, fetch_house_votes, vote_refs.get("house")),
        loop.run_in_executor(None, fetch_senate_votes, vote_refs.get("senate"))
    )

    # Map to seat positions
    house_mapped = map_house_votes(house_raw)
    senate_mapped = map_senate_votes(senate_raw)

    log_action(
        agent_name="api",
        action="get_bill",
        input_data={"congress": request.congress, "type": request.bill_type, "number": request.number},
        output_data={
            "status": "complete",
            "house_votes": len(house_raw) if house_raw else 0,
            "senate_votes": len(senate_raw) if senate_raw else 0,
        }
    )

    log_bill_opened(
        bill_id=f"{request.bill_type}{request.number}",
        title=bill_data.get("bill", {}).get("title", ""),
        from_query=""
    )

    return {
        "congress": request.congress,
        "type": request.bill_type,
        "number": request.number,
        "translation": translation,
        "timeline": timeline,
        "votes": {
            "house": house_mapped,
            "senate": senate_mapped
        }
    }

@app.post("/law")
async def get_law(request: LawRequest):
    loop = asyncio.get_event_loop()

    bill_data = await loop.run_in_executor(
        None, fetch_law, request.congress, request.law_number
    )

    if not bill_data:
        raise HTTPException(status_code=404, detail="Law not found")

    # Extract bill identifiers from the fetched data
    bill = bill_data.get("bill", {})
    bill_congress = bill.get("congress", request.congress)
    bill_type = bill.get("type", "").lower()
    bill_number = int(bill.get("number", 0))

    translation, actions = await asyncio.gather(
        loop.run_in_executor(None, translate_bill, bill_data, client),
        loop.run_in_executor(None, fetch_bill_actions, bill_congress, bill_type, bill_number)
    )

    timeline, vote_refs = await asyncio.gather(
        loop.run_in_executor(None, summarize_history, actions, client),
        loop.run_in_executor(None, parse_vote_references, actions)
    )

    house_raw, senate_raw = await asyncio.gather(
        loop.run_in_executor(None, fetch_house_votes, vote_refs.get("house")),
        loop.run_in_executor(None, fetch_senate_votes, vote_refs.get("senate"))
    )

    house_mapped = map_house_votes(house_raw)
    senate_mapped = map_senate_votes(senate_raw)

    log_action(
        agent_name="api",
        action="get_law",
        input_data={"congress": request.congress, "law_number": request.law_number},
        output_data={"status": "complete"}
    )

    return {
        "congress": request.congress,
        "law_number": request.law_number,
        "translation": translation,
        "timeline": timeline,
        "votes": {"house": house_mapped, "senate": senate_mapped}
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

@app.get("/monitor/analysis")
async def get_analysis():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, analyze, client)
    return result