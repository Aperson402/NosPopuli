# Committee Reports — Feature Spec
**NosPopuli · Draft for review**

---

## What we're building

A new section on the bill detail page that surfaces committee reports about the bill — the document a committee publishes when it marks up a bill, explaining its reasoning, dissenting views, fiscal impact, and recommended changes.

For every report we display: the committee that issued it, the report number (e.g. *H. Rept. 119-247*), the date, a one-line description, and a link to the full PDF / HTML on Congress.gov. When the report has an accompanying summary or "purpose" section, we surface that inline so users don't have to leave the page to understand why the committee approved the bill.

---

## Why it matters

Committee reports are where the real reasoning lives. The bill text says *what* the bill does; the committee report says *why* the committee thinks it should pass — and crucially, who disagreed and on what grounds. Dissenting and minority views are published in the same report.

Today, a user reading our plain-English summary has no way to access this layer. They see the bill, the sponsors, the timeline, the related bills — but the actual deliberative product of Congress is hidden behind two extra navigation steps on Congress.gov. This makes the bill detail page feel like a directory of identifiers rather than a window into how Congress reasons.

This also addresses a known weakness in our current translator: when full bill text isn't yet published (true for ~2 weeks after introduction), the plain-English summary is generated from metadata alone and is necessarily vague. Once a committee marks up a bill, the report often appears *before* the formal text, and reports contain rich, structured language that our translator can use to produce sharper summaries.

---

## Data sources

### Congress.gov `/committee-report` endpoint

`GET /v3/committee-report?conference=false&fromDateTime=...&toDateTime=...` lists reports. Each report has:

| Field | Meaning |
|---|---|
| `citation` | "H. Rept. 119-247" — human-readable identifier |
| `congress` | Congress number |
| `chamber` | "House" / "Senate" |
| `reportType` | HRPT / SRPT / ERPT (executive report on treaty) |
| `number` | Report number |
| `part` | For multi-part reports |
| `updateDate` | Last updated |
| `url` | API URL for the report's full record |

### Congress.gov `/committee-report/{congress}/{type}/{number}` endpoint

Detail call returns:

| Field | Meaning |
|---|---|
| `title` | Official report title |
| `issueDate` | When the report was filed |
| `committees` | The committee(s) that issued it |
| `associatedBill` | The bill(s) this report covers (this is our join key) |
| `text` | URLs to PDF / HTML / Formatted Text versions |

### How we find reports for a specific bill

The API does not expose a direct "reports for bill X" endpoint. The path is:

1. `GET /bill/{congress}/{type}/{number}` already returns an embedded `committeeReports` array (we are currently ignoring it). Each entry has `citation` and `url`.
2. For each report URL, fetch the detail call to get title, issue date, and text URLs.

This means **no additional API surface area is required from the user's perspective** — the bill detail call already tells us which reports exist, we just need to enrich them.

---

## What we show, what we skip

### Show
- **House and Senate committee reports** on this bill (HRPT, SRPT)
- The report's **stated purpose** (the "Purpose" section at the top of every report) — this is short and the highest-signal extract for civic understanding
- A direct link to the **full report** on Congress.gov
- Dissenting / minority views indicator when present (the API surfaces this as a section count)

### Skip in v1
- Conference reports (ERPT, conference variant) — these are valuable but rare and appear only after both chambers pass different versions, deserving a separate treatment.
- Pre-1995 reports — Congress.gov has gaps before the 104th Congress; we just don't show anything for old bills and don't pretend.
- Auto-translating the report into plain English — this is a follow-up. v1 just exposes the human-readable report so users can read what already exists.

---

## UI placement

The Connections panel (built in `spec_legislation_relationships.md`) is the natural home. We add a new category between **Amends** and **Identical bills**:

```
Connections
  ├─ Amends ........................ Immigration and Nationality Act
  ├─ Committee Reports             ← NEW
  │    H. Rept. 119-247 · House Judiciary · Jun 18 2026
  │    "To require collection of a fee for credible-fear interviews…"
  │    Read full report → (link to congress.gov PDF)
  │    + 1 dissenting view filed
  ├─ Identical bill ................ H.R. 5012
  ├─ Amended by .................... 3 amendments
  ├─ Related legislation ........... S. 4205, S. 4521
```

Each report row is a self-contained card with:
- The citation as the title
- The committee name and issue date as a single mono-caps subline
- The stated purpose (one short paragraph, truncated to ~200 chars with "more" toggle)
- A "Read full report →" external link
- A small inline tag "+ N dissenting views" when applicable

