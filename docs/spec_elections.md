# Spec: Elections Feature

**Status:** Approved — ready to build  
**Date:** 2026-06-12

---

## Goal

A top-level Elections page showing upcoming and recent elections across all levels. Elections that affect the user are highlighted and floated to the top. Proximity drives visual emphasis — closer elections feel more urgent. Users can track individual elections; in V2 tracking unlocks polling, discourse, and area-by-area results.

---

## Data Source

**Google Civic Information API** (key to be added to `.env` as `GOOGLE_CIVIC_API_KEY`)

Endpoints used:
- `GET /elections` — all upcoming elections (`name`, `electionDay`, `id`)
- `GET /voterinfo?address={zip}+USA&electionId={id}` — user-specific contests, candidates, registration deadline, polling place

**Coverage notes:**
- Elections + Divisions APIs are active as of 2026 (Representatives API was shut down April 2025 — not used here)
- Local elections have spotty coverage — shown with a disclaimer, not hidden
- Candidate data (`photoUrl`, `party`, `candidateUrl`, `channels`) returned per-contest when available

**Past results:** Google Civic does not provide vote counts. For past elections, link out to Ballotpedia. The card shows the election name, date ("X days ago"), and a "View results →" link — no scraped data.

---

## What "Affects You" Means

Derived from existing `prefs` (state, representative, senators):

| Election type | Affects user if… |
|---|---|
| Presidential | always |
| U.S. Senate | election is in user's state |
| U.S. House | election matches user's congressional district |
| Governor | election is in user's state |
| State legislature | election is in user's state |
| Local (county/city) | best-effort via voterinfo; shown with "may affect you" label |

---

## Page Layout

New page: `page-elections`, accessible via a top-level nav button (same row as the existing home header controls).

### No zip set
Show full national list, with a banner at the top:
> "Set your zip code to see elections that affect you."
> [Set zip] button → triggers onboarding zip step inline

### Zip set — section breakdown

```
UPCOMING ELECTIONS
Based on zip 22202 · Virginia

  ┌─── YOUR ELECTIONS ──────────────────┐
  │                                     │
  │  ★  47 DAYS                         │  ← red countdown badge
  │  Virginia General Election          │
  │  November 4, 2026                   │
  │  Senate · Governor · House (VA-09)  │
  │  Registration deadline: Oct 12      │
  │  [Track]  [Voter info →]            │
  │                                     │
  └─────────────────────────────────────┘

  ┌─── OTHER ELECTIONS ─────────────────┐
  │  124 DAYS                           │  ← muted badge
  │  Texas Special Election — TX-15     │
  │  March 17, 2027                     │
  │  [Track]  [Voter info →]            │
  └─────────────────────────────────────┘

  ┌─── RECENT RESULTS ──────────────────┐
  │  32 DAYS AGO                        │
  │  Virginia Primary — Senate          │
  │  May 12, 2026                       │
  │  [View results →]  (Ballotpedia)    │
  └─────────────────────────────────────┘
```

---

## Election Card

### Collapsed (default)

- **Countdown badge** — large mono. Color: ≤30 days = accent red, 31–90 = amber, 90+ = muted. Past elections show "X days ago" in muted.
- **Star** — only on elections that affect the user
- **Election name** — serif, prominent
- **Date** — "November 4, 2026"
- **Race types** — comma list: "Senate · Governor · U.S. House (VA-09)"
- **Registration deadline** — shown if within 60 days and available from voterinfo
- **[Track] button** — toggles tracking state (localStorage). Shows "Tracking ✓" when active.
- **[Voter info →]** — links to Google's voter info page for this election. For past elections: **[View results →]** linking to Ballotpedia search.

### Expanded (click/tap to toggle)

Shows contests on the user's ballot. Each contest:

```
U.S. Senate — Virginia
┌──────────────────────────────────────┐
│  [photo]  JANE SMITH  (D)            │
│           janesmith.com              │
│           @janesmith · facebook      │
├──────────────────────────────────────┤
│  [photo]  JOHN DOE  (R)              │
│           johndoe.com                │
└──────────────────────────────────────┘
```

Candidate fields shown (all conditional on API returning them):
- Photo (circular, fallback to initials avatar)
- Full name
- Party (full label + colored dot: D=blue, R=red, I=grey, L=gold)
- Campaign website link
- Social channels (Twitter/X, Facebook, YouTube — icons)
- Phone / email if present

If no candidate data: "Candidate information not yet available."

---

## Tracking (V1 scope)

- `tracked_elections` stored in localStorage as a Set of election IDs
- Tracked elections get a "TRACKING" badge in top-right corner of card
- On the elections page, tracked elections are pinned to the very top of their section (above other "your elections")
- V2 will add: polling averages, news/discourse feed, precinct-level results map — all scoped to the tracked election

---

## Backend

### New endpoint: `GET /elections?zip={zip}`

1. Call Google Civic `/elections` → list of all elections
2. Partition into upcoming (future) and recent (within last 60 days)
3. For each upcoming election + recent election: call `/voterinfo?address={zip}+USA&electionId={id}` (parallel, max 5 concurrent to avoid rate limits)
4. For each election, determine `affects_user` using state/district matching
5. Cache per zip for 6 hours

**Response shape:**

```json
{
  "zip": "22202",
  "state": "VA",
  "upcoming": [
    {
      "id": "2000",
      "name": "Virginia General Election",
      "date": "2026-11-04",
      "countdown_days": 47,
      "affects_user": true,
      "contests": [
        {
          "type": "U.S. Senate",
          "district": null,
          "candidates": [
            {
              "name": "Jane Smith",
              "party": "Democratic",
              "photo_url": "https://...",
              "candidate_url": "https://...",
              "channels": [
                {"type": "Twitter", "id": "@janesmith"}
              ]
            }
          ]
        }
      ],
      "registration_deadline": "2026-10-12",
      "voter_info_url": "https://www.google.com/search?q=voter+info+virginia+2026"
    }
  ],
  "recent": [
    {
      "id": "1999",
      "name": "Virginia Primary",
      "date": "2026-05-12",
      "days_ago": 32,
      "affects_user": true,
      "ballotpedia_url": "https://ballotpedia.org/..."
    }
  ]
}
```

### Rate limit & caching
- Cache: `TTLCache(maxsize=200, ttl=21600)` keyed by zip
- voterinfo calls: `asyncio.gather` with semaphore (5 concurrent)
- Endpoint rate limit: 10/minute (same as other public endpoints)

---

## Frontend

### Nav button
Add "Elections" button to home page header (same row as jurisdiction toggle).

### New page: `page-elections`
- Standard `<div class="page" id="page-elections">` pattern
- `showPage('page-elections')` + `loadElections()` on nav click

### State
```js
let _electionsData = null;
let _trackedElections = new Set(JSON.parse(localStorage.getItem('tracked_elections') || '[]'));
```

---

## Scope Cuts (not building now)

- Voter registration flow (link to vote.gov)
- Endorsements / campaign finance
- Ballot measure full text
- Push/email reminders for election day
- V2 tracking features (polling, discourse, precinct results)
