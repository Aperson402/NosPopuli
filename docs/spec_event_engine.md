# Event Engine — Feature Spec
**NosPopuli · Draft for review**

---

## What we're building

A system that watches the bills users have acted on and notifies them when those bills meaningfully change — a vote, a passage, a signature, or a reply from their representative's office. The goal is to convert a one-shot action ("I sent a letter") into an ongoing relationship ("my letter connected to something real") without manufacturing engagement. Every notification corresponds to a real-world event the user would be glad to receive even if they never open the app again.

This is the retention layer for the correspondence feature. It reuses the existing bill-actions pipeline (the same data that powers the bill timeline) and the existing reply-tracking from `correspondence/`.

---

## Core principle

> A notification is sent only when something **consequential and legible to a normal person** has happened to a bill the user personally acted on.

Procedural noise (referrals, calendar placement, technical amendments) is recorded but never notified. The bar does not move to chase engagement metrics. Fewer real notifications beat more thin ones — for a civic tool, one "why is this app emailing me junk" costs more than ten extra opens earn.

---

## Core flow

```
User sends a letter on a bill (existing correspondence flow)
  └── Implicit subscription created (user_id, bill_id)
        └── Daily watcher fetches current bill state
              ├── Compares to last recorded state
              ├── No change → do nothing
              └── State changed → classifier evaluates significance
                    ├── Procedural / noise → record state, no notification
                    └── Consequential → deliver notification (once) + record state
        └── Reply-tracking detects office reply → deliver notification (once)
```

---

## Decisions

| Question | Answer |
|---|---|
| Subscription trigger | Sending a letter auto-subscribes the user to that bill. Explicit subscribe-without-writing allowed but secondary. |
| Watch scope | Only bills with ≥1 active subscription. Never poll all of Congress. Cost scales with engaged users, not size of Congress. |
| Poll cadence | Daily. Legislation does not move faster than this. |
| Notification channel | Email (address already held from the correspondence OAuth flow). No new channel in V1. |
| Permission model | Implicit subscription is the basis, but it must be explicit at point of sending ("we'll tell you when this moves — unsubscribe anytime") and reversible via a working unsubscribe in every email. |
| Dedup | Notify on state *transition* only. Never re-send the same event. |
| Reply events | "Office replied" is a first-class event type, equal priority to "rep voted," sourced from reply-tracking rather than the bill pipeline. |

---

## Feature modules

### 1. Subscriptions

Records what each user cares about. A subscription is created as a side effect of sending a letter; the act of writing *is* the consent to be followed up.

**Stored per subscription:**
- `user_id`
- `bill_id`
- `subscribed_at`
- `last_notified_state` — the bill state as of the last time we notified (or recorded) this subscription. Drives dedup.
- `source` — `letter` (implicit) or `manual` (explicit subscribe)
- `active` — boolean; flips false on unsubscribe

**Notes:**
- A user may subscribe to the same bill once. Sending a second letter on a bill they already follow does not duplicate the subscription.
- Unsubscribe sets `active = false` but retains the row (so history and re-subscribe work cleanly).

---

### 2. Watcher

A scheduled job that detects state changes on subscribed bills.

**Logic:**
1. Collect the distinct set of `bill_id`s with at least one `active` subscription.
2. For each, fetch the current canonical state via the existing bill-actions pipeline.
3. Map the raw actions to a normalized **bill state** (see state model below).
4. Compare to `last_notified_state` on each subscription for that bill.
5. If unchanged → no-op.
6. If changed → pass to the classifier (module 3).

**Notes:**
- Reuses the bill-actions fetch already built for the timeline — no new data source.
- Scoped to subscribed bills only. A few hundred bills, not ten thousand.
- Idempotent: safe to run twice in a day; dedup lives in the state comparison, not the schedule.
- Runs as a cron-style job (mirrors the daily-refresh pattern already used elsewhere).

---

### 3. Event classifier

Decides whether a detected state change warrants a notification.

**Normalized bill state model (federal):**
```
introduced
  → in_committee
  → passed_committee
  → floor_scheduled
  → passed_chamber / failed_chamber
  → sent_to_other_chamber
  → to_president
  → signed / vetoed
```

**Notifiable events (send):**
| Event | Why it qualifies |
|---|---|
| User's own rep voted on the bill | The single highest-value bill event — direct, personal consequence |
| Bill passed or failed a chamber | Major, legible milestone |
| Bill signed into law or vetoed | Terminal consequence the user wrote about |
| Bill passed committee | Significant momentum; borderline — include in V1, revisit |
| Office replied to the user's letter | Direct proof the voice was heard (from reply-tracking) |

**Non-notifiable (record only, no send):**
- Referral to committee / subcommittee
- Calendar placement (e.g. Union Calendar)
- Technical or minor amendments
- Any change not legible to a non-expert

