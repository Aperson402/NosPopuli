# NosPopuli — Law for the People

> *Nos populus — Latin: "we the people"*

A civic intelligence platform that makes American law accessible to every citizen regardless of legal background, education, or political affiliation. The law affects everyone but is practically readable by almost no one. NosPopuli fixes that.

Live at: **nospopuli-production.up.railway.app**

---

## What It Does

A unified search bar accepts plain English questions and routes them intelligently:

- **"What has Congress done about student loans?"** → ranked relevant bills, translated into plain English
- **"Ted Kennedy"** → full member profile with career stats, policy breakdown, photo, recent bills
- **"Senate Judiciary Committee"** → committee page with recent referred legislation
- **"Give me a law that has been passed"** → filters to actually enacted legislation only
- **"HR 3590"** → goes directly to that specific bill
- **"GENIUS Act"** → directly resolves to S.1582, the Guiding and Establishing National Innovation for US Stablecoins Act
- **"3 gun rights bills under Biden"** → respects quantity and presidential term filtering
- **"Kennedy healthcare"** → flags ambiguity with 60% confidence, shows clarification options

Every bill detail page includes:
- Plain English explanation **personalized to the user's state and interests**
- Legislative timeline showing exactly how it moved through Congress
- House and Senate chamber visualizations — every member's vote as a colored dot in a semicircle, hover for name/party/vote
- Voice votes hidden automatically, recorded votes shown

---

## Architecture

NosPopuli is a multi-agent AI system. Each agent has one job. They communicate through a structured pipeline coordinated by a dispatcher.

```
User question
      ↓
Router agent          Classifies intent: legislation / member / committee / relational
                      Extracts keywords, time range, result count, entity name
                      Outputs confidence score (0.0–1.0) + ambiguity reason
                      Handles presidential terms: "under Biden" → congress 117, 118
      ↓
Dispatcher            Routes to the correct handler based on query_type
      ↓
─── federal legislation ──────────────────────────────────────
Query Expander        Haiku → expands keywords to legislative vocabulary
                      "opioid epidemic" → ["fentanyl", "naloxone", "CARA", "overdose"]
                      Acronym table: "GENIUS Act" → exact bill S.1582
                      Known bills table: bypasses search for famous named acts
      ↓
Title Search          Two-phase lookup for named acts
                      Popular names table: "Title IX", "Voting Rights Act", etc.
                      Falls back to Congress.gov title search + recent amendments
      ↓
Search agent          GovInfo API → full text search (BILLS or PLAW collection)
                      Congress.gov summaries → for named act lookups
                      Deduplicates by bill number across versions
      ↓
Result Validator      Haiku → scores each result 0–10 for query relevance
                      Drops results scoring below 5
      ↓
[These run simultaneously per bill]
Bill fetcher          Congress.gov API → raw bill data
Translator agent      Haiku → plain English, personalized to user's state + interests
Historian agent       Congress.gov actions → legislative timeline
Vote parser           Scans actions for roll call numbers (House + Senate)
Vote fetcher          House: Congress.gov v3 (118th+) or clerk.house.gov XML
                      Senate: senate.gov XML feed
Vote mapper           Semicircle seat coordinates
                      House: 435 seats, 8 rows · Senate: 100 seats, 4 rows
                      Democrats left, Republicans right

─── state legislation ────────────────────────────────────────
State Search          OpenStates v3 API → state bill search by keyword + session
                      Filters enacted bills by governor signature actions
                      Currently enabled: Virginia (VA)
                      SKIP_PATTERNS filter ceremonial resolutions automatically
      ↓
State Bill Fetcher    Full bill detail: actions, versions, sponsorships, votes
                      Fetches bill text HTML → strips boilerplate via BeautifulSoup
                      Version preference: Chaptered > Enrolled > Engrossed > Introduced
      ↓
Translator agent      Same Haiku translator, adapted for state bill context

─── member (federal) ─────────────────────────────────────────
Member search         Paginates Congress.gov member list (up to 2,500 members)
                      Nickname expansion: Ted→Edward, Bernie→Bernard
                      Scores by name match weight
                      Fetches profile, terms, photo, sponsored legislation
                      Policy area breakdown from 250 most recent bills

─── member (state) ───────────────────────────────────────────
State Member Search   OpenStates /people endpoint → state legislators by name + state
                      Returns normalized profile: chamber, party, district, role

─── committee ────────────────────────────────────────────────
Committee search      Fetches 500 committees across both chambers
                      Scores by distinctive word match (not common words)
                      GovInfo search for recent referred bills with titles

─── All actions logged ───────────────────────────────────────
Documentor            Thread-safe JSON logging of every agent action
Search Logger         User-facing event logging (searches, bill opens, member opens)
                      Includes confidence scores for quality tracking
Flag Logger           User feedback on incorrect results or translations
Analyst               Reads search + agent logs, generates plain English report
                      Surfaces zero-result queries, misclassifications, top topics
```

