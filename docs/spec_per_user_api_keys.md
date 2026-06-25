# Per-User API Keys — Feature Spec
**NosPopuli · Draft for review**

---

## What we're building

Today every NosPopuli request uses one shared `CONGRESS_API_KEY` and one shared `GovInfo_API_KEY` baked into `.env`. When that single key gets soft-flagged (which happened in this dev session), every user's federal bill detail, member, and full-text fetches go dark at once.

This spec replaces the shared-key model with **per-user keys provisioned automatically during signup**, using the user's already-connected Gmail account to scrape the welcome email from api.data.gov. The shared keys stay as a fallback for users mid-onboarding or whose key got revoked.

---

## Why it matters

- **No single point of failure.** One flagged key disabling the whole platform — which we lived through — is a real product risk that grows with the user base. Per-user keys spread the rate-limit load across 5,000 req/hr per user instead of 5,000 req/hr for everyone combined.
- **Free for us.** Users carry their own quota; we don't pay for higher tiers.
- **Legitimate under the api.data.gov ToS.** Both Congress.gov and GovInfo issue keys through api.data.gov, which explicitly expects one key per developer. Users registering their own keys for their own usage is the intended model — what we're doing today (one key servicing N users) is the deviation.
- **Onboarding flow already exists.** We already have Gmail OAuth in place for the correspondence feature. Extending that scope to also watch for the api.data.gov welcome email is a small marginal cost on an existing piece of infrastructure.

---

## The flow, end-to-end

1. **User signs in with Google** (already implemented for correspondence; the OAuth flow gives us read access to their inbox).
2. **On first signin** (or whenever a key is missing), we show a one-time onboarding panel: *"NosPopuli works best when you have your own Congress.gov API key. We'll register one for you — takes about a minute."*
3. The panel opens `https://api.data.gov/signup/` in a popup with name + email prefilled via query string (the form supports prefill).
4. User clicks **Submit** on api.data.gov.
5. **Our backend polls the user's inbox** (via the existing Gmail scope) for a message matching `from:noreply@api.data.gov AND subject:"API Key"`. Poll for up to 5 minutes at 15-second intervals; if no email arrives, surface a "Didn't get it? Try again" prompt with a paste-from-email fallback.
6. **Extract the key with a regex** — api.data.gov's welcome email contains the key in a `<pre>` block with a stable surrounding text marker.
7. **Persist encrypted-at-rest** in `correspondence.db` keyed by user id. Use `cryptography.fernet` with a master key in `.env` (`USER_KEY_ENCRYPTION_KEY`).
8. **From that point forward**, every Congress.gov / GovInfo call routes through the user's key instead of the shared one.

---

## Key technical pieces

### Storage

New table:

```sql
CREATE TABLE user_api_keys (
    user_id            TEXT PRIMARY KEY,
    congress_key_enc   BLOB,
    govinfo_key_enc    BLOB,
    provisioned_at     REAL,
    last_verified_at   REAL,
    last_error         TEXT
);
```

Both keys are stored encrypted with `cryptography.fernet`. The encryption key lives in `.env` as `USER_KEY_ENCRYPTION_KEY`; loss of that file requires re-provisioning, which is a per-user 1-minute flow and acceptable.

### Inbox watcher

New module `user_api_key_provisioner.py` exposes:

```python
def start_provision_flow(user_id: str, gmail_creds: dict) -> dict:
    """Trigger the api.data.gov signup popup metadata for the frontend."""

def poll_for_key(user_id: str, gmail_creds: dict, deadline_seconds: int = 300) -> str | None:
    """Watch the inbox for the welcome email; return the extracted key or None."""

def store_key(user_id: str, key: str, kind: Literal["congress", "govinfo"]) -> None:
    """Encrypt and persist to user_api_keys."""

def get_user_key(user_id: str, kind: str) -> str | None:
    """Decrypt and return the user's key, or None if not provisioned."""
```

### Per-user breaker

`congress_breaker.py` currently has process-wide state — `_tripped_until`, `_cooldown_seconds`. We move that to a per-user dict:

```python
_BREAKER_STATE: dict[str, dict] = {}  # keyed by (user_id, kind)
```

When `user_id`'s Congress.gov key trips, only that user's breaker opens. Other users continue working. The shared key has its own bucket keyed by `("shared", "congress")` for the fallback path.

### Request-time wiring

`congress_get` gains a `user_id` parameter:

