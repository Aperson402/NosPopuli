# NosPopuli Engineering Principles
**The contract for how code gets written here, designed to hold from a single developer up to a team of ten.**

---

## Why this document exists

NosPopuli is built around a deliberate constraint: one person should be able to fit the whole system in their head, edit any file, and see the result on reload. That's why there's no framework, no bundler, no ORM, no microservices. The simplicity is the product feature, not an accident.

As soon as more than one person works on this, that constraint stops being free. Without explicit rules, a second contributor's instincts are to introduce abstractions, frameworks, or layers that make sense in a 50-person team but quietly destroy the property that made the codebase tractable in the first place. This document is the load-bearing rule set that keeps the codebase coherent regardless of team size.

**The rules in this document are not preferences. They are the contract.** Break them when the task genuinely requires it, but never silently — the PR description has to explain *why* the rule didn't fit.

---

## Section 1: The philosophy

### 1.1 The right data structure for the job

A plain dict is the first thing you reach for *for config and lookup tables*. A list of tuples is the right answer when you need ordered priority matching. A `set` is the right answer for dedup with O(1) membership. An LRU cache is the right answer for transient API data.

**Use a class when it actually earns its keep.** Specifically:
- **Non-trivial invariants over state that lives across multiple operations.** A `VoteCandidate` with `is_committee_vote`, `participation_score`, `score()` is more grep-able than nested helpers when the logic crosses three or more methods.
- **A real interface with multiple implementations.** Once we have three bill-text sources (Congress.gov, GovInfo, future state legislatures), a `BillTextSource` abstract base earns its existence.
- **Lifecycle that needs coordination.** Anything with `__enter__`/`__exit__`, async cleanup, or coordinated init/retry/destroy.
- **Modeling a real-world entity with behavior.** A `User` class once auth lands; a `Bill` class would be premature until bills have meaningful operations on them beyond "fetch and render."

What we're pushing back on is the **reflexive** reach for OOP — `class BillFetcherManager` wrapping a single function, `class TimelineRenderer` for code that runs once per render, `class CacheService` instead of a module-level TTLCache. That's ceremonial bureaucracy: indirection without clarity.

**Rule of thumb:** if your class has only `__init__` and one other method, it's probably a function. If your class has only static methods, it's definitely a module. If your class's state is "the same data the caller already had", you didn't need the class.

**Examples from the codebase that got this right:**
- `POPULAR_NAMES` is a flat dict because it's pure config — no behavior.
- Circuit breaker state is a float because the "state machine" has two states and one transition condition.
- The translator's Supabase client wraps state + behavior + a coordinated lifecycle — that one is a class for good reason.

When in doubt, write the function first. Promote to a class when you've added the third method, not before.

### 1.2 No abstractions beyond what the task needs

Three similar lines is better than a premature helper function. Two similar handlers is better than a base class. Code that exists "in case we need it later" is a permanent cost for hypothetical benefit.

If you write the same eight lines in three places, *then* extract a helper. Not before. The helper's name will be better when you've seen three real use cases instead of guessing at one.

### 1.3 Edit-and-reload is sacred

If your contribution requires a new build step, a new compilation phase, or a new tool installation, you must defend that explicitly. The current workflow is: edit any file → hit save → reload the browser. Anything that breaks that loop is the wrong tool, even if it's individually better.

This is why the frontend is vanilla JS without React/Vue/Svelte. It's why there's no TypeScript. It's why there's no Webpack/Vite/esbuild. The cost is real (no type checking, no JSX) but the benefit is enormous (instant feedback, no toolchain pain, no version-pin drift).

### 1.4 Honesty over magic

The codebase prefers explicit empty states with explanatory text over "smart" automatic behavior. When a query returns nothing, tell the user why. When a circuit breaker is open, say so. When the bill text isn't published yet, say which system doesn't have it.

Magic feels good when it works. It is impossible to debug when it doesn't. Be boring.

### 1.5 Fail-open vs fail-closed is a load-bearing decision

Every external call has a failure mode. You must consciously pick:
- **Fail-closed** (return empty / error) when a partial result would mislead the user. The validator min-score floor is fail-closed: better to show nothing than weak garbage.
- **Fail-open** (return stale / unscored data) when the user values *anything* over *nothing*. The validator's exception path is fail-open: if the LLM call dies, return the raw results unscored.

When you write a function that can fail, choose. Don't punt the decision to the caller; they don't have the context.

