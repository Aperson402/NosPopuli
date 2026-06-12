# Civic Correspondence — Feature Spec
**NosPopuli · Draft for review**

---

## What we're building

A one-click pipeline that lets a user read a bill, explain in plain language how it affects them personally, and send a well-crafted email to their own elected federal representatives — from their own Gmail address. The platform surfaces replies, drafts follow-ups, and throttles use hard enough to prevent botting.

---

## Core user flow

```
Bill detail page
  └── "Write to Your Representatives" button
        ├── [First time] Enter zip code → we find your 3 federal reps
        ├── [First time] Gmail account screened + OAuth connected
        ├── Select who to write to (House rep + 2 Senators shown)
        ├── Tell us: how does this bill affect you? (2–4 sentence freeform)
        ├── AI drafts → user edits in textarea
        ├── User approves → platform sends via Gmail API
        └── Correspondence tab tracks all letters + surfaces replies
```

---

## Decisions

| Question | Answer |
|---|---|
| Zip persistence | Single home zip only — no multiple addresses |
| Scope | Federal only (House + Senate). State button hidden in V1. |
| Email footer | Yes — every sent email includes "Sent via NosPopuli — nospopuli.com" |
| Contact form fallback | Acceptable for V1 — copy draft + open form URL |
| Email screening | Gmail address username screened before account is activated |

---

## Feature modules

### 1. User accounts

Required — ties correspondence history to a person and is the primary anti-abuse gate.

**Auth:**
- Google Sign-In (OAuth). Shares the consent screen with Gmail permission request — one click to both create an account and connect Gmail.
- Email + password fallback for users without Google accounts (then Gmail OAuth is a separate step).

**Stored per user:**
- `zip_code` (entered once, home district only)
- `gmail_address` (the address that will send letters)
- `gmail_refresh_token` (encrypted at rest)
- `email_screened` (boolean — cleared by the username screen, see §8)
- Rate limit counters

---

### 2. Zip → representative lookup

API: **Google Civic Information API** (free, no auth cost beyond a key).

Endpoint: `GET https://www.googleapis.com/civicinfo/v2/representatives?address={zip}`

Returns: office title + name + party + contact URL for each elected official.

We call this on zip save and cache the result for 24 hours. Display: name, party, office, their headshot if available.

**Scope:** Federal only — House rep + 2 Senators. State button is hidden entirely until a later sprint.

---

### 3. Legislator contact

Federal legislators' email addresses are not publicly indexed — most use web contact forms. Two approaches, used in order:

1. **Email addresses we can find** — the `unitedstates/congress-legislators` GitHub dataset (public domain) includes direct emails for some members. We load this as a static JSON at startup and refresh weekly.
2. **Contact form fallback** — for members without a known email, we draft the message, show a "Submit via their contact form" button that copies the draft to clipboard and opens the senator's official form URL (also in the dataset) or `https://www.house.gov/representatives/find-your-representative`.

We track in `correspondence` which delivery method was used.

---

### 4. AI draft generation

**Input to Claude:**
- Bill title, short summary (from existing `/bill` endpoint)
- Key actions / status (from timeline)
- User's freeform personal impact statement
- Legislator name and title

**Prompt template:**
```
You are helping a constituent write a letter to their representative.
Write a concise, respectful letter (200–300 words) that:
- Opens with who the constituent is and where they're from
- References the specific bill by name and number
- Explains the personal impact in the constituent's own words (use their statement, don't embellish)
- Asks for a specific action (support / oppose / clarify their position)
- Closes with a thank-you and request for a response

Do not use advocacy boilerplate or group-campaign language. Make it sound like one person.

Bill: {title} ({id})
Summary: {summary}
Personal impact (constituent's words): {user_statement}
Legislator: {name}, {office}
Constituent location: {city_from_zip}, {state}
```

Model: `claude-haiku-4-5-20251001` (fast, cheap — this runs on every draft click).

User edits the draft before sending. The textarea is fully editable.

---

### 5. Gmail send

**OAuth scopes requested:**
- `https://www.googleapis.com/auth/gmail.send` — send on behalf of user
- `https://www.googleapis.com/auth/gmail.readonly` — surface replies

**Send flow:**
1. Build RFC-2822 message (To, Subject, body + footer)
2. `POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send`
3. Store returned `message.id` + `threadId` in `correspondence` table

**Subject line format:** `[Bill ID] — [Bill short title]`

**Mandatory footer appended to every email:**
```
—
Sent via NosPopuli (nospopuli.com) — civic intelligence platform.
This message was written and approved by the constituent above.
```

The footer is non-editable in the UI (shown greyed out below the editable body). This makes the platform's role transparent to legislators' offices while making clear the human authored and approved the message.

---

### 6. Reply surfacing

We don't run a polling daemon. Instead, we query Gmail on-demand when the user opens their Correspondence tab:

