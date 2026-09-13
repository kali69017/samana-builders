# <Module> — Test Plan

> Template for `specs/<app>.md`. Scenario IDs are the contract Phase C test names must match.

## 1. Scope & roles
- One paragraph: what this plan covers.
- Roles that exercise it (and which are expected to be denied).

## 2. Preconditions & fixtures
- Seed data / roles needed (how to create cleanly; timestamped unique values).
- URLs exercised (relative to http://127.0.0.1:8000).

## 3. Scenario catalog
Grouped by category. Each scenario: **ID**, **Title**, **Preconditions**, **Steps**, **Expected result**, **Evidence on failure**.

Categories:
- `HP` — happy path
- `EC` — edge case / boundary
- `SEC` — negative & security (auth, authorization, IDOR, injection)
- `API` — API contract (only where the module exposes DRF endpoints)

Scenario ID convention: `<APP>-<CATEGORY>-<NN>`, e.g. `CUS-HP-01`, `BOOK-EC-03`, `PAY-SEC-02`, `HR-API-01`.
App prefixes: CORE, CUS, PROP, BOOK, PAY, FIN, EXP, HR, NOTIF, AI, API, FE.

## 4. Data isolation rules
- What is unique/timestamped so tests never depend on each other; what to clean up.

## 5. Coverage checklist (for the master map)
List of scenario IDs, one line each, ready to paste into TEST_PLAN.md.