---

## Section 2: Architecture principles

These are numbered for reference in PR comments ("violates #4") and ordered by how often they come up.

1. **One person can fit it in their head.** No framework, no bundler, no ORM. Adding any of these has to clear a high bar in a written design doc.
2. **Edit-and-reload feedback loop.** Vanilla JS, `uvicorn --reload`. Any tooling that breaks this is wrong.
3. **Plain data structures unless you can't.** Dicts for config, lists of tuples for ordered priority, sets for dedup.
4. **Single dispatch entrypoint per concept.** One `/search`, one `/bill`, one feed handler. Not five overloaded variants.
5. **No comments unless the WHY is non-obvious.** Don't restate code. Do explain hidden invariants, known-bad upstream behaviour, or constraints a reader can't see.
6. **No abstractions beyond what the task needs.** Three similar lines beats premature helpers.
7. **No backwards-compat shims for code only this app calls.** Delete cleanly.
8. **Fail-open vs fail-closed is a load-bearing decision.** Choose explicitly per function.
9. **Graceful degradation over hard errors.** Circuit breaker, GovInfo fallback, stale-while-revalidate, empty states with text.
10. **Wall-clock budgets, not per-call timeouts.** One slow call must not burn the whole user wait.
11. **Cache namespace, never collide.** Prefixes like `search:v1:`, `feed:v7:` so version bumps invalidate without manual purges.
12. **Honest empty states, not silent zeros.** Tell the user *why* a result is empty.
13. **Trust user input only at system boundaries.** Pydantic at the perimeter; loose dicts inside.
14. **DOM as state, sparingly.** Module variables hold authoritative state; DOM is a render target. Clear stale DOM on context switch.
15. **Cache-bust CSS via query string.** `?v=feature-name` whenever styles change. `CachedStaticFiles` is aggressive about caching.
16. **No new files unless unavoidable.** Existing files grow; the codebase doesn't sprawl.

---

## Section 3: Code style

### 3.1 Comments

**Default to no comments.** Well-named identifiers do most of the work.

Write a comment only when removing it would confuse a future reader. The good cases:
- A hidden invariant ("title_results[0] is authoritative when source == popular_names_hardcoded")
- A workaround for a specific upstream bug ("OpenStates labels committee + floor votes with same chamber tag — disambiguate by motion_text")
- A subtle business rule ("fail-open only for transport errors, not for empty validator scoring")
- A trade-off explanation ("we re-fetch instead of caching because freshness matters more than RPS")

The bad cases — don't write these:
- Restating what the code does ("// increment counter")
- Reference to current task ("// for the housing affordability fix")
- Reference to caller ("// used by feed renderer")
- "TODO" without a date and a condition

### 3.2 Function naming

Functions are named for **what they do**, not how they do it. `fetch_bill_text` is correct. `getBillTextFromCongressGovWithFallback` is not.

Helpers prefixed with underscore are module-private. `_govinfo_text_fallback` says "you don't call this directly." Public functions have no prefix.

### 3.3 Variable naming

- Module-level constants in `UPPER_CASE`: `POPULAR_NAMES`, `STATE_CHAMBERS`, `_BILL_ID_RE`
- Local variables in `snake_case`
- Boolean variables phrased as questions: `is_state_bill`, `has_committee_match`, `should_skip_validator`
- Avoid abbreviations except universally-known ones (`url`, `id`, `req`, `res`)

### 3.4 Error handling

- Catch the narrowest exception type you can. `except Exception` is a smell.
- If you `except` and `print`, you have lost information. Re-raise or log with full context.
- The FastAPI global exception handler catches uncaught errors. Trust it; don't wrap every endpoint in its own try/except just to print.
- When an external API can be slow, wrap in `concurrent.futures.wait(..., timeout=N)` not per-request timeout alone.

### 3.5 Imports

- Group at the top of the file: stdlib, third-party, then local (`bill_fetcher`, `router_agent`, etc).
- Don't re-import inside functions unless avoiding a circular dependency.
- One import per line is verbose; we use `from x import a, b, c` style.
- Delete imports the moment they're unused. Use `ruff check` if you want automatic detection.

### 3.6 Frontend

