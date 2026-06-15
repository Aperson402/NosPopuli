# NosPopuli — Claude Code Context

## Dev server
```
uvicorn api:app --reload --port 8000
```
Frontend is served as static files from `frontend/` by FastAPI. No separate build step.

## Stack
- **Backend**: FastAPI (`api.py`), Python, SQLite (`correspondence.db`)
- **Frontend**: Vanilla JS SPA (`frontend/js/index.js`), no framework, no bundler
- **Navigation**: `showPage(id)` swaps `.page` divs — no URL changes, no router
- **Translation cache**: Supabase `bill_translations` table (`translator_agent.py`)
- **Disk cache**: `correspondence.db → disk_cache` table (elections + feed)
- **AI**: Anthropic Claude — Haiku for validation/ranking, Sonnet for translation and web search

## Key files
| File | Role |
|------|------|
| `api.py` | All HTTP endpoints, orchestrates agents |
| `router_agent.py` | Classifies query type, extracts structure |
| `query_expander_agent.py` | Expands keywords for GovInfo search |
| `search_agent.py` | GovInfo + Congress.gov bill search |
| `result_validator_agent.py` | Scores/ranks/filters results (Haiku) |
| `title_search_agent.py` | Named-act lookup (hardcoded → scraped → Congress.gov → GovInfo) |
| `translator_agent.py` | Plain-English bill translation, Supabase cache |
| `bill_fetcher.py` | Congress.gov bill/text/cosponsors fetch, TTL caches |
| `historian_agent.py` | Legislative timeline from bill actions |
| `feed_agent.py` | Personalized feed (interests + reps + state), 1hr disk cache |
| `elections_agent.py` | Google Civic + Claude web search elections, 6hr disk cache |
| `correspondence/db.py` | SQLite helpers — users, subscriptions, disk_cache, etc. |
| `frontend/js/index.js` | Entire frontend: search, bill detail, member, feed, elections |
| `frontend/index.html` | Single HTML shell; all pages as hidden `.page` divs |
| `frontend/css/index.css` | All styles |

## Design system
- Fonts: IBM Plex Mono (mono/UI labels), Source Serif 4 (body), Playfair Display (display)
- Colors: `--ink #0e0e0e`, `--paper #f5f0e8`, `--accent #8b1a1a`, `--rule` (borders), `--muted` (secondary text)
- No emojis. No rounded corners (border-radius: 2px max). Newspaper aesthetic.

## Search pipeline
1. `router_agent` → classifies into `legislation`, `named_entity`, `concept_with_date`, etc.
2. `query_expander_agent` → produces `expanded_terms`
3. `search_agent.search_bills()` → GovInfo Solr query + Congress.gov summaries fallback
4. `result_validator_agent.validate_results_batch()` → scores 0-10, sorts by score, drops < min_score
5. Returns top N results

**Full-history mode**: triggered by "Show More" button. Sends `full_history=true` + `before_congress` to go back 20 congresses from the initial search. Results deduplicated in the frontend against `currentResults`.

## Key frontend state
```js
let currentResults = [];
let _searchState = { question, maxResults, endpoint, isState, fullHistory, beforeCongress };
const PREFS_KEY = 'np_preferences';   // localStorage — user zip/state/interests/reps
const SUBS_KEY  = 'np_subscriptions'; // localStorage — bill notification subscriptions
```

## Data sources
- **GovInfo API**: Full-text bill search (Solr/Lucene). Key: `GovInfo_API_KEY`
- **Congress.gov API v3**: Bill metadata, cosponsors, summaries, laws. Key: `CONGRESS_API_KEY`
- **Google Civic API**: Elections data. Key: `GOOGLE_CIVIC_API_KEY`
- **OpenStates/Plural**: State bill search. Key: `OPENSTATES_API_KEY`
- **Supabase**: Translation cache. Keys: `SUPABASE_URL`, `SUPABASE_API_KEY`

## Conventions
- No comments unless the WHY is non-obvious
- No abstractions beyond what the task needs
- No new files unless unavoidable — prefer editing existing ones
- Member navigation: `openMemberFromVote({ name: fullName })` → `/member/search`
- Bill navigation: `openDetail({ congress, type, number, title })`
- Git: commit and push after every completed task