```
GET /gmail/v1/users/me/threads/{threadId}
```

For each stored thread, fetch the latest message count. If the count increased since last check, mark the correspondence as "replied" and surface the preview (first 200 chars of the new message body).

The user reads the reply in their Gmail inbox — we just tell them it arrived and show a preview to surface it in context.

---

### 7. Follow-up management

When a reply arrives, the Correspondence tab shows:
- Original letter (collapsed)
- Reply preview + "Open in Gmail" link
- "Draft a follow-up" button

Follow-up generation uses the same AI draft flow but adds the reply content as context:
```
Prior letter: {original_body}
Their reply: {reply_text}
Draft a respectful follow-up (100–200 words) that acknowledges their response and continues the conversation.
```

User edits and sends exactly as before. Footer is added automatically.

---

### 8. Anti-abuse / moderation

The feature is designed so it's expensive to abuse at volume.

**Rate limits:**

| Gate | Limit |
|---|---|
| Account required | ✓ — email verified before first send |
| Per user per day | 5 emails max |
| Per bill per legislator per user | 1 email per 30 days |
| Draft AI generation | 10 drafts/day (prevent prompt farming) |
| IP-level (unauthenticated) | Block |

**Content moderation:**
- Before sending, run a lightweight Claude call: "Does this email contain threats, harassment, or content unrelated to the stated bill? Yes / No." If yes, block with a clear message.
- No mass-send UI — one recipient at a time, chosen from the user's own reps only.
- No email list import.

**Email username screening:**

When a user connects their Gmail account, we extract the local part of their address (before the `@`) and screen it before activating the correspondence feature. The check runs once at account connection time and the result is stored as `email_screened = true/false`.

Screen using a Claude call:
```
The following is the username portion of a Gmail address that will be used
to send letters to elected officials on a civic platform.

Username: {local_part}

Is this username appropriate for civic correspondence with government officials?
Flag it if it contains: profanity, slurs, sexual language, references to violence,
clearly juvenile or troll-style names (e.g. "bigfart42", "hitlerwasgood").
Allow: real names, initials, professional-sounding handles, usernames with numbers.

Reply with APPROVED or FLAGGED and one short reason.
```

If flagged:
- The user sees: *"Your Gmail address isn't suitable for civic correspondence. Please connect a more professional email address."*
- The correspondence feature is locked for that account until they reconnect with a different address.
- We do not store or log the flagged username beyond what's needed to show the message.

**Platform commitment displayed to users:**
> "NosPopuli never sends anything without your review and approval. Each email is sent from your personal address. We don't sell contact data or run campaigns."

---

## Backend data model

```sql
users
  id, email, verified_at, zip_code, state, city,
  gmail_address, email_screened (bool),
  gmail_refresh_token (encrypted), created_at, last_active

correspondence
  id, user_id, bill_id, bill_title,
  legislator_name, legislator_office, legislator_state,
  to_email,           -- null if contact-form delivery
  contact_form_url,   -- null if email delivery
  subject, body,
  sent_at, delivery_method (email | form),
  gmail_thread_id,    -- null for form delivery
  status (sent | replied | followed_up)

replies
  id, correspondence_id,
  gmail_message_id, received_at, preview_text (200 chars)
```

---

## New API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/register` | Create account |
| `POST` | `/auth/google` | Google Sign-In |
| `GET` | `/user/reps` | Get reps from stored zip |
| `POST` | `/user/zip` | Save zip, trigger rep lookup |
| `GET` | `/auth/gmail` | Start Gmail OAuth flow |
| `GET` | `/auth/gmail/callback` | Handle Gmail OAuth callback + screen username |
| `POST` | `/correspondence/draft` | AI draft for a bill + legislator |
| `POST` | `/correspondence/send` | Send approved email |
| `GET` | `/correspondence` | List user's sent correspondence |
| `GET` | `/correspondence/{id}/replies` | Check for replies on one thread |

---

## Frontend surfaces

**On bill detail page:**
- "Write to Your Reps" button (below the vote section, above related bills)
- Opens a right-side panel (not a new page)
- Panel state machine: `setup_zip → setup_gmail → [screen] → pick_rep → write_impact → review_draft → sent`
- Footer shown greyed out and non-editable below the draft textarea

**New "Correspondence" tab in main nav:**
- Lists all sent letters grouped by bill
- Shows reply status (awaiting / replied)
- Follow-up drafting for replied threads

---

## Build order

1. User auth (Google Sign-In + email/password)
2. Zip → rep lookup + display (federal only)
3. Gmail OAuth + username screening
4. Gmail send + mandatory footer
5. AI draft generation
6. Correspondence tab + reply surfacing
7. Follow-up drafting
8. Rate limiting + content moderation
9. State legislators (later sprint — button hidden in V1)