---

## Tech Stack

```
Backend:      Python, FastAPI, uvicorn
AI:           Anthropic API, claude-haiku-4-5-20251001 (almost exclusively)
Data:         Congress.gov API — bills, members, votes, committees, laws
              GovInfo API — full text search (BILLS + PLAW collections)
              OpenStates v3 API — state legislation + state legislators
              senate.gov XML — Senate roll call votes
              clerk.house.gov XML — House roll call votes (pre-118th)
              pgeocode + unitedstates/congress-legislators — zip→representative
Ingest:       VoyageAI voyage-law-2 — legal document embeddings
              Supabase pgvector — vector store for bill chunks
              BeautifulSoup — bill HTML text extraction
Deployment:   Railway (auto-deploys from GitHub)
Frontend:     Vanilla HTML/CSS/JS (no framework), CSS and JS in separate files
Fonts:        Playfair Display · Source Serif 4 · IBM Plex Mono
Rate limiting: slowapi (20/min search, 30/min bill, 10/min feed)
```

---

## File Structure

```
/NosPopuli
  api.py                      FastAPI app — all endpoints, dispatcher pattern
  router_agent.py             Intent classification, confidence scoring,
                              presidential term handling, known bill lookup
  query_expander_agent.py     Keyword expansion to legislative vocabulary
                              Acronym table, known bills bypass
  title_search_agent.py       Two-phase named act lookup
                              Popular names table (Title IX, VRA, Civil Rights Act…)
                              Falls back to Congress.gov title search
  search_agent.py             GovInfo full text search + Congress.gov summaries
  result_validator_agent.py   Post-search relevance scoring via Haiku
                              Filters results below threshold before display
  bill_fetcher.py             Congress.gov bill and public law fetching
  translator_agent.py         Plain English translation, personalized by
                              user state and interests (STATE_CONTEXT table)
  historian_agent.py          Legislative timeline generation
  vote_parser_agent.py        Roll call number extraction from bill actions
  vote_fetcher_agent.py       House + Senate vote data (multiple sources)
  vote_mapper_agent.py        Semicircle seat position math
  member_search_agent.py      Federal member lookup, profile, legislation, policy areas
  state_search_agent.py       OpenStates state bill search
                              ENABLED_STATES gates rollout per state (VA first)
  state_bill_fetcher.py       OpenStates bill detail + HTML text extraction
  state_member_search_agent.py  State legislator lookup via OpenStates /people
  documentor_agent.py         Thread-safe agent action logging
  search_logger.py            User-facing event logging with confidence scores
  flag_logger.py              User feedback logging (search + bill flags)
  analyst_agent.py            Usage pattern analysis, AI-generated report
  feed_agent.py               Personalized feed — rep bills + interest matching
                              INTEREST_TERMS map topics to legislative vocabulary
  civic_resolver.py           Zip code → state → senators + representative
                              Uses pgeocode + legislators-current.json
  ingest_bills.py             6-stage bill embedding pipeline (offline, run manually)
                              Discovery → Metadata → Text → Chunking → Embedding → Index
                              VoyageAI voyage-law-2 + Supabase pgvector
  watch_agents.py             Terminal agent monitor — color-coded live log tail

  /Frontend
    index.html                Main app:
                              - Unified search bar (always visible)
                              - Personalized feed (below search, localStorage)
                              - Two-step onboarding (zip + interests)
                              - Bill detail (translation, timeline, votes)
                              - Member profile (photo, stats, policy bars)
                              - Committee page (recent bills)
                              - Flag system (search + bill feedback)
                              - Clarification bar for low-confidence queries
    monitor.html              Real-time agent monitor:
                              - Agent feed with color coding
                              - Pipeline flow visualization
                              - Analytics tab (AI-generated report)
                              - Flags tab (user feedback log)
    /css
      index.css               Main app styles
      monitor.css             Monitor page styles
    /js
      index.js                Main app logic
      monitor.js              Monitor page logic

  /data
    legislators-current.json  All current US members (1.4MB)
                              Source: unitedstates/congress-legislators

  STYLEGUIDE.md               Complete design system reference
  Procfile                    Railway: uvicorn api:app --host 0.0.0.0 --port $PORT
  nixpacks.toml               Railway build configuration
  requirements.txt            Python dependencies
  .gitignore                  Excludes: .env, agent_log.json, search_log.json,
                              flags.json, __pycache__, .DS_Store
```