- Module-scoped `let` for state, never a `class` for a singleton.
- Functions named `render*` produce DOM. Functions named `_open*` change navigation. Functions named `fetch*` hit the API.
- Use `escapeHtml()` on every piece of user-controlled string concatenated into HTML.
- When you change CSS, bump the `?v=` query string on the `<link>` tag.
- When you change context (e.g. from federal to state bill), explicitly clear the previous context's DOM via the existing render functions with empty args (e.g. `renderSponsors([], [])`).

---

## Section 4: How to add a new feature

This is the recipe. Follow it.

### Step 0 — Decide if you need a spec

If the feature touches more than two of {auth, schema, frontend, API surface, external service}, write a spec first. Specs live in `docs/spec_*.md`. The format is in any existing spec — start with **What we're building**, **Why it matters**, **Data sources**, **What we show / skip**, **Backend changes**, **Frontend changes**, **Open questions**, **Success criteria**.

The spec is for *you* as much as for review. If you can't write the spec, you can't write the feature.

For one-file changes, skip the spec.

### Step 1 — Find the right file

Look for the closest existing module. If your feature is search-routing, it goes in `router_agent.py`. If it's a new data type from Congress.gov, it goes in a new module like `committee_reports_fetcher.py` *only if* it's substantial enough to deserve its own file.

**Don't make a new file just because you're nervous about touching an old one.** Existing files grow.

### Step 2 — Write the backend first

Backend behaviour shapes frontend possibilities, not the other way around. Add the function, wire it into the relevant API endpoint, return the new data shape, *then* go to the frontend.

If the backend isn't done you can't reason about the frontend's success criteria.

### Step 3 — Use the existing patterns

- New external API call? Wrap it in the circuit breaker pattern. See `congress_breaker.py`.
- New cache need? Use `cachetools.TTLCache` with `RLock`. Pick a TTL that maps to how fast the data changes.
- New search namespace? Add a `prefix:vN:` and pick a 30d–60d disk cache or in-memory TTL.
- Per-state config? Add a new top-level dict in `state_search_agent.py` (e.g. `STATE_VALIDATOR_FLOOR`, `STATE_CHAMBERS`). Provide a `get_*` helper for default-fallback lookup.
- New LLM call? Choose Haiku for classification/scoring/extraction; Sonnet only when you need reasoning or web search.

### Step 4 — Wire the frontend

- Add the new section to `frontend/index.html` as a hidden `<div>` inside `#detail-content` (or wherever it lives).
- Add a `render*()` function in `frontend/js/index.js`. Make it idempotent — calling it twice should produce the same result.
- If the section is conditional, hide it (`display: none`) in the empty case rather than skipping the call.
- Add CSS in `frontend/css/index.css` following the newspaper aesthetic: Source Serif 4 for body, IBM Plex Mono caps for labels/eyebrows, Playfair Display for headlines. No `border-radius` above 2px. No `box-shadow` except for accent dots. No purple/blue/green outside the vote palette.
- Bump `?v=feature-name` on the CSS link.

### Step 5 — Test against the failing case

Before declaring done, find the user-visible case that should *not* work and verify it shows a clean empty state. Most regressions are in the unhappy path, not the happy path.

If you added a new search type, run `search_smoketest.py` (extend it with cases that exercise your new code). If you added a new bill section, load a bill that doesn't have that data and confirm the section hides gracefully.

### Step 6 — PR description

The PR description has these sections:

```
## What changed
- One line per logical change

## Why
- The reason this isn't obvious from reading the diff

## Trade-offs
- What you chose not to do, and why

## Test plan
- The unhappy paths you verified
```

If you broke a numbered principle from Section 2, name it: "PR breaks #16 (new file `foo_agent.py`) because Y."

---

## Section 5: How to debug

### 5.1 First, look at the boundary

When the system misbehaves, the bug is almost always at a *boundary* — between two services, between cache and source-of-truth, between a stale DOM and current state. Inside the code, things mostly do what they say.

**Read the request/response cycle of the failing call.** What did the upstream service actually return? Run a `curl` or `python -c` against the same endpoint with the same params. If the upstream is wrong, your job is to handle the wrongness, not to fix the upstream.

### 5.2 Trust the comments

The codebase has comments where invariants are subtle. When debugging in that area, *read the comment*. The codebase has lost time to people not reading the "OpenStates labels committee and floor votes with the same chamber tag" comment and thinking the vote-mapper was broken.

### 5.3 Reproduce in isolation

Before changing anything, reproduce the bug deterministically in a single command. If you can't reproduce it, you can't fix it — you can only guess.