**The test, encoded:** *Would the user be glad to receive this even if they never open the app again?* If no → record state, suppress notification.

**Guardrail:** the bar is fixed. It is not lowered in response to low engagement. Adding event types is a deliberate, reviewed change — never a growth-hack reflex.

---

### 4. Delivery + dedup

Sends qualifying events exactly once and records that they were sent.

**On a qualifying event:**
1. Compose the notification (module 5).
2. Send via email.
3. Update `last_notified_state` on the subscription to the new state.

**Dedup guarantee:**
- Notify on the transition, then stay silent until the next transition.
- A bill sitting in `in_committee` for 30 days produces zero repeat emails.
- `last_notified_state` is the source of truth; the watcher's daily run cannot double-send because the state already matches after the first send.

---

### 5. Notification content

Every notification carries the **consequence** and the **source**, and links back into the product where the user's correspondence history lives.

**Template shape:**
> The House voted on **HR 9263 (Housing Supply Fund Act of 2026)** — the bill you wrote to Rep. Brown about. It passed 240–190. **Rep. Brown voted yes.** [See the vote →]

**Requirements:**
- States what happened (the event) in one sentence.
- Names the user's own rep and how they voted, when applicable — this is the personal hook.
- Includes a source link back to the bill detail / vote on NosPopuli.
- Includes a working unsubscribe link.
- Never editorializes on whether the outcome is good or bad — same neutrality discipline as bill translations.

---

## Event types summary

| Event type | Source | Priority |
|---|---|---|
| Rep voted | bill-actions pipeline | High |
| Passed / failed chamber | bill-actions pipeline | High |
| Signed / vetoed | bill-actions pipeline | High |
| Office replied | reply-tracking (`correspondence/`) | High |
| Passed committee | bill-actions pipeline | Medium (V1, revisit) |
| Procedural | bill-actions pipeline | None (record only) |

---

## Subscribe button in bill detail view

A "Notify me when this moves" button sits in the Plain English Explanation section, next to the existing "Write to Your Reps" button. This covers the explicit subscribe-without-writing path.

**Placement:**
```
[ Plain English Explanation section ]
  ✉ Write to Your Reps     [ Notify me when this moves ]     Flag inaccuracy
```

The button lives in the same `display:flex; justify-content:space-between` row as the write button and flag link (`index.html` lines 190–199). It is hidden until the bill loads, same as the write button.

**States:**
| State | Label | Appearance |
|---|---|---|
| Not subscribed | `Notify me when this moves` | Same style as `write-reps-btn` |
| Subscribed | `Notifying you ✓` | Muted / dimmed — same ink color, lower opacity |
| Loading | `…` | Disabled |

**Behavior:**
- On click: prompts for email if not already held (correspondence OAuth may already have it). Stores subscription locally and calls a `/subscribe` endpoint.
- If the user has already sent a letter on this bill (implicit subscription already exists), the button renders as `Notifying you ✓` on page load.
- Subscription state is persisted in `localStorage` keyed by `bill_id` so the button renders correctly on revisit without an extra API call.
- Clicking `Notifying you ✓` unsubscribes (calls `/unsubscribe`, updates localStorage, reverts label).

**Email capture:**
- If an email is already stored in localStorage (from correspondence flow), skip the prompt and subscribe silently.
- If not, show a small inline input beneath the button: `Your email →  [________]  [Subscribe]`. On submit, store email in localStorage and proceed.
- No account required. Same anonymous-first principle as the rest of the product.

---

## What we are NOT building (V1)

- Notifications for bills the user only viewed but never acted on.
- Push notifications, SMS, or any channel beyond email.
- Digest/batching across multiple bills (each event is its own email in V1).
- Monitoring of unsubscribed or non-subscribed bills.
- Any "we miss you" / "bills you might like" re-engagement messaging. This is explicitly prohibited — the engine sends consequences, never solicitations.

---

## Scaling note

Cost and load scale with the number of **engaged users** (bills written about), not with the size of Congress. The watcher polls only the subscribed slice. This is the property that keeps the feature compatible with the project's low-cost public-utility goal.

---

## Open questions

- Is "passed committee" too noisy for the Medium tier, or right? Decide after observing real volume.
- Batching: if a single bill produces two events close together (e.g. passed chamber + rep voted on the same day), send one combined email or two? Lean toward one.
- Re-subscription UX: if a user unsubscribes from a bill then writes a second letter on it, do we re-subscribe? Proposed: yes, a new letter re-activates.
- Reply-event detection reliability: how confidently does reply-tracking distinguish a real office reply from an auto-acknowledgement? An auto-ack should probably not fire the high-value "your voice was heard" notification.
