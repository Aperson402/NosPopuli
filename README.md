# NosPopuli — Comprehensive README

## Vision

NosPopuli (Latin: "of the people") is a civic intelligence platform that makes American law accessible to every citizen regardless of legal background, education, or political affiliation. The law affects everyone but is practically readable by almost no one. NosPopuli fixes that.

The project has three phases:

```
Phase 1  → Federal legislation search and translation (largely complete)
Phase 2  → Personalized civic feed based on user interests and location
Phase 3  → State and local legislation, open public API
```

---

## What It Does Right Now

A user types a plain English question into a single search bar:

- **"What has Congress done about student loans?"** → returns relevant bills translated into plain English with legislative timelines
- **"Ted Kennedy"** → returns his full member profile with career stats, policy breakdown, and recent bills
- **"Give me a law that has been passed"** → filters to actually enacted legislation only
- **"HR 3590"** → goes directly to that specific bill
- **"Show me one bill about housing"** → respects the quantity intent

Every bill detail page includes:
- Plain English explanation written for any reading level
- Legislative timeline showing exactly how it moved through Congress
- House and Senate chamber visualizations showing every member's vote as a colored dot in a semicircle layout, with hover tooltips showing name, state, party, and vote

---

## Architecture

NosPopuli is a multi-agent AI system. Each agent has one job and one job only. They communicate through a shared pipeline coordinated by an orchestrator.

```
User question
      ↓
Router agent          Classifies intent: legislation / member / committee
                      Extracts keywords, time range, result count, entity name
      ↓
─── If legislation ───────────────────────────────────────────────
Search agent          Hits GovInfo API for full text search
                      Uses BILLS collection normally
                      Uses PLAW collection for enacted laws only
      ↓
Orchestrator          Spins up parallel instances per bill
                      Uses asyncio semaphore to cap concurrency
      ↓
[These three run simultaneously per bill]
Bill fetcher          Congress.gov API → raw bill data
Translator agent      Haiku → plain English explanation
Historian agent       Congress.gov actions endpoint → legislative timeline

      ↓
Vote parser agent     Scans action text for roll call numbers
                      Extracts House roll number and Senate record vote number
      ↓
[These run simultaneously]
Vote fetcher agent    House: Congress.gov v3/house-vote (118th+)
                             clerk.house.gov XML (older bills)
                      Senate: senate.gov XML feed
Vote mapper agent     Converts member votes to semicircle seat coordinates
                      House: 435 seats, 8 rows
                      Senate: 100 seats, 4 rows
                      Democrats left, Republicans right

─── If member ────────────────────────────────────────────────────
Member search agent   Paginates Congress.gov member list
                      Scores by name match with nickname expansion
                      (Ted → Edward, Bernie → Bernard, etc.)
                      Fetches profile, terms, photo
                      Fetches sponsored legislation with policy breakdown

─── All actions logged ───────────────────────────────────────────
Documentor agent      Thread-safe JSON logging of every agent action
                      Stored in agent_log.json
                      Viewable at localhost:8000/monitor
```

---

## Tech Stack

```
Backend:    Python, FastAPI, uvicorn
AI:         Anthropic API, claude-haiku-4-5 (almost exclusively)
Data:       Congress.gov API (bills, members, votes, laws)
            GovInfo API (full text search, PLAW collection)
            senate.gov XML (Senate roll call votes)
            clerk.house.gov XML (House roll call votes, older bills)
Frontend:   Vanilla HTML/CSS/JS, no framework
            IBM Plex Mono + Playfair Display + Source Serif 4
Design:     Newspaper editorial aesthetic, aged paper palette
            Full design system documented in STYLEGUIDE.md
```

---

## File Structure

```
/NosPopuli
  api.py                    FastAPI app, all endpoints
  orchestrator.py           Parallel bill processing
  router_agent.py           Intent classification and query routing
  search_agent.py           GovInfo full text search
  bill_fetcher.py           Congress.gov bill and law fetching
  translator_agent.py       Plain English translation via Haiku
  historian_agent.py        Legislative timeline generation
  vote_parser_agent.py      Roll call number extraction from actions
  vote_fetcher_agent.py     House and Senate vote data fetching
  vote_mapper_agent.py      Semicircle seat position calculation
  member_search_agent.py    Member lookup, profile, legislation
  documentor_agent.py       Thread-safe audit logging

  /frontend
    index.html              Main app (search, bill detail, member profile)
    monitor.html            Real-time agent activity monitor

  STYLEGUIDE.md             Complete design system reference
  agent_log.json            Runtime log (gitignored)
  .env                      API keys (gitignored)
  .gitignore
```

---

## API Endpoints