Tools we use:
- `python -c "from x import y; print(y(...))"` for backend functions
- `curl -s -X POST localhost:8000/... | jq` for endpoint behaviour
- Browser DevTools network tab + JS console for frontend
- The `/monitor/stream` SSE feed for backend agent timings

### 5.4 Watch the rate limits

We share OpenStates, Congress.gov, and GovInfo with the user's app. When debugging, don't sit in a loop hammering an API. The user (you, in dev) is on the same quota.

If you're going to hit an API more than three times to debug something, switch to an in-memory mock for the duration.

---

## Section 6: Code review checklist

This is what reviewers should look for, in order of importance.

**Critical — block merge:**
- [ ] Does the change introduce a new framework, build step, or runtime dependency? If yes, is there a written justification?
- [ ] Does it silently swallow exceptions or hide failures from the user?
- [ ] Does it leak per-user data across users (state pollution)?
- [ ] Does it bypass the circuit breaker for an upstream that already trips it elsewhere?
- [ ] Does it add a new external API call without caching, timeout, or fallback?

**Important — discuss in PR:**
- [ ] Could this be a dict instead of a class? Three similar lines instead of a helper?
- [ ] Are the new comments load-bearing (explain *why*) or decorative (restate *what*)?
- [ ] Is the fail-open vs fail-closed choice explicit?
- [ ] Is the cache key prefixed and versioned (`prefix:vN:`)?
- [ ] Does the frontend clear stale context when navigating?
- [ ] Does the CSS cache-buster (`?v=…`) get bumped?

**Polish — suggest, don't block:**
- [ ] Are variable names self-documenting?
- [ ] Is the function size reasonable (under ~80 lines, ideally)?
- [ ] Are there unnecessary imports?
- [ ] Is the empty state honest and explanatory?

---

## Section 7: When to break the rules

The rules in Section 2 aren't preferences — they're load-bearing. But there are legitimate reasons to break each:

- **Break #1 (one person in their head)** when the feature genuinely requires team-scale infrastructure: realtime collaboration, distributed compute, multi-tenant isolation. Document the deviation in the spec.
- **Break #4 (single dispatch entrypoint)** when one endpoint has acquired so much branching that the dispatcher is harder to read than two separate handlers. Move the split, don't proliferate.
- **Break #6 (no abstractions)** when the same logic genuinely appears in 4+ places. Three places is borderline.
- **Break #16 (no new files)** when an existing file passes ~2000 lines and the new logic is conceptually distinct. `api.py` is approaching this; the natural split is to extract `search_dispatcher.py`.

The rule for breaking rules: **say so in the PR description.** "This breaks principle #16 because the existing module is past 2000 lines and the new logic is independent." That sentence is the contract that keeps deviations honest.

---

## Section 8: How rules change as the team grows

The principles in Section 2 are written for the 1-to-10 person range. Some hold forever; some bend at scale.

### 1 person

- Skip Section 4's spec-writing step for most features. You hold the design in your head.
- Skip Section 6's PR checklist — there's no PR.
- Be ruthless about deletion. Code you wrote last week and don't love? Delete it.
- Keep `CLAUDE.md` updated as a personal cheat sheet.

### 2–3 people

- **Specs become mandatory** for any change touching >2 modules. The spec is the place where you and your collaborators align before code.
- **Code reviews start.** Use the Section 6 checklist as a literal checklist.
- **A shared dev `.env` is now a footgun.** Move to per-developer keys (the existing per-user API key spec covers this).
- **No silent rule-breaking.** PR descriptions explicitly name which principle they deviate from.

### 4–6 people

- The codebase is approaching the size where one person can no longer hold all of it. Split ownership: someone owns the search pipeline, someone owns the bill detail flow, someone owns elections.
- **Add automated lint** for the rules that are mechanically checkable: import ordering, unused imports, function size limits. Use `ruff`.
- **Add a `decisions/` folder** where significant design choices get written up in 1–2 page memos. These are different from specs — they're "we tried X, ended up with Y, here's why."
- **Frontend may need to split** — `index.js` at 2500+ lines becomes hard. Extract `frontend/js/search.js`, `frontend/js/detail.js`, etc. Resist the urge to introduce a framework.

### 7–10 people

