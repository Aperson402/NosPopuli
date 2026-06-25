# State Search Parity — Feature Spec
**NosPopuli · Draft for review**

---

## What we're building

State search currently runs through a much thinner pipeline than federal — no router, no popular-name resolution, no fast-path for bill IDs, no search cache, and a permissive validator threshold. As a result, a user searching for an Indiana housing bill gets a noticeably worse experience than searching for a federal one.

This spec brings state search up to roughly federal-grade behaviour using the same components we already trust: route → search → validate → cache, with state-specific accommodations baked into each step.

---

## Why it matters

State legislation is where most of the laws that affect people's daily lives actually originate — housing, education, criminal justice, healthcare access, voting rules. Making this surface as good as federal search is the unlock for NosPopuli being a complete civic tool rather than a federal-bills site with a state add-on.

The current behaviour also undermines trust: when someone searches "tenant rights" in their state and gets an off-topic appropriations bill at position 1, they have no way to know whether their state genuinely has nothing on the topic or whether our search is just weak. Federal search no longer has that failure mode; state search still does.

---

## Current state of the pipeline

For reference, here's what `/state/search` does today (api.py:1314):

1. Reject if `state_code` not in `ENABLED_STATES`.
2. Strip a small hardcoded filler-word list from the query.
3. Pass the cleaned query directly to OpenStates v3 `/bills?q=…&jurisdiction=…&session=…`.
4. Run the result list through `validate_results` with `min_score=3` and `fail_open=True`.
5. Return.

What's missing relative to federal:
- **No router** — no intent classification, no off-topic detection, no popular-name mapping, no fast-path bill-ID short-circuit.
- **No expander** — federal uses LLM-driven synonym expansion to broaden coverage of GovInfo.
- **No search cache** — every state query pays the full OpenStates round-trip every time.
- **Low validator floor** (`min_score=3`) — federal uses 5, which is part of why federal is much less prone to weak-match hallucinations.

---

## What we're keeping the same

- **OpenStates v3 stays our state data source.** No change to the upstream API.
- **State-bill detail flow** (`/state/bill`, translation, votes, timeline) stays as-is. This spec only touches the search pipeline.
- **`ENABLED_STATES` gating** stays — we don't promise quality for states we haven't validated.

---

## Pipeline changes

### 1. Route state queries through `router_agent.route_query`

Today the dispatcher (api.py:1019) calls `handle_state_search` based on jurisdiction *after* running `route_query` — but `handle_state_search` ignores most of the structured output. We want it to use:

| Router output | How state search uses it |
|---|---|
| `query_type: off_topic` | Return empty + polite message, same as federal. |
| `query_subtype: named_entity` | Pass `named_entity` to OpenStates as the search phrase (likely higher precision than the cleaned-keyword approach). |
| `specific_bill: {type, number}` | Fast-path to `fetch_state_bill_by_identifier` — skip the LLM round-trip entirely. |
| `keywords` | Use as the OpenStates `q` parameter (current behaviour, just structured rather than filler-stripped). |
| `status: enacted` | Pass `classification=law` to OpenStates so we only return enacted bills. |
| `time_range` | Map to OpenStates `from_session` / `to_session` filters when present. |

Router already has a `jurisdiction` rule that detects "Virginia bill" / "California legislature" — we keep using that to choose state vs federal upstream of this function.

### 2. Add a state fast-path for bill IDs

Each state has its own bill numbering, but 90% of the live legislative chambers use one of these patterns:

- `HB 1234`, `SB 1234` — most states (Indiana, Texas, Florida, etc.)
- `H.R. 1234`, `S.R. 1234` — some New England states
- `A 1234`, `S 1234` — New York and California assembly
- `LB 1234` — Nebraska (unicameral)
- `LD 1234` — Maine

Add a new `fast_route_state` in `router_agent.py` that takes (`question`, `state_code`) and matches against a per-state regex set. On hit, return a structured dict with `specific_bill` filled and `_fast_path: "state_bill_id"` so the dispatcher can short-circuit to `fetch_state_bill_by_identifier`. Same pattern as the federal fast-path.