If a bill has no committee reports, the section is hidden entirely. We do not show an empty state — unlike "Bill text not yet published," a missing committee report is normal for bills that haven't been marked up.

---

## Backend changes

### New module: `committee_reports_fetcher.py`

Exposes:

```python
def fetch_committee_reports_for_bill(congress, bill_type, bill_number) -> list[dict]:
    """
    Returns list of report dicts, ordered most-recent first.
    Each dict: {
        citation, committee, chamber, issue_date, purpose,
        full_url, has_dissenting_views, report_type, number
    }
    Returns [] when no reports exist.
    """
```

Implementation:
1. Read the embedded `committeeReports` array from the existing `fetch_bill` call (which we already cache).
2. For each report, call `/committee-report/{congress}/{type}/{number}` via the shared `congress_breaker` wrapper.
3. Parse out the purpose section from the report text URL (first `<h2>Purpose</h2>` block; fall back to the first paragraph of the formatted text version, capped at 400 chars).
4. Cache per-report in `disk_cache` with a 30-day TTL — committee reports do not change after publication.

Calls fan out in parallel via `ThreadPoolExecutor(max_workers=4)` with a 10s wall-clock budget. If we can't fetch all reports in time, we return what we have and let the next page load fill the rest from the disk cache.

### `api.py` changes

In the bill detail endpoint (`/bill`) and law endpoint (`/law`), call `fetch_committee_reports_for_bill` in parallel with the existing `bill_text`, `related`, `amendments`, `cosponsors` `asyncio.gather`. Add `committee_reports: list` to the response payload.

In `_build_connections`, add a `committee_reports` key.

### Circuit breaker

All committee-report API calls go through `congress_get` from `congress_breaker.py`. When the breaker is tripped, this section degrades silently — same as our existing rep enrichment.

---

## Frontend changes

### `index.html`

Add a new `<div class="conn-category" id="connections-committee-reports">` inside the connections section, placed between `connections-amends` and `connections-identical`.

### `index.js`

In `renderConnections(conn)`, add a block to render `conn.committee_reports` if present. Each report becomes a `.report-card` with the title, subline, purpose paragraph, dissenting-view tag, and external-link button.

New helper `_reportCard(r)` builds the card markup; we use the existing newspaper aesthetic (no rounded corners, mono caps for subline, serif for purpose body).

### `index.css`

New rules under the existing `.conn-category-body` patterns:
- `.report-card` — vertical stack, top/bottom rule lines for separation
- `.report-citation` — Source Serif 4, 1rem, bold
- `.report-subline` — IBM Plex Mono, 0.65rem, accent color
- `.report-purpose` — Source Serif 4, 0.88rem, muted color
- `.report-dissent-tag` — small inline chip indicating dissenting views

---

## Open questions

1. **Length of purpose extract.** I propose 200 chars in the card with a "show more" inline toggle to expand. Alternative is a fixed 400 chars no toggle. Trade-off is readability vs. completeness.

2. **What about reports filed against an *amendment* to this bill, not the bill itself?** These are rare but happen. Probably skip in v1 and revisit if users ask.

3. **Translator integration.** Should the plain-English summary use committee report text as a source when bill text isn't yet published? My recommendation: yes, but as a v2 follow-up — it requires changes to `translator_agent.py`'s prompt assembly and a re-translation pass for affected bills.

4. **State legislation.** OpenStates does not expose committee reports in v3 (state legislatures rarely publish equivalent documents). State bill pages would just hide this section. Acceptable.

---

## Out of scope for this spec

- Conference reports (ERPT) and their associated final-passage workflows
- Floor speeches (Congressional Record) integration — separate spec
- House/Senate Communications (presidential messages, withdrawal notices)
- Nominations, treaty documents — these are separate document types that do not generally connect to bills

These are listed not because they're worthless, but because each warrants its own design pass.

---

## Success criteria

- A bill that has at least one committee report shows the section with the report's title, committee, date, purpose, and a working link to the full report on Congress.gov.
- A bill with no reports does not show the section (no empty state, no "loading…" remnant).
- The bill detail page does not get slower for bills with no reports — fan-out happens in parallel with existing fetches.
- When `congress_breaker` is tripped, the bill page renders cleanly without this section and no console errors.
- A user reading a bill can now answer "what did the committee say about this?" without leaving NosPopuli.
