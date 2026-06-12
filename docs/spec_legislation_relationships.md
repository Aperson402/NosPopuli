# Legislation Relationships — Feature Spec
**NosPopuli · Draft for review**

---

## What we're building

A "Connections" panel on every bill detail page that maps the legislative web around a bill — what it amends, what amends it, identical companion bills, and substantively related legislation. Currently the detail page shows a flat undifferentiated list of "related bills." This replaces that with structured, labeled, clickable relationships.

---

## Why it matters

Most bills don't exist in isolation. A spending bill might amend a 30-year-old entitlement law. A House bill might have an identical Senate companion. Understanding a bill fully means understanding what it touches — and right now that context is invisible to the user.

---

## Data sources

### Congress.gov `/relatedbills` endpoint
Already called via `fetch_related_bills`. Currently filters to `"Related bill"` type only and drops everything else. Full set of relationship types returned by the API:

| API type string | Meaning |
|---|---|
| `Related bill` | Substantively related |
| `Identical bill` | Same text, other chamber (companion bill) |
| `Superseded by` | This bill was replaced by another |
| `Procedurally related` | Rules/procedure connection only — low signal |

### Congress.gov `/amendments` endpoint
`/bill/{congress}/{type}/{number}/amendments` — lists amendments formally filed against this bill. Each amendment has its own bill-style identifier, sponsor, and latest action.

### Title parsing
Many bills open with "To amend [Act name] of [year]..." or "To reauthorize [Act]...". This is extractable from the bill's official title and represents the most direct relationship — the law this bill would modify.

---

## Connections panel — structure

Replaces the current flat "Related Legislation" section in the detail page. Grouped into labeled categories, each collapsible, each entry clickable to open that bill's detail.

```
CONNECTIONS

── AMENDS ──────────────────────────────────────────────
  Parsed from title or bill summary. One entry max.
  "Inflation Reduction Act (P.L. 117-169)"
  Click → opens that law's detail page

── IDENTICAL BILL ──────────────────────────────────────
  Same legislation introduced in the other chamber.
  HR 1234 · 119th Congress — [title]

── AMENDED BY ──────────────────────────────────────────
  Bills that formally amend this one (from /amendments).
  HR 456 · 119th Congress — [title]  [latest action date]
  S 321  · 119th Congress — [title]  [latest action date]

── RELATED LEGISLATION ─────────────────────────────────
  "Related bill" type from /relatedbills, max 5.
  HR 789 · 118th Congress — [title]  [latest action date]
  ...

── SUPERSEDED BY ───────────────────────────────────────
  Only shown if present. One entry.
  "HR 999 · 119th Congress — [title]"
```

"Procedurally related" entries are silently dropped — no section shown.

If a category has no entries, that section is hidden entirely. If all categories are empty, the entire Connections panel is hidden (same as current behavior).

---

## Backend changes

### `bill_fetcher.py` — `fetch_related_bills`

Current behavior: filters to `"Related bill"` only, returns flat list of max 5.

New behavior: returns a dict grouped by relationship type:

```python
{
  "identical":   [...],   # "Identical bill" type
  "related":     [...],   # "Related bill" type, max 5
  "superseded":  [...],   # "Superseded by" type
}
```

Each entry keeps the same shape as today: `{congress, type, number, title, latest_action, latest_action_date}`.

### `bill_fetcher.py` — `fetch_amendments` (new function)

Calls `/bill/{congress}/{type}/{number}/amendments`, returns list of:
```python
{
  "congress": int,
  "type": str,       # amendment bill type
  "number": int,
  "title": str,
  "latest_action": str,
  "latest_action_date": str,
}
```

Cap at 5. Return `[]` on 404 (many bills have no amendments).

### `bill_fetcher.py` — `parse_amends_from_title` (new function)

Checks the bill's official title for common amendment patterns:
- `"To amend the X Act"` → extract `"X Act"`
- `"To reauthorize the X Act"` → extract `"X Act"` with label "Reauthorizes"

Returns `{"label": "Amends"|"Reauthorizes", "act_name": str}` or `None`.

No API call — pure text parsing. Runs on the title already in hand.

### `api.py`

Replace the `related_bills` field in both bill detail endpoints with a `connections` object:

```json
{
  "connections": {
    "amends":     { "label": "Amends", "act_name": "Inflation Reduction Act" },
    "identical":  [...],
    "amended_by": [...],
    "related":    [...],
    "superseded": [...]
  }
}
```

The `fetch_related_bills` and `fetch_amendments` calls run concurrently via `asyncio.gather` (already the pattern in use).

---

## Frontend changes

### `index.js` — `renderConnections` (replaces `renderRelatedBills`)

Accepts the `connections` object. Builds each section only if that category has entries. Each entry is a clickable row using the existing `member-bill-row` style — same as today.

The "Amends" section, if present, renders slightly differently: it's a single line linking to the referenced law by name, not a bill row.

### `index.html`

Replace `#related-bills-section` with `#connections-section` containing the new structure.

### `index.css`

Add `.connections-category` header style — small-caps label with a thin rule, consistent with the existing tab/section aesthetic. No new colors, no rounded corners.

---

## What we are not building

- **Visual graph** — network visualization of relationships. Too heavy for the current UI language, and the structured panel communicates the same information more precisely.
- **Cross-congress lineage tracing** — automatically fetching ancestors (the law that the amended law itself amended). Too recursive, too many API calls. The "Amends" link gives the user one click to get there themselves.
- **Procedurally related bills** — low signal, clutters the panel.
- **Amendment text diffing** — showing what changed between a bill and its amendments. Out of scope.

---

## Decided

1. **Amends parsing**: check title first; fall back to first paragraph of `bill_summary` if title yields nothing.
2. **Identical bill UX**: if multiple, show only the most recent (by `latest_action_date`).
3. **Amendments cap**: 5 shown by default, "Show all" expansion for bills with more.