States where we can't pin down the format → fall through to the LLM router as before. No regression risk.

### 3. Drop the filler-word strip

The current `FILLER` set is a crude approximation of what the router already does better. Once the router is in the pipeline, we use the structured `keywords` array directly.

### 4. Raise validator floor to `min_score=5`, keep `fail_open=True` for state

State metadata is thinner than federal (no policy area, fewer subjects), so the LLM has less signal. But after the recent validator changes, the floor only applies to *successful* scoring — transport failures still fail open. The risk of empty results is the right tradeoff vs. the current weak-match hallucinations.

For one edge case — bill-text-thin states like Wyoming or South Dakota — we should monitor whether `min_score=5` returns empty too often and fall back to 4 selectively. v1 ships with 5 and we measure.

### 5. Add search cache for state queries

`search_cache.py` already supports a `jurisdiction` parameter (`cache_key(... jurisdiction="federal")`). Wire it for state with `jurisdiction=f"state:{state_code}"`. Same 30-minute TTL, same freshness-query bypass.

State bills move slowly (legislatures meet ~5 months a year in most states) so caching is even safer than for federal. The freshness bypass list ("this week", "today", etc.) stays as-is.

---

## What we're explicitly skipping in v1

### Popular-names table

For federal we have `POPULAR_NAMES` covering Civil Rights Act, CHIPS Act, PACT Act, etc. The state analog would be 50 × ~10–20 landmark statutes — Proposition 13 in California, the Texas Heartbeat Act, Florida HB 1557, etc. This is real work and the cross-state breadth makes it impractical for v1.

Instead, we rely on:
- The router's `named_entity` extraction (which catches most short titles when the LLM has seen them in training data).
- OpenStates' built-in `popular_name` field on the bill record (we expose it as alt-title in results).

A future v2 could add a manually-curated table for each state's top-10 landmark acts, but that's an ongoing maintenance burden and is out of scope here.

### Query expansion

Federal uses `query_expander_agent` to generate synonym lists for GovInfo's Solr search. OpenStates' relevance ranking is closer to a plain BM25, so synonym expansion helps less and adds latency. v1 ships without it; revisit if recall is genuinely weak.

### Cross-state search

"Show me abortion bills in any state" requires fanning out across enabled states and merging results. Real demand uncertain, and the LLM scoring cost would multiply by 5+. Defer to v2.

### State-level full-text fallback

For federal we just added a GovInfo fallback when Congress.gov hasn't synced text yet. There's no equivalent unified source for state bills — text quality and availability is per-state. Out of scope; if we find a state-by-state pattern (e.g. NC General Assembly direct URLs), that's its own spec.

---

## Backend changes

### `router_agent.py`

- Add `fast_route_state(question, state_code)` returning a structured dict on bill-ID match, else `None`.
- The existing `route_query` already produces `jurisdiction` — no change there.

### `api.py` — `handle_state_search`

- Accept the structured router output (currently it ignores most of it).
- Before falling through to OpenStates keyword search, try `fast_route_state` for a bill-ID short-circuit.
- Use `structured.get("named_entity")` or `structured.get("keywords")` for the OpenStates query string.
- Pass `classification="law"` when `status == "enacted"`.
- Cache key includes `state_code`.
- Validator call uses `min_score=5`, same fail-open semantics as federal.
- Handle `query_type: off_topic` with the same empty-result polite response federal uses.

### `api.py` — `/state/search` endpoint

Replace the standalone filler-stripping path with a direct call to `route_query` → `handle_state_search`. This unifies state and federal so future router improvements lift both at once.

---

## Frontend changes

### Search results card parity

Today state search results render with a sparser card than federal — the visual difference makes state results feel like a second-tier feature. Bring them to parity:

- Same "Read more →" interaction.
- Same "Show more" pagination behaviour.
- Same "Confidence" / ambiguity banner when the router flagged ambiguity.

### Empty state and off-topic state

