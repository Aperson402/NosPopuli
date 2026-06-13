# Spec: Election Detail View — Phase 1

## Goal

When a user clicks an election card (on `/elections` or the feed widget), they see a full detail view: who is running, what stage the election is in, current polling summary, and how to participate. Zero new API cost for candidate/stage data; polling uses the existing Claude web search pattern cached per election per 24hr.

---

## Trigger

Any `.election-card` click currently toggles `.election-contests` open inline. Phase 1 replaces that toggle with navigation to a dedicated detail panel — either:
- A new `/elections/{id}` standalone page (preferred — shareable URL)
- Or a slide-in panel within `/elections` (simpler, no routing)

**Decision: standalone page** at `/elections/{id}` where `{id}` is the Google Civic election ID (e.g. `8095`) or the web-search synthetic ID (e.g. `web_VA_2026-08-04`). Detail data fetched from a new `GET /api/elections/{id}` endpoint.

---

## Sections

### 1. Header
- Election name (large, Playfair)
- Date — formatted long form (Tuesday, August 4, 2026)
- Countdown badge (same urgent/near/far coloring)
- `← Back` button (history.back())
- Source badge if Claude-sourced: `"Web search · updated {date}"`

### 2. Election Stage
A horizontal stage indicator showing where the election sits in the cycle:

```
Primary  →  General  →  Runoff  →  Results
   ●             ○           ○          ○
```

Stage derived from:
- `type` field from Google Civic voterinfo (`primary`, `general`, `runoff`, `special`)
- For Claude-sourced elections: parse from name ("Primary", "General", "Runoff")
- Special elections shown with a separate `SPECIAL` badge instead of stage rail

### 3. Polling Summary (Claude web_search → RealClearPolling)

**Source**: RealClearPolling via Claude `web_search_20260209` tool.

**Why this works**: `httpx` and Playwright are both blocked by DataDome (tested 2026-06-12). Claude's web search runs on Anthropic's infrastructure — different fingerprint, not flagged. Confirmed live: Claude successfully retrieved NC Senate, NH Senate, Maine Senate, Ohio Senate polling numbers with specific percentages and pollster names.

Data is indexed content with a few-hour lag at most — acceptable for polling that doesn't change minute-to-minute.

**Approach**: same pattern as `_search_elections_with_claude` already in `elections_agent.py`.

```python
async def _fetch_polling_with_claude(election_name, state_name, election_id):
    client = AsyncAnthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    response = await client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=512,
        tools=[{'type': 'web_search_20260209', 'name': 'web_search'}],
        messages=[{'role': 'user', 'content': (
            f'Find the latest polling data for the {election_name} in {state_name} '
            f'on realclearpolling.com. Return ONLY a JSON object: '
            f'{{"leader": "Name or null", "margin": "X.X points or Too close to call", '
            f'"polls": [{{"candidate": "...", "pct": 45.2, "source": "...", "date": "YYYY-MM-DD"}}], '
            f'"summary": "one sentence"}} — if no polls found, return {{}}'
        )}]
    )
    # same greedy JSON extraction as elections agent
```

**Cache**: `poll_{election_id}` in `elections_search_cache` table — 6hr TTL.

**Cost**: ~$0.01–0.02 per cache miss (512 max_tokens, web search overhead). Shared across all users. Major races will have data; local primaries may return `{}`.

**Render**:
- **Leader bar**: two CSS-width bars, party dot colors, name + percentage labels
- **Poll table**: pollster · date · candidates · percentages. Max 5 most recent.
- **Summary line**: one-sentence narrative, italic Source Serif
- **Empty state**: section hidden entirely — no message shown

**Failure modes**: fetch error, parse error, or `{}` response → section hidden, no user-facing error.

### 4. Candidates
Grid of candidate cards. Data from Google Civic voterinfo `contests[].candidates`.

Each card:
- Photo (img with initials fallback — already implemented in elections.html)
- Name (bold)
- Party dot + party name
- Incumbent badge if detectable from name/title field
- Links: Website ↗ · social channels (already implemented)

Group by contest (office). Contest header shows:
- Office name
- District if present
- Level badge (Federal / State / Local)

For Claude-sourced elections with no voterinfo: show "Candidate information not yet available." with Ballotpedia link.

### 5. Participation
- **Registration deadline** (if in voterinfo)
- **Register to vote →** link (voter info URL from voterinfo, or USA.gov fallback)
- **Find your polling place →** (voter info URL)
- **Absentee/mail ballot →** (absentee URL from voterinfo if present)
- **Track this election** button (same localStorage toggle as existing)

### 6. Related Links
- Ballotpedia page (generated URL — already implemented)
- Official state election authority link (from voterinfo `electionInfoUrl`)

---

## Backend

### New endpoint: `GET /api/elections/{election_id}`

```python
@app.get("/api/elections/{election_id}")
async def election_detail(election_id: str, request: Request, zip: str = None, state: str = None):
    # 1. Fetch base election data (re-use fetch_elections cache if warm)
    # 2. Fetch voterinfo for this specific election ID + zip
    # 3. Fetch polling summary via Claude (cached 24hr per election_id)
    # 4. Return combined detail object
```

Response shape:
```json
{
  "id": "8095",
  "name": "Virginia Primary Election",
  "date": "2026-08-04",
  "type": "primary",
  "stage": "primary",
  "countdown_days": 53,
  "affects_user": true,
  "source": "google_civic",
  "contests": [...],
  "registration_deadline": "July 19, 2026",
  "voter_info_url": "...",
  "absentee_url": "...",
  "ballotpedia_url": "...",
  "polling": {
    "leader": "...",
    "margin": "...",
    "polls": [...],
    "summary": "..."
  }
}
```

Polling field in response will be `null` until the polling solution is implemented. Frontend handles gracefully.

---

## Frontend

### New page: `frontend/election_detail.html`
Served at `/elections/{id}`. Same header/nav/fonts as `elections.html`.

On load:
```js
const id = window.location.pathname.split('/').pop();
const params = new URLSearchParams(window.location.search); // ?zip=&state=
fetch(`/api/elections/${id}?${params}`)
  .then(r => r.json())
  .then(renderElectionDetail);
```

`renderElectionDetail(data)` populates all sections above.

### Modified: election cards in `elections.html` and feed widget
`onclick` changes from toggle to:
```js
window.location = `/elections/${election.id}?zip=${zip}&state=${state}`;
```

---

## Out of Scope (Phase 1)

- Geographic voter maps (Phase 2 — needs shapefiles + D3)
- Live poll updates / websocket streaming
- Historical results from past elections
- Scraped polling (Phase 2 — RCP, Wikipedia)
- Candidate fundraising data (Phase 3 — OpenSecrets API)
- Debate schedules

---

## Phase 2 Preview: Expanded Polling Coverage

Once RealClearPolling LLM scraping is validated, extend to:
- **Per-race pages** on RCP (e.g. `/polls/president/general/2026/...`) for richer historical poll tables
- **Wikipedia** as fallback for races RCP doesn't cover (local primaries, state legislative races)
- **Poll trend line**: if historical polls available, simple CSS sparkline showing movement over time (no JS charting library)

---

## Cost Estimate

| Source | Cost per call | Cache TTL | Est. daily cost at 100 users |
|--------|--------------|-----------|------------------------------|
| Google Civic voterinfo | Free | 6hr (existing) | $0 |
| Claude polling search | ~$0.008 | 24hr per election | ~$0.08 (10 distinct elections viewed) |

Total Phase 1 marginal cost: negligible.
