# Samana Builders ERP — Master Test Plan (Playwright E2E)

> Generated 2026-09-13 by the QA agent. This supersedes the earlier stub plan.
> Source of truth for scenario detail = `specs/<app>.md`; static code findings =
> `docs/qa/<app>_analysis.md` + `docs/qa/README.md` (risk register).
> Every scenario has a stable ID (`<APP>-<CAT>-<NN>`) that Phase C test names must match.

## 1. Scope & approach

Browser E2E against the local Django dev server (`http://127.0.0.1:8000`, `DJANGO_DEBUG=True`,
system Chrome via Playwright `channel:'chrome'`). Plans are written from static code analysis
(models/views/serializers/forms/templates/JS) and are biased toward the money/status flows and
the authorization/IDOR/XSS/CSRF findings — not just happy paths. Highest-severity scenarios get
precise reproduction steps so Phase D can confirm or refute each suspected defect against the
live app.

## 2. Coverage map

| Module | Scenarios Planned | Edge Cases (EC) | Negative/Security | Auth Required | Spec | Test File (Phase C) | Status |
|---|---|---|---|---|---|---|---|
| core | 35 | 8 | 12 | Yes | `specs/core.md` | `tests/core/core.spec.ts` | Planned |
| customers | 35 | 8 | 10 | Yes | `specs/customers.md` | `tests/customers/customers.spec.ts` | Planned |
| properties | 47 | 15 | 11 | Yes | `specs/properties.md` | `tests/properties/properties.spec.ts` | Planned |
| bookings | 40 | 13 | 8 | Yes | `specs/bookings.md` | `tests/bookings/bookings.spec.ts` | Planned |
| payments | 38 | 14 | 8 | Yes | `specs/payments.md` | `tests/payments/payments.spec.ts` | Planned |
| finance | 34 | 12 | 6 | Yes | `specs/finance.md` | `tests/finance/finance.spec.ts` | Planned |
| expenses | 32 | 12 | 10 | Yes | `specs/expenses.md` | `tests/expenses/expenses.spec.ts` | Planned |
| hr | 28 | 10 | 5 | Yes | `specs/hr.md` | `tests/hr/hr.spec.ts` | Planned |
| notifications | 27 | 9 | 8 | Yes | `specs/notifications.md` | `tests/notifications/notifications.spec.ts` | Planned |
| ai | 44 | 14 | 14 | Yes | `specs/ai.md` | `tests/ai/ai.spec.ts` | Planned |
| api | 35 | 6 | 14 | Mixed¹ | `specs/api.md` | `tests/api/api.spec.ts` | Planned |
| frontend | 35 | 9 | 11 + 7 a11y | Mixed² | `specs/frontend.md` | `tests/frontend/frontend.spec.ts` | Planned |
| **Total** | **≈430** | **130** | **117** | | | | |

¹ `api`: one public endpoint (`/api/plots/list/`); everything else authenticated.
² `frontend`: corporate landing/lead form are public; ERP pages authenticated.

## 3. Priority targets for Phase D reproduction

These are the suspected defects (from `docs/qa/README.md`) that the plans turn into concrete,
reproducible scenarios. Phase D will confirm/refute each with browser + API evidence.

1. **CRITICAL — vertical privilege escalation** (`CORE-SEC-01/02`, `API-SEC-01/02`):
   `role` writable via `profile_view` / `ProfileViewSet.update_profile` → any user becomes `super_admin`.
2. **CRITICAL — systemic IDOR / PII read-open** (`CUS-SEC-*`, `BOOK-SEC-*`, `HR-SEC-01`, `PAY-SEC-01`,
   `API-SEC-03…08`, `FIN-SEC-01`): `@login_required`-only views + DRF `SAFE_METHODS` open to any
   authenticated user leak CNIC/phone/address/salary/amounts/audit IPs to customer-portal users.
3. **HIGH — CSRF via GET** (`EXP-SEC-01…03`): expense approve/reject/mark-paid mutate on GET.
4. **HIGH — booking reopen conflict** (`BOOK-EC-01`): two active bookings on one re-sold plot.
5. **HIGH — money-flow bugs** (`PAY-EC-01/02/03`, `BOOK-EC-02/03`): reverse-corruption,
   double-verify race, double-approve refund, cancel-without-verified.
6. **HIGH — stored XSS** (`AI-SEC-01`, `FE-SEC-01/02`): AI insights/history + AI HR chat.
7. **HIGH — HR API read-open + leave self-approve** (`HR-SEC-01/02`).

## 4. Data isolation & conventions (all suites)

- Unique, timestamped test data (`QA-<ts>-...` names/emails/phones); never depend on another
  test's rows. Clean up created records in `afterEach`/`afterAll` unless a fixture is meant to persist.
- Only the local dev SQLite `db.sqlite3`. No production/staging URLs anywhere.
- Never modify application code; report defects, don't patch them.
- Auth-heavy suites reuse a login via a storageState helper (`tests/helpers/auth.ts`) instead of
  logging in per test.

## 5. Evidence capture on failure

- `trace: 'on-first-retry'` + `screenshot: 'only-on-failure'` (already in `playwright.config.ts`).
- For a suspected real bug: capture screenshot + trace + console + HAR via the `playwright` MCP
  browser, and record severity + exact repro steps into `test_report.md`.

## 6. Spec index

See `specs/README.md` for the full file list and the scenario-ID convention.