When state search returns `query_type: off_topic` or empty results, show the same polite message federal shows ("This doesn't look like a question about legislation…"). Today state search just renders "0 results" without context.

### State picker reminder

When the user has a state selected but their query reads as federal (router classified `jurisdiction: federal`), show a one-line nudge: *"Searching {state_name}. Switch to Federal? →"*. Today we silently force the state interpretation.

---

## Resolved decisions

1. **Hybrid federal+state queries.** v1 picks whichever jurisdiction the router selected and surfaces that one. If users complain we'll revisit; until then the simplicity of a single result set wins over cross-jurisdiction merging.

2. **Per-state validator threshold.** Parametrised. The validator call accepts a per-state floor passed in from a small `STATE_VALIDATOR_FLOOR` map in `state_search_agent.py`, defaulting to `5`. Thin-metadata states (Wyoming, South Dakota, Vermont, etc.) start at `4`; high-volume states with rich metadata (California, New York, Texas) stay at `5`. The map ships with conservative defaults and is the obvious knob to tune once we have real usage data — no code change required to adjust per state.

3. **Session-aware bill-ID fast-path.** `fast_route_state` accepts an optional session hint extracted from the query text. Behaviour:
   - `"HB 1"` → resolve in the current session (whatever OpenStates says is the active one for that state).
   - `"HB 1 from 2023"`, `"2023 HB 1"`, `"HB 1 in the 88th session"` → extract the session identifier and pass it through to `fetch_state_bill_by_identifier`.
   - When the requested session isn't found and a current-session match exists, return the current-session match plus a one-line note in the response that says *"Showing current-session HB 1. Did you mean the 2023 version?"*. This stays honest about which session we showed.
   - Session-extraction patterns: a 4-digit year, an ordinal like "88th session" / "2023 session", or an explicit "from {year}" / "in {year}" phrase. Anything more exotic falls through to the LLM router.

## Still open

1. **OpenStates rate limits.** Free tier allows ~500 calls/day, ~1/sec. With caching this should be plenty for current usage, but if traffic grows we'd need to either pay for higher limits or add a backoff layer. Worth noting; not blocking.

2. **Per-user API keys for Congress.gov / GovInfo.** Tracked as a separate spec (`spec_per_user_api_keys.md`, pending) — touches auth, DB schema, onboarding, and the breaker layer, so it deserves its own design pass and doesn't gate this work.

---

## Out of scope

- State-level Connections / Amends / committee report integration. OpenStates doesn't expose committee reports the way Congress.gov does. Worth a separate spec if we can find a pattern.
- State-level full-text fallback (no equivalent of GovInfo).
- "Cross-state" search (compare bills across states).
- State-level feed enrichment (the "What's Moving" feed currently mixes federal + selected state; this spec doesn't change that path).

---

## Success criteria

- A state query for a bill ID (e.g. "HB 1557" with state=FL) short-circuits via fast-path to the bill detail page with no LLM round-trip — defaults to the current session.
- A state query with an explicit session anchor (e.g. "HB 1 from 2023" with state=IN) resolves to that session, not the current one.
- A state query with an off-topic question ("weather forecast tomorrow" with state=IN) returns empty + polite message, not a list of unrelated bills.
- A state query for a known landmark (e.g. "California Proposition 13" with state=CA) returns the canonical bill at position 1 via the router's named-entity extraction.
- A repeated state query within 30 minutes is served from cache.
- A state query for a substantive topic returns no worse than today; ideally noticeably better because of validator floor + structured keywords.
- When the router can't classify, the user sees an "ambiguous query" banner with suggested rephrasings — same as federal.

---

## Rough effort

Backend changes: ~half a day. Router function, dispatcher rewiring, validator-floor flip, cache wiring.

Frontend changes: ~half a day. Card unification, empty-state polish, jurisdiction-mismatch nudge.

Test passes: ~quarter day with the existing `search_smoketest.py` extended to add a "state" group (analogous to "named" / "concept" / "edge") with a handful of state-specific cases per enabled state.

Total: ~1.5 days of focused work, no new dependencies, no schema changes.
