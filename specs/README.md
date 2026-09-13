# Specs — Test Plan Index

One test plan per module, each produced from the corresponding `docs/qa/<app>_analysis.md`.

## Scenario-ID convention (the contract for Phase C)

`<APP>-<CATEGORY>-<NN>` where `<CATEGORY>` ∈ `HP` (happy path), `EC` (edge/boundary),
`SEC` (negative & security), `API` (API contract), `A11Y` (accessibility, frontend only).
Phase C test titles must match the scenario ID so tests stay in sync with the plan.

## Plans

| Module | Plan | Scenarios | Notes |
|---|---|---|---|
| core | `core.md` | 35 | auth, dashboard revenue, users, backup, privilege-escalation + IDOR repros |
| customers | `customers.md` | 35 | CNIC/phone validation divergence, IDOR, PII exposure |
| properties | `properties.md` | 47 | plot status machine, charge-field gaps, XSS, API delete guards |
| bookings | `bookings.md` | 40 | lifecycle, reopen conflict, price guards, installment auto-gen |
| payments | `payments.md` | 38 | money-flow invariants, double-verify/approve races, receipt exposure |
| finance | `finance.md` | 34 | ledger idempotency, approval bypass, orphan rows, API read-open |
| expenses | `expenses.md` | 32 | GET-mutation CSRF, upload XSS, media exposure |
| hr | `hr.md` | 28 | payroll/post-to-ledger, HR API read-open, leave self-approve |
| notifications | `notifications.md` | 27 | send triggers, normalization, 500 on filter, smishing/injection |
| ai | `ai.md` | 44 | DeepSeek gating, prompt injection, stored DOM-XSS, IDOR |
| api | `api.md` | 35 | auth handshake, privilege escalation, role×method permission matrix |
| frontend | `frontend.md` | 35 | XSS sinks, CSRF coverage, money rendering, a11y |

`_plan-template.md` — the required plan structure (preconditions, happy path, edge cases,
negative/security, API contract, data isolation, evidence-on-failure).