---

## API Endpoints

```
POST /search              Unified search — routes to legislation, member, or committee
                          Returns confidence score + ambiguity reason
POST /bill                Full bill processing (translation, timeline, votes)
                          Accepts optional user_context for personalization
POST /law                 Public law lookup by congress + law number
POST /feed                Personalized feed — interests + representative bioguides
POST /resolve-zip         Zip code → state + senators + representative
POST /state/search        State legislation search via OpenStates
                          Requires state_code; filters enacted bills only
POST /state/bill          Full state bill detail + translation
POST /state/member/search State legislator lookup by name + state
POST /member/search       Federal member search
POST /flag/search         Log user feedback on search results
POST /flag/bill           Log user feedback on bill translation/timeline
GET  /member/photo/{id}   Proxied Congress.gov member photo
GET  /monitor             Real-time agent monitor UI
GET  /monitor/stream      Agent log as JSON (polled every 500ms)
GET  /monitor/analysis    AI-generated usage analysis
GET  /monitor/flags       All user flags
POST /monitor/clear-search-log  Clear the search log (monitor admin action)
GET  /health              Service health check
```

---

## Personalized Feed

Completely anonymous. No account. No email. Stored only in browser localStorage. Clearing cookies resets everything.

**Onboarding (2 steps):**
1. Enter zip code → resolves to your state, 2 senators, 1 house rep
2. Select interests from 12 topics → Healthcare, Climate, Housing, Education, Veterans, Economy, Immigration, Gun Policy, Foreign Policy, Criminal Justice, Small Business, Agriculture

**Feed generation:**
- Rep bills: most recent sponsored legislation from your 3 representatives (90-day window, max 3)
- Interest bills: GovInfo search using curated legislative term maps per topic (max 3 per interest)
- Designation resolutions filtered out automatically
- Bill translations personalized to your state context

---

## Design System

Full reference in `STYLEGUIDE.md`. Key principles:

- Newspaper editorial aesthetic — aged paper, ink, serif typography
- **Never** use border-radius, box-shadow, or purple/blue/green
- Three fonts only: Playfair Display (headings), Source Serif 4 (body), IBM Plex Mono (labels)
- Colors: `--ink #0e0e0e` · `--paper #f5f0e8` · `--accent #8b1a1a` · `--muted #6b6355` · `--rule #c8bfaa`
- When in doubt: would this look at home in a 1940s legal newspaper?

---

## Confidence Scoring

The Router outputs a confidence score (0.0–1.0) for every query:

```
1.0  → Completely unambiguous: "HR 3590", "Ted Kennedy", "Senate Judiciary Committee"
0.85 → Clear with minor uncertainty: "healthcare bills", "what did Biden sign"
0.6  → Ambiguous: "Kennedy healthcare" — person or legislation?
<0.7 → Shows clarification bar with alternative search suggestions
```

