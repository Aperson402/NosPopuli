# Spec: Migrate `correspondence.db` (SQLite) → Postgres on Supabase

## What we're building

Replace the on-disk SQLite file `correspondence.db` with a Supabase Postgres database. All eight tables move 1:1 — same names, same columns, same semantics. `correspondence/db.py` is rewritten as a thin psycopg3 wrapper over Postgres; every caller keeps its current call signature.

## Why it matters

### The immediate problem

Today the file lives at `<repo>/correspondence.db` and Railway has no volume mounted there. **Every deploy and container restart wipes**:

- Gmail OAuth refresh tokens (users re-auth — silent breakage)
- Sent letters + replies (history loss — user opens "My Letters", sees nothing they sent yesterday)
- Bill subscriptions (`event_watcher.py` has nothing to email — the daily notification job becomes a no-op)
- Curated `known_elections` rows (admin re-enters by hand)
- All disk caches (mild — they rebuild, but the cold-start hit returns on every deploy)

Of those, the first three are not "stale data" problems — they're **trust problems**. A user who OAuthed yesterday and finds themselves logged out today will not OAuth a third time. A subscriber who never gets the email when their bill moves concludes the notification system doesn't work. These compound: each deploy taxes the trust of every existing user.

### Why now, not later

Three reasons it should not wait:

1. **It actively breaks the product as we sit here.** Not theoretically — the next `git push` to main wipes whatever Gmail tokens have accumulated. The longer we delay, the more users get burned.
2. **The fix is cheapest right now.** Eight tables, one schema, sync-only callers, no migrations history. As the schema grows the port grows linearly. A Postgres-shaped problem at 8 tables is mechanical; at 30 tables it's a project.
3. **The deferred fixes pile up against it.** The README CODE HEALTH section names a planned per-user-API-keys migration (`spec_per_user_api_keys.md`) that adds another table; the lobbying directory roadmap adds several more; the local/municipal phase adds ingestion state. Every one of those is built easier on durable Postgres than on "SQLite plus a volume we keep meaning to mount."

### Why Postgres on Supabase, specifically

We considered four options before landing here:

| Option | Verdict | Why |
|---|---|---|
| **Mount a Railway volume on the existing SQLite file** | No | Fixes persistence today but leaves us on SQLite — single-writer lock, no operational dashboard, no concurrent-deploy story, and every future feature inherits it. Solves the symptom, not the trajectory. |
| **Railway Postgres add-on** | No | Works fine but adds a second managed service. We already pay Supabase for the translation cache; doubling up on managed Postgres providers means two dashboards, two bills, two outage radii. |
| **Supabase Postgres (chosen)** | Yes | Already paid-for, already used by `translator_agent.py`. Free tier (500 MB / 60 conns) is two orders of magnitude beyond our usage. One vendor to monitor. Dashboard for ad-hoc SQL. |
| **Self-host Postgres on a separate VPS** | No | Engineering.md §1 — one person in their head. Adding ops surface (backups, patching, monitoring) for a server that adds nothing the managed offer doesn't already give us. |

### What this unlocks

Persistence is the floor, but the move pays for itself beyond it:

- **Concurrent writes stop blocking.** SQLite serialises every writer; under any real traffic the rate-limit table and disk_cache table contend. Postgres doesn't.
- **Operational visibility.** A bad subscription row, a poisoned cache entry, a duplicate user — these can be inspected and fixed in the Supabase SQL editor instead of by SSH'ing into a container that no longer exists by the time we look.
- **Backups are someone else's job.** Supabase takes daily automated backups on the free tier. SQLite-on-a-volume means we own backup tooling, retention, and restore drills — none of which we have.
- **Roadmap unblocks itself.** Lobbying tables, per-user API keys, vote-cache tables — all of them get a real database to land in.

### What we accept by doing this

Honesty per Engineering.md §1.4:

- **Per-call latency goes from sub-ms to 20-50 ms.** Real but absorbed; see the Latency budget section.
- **One more env var (`SUPABASE_DB_URL`) and one more cold-start step (pool warmup).** Trivial.
- **Local dev needs a Postgres endpoint** — see Local dev section. Edit-and-reload survives because all calls stay sync.
- **A single point of failure shifts from "the disk under the container" to "the Supabase project."** Acceptable: Supabase has better uptime than our deploy cadence, and the failure mode is "the app returns 500" rather than "the app silently lies to users about their data."

## What we keep, what we change