```python
def congress_get(url, *, user_id: str | None = None, params=None, timeout=10, **kw):
    key = get_user_key(user_id, "congress") if user_id else None
    if not key:
        key = os.getenv("CONGRESS_API_KEY")  # fallback to shared
    ...
```

Every API endpoint that already accepts a `user_context` (most do) threads `user_id` through. Endpoints that don't currently take user context (the feed, the search) gain an optional `user_id` field on their request models — frontend sends it whenever the user is signed in.

### Fallback path

When a user's key isn't provisioned yet (mid-onboarding) or has been flagged, the system falls back to the shared key transparently. We never block functionality on "you need a key" — onboarding is a *nice-to-have* prompt, not a gate.

If the shared-key breaker is *also* tripped, we degrade exactly the way we do today (graceful empty states, GovInfo fallback for bill text, etc.).

---

## Frontend changes

### Onboarding card

A dismissible card in the main UI:

```
┌─ Get your own API key (recommended) ──────────────┐
│ NosPopuli uses Congress.gov and GovInfo APIs to   │
│ load federal bills. Your own key gets you faster  │
│ responses and insulates you from rate limits when │
│ other users are active.                           │
│                                                   │
│ Takes about a minute. We'll watch your inbox for  │
│ the welcome email so you don't have to copy-paste.│
│                                                   │
│              [ Get my key → ]   Skip for now      │
└───────────────────────────────────────────────────┘
```

Shown:
- After first sign-in via Google
- After any session where the shared-key breaker tripped (a contextual nudge: *"Things were slow this session because of shared rate limits — get your own key for ~60s"*)

### Settings page

Add a "API Keys" section showing:
- Whether each key is provisioned (just status, never the key itself)
- "Re-provision" button if a key is bad
- "Disconnect" button (deletes from `user_api_keys`)

### Status indicator

Small dot in the search bar's corner — green when user's key is active, yellow when on shared fallback. Tooltip explains. Subtle, not alarming.

---

## ToS considerations

api.data.gov terms allow one key per developer, used for that developer's own purposes. Some legal questions worth thinking about before shipping:

1. **Are we "registering on behalf of" the user, or are they registering themselves?** The form is submitted from the user's browser with their email and name. We're providing UI sugar (prefill + email scraping). I read this as the user registering themselves with our help, which is fine. Worth getting a one-paragraph review from someone with public-API experience before launch.
2. **Inbox access.** The Gmail scope we already use for correspondence covers what we'd need here. We should narrow the scope to `from:noreply@api.data.gov` during the poll window so we're not scanning the user's whole inbox.
3. **Data retention.** Keys are encrypted at rest. If a user deletes their account, we destroy both encrypted columns. Document this in the privacy page.

---

## Open questions

1. **What happens for anonymous users?** Today most of the app works without sign-in. Per-user keys only help signed-in users; anonymous users continue on the shared key. That's fine, but worth being explicit: anonymous traffic is the load that determines whether we need the per-user model at all. If anonymous traffic dominates, per-user keys are a smaller win than we'd hope.

2. **Should we extend this to other APIs?** OpenStates also issues per-developer keys. Same flow could provision an OpenStates key. Worth doing in the same sprint if we're already building the infrastructure — adds maybe 20% to the work.

3. **Key rotation.** api.data.gov keys don't expire by default but can be rotated by the user. We have no detection mechanism for "your key got revoked outside our system." Probably fine to let users hit "re-provision" when they notice issues.

4. **What if Gmail OAuth fails to grant inbox-read scope?** Fall back to a manual paste-key flow. Onboarding panel shows the same popup but instead of polling, shows a textarea labeled "Paste the key from your welcome email here."

---

## Success criteria

- A new user signs in with Gmail, clicks "Get my key", and within ~60 seconds is on their own Congress.gov key with no manual key-pasting.
- A user whose key gets flagged sees a "Re-provision" button in settings; clicking it walks them through the flow again in under a minute.
- A user's flagged key only affects that user — other users keep working.
- An unsigned-in user, or a user who skipped onboarding, falls through to the shared key transparently with no UX change.
- The shared `CONGRESS_API_KEY` in `.env` is never the *only* defense against an outage again.

---

## Rough effort

- Backend (db schema, encryption layer, provisioner, breaker rework, request wiring): ~3 days
- Frontend (onboarding panel, settings page, status indicator): ~1 day
- ToS / legal review and privacy page update: ~half a day
- Testing across signed-in / anonymous / breaker-tripped / no-Gmail-scope branches: ~1 day

**Total: ~5–6 days of focused work.** Bigger than the state-search spec because of the auth and encryption surface area.