Low-confidence queries are logged to `search_log.json` for Analyst review.

---

## Currently Running

https://nospopuli-production.up.railway.app/

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set up .env
ANTHROPIC_API_KEY=your_key
CONGRESS_API_KEY=your_key
GovInfo_API_KEY=your_key
OPENSTATES_API_KEY=your_key       # required for state legislation endpoints

# Optional — only needed if running ingest_bills.py
SUPABASE_URL=your_url
SUPABASE_KEY=your_key
VOYAGEAI_API_KEY=your_key

# Run
uvicorn api:app --reload

# Open
http://localhost:8000          Main app
http://localhost:8000/monitor  Agent monitor

# Terminal agent monitor (live log tail with color coding)
python watch_agents.py

# Bill embedding pipeline (run once offline to populate pgvector)
python ingest_bills.py
```

---

## Cost

Total spend across 3 days of development and testing: **$0.49**

Model routing philosophy: use the cheapest model that can reliably do the job. Haiku handles ~98% of all tasks. Sonnet would only be needed for relational query reasoning (planned). Opus unlikely to ever be needed for the core pipeline.

Production estimate at 1,000 daily active users: ~$3–5/day.

---

## Roadmap

```
SEARCH QUALITY
→ Relational queries: "How does X relate to Y" (Sonnet)
→ Member search filters (party, chamber, state)
→ RAG over embedded bill corpus (ingest pipeline built, query layer pending)

VISUALIZATIONS
→ Vote breakdown charts (party line vs independent)
→ Legislative knowledge graph (D3.js force-directed)
→ Sponsor map (geographic cosponsorship)
→ Bill progress tracker

STATE EXPANSION
✓ OpenStates v3 integration — state bills, state member search
✓ State bill search, detail, translation endpoints
✓ All 50 states enabled
→ State vote data + chamber visualizations
→ Session identifier coverage for remaining ~30 states

LOCAL / MUNICIPAL
→ Phase 1: Legistar API — covers 100+ major cities (NYC, Chicago, LA, Seattle, Boston, SF)
           Legistar is the dominant council management platform; unofficial API at webapi.legistar.com
→ Phase 2: Municode / American Legal Publishing — municipal code search for ordinances
→ Phase 3: Direct scraping for non-Legistar cities (high maintenance, low priority)
   Note: No equivalent of Congress.gov or OpenStates exists for local government.
         This is a genuine gap in civic infrastructure — building it is a multi-year effort.

COLLECTIVE ACTION (V2 CORE)
  The thesis: NosPopuli makes it so easy for a group to be heard that people
  will use it. The friction between "I care about this" and "my representative
  knows I care about this" is enormous for most people. NosPopuli collapses it.

  The unit of impact is the group, not the individual user.
  One letter is noise. A thousand letters from identifiable constituents in
  a single week on a bill in committee is signal a staffer briefs their boss on.

→ District signal: show how many users in a zip/district care about a bill
→ Fence-sitter map: identify representatives whose votes are genuinely persuadable
→ Committee timing: surface bills in committee now (when pressure matters most)
→ Momentum tracker: bills gaining constituent attention across districts
→ Coordinated send: synchronized letter campaigns on a bill + date window
→ Coalition view: same position across 40 districts carries structural weight
  Note: this is not ideology — it is infrastructure. A conservative and a
        progressive both benefit from a government that responds to constituents.

SELF-IMPROVEMENT PIPELINE
→ Prompt versioning + performance monitoring
→ Prompt improver agent (Opus)
→ Drift detector + arbitrator

DEPLOYMENT
→ Custom domain
→ CDN for frontend assets
```

---

## Legal

Public law is not copyrightable in the United States. All legislative text fetched and displayed by NosPopuli is in the public domain. Plain English translations are original works created by the system. NosPopuli displays information only — it is not legal advice. Every page includes a disclaimer to this effect.

---

*NosPopuli — Law for the People*
