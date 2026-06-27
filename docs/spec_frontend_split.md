# Spec: Split `frontend/js/index.js` into ES Modules

## What we're building

Replace the single 3,059-line `frontend/js/index.js` with a set of focused ES modules loaded via native `<script type="module">`. No bundler, no build step — edit-and-reload stays intact (Engineering.md #2).

The split targets the structural weakness called out in the README CODE HEALTH section: every state-leak bug we've shipped (federal sponsors leaking into state bill detail, stale `stateName` from prefs) traces back to one file with implicit cross-section coupling through module-scoped `let`s and `window.*` handlers.

## Why it matters

- **State leaks become impossible to write accidentally.** Each module owns its `let`s; cross-module state goes through an explicit getter/setter in `state.js`. The "federal sponsors leaking into state bill" bug class disappears at compile/parse time.
- **Code review surface shrinks.** A change to the feed touches `feed.js`, not a file with elections, votes, onboarding, and sidebar above and below it.
- **Cognitive load matches Engineering.md #1.** Each module fits in one screen of scrolling.
- **Sets up the next refactor.** The `api.py` dispatcher split happened already; this is the symmetric frontend move.

## What we keep, what we change

**Keep:**
- Inline `onclick="…"` in `index.html`. Migrating ~80 inline handlers to `addEventListener` is a separate, larger refactor and not part of this scope.
- The newspaper aesthetic and all rendering output — this is a pure structural change.
- `correspondence.js` stays as it is (already separate, already working).
- Vanilla JS, no framework, no bundler.

**Change:**
- One `<script defer>` becomes one `<script type="module">` entry point that re-exports public functions onto `window` so existing `onclick` handlers keep working.
- Module-scoped `let`s for cross-cutting state (`_currentBill`, `_searchState`, `currentResults`, `currentJurisdiction`, `currentStateCode`, `previousPage`, `_feedItems`, `_feedExpanded`) move to `state.js` with named getters/setters. Single-section state stays local to its module.

## Module layout

```
frontend/js/
  index.js          # entry point — imports all modules, attaches public fns to window
  helpers.js        # pure utilities: escapeHtml, formatBillId, stateNameFromCode,
                    #   _compactBillTitle, capitalize, formatCongress, renderMarkdown,
                    #   formatDeck, _relativeDate, getStatusLabel/Class/Rank,
                    #   billIdFromParts, _initials
  state.js          # cross-cutting state getters/setters
  prefs.js          # getPrefs/savePrefs, _getSubs/_saveSubs, _getNotifyEmail,
                    #   _trackedElections set + _saveTracked
  ui.js             # showPage, goHome, goBack, setStatus, clearStatus,
                    #   tooltip helpers (showTooltip/moveTooltip/hideTooltip),
                    #   checkServer, masthead easter egg
  search.js         # runSearch, renderResults, loadMoreResults, _makeResultCard,
                    #   _makeCompactResultCard, _appendShowMoreFooter,
                    #   showClarificationBar, searchForAct, renderCommitteePage
  detail.js         # openDetail, renderExplanation, renderTimeline, renderChamber,
                    #   renderVotes, renderSponsors, renderFullText,
                    #   renderConnections + connection sub-helpers,
                    #   openBillText, toggleFullText, _userRepNames, USER_REP_HIGHLIGHT
  state_search.js   # runStateSearch, renderStateResults, _makeStateCard,
                    #   openStateBill, state picker (_initStatePicker,
                    #   _renderStatePicker, _shiftState, STATE_CODES,
                    #   STATE_NAMES_BY_CODE), setJurisdiction,
                    #   updateJurisdictionToggle, _switchToFederalAndSearch
  member.js         # openMemberFromVote, openStateMemberFromVote, renderMemberPage,
                    #   openDetailFromBill
  feed.js           # loadFeed, renderFeedSection, _toggleFeedExpanded, ledeAction,
                    #   _feedFollowingHtml, _feedElectionsHtml, _sectionTag,
                    #   _sponsorLastName, _whySuffix, _whyText, _repActivity,
                    #   _electionLevels, _electionSubLine, _leadCardHtml,
                    #   _storyCardHtml, billKey
  elections.js     # loadElections, openElections, _renderElectionsPage,
                    #   _renderElectionSection, _makeElectionCard, _renderContests,
                    #   _renderCandidate, _countdownDisplay, _formatElectionDate,
                    #   _candidateInitials, toggleTrackElection
  onboarding.js     # handleZipInput, lookupZip, showStep, goToStep2,
                    #   toggleInterest, finishOnboarding, onboardingData
  notifications.js  # _initNotifyBtn, _setNotifyBtnState, toggleSubscribe,
                    #   submitSubscribeEmail, _doSubscribe, loadNotificationsPage,
                    #   reopenBillFromNotif, stopNotifying
  sidebar.js        # _renderSidebar
  flags.js          # showSearchFlag, showBillFlag, renderFlagReasons,
                    #   openFlagModal, closeFlagModal, submitFlag,
                    #   SEARCH_REASONS, BILL_REASONS, currentFlagType,
                    #   currentFlagContext
  correspondence.js # untouched — already separate
```

Estimated post-split line counts (rough): helpers ~150, state ~60, prefs ~50, ui ~100, search ~300, detail ~600, state_search ~350, member ~200, feed ~550, elections ~250, onboarding ~120, notifications ~250, sidebar ~50, flags ~120, index ~80. Largest module ~600 lines, target ceiling 800.

## How modules share state

A single `state.js` exports getters/setters for cross-cutting fields. Modules that read or mutate them go through these accessors; no module reaches into another module's private `let`s.

```js
// state.js
let _currentBill = null;
export const getCurrentBill = () => _currentBill;
export const setCurrentBill = (b) => { _currentBill = b; };

let _searchState = { question: '', maxResults: 10, ... };
export const getSearchState = () => _searchState;
export const updateSearchState = (patch) => { _searchState = { ..._searchState, ...patch }; };

// …same pattern for currentResults, currentJurisdiction, currentStateCode,
//   previousPage, _feedItems, _feedExpanded, currentSearchContext
```

Single-section state (`_connAmendedByFull`, `onboardingData`, flag-modal locals, `memberLoadingInProgress`, `_electionsLoaded`) stays inside its module. Module-private = `let` with no export.

## How modules talk to `index.html`

`index.html` calls handlers via `onclick="goHome()"`, `onclick="loadElections()"`, etc. ES modules don't expose globals by default, so the entry point explicitly attaches each public handler to `window`:

```js
// index.js (entry)
import { goHome, goBack, showPage } from './ui.js';
import { runSearch, searchForAct, loadMoreResults } from './search.js';
import { setJurisdiction, ... } from './state_search.js';
// … etc

Object.assign(window, {
  goHome, goBack, showPage,
  runSearch, searchForAct, loadMoreResults,
  setJurisdiction, /* … */
});
```

Every function currently called from an `onclick` in `index.html` (or in `innerHTML` strings inside the JS) must appear in this list. Audit pass: `grep -nE 'onclick=\"[a-zA-Z_]' frontend/index.html` plus a scan of `innerHTML =` strings inside the new modules.

## Inter-module imports

Allowed direction (no cycles):

```
helpers.js, prefs.js          ← leaves, no internal imports
state.js                       ← leaf
ui.js                          → helpers, state, prefs
detail.js                      → helpers, state, prefs, ui, member, notifications
search.js                      → helpers, state, prefs, ui, detail, member
member.js                      → helpers, state, prefs, ui, detail
state_search.js                → helpers, state, prefs, ui, detail, member, search
feed.js                        → helpers, state, prefs, ui, detail, elections (read-only),
                                 notifications (read subs), onboarding (state transitions)
elections.js                   → helpers, state, prefs, ui
onboarding.js                  → helpers, state, prefs, ui, feed (loadFeed at finish),
                                 sidebar (re-render), state_search (updateJurisdictionToggle)
notifications.js               → helpers, state, prefs, ui, detail (reopen)
sidebar.js                     → helpers, prefs, member
flags.js                       → state (read currentSearchContext)
index.js (entry)               → all
```

Circular risk: `detail ↔ notifications`. Resolution: `detail.js` calls a `_initNotifyBtn` import; `notifications.js` calls `openDetail` only via `reopenBillFromNotif`, which is fine because reopening crosses async boundary. If parse-time cycles bite, lazy-import inside the function: `const { openDetail } = await import('./detail.js')`.

## What we skip

- **Migrating inline `onclick` to `addEventListener`.** Out of scope. A future refactor.
- **TypeScript / JSDoc type annotations.** Out of scope. Engineering.md §8 puts this at the 7–10-person threshold.
- **Renaming `_private` helpers.** They keep their `_` prefix to flag module-private intent.
- **Touching `correspondence.js`.** Already separate; leave it alone.
- **Renaming or removing functions.** Pure mechanical move + import wiring.
- **Behavior changes.** Zero. This refactor is a no-op for the user.

## Backend changes

None.

## Frontend changes

1. Create the 14 new module files listed above by extracting code from `index.js` (no logic changes).
2. Rewrite `index.js` as the entry point that imports modules and attaches public handlers to `window`.
3. In `index.html`, change `<script defer src="/static/js/index.js?v=2"></script>` to `<script type="module" src="/static/js/index.js?v=split"></script>`. `correspondence.js` stays as `<script defer>`.
4. Bump CSS cache buster if any styles change (none planned — `?v=` stays).

## Open questions

1. **One PR or staged?** Recommendation: one PR. Staged splits create an awkward interim where some functions are in modules and others are still in `index.js` calling each other through `window`. Easier to review one mechanical move than five overlapping ones.

2. **Should `correspondence.js` also become a module?** Not in this scope. It already works as a separate script and the inline handlers in `index.html` for `loadCorrespondencePage`, `openWritePanel`, etc. would need the same `window.*` attachment treatment. Worth doing later, not now.

3. **Should `state.js` expose objects or pairs of getters/setters?** Pairs of getters/setters. Returning the raw `let` would let any importer mutate it directly, which is exactly the pattern we're trying to escape.

4. **Tooltip element (`tooltip` const)** — currently `const tooltip = document.getElementById('tooltip')` at top of file. Goes in `ui.js`. Other modules import `showTooltip`/`hideTooltip` rather than touching the element directly.

## Success criteria

A new contributor can:
- Open `feed.js` and read the entire feed-rendering logic in one screen without scrolling past elections, votes, or onboarding.
- Edit `detail.js` knowing that nothing in `state_search.js` can have written to its locals — only through `state.js`.
- Trace any `onclick="foo()"` in `index.html` to a single source module via the explicit `Object.assign(window, …)` block in `index.js`.

Manual verification before declaring done (Engineering.md §4 step 5 — unhappy paths):
- [ ] Front page loads with a personalized feed (zip + interests configured)
- [ ] Empty-prefs state: onboarding prompt renders
- [ ] Federal search: a topic ("healthcare bills")
- [ ] Federal search: a named act ("GENIUS Act")
- [ ] Federal search: a specific bill ID ("HR 3590")
- [ ] Federal search: a member ("Ted Kennedy")
- [ ] Federal search: a low-confidence query — clarification bar appears
- [ ] State search: bill ID ("HB 1557" with FL picked)
- [ ] State search: a topic, then "Switch to Federal?" nudge clicked
- [ ] Bill detail: open a federal bill, then a state bill — sponsor section properly hidden on state (the bug class this refactor exists to prevent)
- [ ] Member detail: federal member, state legislator
- [ ] Subscribe / unsubscribe to a bill, manage from `/notifications`
- [ ] Elections page: tracked / yours / other sections render
- [ ] Onboarding flow start-to-finish
- [ ] "Show more" search history mode
- [ ] Masthead easter egg jiggle still fires (canary for the entry-point IIFE migration)

## File-by-file extraction order

To keep each commit reviewable in isolation while the refactor is in flight, order matters. Recommended sequence within the one PR:

1. `helpers.js` — pure, no dependencies, biggest payoff per line moved
2. `prefs.js` — pure, no dependencies on UI
3. `state.js` — pure, no dependencies
4. `ui.js`
5. `member.js`
6. `detail.js`
7. `notifications.js`
8. `search.js`
9. `state_search.js`
10. `feed.js`
11. `elections.js`
12. `flags.js`
13. `sidebar.js`
14. `onboarding.js`
15. Rewrite `index.js` as the entry; update `index.html`
16. Manual smoke test against the checklist above

## Risk

- **Cycle bites at parse time.** Mitigation: the dependency graph above is acyclic. If a cycle slips in, fix with a lazy `await import()` at the call site.
- **A missed `window.*` attachment breaks an `onclick`.** Mitigation: grep audit pass listed above before the smoke test.
- **Module load order surprises.** ES modules are deferred and dependency-ordered automatically; the entry point runs after DOM is parsed, so `document.getElementById(...)` calls inside top-level module code still work the same as the current `defer`-tagged script.