**Keep:**
- One function per operation in `correspondence/db.py`, same names, same arguments, same return shapes. Callers don't change.
- Sync API (`run_in_executor` pattern stays). No async refactor.
- `init_db()` called once at app startup; idempotent `CREATE TABLE IF NOT EXISTS`. No migrations framework.
- The `data/known_elections.json` fallback for `get_known_elections` — that path is already independent of SQLite and stays as-is.
- JSON blobs stored as `TEXT` with `json.dumps`/`json.loads` in Python (don't switch to JSONB — no caller benefits from server-side JSON queries today).

**Change:**
- `sqlite3` → `psycopg[binary]` (psycopg 3, sync API)
- `psycopg_pool.ConnectionPool` shared across the process — opened on first use, reused for life of process
- `?` placeholders → `%s` placeholders
- `INSERT … ON CONFLICT(col) DO UPDATE SET col=excluded.col` already works on Postgres — direct port
- `datetime('now')` defaults → `NOW()`
- `INTEGER` boolean cols (`email_screened`, `active`) → `BOOLEAN`. Python callers stop passing `1`/`0`, pass `True`/`False`
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGSERIAL PRIMARY KEY`. `cur.lastrowid` → `RETURNING id` clause
- `cached_at REAL` (epoch seconds) → `DOUBLE PRECISION` — keep epoch seconds for minimum-diff port
- `created_at TEXT DEFAULT (datetime('now'))` → `created_at TIMESTAMPTZ DEFAULT NOW()`. Callers that read this never parse it; they pass it back to the frontend as a string, which Postgres returns as a `datetime` object — caller code needs `.isoformat()` for those rows
- `sent_at > datetime('now', '-30 days')` (in `check_bill_rep_cooldown`) → `sent_at > NOW() - INTERVAL '30 days'`

## Schema port table

| SQLite | Postgres | Notes |
|---|---|---|
| `TEXT PRIMARY KEY` | `TEXT PRIMARY KEY` | UUIDs stay TEXT (we generate in Python) |
| `TEXT` | `TEXT` | |
| `INTEGER` (numeric) | `INTEGER` | |
| `INTEGER` (boolean, `email_screened`/`active`) | `BOOLEAN` | callers pass Python bool |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL PRIMARY KEY` | `known_elections.id` |
| `REAL` (`cached_at`) | `DOUBLE PRECISION` | keep epoch seconds |
| `TEXT DEFAULT (datetime('now'))` | `TIMESTAMPTZ DEFAULT NOW()` | |
| `TEXT` (JSON blob in `disk_cache.value`, `elections_search_cache.results`) | `TEXT` | keep — no caller needs JSONB |
| `REFERENCES users(id)` | same | foreign keys port directly |
| `UNIQUE(a, b, c)` | same | port directly |
| `CREATE INDEX … IF NOT EXISTS` | same | port directly |

## Connection strategy

- One process-wide `ConnectionPool(min_size=2, max_size=10, conninfo=os.getenv("SUPABASE_DB_URL"))`. Opened lazily on first `get_conn()` use.
- Connect through Supabase's **transaction pooler** (port 6543) — works with PgBouncer in `transaction` mode, no prepared statements, no LISTEN/NOTIFY. We don't need either.
- Each function does `with pool.connection() as conn: with conn.cursor(row_factory=dict_row) as cur: …`. psycopg3 manages commit/rollback inside the `with`.
- Reads use `cur.fetchone()` / `cur.fetchall()` returning dicts (matches current `dict(row)` callers).

## Environment

Add one env var: `SUPABASE_DB_URL` — the Postgres connection string from Supabase → Settings → Database → "Connection pooling" → URI format. Looks like:

```
postgresql://postgres.<project>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

Existing `SUPABASE_URL` / `SUPABASE_API_KEY` for the translator REST client are unchanged.

`README.md` env-var list and the local-dev block both get a line added.

## Local dev

**Decision point**: pick one of —

1. **Same Supabase project as prod, separate schema** — set `search_path=dev,public` for the local app. Free, no extra service. Risk: a mistake on local could touch prod tables in the `public` schema.
2. **A second free Supabase project** for dev. Zero overlap with prod. Cleanest. Recommended.
3. **Local Postgres via Docker** (`docker run -p 5432:5432 -e POSTGRES_PASSWORD=… postgres:16`). No Supabase round-trip latency. Closest to current edit-and-reload speed.

Recommendation: **option 2 for normal dev, option 3 for offline / iteration on db.py itself.** The `SUPABASE_DB_URL` env var carries either.

## Data migration

Local `correspondence.db` is 176 KB and likely contains throwaway dev rows. Prod state is already being lost on every deploy. **Default plan: drop both, start fresh on Postgres.**

If you'd rather preserve current local rows, I'll add a one-shot `scripts/sqlite_to_postgres.py` (table-by-table dump + insert; ~50 lines, ~5 min to run). Spec assumes "no migration" unless you tell me otherwise.

## Latency budget

Every disk-cache hit currently takes ~0.1 ms (SQLite). Postgres-on-Supabase from Railway is ~20-50 ms round-trip. Real cost per request:

- `/search` cache hit: +20-50 ms (was ~0.1 ms). The whole search costs hundreds of ms cold, so this is noise.
- `/feed` cache hit: +20-50 ms. Same — feed is heavyweight.
- `/elections` cache hit: +20-50 ms. Same.
- Subscription writes (rare): +20-50 ms. Fine.

Net: imperceptible at user level, and the cache becoming durable across restarts more than pays for the per-call cost.

## What stays untouched

- `bill_fetcher.py`'s in-memory TTLCaches (hot path, sub-ms). These aren't in correspondence.db.
- The translation cache in Supabase (REST via `translator_agent.py`). Already Postgres-backed, already working.
- `agent_log.json`, `search_log.json`, `flags.json`. File-based logs, ephemeral by design, stay file-based.
- `data/known_elections.json` — shipped with the repo.

## Backend changes

1. Add `psycopg[binary]` and `psycopg_pool` to `requirements.txt`. Remove nothing (sqlite3 is stdlib).
2. Rewrite `correspondence/db.py` end-to-end:
   - Top: `_pool = None`, `def _get_pool()` lazy-initialiser, `_DB_URL = os.getenv("SUPABASE_DB_URL")`.
   - Replace `get_conn()` with `@contextmanager def conn_cursor(): with _get_pool().connection() as c: with c.cursor(row_factory=dict_row) as cur: yield cur`.
   - Every existing function ports 1:1: `with conn_cursor() as cur: cur.execute(…); …`.
   - `init_db()`: new `CREATE TABLE` statements as in the port table.
3. `api.py`: call `init_db()` once on startup via `@app.on_event("startup")` or by importing for side-effect. Currently `init_db()` is defined but not called anywhere I can see — confirm and wire it in.
4. Update any caller that passes `1`/`0` for booleans (`update_user_gmail`, `upsert_subscription`, `deactivate_subscription`) to pass `True`/`False`, and any caller that compared `row["active"] == 1` to use `row["active"]` directly.
5. Update README env-var list, local-dev section, and the CLAUDE.md storage line.

## Frontend changes

None.

## Deployment

1. Create a new Supabase project (or reuse existing). Copy the pooler `SUPABASE_DB_URL`.
2. Add `SUPABASE_DB_URL` to Railway env.
3. Deploy. `init_db()` runs on first request and creates the eight tables.
4. After confirmed working: delete `correspondence.db` from the repo (it's in `.gitignore` already? check) — and remove the file from any volume if one ever was attached.

## What we skip

- **An ORM (SQLAlchemy, peewee, etc.).** Engineering.md §9 #1 prohibits it without a written design doc. Raw psycopg matches the no-ORM rule and the dispatcher-style ergonomics already in this codebase.
- **Async psycopg.** Sync stays. All callers already wrap DB calls in `run_in_executor`.
- **Migrations framework (alembic).** `CREATE TABLE IF NOT EXISTS` covers us today. When the schema evolves, we'll add a hand-written migration file.
- **Backwards-compat fallback to SQLite.** Engineering.md #6 — no shims. Hard cutover; the SQLite path stops existing.
- **Restructuring `correspondence/db.py` into multiple files.** Same file, same functions, just a different driver underneath. Future refactor: split into `db_users.py`, `db_correspondence.py`, etc. — out of scope here.
- **JSONB / typed columns.** No caller benefits today.
- **Row-Level Security (RLS) policies on Supabase tables.** Our service connects with the database password, not the anon key — RLS doesn't apply on this path. If we ever expose tables via PostgREST that changes; not today.

## Open questions

1. **Data migration: drop or port?** Recommendation: drop. Confirm.
2. **Dev environment: separate Supabase project or local Postgres?** Recommendation: separate Supabase project (free tier).
3. **Is `init_db()` currently called anywhere?** Need to confirm by grep. If not, the prod tables only exist because someone manually created the SQLite file once — that needs a hook on the new Postgres path regardless.
4. **Subscription `active` column is sometimes filtered as `active=1` in SQL.** After bool migration, becomes `active=true`. One-line change inside each query; flagging because it's easy to miss.
5. **`known_elections.id` returned to admin frontend** — comes back as int from both backends, no change needed. Just confirming the contract holds.

## Backend changes — function-by-function delta

| Function | Change |
|---|---|
| `get_conn` | Replaced by `conn_cursor` context manager |
| `init_db` | Postgres DDL; called from `api.py` startup hook |
| `upsert_user` | `?`→`%s`, `datetime('now')`→`NOW()` |
| `get_user` | `?`→`%s` |
| `update_user_gmail` | `?`→`%s`; caller passes `bool` for `screened` |
| `update_user_zip` | `?`→`%s` |
| `check_rate_limit` | `?`→`%s` |
| `increment_rate_limit` | `?`→`%s`; `ON CONFLICT` clause unchanged |
| `check_bill_rep_cooldown` | `datetime('now', '-30 days')` → `NOW() - INTERVAL '30 days'` |
| `save_correspondence` | `?`→`%s` |
| `get_user_correspondence` | `?`→`%s` |
| `get_correspondence_by_id` | `?`→`%s` |
| `save_reply` | `INSERT OR IGNORE` → `INSERT ... ON CONFLICT(gmail_message_id) DO NOTHING` |
| `upsert_subscription` | `?`→`%s`; `1`→`TRUE` |
| `get_subscription` | `?`→`%s` |
| `deactivate_subscription` | `active=0` → `active=FALSE` |
| `get_active_subscribed_bills` | `active=1` → `active=TRUE` |
| `get_subscriptions_for_bill` | `active=1` → `active=TRUE` |
| `update_subscription_state` | `?`→`%s` |
| `get_elections_cache` | `?`→`%s` |
| `set_elections_cache` | `?`→`%s` |
| `_load_known_elections` / `get_known_elections` | **Unchanged** — file-backed |
| `list_known_elections` | `?`→`%s` |
| `add_known_election` | `cur.lastrowid` → `RETURNING id`, then `cur.fetchone()["id"]` |
| `delete_known_election` | `?`→`%s` |
| `get_disk_cache` | `?`→`%s` |
| `set_disk_cache` | `?`→`%s` |
| `clear_disk_cache` | `?`→`%s`; `cur.rowcount` works the same |
| `get_replies` | `?`→`%s` |

Total: ~25 function ports, all mechanical. Estimated diff: +60 / -90 lines (Postgres DDL is slightly more verbose, but no app logic changes).

## Success criteria

After deploy:
- A user OAuths via Gmail → records persist across a Railway redeploy.
- `/feed` cache hit returns immediately after a cold start (was: rebuild from scratch).
- Subscribing to a bill, then redeploying, then triggering `/watcher/run` finds the subscription and emails the user.
- Admin UI at `/admin/elections/ui` shows curated elections that were added before the redeploy.
- `correspondence.db` file no longer exists in the prod container.

Manual verification before declaring done (Engineering.md §4 step 5):
- [ ] Cold start: `init_db()` creates all eight tables; no errors.
- [ ] Auth: complete OAuth → user row written, refresh token stored.
- [ ] Rate limit: send a letter, hit `check_rate_limit` → counter increments.
- [ ] Cooldown: send a letter to a rep on a bill, immediately retry → blocked by `check_bill_rep_cooldown`.
- [ ] Reply: simulate a reply (or run the live correspondence flow) → `replies` row + `correspondence.status='replied'`.
- [ ] Subscribe: hit `/correspondence/subscribe`, then GET `/correspondence/subscription?bill_id=…` → row exists with `active=true`.
- [ ] Unsubscribe: GET `/correspondence/unsubscribe-link?email=…&bill_id=…` → row flipped to `active=false`.
- [ ] Disk cache: run a `/search`, then re-run within 30 min → second run returns `cached: true`.
- [ ] Elections cache: hit `/api/elections?zip=20151&state=VA` twice within 6 hr → second hit served from cache.
- [ ] Curated elections: POST `/admin/elections`, GET `/admin/elections` → row appears.
- [ ] Concurrency probe: 10 concurrent `/feed` calls don't block each other (was an SQLite-writer-lock issue).

## Risk

- **Pooler ceiling on Supabase free tier.** Default 60 connections; our pool max is 10 — fine, but the pooler counts against the project ceiling shared with translator REST calls. Watch the Supabase dashboard after deploy.
- **Cold connection setup adds 100-200 ms on first request after deploy.** One-time per worker. Mitigation: pool min_size=2 opens two on first init.
- **TIMESTAMPTZ return types.** Postgres returns Python `datetime` for timestamp cols; SQLite returned strings. Callers that re-emit `created_at`/`sent_at` to the frontend need `.isoformat()`. I'll audit on the way through and fix in the same PR.
- **`INSERT OR IGNORE` in `save_reply`.** Direct port to `ON CONFLICT(gmail_message_id) DO NOTHING` is correct, but the existing code follows with an `UPDATE correspondence SET status='replied'` that runs even when the insert is ignored. That behavior is preserved (it's idempotent), just calling it out.