- **Test coverage becomes non-optional.** `search_smoketest.py` is the model — extend it to cover every search type, every fast-path, every error case. Add integration tests that exercise real backends in a CI environment with rate-limit-aware backoff.
- **Caching infrastructure needs operational discipline.** Per-developer cache namespaces. Cache-clear endpoints with auth. Cache-warmup jobs.
- **The "no framework" rule starts to creak.** When you have 5 frontend engineers all touching `index.js`, the cost of "no type checking" becomes real. The honest answer at this scale may be: introduce TypeScript (not React; just TS as type-checker). The newspaper aesthetic and DOM-as-state pattern survive that move.
- **The "one big api.py" rule definitely breaks.** Split into `api/search.py`, `api/bill.py`, `api/state.py`, with `api/__init__.py` mounting them. Each file stays under ~500 lines.
- **External API keys must be per-user.** The shared-key model that works for 1-10 users will trip rate limits when serving real traffic. Implement the per-user-key spec.

### Beyond 10 people

This document doesn't cover. By the time you have a team that size, the constraints that shaped this codebase no longer apply, and you need to reconsider whether the philosophy that brought you here is still the right one.

---

## Section 9: The non-negotiables

If you remember nothing else from this document, remember these. They are the contract.

1. **No frameworks, no bundlers, no ORMs** unless explicitly approved by a written design doc.
2. **No silent failures.** Every empty state has explanatory text.
3. **Fail-open vs fail-closed is explicit.** Every function that can fail says which.
4. **External APIs are wrapped:** cache + timeout + fallback + breaker. No exceptions.
5. **Comments explain *why*.** Never *what*.
6. **PRs that break rules name the rule** in the description.
7. **The user is the architect.** Specs go to the user for review before substantial work begins.

---

## Appendix A: File layout reference

```
.
├── api.py                          # All HTTP endpoints, dispatcher
├── router_agent.py                 # Query classification (LLM + regex fast-path)
├── search_agent.py                 # Federal search (GovInfo + Congress.gov)
├── title_search_agent.py           # Named-act lookup, hardcoded popular names
├── query_expander_agent.py         # Synonym expansion for federal search
├── result_validator_agent.py       # Relevance scoring (Haiku)
├── translator_agent.py             # Plain-English bill translation, Supabase cache
├── bill_fetcher.py                 # Congress.gov bill/text/cosponsors, TTL caches
├── historian_agent.py              # Legislative timeline structure
├── feed_agent.py                   # Personalized feed (interests + reps + state)
├── elections_agent.py              # Google Civic + Claude web search
├── committee_reports_fetcher.py    # Federal committee reports
├── congress_breaker.py             # Circuit breaker for Congress.gov
├── search_cache.py                 # Two-tier search cache
├── state_search_agent.py           # OpenStates queries, per-state config
├── state_bill_fetcher.py           # OpenStates bill detail
├── state_vote_mapper.py            # Floor-vs-committee vote disambiguation
├── correspondence/                 # Subscription, notification, email
├── docs/
│   ├── ENGINEERING.md              # This file
│   └── spec_*.md                   # Per-feature specs
├── frontend/
│   ├── index.html                  # Single-page SPA shell
│   ├── test.html                   # Design playground / mockups
│   ├── js/index.js                 # Entire frontend
│   └── css/index.css               # All styles
├── search_smoketest.py             # Regression harness for federal search
├── clear_search_cache.py           # CLI to nuke cache namespaces
└── CLAUDE.md                       # Cheat sheet for Claude Code sessions
```

---

## Appendix B: Frequently broken rules and what to do instead

| Temptation | Why it feels right | What to do instead |
|---|---|---|
| "I'll just add a class for this" | OOP feels professional | Plain function until the class has 3+ methods or genuine invariants — then promote |
| "Let me make this configurable" | Future flexibility | Hardcode it; make it configurable on the 2nd use |
| "I'll wrap this in try/except to be safe" | Defensive coding | Let the global handler catch it unless you can recover |
| "I'll add a comment explaining the loop" | Documentation | Rename the loop variable; delete the comment |
| "This needs its own file for cleanliness" | Single Responsibility | Add to existing file; split when >1500 lines |
| "I'll cache this in case it's slow" | Premature optimization | Profile first; cache when measured |
| "Let me abstract this into a base class" | DRY | Duplicate it; abstract on the 4th instance |
| "I'll add a TODO for later" | Honesty | Either do it now or delete the line |

---

*Last updated when this document was first written. Update the date and add a note at the bottom of Section 8 when team size crosses a threshold.*
