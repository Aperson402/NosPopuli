# Why-Now Context — Feature Spec
**NosPopuli · Draft for review (future thinking)**

---

## What we're building

A new section on the bill detail page called something like **"Why now?"** that surfaces the *deliberative context* a bill exists in — what came before it, what comparable legislation other states or Congresses have already passed, who's been pushing for it, and what changed politically to let it move now.

The motivating example: a user reads VA HB 191 (sex-trafficking immunity for minors) and reasonably asks *"why wasn't this already law? were minors being prosecuted before?"* — questions that require political and policy-history context our current bill page can't answer. The answer lives in news articles, advocacy reports, prior failed bills, and other states' codes. We can stitch that together.

---

## Why it matters

A bill in isolation is a procedural artifact: title, sponsor, status, vote tally. That tells you *what's happening* but not *what it means*. The interesting questions are nearly always comparative or historical:

- *Is this new policy, or is this catching up to what most states already do?*
- *Were similar bills introduced before? Why did they fail?*
- *Who is the constituency pushing this? Who's opposing?*
- *What changed politically that made this winnable now?*

These are the questions that turn passive news-reading into actual civic understanding. They're also exactly the kind of question a curious user would ask their politically-savvy friend — and exactly the kind of question NosPopuli aspires to answer natively.

This isn't a one-off feature for one bill — it's a structural upgrade that makes every bill page meaningfully more useful.

---

## What we'd show

For each bill, a **Why now?** section with up to four panels, each populated only when we have substantive data:

### 1. Prior attempts

*"This is the third time a Virginia legislator has introduced a safe-harbor immunity bill for minors. The 2022 and 2024 versions died in committee."*

Source: search OpenStates / Congress.gov for prior bills with similar titles or amends-clauses to the same underlying statute. Score by title similarity + amends-target overlap. Show the top 1–3 prior attempts with their outcomes ("died in committee 2022", "passed House but not Senate 2024").

### 2. National landscape

*"36 other states already have safe-harbor laws for minor trafficking victims. Most passed between 2010 and 2018."*

