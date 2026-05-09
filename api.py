from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
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

@app.post("/search")
async def search(request: SearchRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    structured = route_query(request.question, client)
    raw_results = search_bills(structured, max_results=request.max_results)

    if not raw_results:
        return {"query": structured, "results": [], "message": "No bills found."}

    log_action(
        agent_name="api",
        action="search",
        input_data={"question": request.question},
        output_data={"results_count": len(raw_results)}
    )

    return {"query": structured, "results": raw_results}

@app.post("/bill")
async def get_bill(request: BillRequest):
    loop = asyncio.get_event_loop()

    bill_data = await loop.run_in_executor(
        None, fetch_bill, request.congress, request.bill_type, request.number
    )

    if not bill_data:
        raise HTTPException(status_code=404, detail="Bill not found")

    translation, actions = await asyncio.gather(
        loop.run_in_executor(None, translate_bill, bill_data, client),
        loop.run_in_executor(None, fetch_bill_actions, request.congress, request.bill_type, request.number)
    )

    timeline = await loop.run_in_executor(
        None, summarize_history, actions, client
    )

    log_action(
        agent_name="api",
        action="get_bill",
        input_data={"congress": request.congress, "type": request.bill_type, "number": request.number},
        output_data={"status": "complete"}
    )

    return {
        "congress": request.congress,
        "type": request.bill_type,
        "number": request.number,
        "translation": translation,
        "timeline": timeline
    }

@app.get("/")
async def root():
    return FileResponse("frontend/index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "NosPopuli"}