```
POST /search              Unified search — routes to legislation or member
POST /bill                Full bill processing (translation, timeline, votes)
POST /law                 Public law lookup by congress + law number
POST /member/search       Member profile by name
GET  /member/photo/{id}   Proxied Congress.gov photo
GET  /monitor             Real-time agent monitor UI
GET  /monitor/stream      Current agent log as JSON
GET  /health              Service health check
```

---

## Data Sources

```
Congress.gov API          Bills, members, committees, actions, votes (118th+)
                          Free, requires API key from api.congress.gov
GovInfo API               Full text search across all federal documents
                          BILLS collection: all legislation
                          PLAW collection: enacted laws only
                          Free, uses same api.data.gov key
senate.gov XML            Senate roll call votes, all congresses
                          Public, no key required
clerk.house.gov XML       House roll call votes, pre-118th Congress
                          Public, no key required
```

---

## Design System

The full design system is in `STYLEGUIDE.md`. Key principles:

- Newspaper editorial aesthetic — aged paper, ink, serif typography
- Never use border-radius, box-shadow, or purple gradients
- Three fonts only: Playfair Display (headings), Source Serif 4 (body), IBM Plex Mono (labels/code)
- Color palette: `--ink #0e0e0e`, `--paper #f5f0e8`, `--accent #8b1a1a`, `--muted #6b6355`, `--rule #c8bfaa`
- When in doubt: would this look at home in a 1940s legal newspaper?

---

## What's Built — What's Next

### Complete
- Federal bill search via GovInfo full text search
- Plain English translation via Haiku
- Legislative timeline generation
- House and Senate vote visualization (semicircle chamber diagrams)
- Enacted law filtering (PLAW collection)
- Member profiles (photo, career stats, policy areas, recent bills)
- Smart query routing (legislation / member / committee / specific bill)
- Natural language result count ("show me one bill" → 1 result)
- Nickname expansion for member search (Ted → Edward, Bernie → Bernard)
- Real-time agent monitor at /monitor
- Two-stage lazy loading (search fast, process on click)
- Parallel agent processing with asyncio

### In Progress / Next Session
- Personalized feed (anonymous, localStorage only)
  - Zip code → congressional district → your specific representatives
  - Interest selection (healthcare, climate, housing, etc.)
  - Daily feed of relevant new legislation
  - Tracking bills you care about
  - How your representatives voted on issues you care about

### Planned
- Committee pages
- Member search filters (party, chamber, state)
- State legislature expansion (California, New York, Texas first)
- Charts on bill detail page (vote breakdown by party, sponsor map, bill progress, amendment history)
- Open public API (free tier, commercial tier)
- FOIA automation agent for non-digitized local records
- Demand-driven county/local coverage

---

## The Bigger Vision

NosPopuli is civic infrastructure. The goal is not a product — it is a public utility.

**Phase 1: Federal** (current)
Make federal legislation readable by anyone.

**Phase 2: Personalized**
Curated feed based on where you live and what you care about. Completely anonymous, stored only in the browser. Clearing cookies clears everything.

**Phase 3: State and Local**
Every state legislature. Eventually every county and municipality. Demand-driven expansion — counties get added when users request them. Local governments are in various stages of digitalization; agents handle scraping, FOIA requests, and OCR of physical documents.

**Phase 4: Open API**
Free for individuals and nonprofits. Commercial tier for companies above a request threshold. Grants from Knight Foundation, Mozilla Foundation, civic tech organizations.

**The architecture scales to all of this.** Each jurisdiction gets its own fetcher agent. The translation, timeline, and vote pipeline stays identical regardless of source. The Router learns to handle state and local queries. The feed personalizes to state and local legislation automatically.

---

## Cost

Running cost as of initial build: approximately $0.20 for a full day of development and testing using claude-haiku-4-5 almost exclusively.

Production estimate at 1,000 daily active users: approximately $3/day.

Model routing philosophy: use the cheapest model that can reliably do the job. Haiku handles approximately 95% of all tasks. Sonnet would only be needed for genuinely complex legal reasoning on very long bills. Opus is unlikely to ever be needed.

---

## Running Locally

```bash
# Install dependencies
pip install fastapi uvicorn anthropic requests python-dotenv httpx

# Set up .env
ANTHROPIC_API_KEY=your_key
CONGRESS_API_KEY=your_key
GovInfo_API_KEY=your_key

# Run
uvicorn api:app --reload

# Open
http://localhost:8000        Main app
http://localhost:8000/monitor   Agent monitor
```

---

## Legal

Public law is not copyrightable in the United States. All legislative text fetched and displayed by NosPopuli is in the public domain. Plain English translations are original works created by the system. NosPopuli displays information only — it is not legal advice. Every page includes a disclaimer to this effect.

---

*NosPopuli — Law for the People*
*Started May 2026 by a high school student who thought the law should be readable by everyone.*