Source: a curated reference dataset that maps topic areas (drawn from OpenStates' subject classifications) to "% of states with this kind of law". This is the most editorial of the four panels — requires a hand-built or periodically-refreshed corpus. v1 starts with ~30 high-salience topic areas (safe harbor, marijuana decriminalization, paid family leave, voter ID, ranked-choice voting, etc.) and expands.

### 3. Stakeholders

*"This bill is championed by Amara Legal Center and Shared Hope International. It's been opposed in prior years by prosecutors' associations citing trafficker exploitation of automatic-immunity provisions."*

Source: web search at bill-page-render time against a tight query like `"{bill short title}" supporters OR opponents`. Use the LLM to extract organizations from the top 5 results, capped to ~3 supporters and ~3 opposers. Cite each with its source URL inline so users can verify.

### 4. Political turn

*"Similar bills failed in 2022 and 2024 with mixed party support. In 2026 the House Republican leadership signed on as cosponsors — that's the substantive change."*

Source: comparison of cosponsor partisan balance + leadership status across prior attempts. Computed from the prior-attempts data in panel 1 plus Congress.gov / OpenStates member metadata.

---

## Data sources and risks

### Existing sources we can lean on
- **OpenStates subjects + bill-title similarity** — for prior-attempts identification within a state
- **Congress.gov related-bills + amends parsing** — for prior federal attempts
- **Web search via Anthropic Sonnet with web tool** — for stakeholders + news framing
- **Hand-curated topic corpus** — for the national landscape panel (requires editorial work)

### Honesty constraints

This feature is the highest-trust-risk thing we've designed. Surfaces editorial-feeling content driven by LLMs — and we explicitly do *not* want a "Why this bill matters" panel that reads like an advocacy pamphlet. Two design principles:

1. **Facts side-by-side, not implication.** Same rule we adopted for lobbying. "36 states have this kind of law" is a fact; "Virginia is behind" is implication and we don't write it.
2. **Cite everything.** Every stakeholder mention links to the source article. Every "prior attempt" links to that bill's page. The national-landscape panel links to the underlying state-by-state dataset. No claim without provenance.

### Hallucination risk

The stakeholders panel is the riskiest — LLM extraction from web search can confidently invent supporting organizations. Mitigations:

- Require *at least two* independent sources to mention an organization before we surface it.
- Show each organization with its source URL, not just a name.
- Add a "Flag inaccuracy" button on this panel specifically — feeds into the existing flag-translation pipeline.

The prior-attempts panel is the safest — it's deterministic on bill-database queries.

---

## What we'd skip in v1

- **Predictive analytics.** No "this bill has an X% chance of passing." We don't have the model and the user already has working senses.
- **Sentiment analysis.** No "70% of news articles framed this favorably." Editorial framing on top of editorial framing is a trust hole.
- **Anyone-can-edit annotations.** Not Wikipedia. The corpus is curated by us; users can flag inaccuracies but not edit panels directly.
- **Real-time updates.** v1 generates the why-now context at bill-page-load time and caches for 24 hours. Bills don't usually get a dramatic political turn within a day.

---

## How this composes with what we already have

This isn't a standalone feature — it leverages every piece of infrastructure we've already built:

- **Committee Reports** section answers *"what did the committee say about this?"*
- **Connections panel** answers *"what does this bill touch?"* (amends, related, identical, amended-by)
- **Plain-English translation** answers *"what does the bill do?"*
- **Why now?** answers *"why does this bill exist, and why now?"*

Together those four sections give a complete account of a bill: what, why, who's involved, what's the policy context. That's the editorial product we've been building toward without articulating it as a single shape until now.

---

## Open questions

1. **Editorial labor on the national landscape panel.** A hand-curated state-by-state corpus is real ongoing work. Who maintains it? My recommendation: start narrow (10 topics), see how often users hit a Why-now section that *doesn't* have national-landscape data, expand based on demand. The honest alternative is to skip this panel in v1 and just ship the prior-attempts + stakeholders + political-turn panels.

2. **Where does this live on the page?** Below the plain-English summary and above Connections, probably. But it competes with the committee reports section for attention. Worth a design pass.

3. **What about state bills vs federal bills?** Both work, but the data quality differs. Prior-attempts and political-turn panels are richer for federal because of cosponsor partisan data; national-landscape is more useful for state because comparison across states is what users actually care about. v1 ships both, with the relative panel mix tuned by jurisdiction.

4. **Caching and freshness.** Prior attempts and national landscape are essentially static; stakeholders and political turn can move with the news cycle. Different TTLs per panel (30d for the first two, 24h for the others) keeps cost down.

5. **Cost.** Each Why-now render involves a web search and 2–3 LLM calls. At scale this becomes the most expensive section of a bill page. Acceptable for a feature this differentiating, but worth knowing — back-of-envelope ~$0.05 per uncached bill page, against ~$0.005 for everything else combined.

---

## Out of scope

- Cross-bill comparisons within the same Why-now panel ("how is this different from SB 4205?")
- Long-form essays — Why-now is structured panels, not LLM-generated prose
- User-contributed annotations or comments
- Anything that requires a manually-curated dataset bigger than the 10–30 topic-area mapping mentioned above

---

## Success criteria

- A user reading VA HB 191 in 2026 sees the prior-attempts panel mentioning the 2022 and 2024 failed Virginia bills, the national-landscape panel noting most states already have this law, and at least one stakeholder mentioned by name with a source link.
- A user reading a routine appropriations bill sees the Why-now section *hidden* — it doesn't manufacture insight for procedural votes.
- A user can flag inaccuracies in any panel, and those flags feed into our existing review queue.
- A returning user sees the panel render in < 500ms from cache; a first-time render takes 5–10 seconds while the LLM calls fan out.

---

## Rough effort

This is a real feature, not a polish item.

- Prior-attempts panel: ~2 days (mostly bill-similarity scoring + dedup)
- National-landscape panel: ~3 days for v1 scaffolding + 1 ongoing engineer-week per quarter to maintain the corpus
- Stakeholders panel: ~2 days (web search wiring + extraction + provenance display)
- Political-turn panel: ~1 day (computed from prior-attempts data)
- Caching, UI, integration: ~2 days
- Inaccuracy-flag wiring: ~half a day

**Total: ~10 days of focused work for v1, plus an ongoing editorial commitment for the national-landscape corpus.** Worth doing only when state-search parity and per-user API keys are shipped — this builds on both.
