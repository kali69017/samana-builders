# <APP> Module — QA Analysis

> Template for `docs/qa/<app>_analysis.md`. Replace `<APP>` with the module name.
> Read `docs/qa/_shared-context.md` first — do NOT re-derive roles/permissions/URLs.

## 1. Business purpose & user journeys
- One paragraph: what this module does and why it matters.
- Bulleted real user journeys (login → action → outcome), each labeled with the
  role(s) that perform it.

## 2. Data model
For each model: fields (name, type, null/blank, default), relationships,
unique/`unique_together` constraints, `save()` hooks (auto IDs), properties/
computed methods, `Meta.ordering`, and any `clean()`/model-level validation.

## 3. Roles & permissions
- Table: action → allowed role(s) → enforced by (decorator / DRF permission class / template flag).
- Explicitly call out owner/object-level gating (or its ABSENCE = IDOR risk).
- Note any endpoint where a role check is missing or inconsistent with the
  template flag (e.g. UI hides the button but the view is unguarded).

## 4. Business rules, state machines, invariants
- Every status field and its full transition graph (legal + illegal transitions).
- Every invariant (e.g. "advance_paid ≥ holding_deposit", "refund ≤ refundable").
- Every side effect (ledger post, plot status change, notification send, audit log).

## 5. Edge cases (go deep)
For each field/flow: empty input, null, max length, boundary values (0, negative,
huge numbers, float/money precision), duplicate records, concurrent double-submit,
unavailable referenced record (deleted FK / 404 / protected delete), expired/invalid
session, unauthorized access to another user's data (IDOR), malformed payloads,
wrong HTTP verb (GET vs POST), timezone/date boundaries (fiscal year July/June),
soft-delete, pagination tails, network failure on save. Each edge case states the
EXPECTED behavior, not just "should not crash".

## 6. Cross-cutting risks
- XSS: any user content rendered unescaped (`|safe`, `mark_safe`, `innerHTML` in JS).
- CSRF: state-changing forms/endpoints without CSRF token/`@csrf_exempt`.
- IDOR / broken object-level authorization: `pk`-based views lacking ownership checks.
- Sensitive data exposure: APIs/templates leaking CNIC, phone, amounts, email.
- Accessibility: missing labels, contrast, keyboard traps in key flows.

## 7. API surface
Table: method + path → ViewSet/action → permission → request fields (required/
optional) → response. Note serializer validation rules and any custom actions.

## 8. Test data & fixtures needed
- Preconditions (which roles/seed records), and how to create cleanly.
- Isolation rules: what must be unique/timestamped so tests don't collide.

## 9. Key files (for traceability)
List the files actually read, with one-line note each.
