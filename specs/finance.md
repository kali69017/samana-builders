# Finance — Test Plan

> Module: `finance` (unified ledger `AccountTransaction` + `Office`/`ExpenseCategory`/`OfficeExpense` + `ProjectCost`/`ProjectBudget`/`ProjectInvestment`).
> Source of truth for risks and line references: `docs/qa/finance_analysis.md`; role/permission/money facts: `docs/qa/_shared-context.md`.
> Scenario IDs here are the contract Phase C test names must match (prefix `FIN`).

## 1. Scope & roles

This plan covers the finance module's happy paths (office, office expense, project cost, project budget/investment, ledger list), its edge cases around the ledger and state machines, and its negative/security scenarios around the `IsFinanceOrAbove` API permission and missing transition/delete guards. Both the HTML (Django template) surface and the DRF API surface are in scope.

Roles exercised:

- **super_admin** (`admin`/`admin123`) — all finance pages + all API writes. Happy-path operator.
- **management** (`management` role) — approve/pay office expenses, delete office/category/cost, edit budget/investment.
- **accounts** (`accounts` role) — finance role but **below** management; used to prove the approval-bypass (create already-`paid` records) and to confirm normal finance write access.
- **sales** (`sales` role, the default role) — expected **denied** everywhere; used to prove the API read leak (SEC) and HTML denial.
- **hr** / **staff** (`hr`/`staff` roles) — additional non-finance roles to prove the API read leak is not limited to `sales`.

Expected-denied set for every finance capability: `sales`, `hr`, `project_manager`, `contractor`, `staff`. Expected-allowed set: `super_admin`, `admin`, `management`, `accounts` (with the management-only sub-gates for approve/pay/delete).

## 2. Preconditions & fixtures

### Roles (create once, cleanly)
- Superuser `admin` exists by default.
- `management` user → `UserProfile(role='management')`.
- `accounts` user → `UserProfile(role='accounts')`.
- `sales` user → `UserProfile(role='sales')` (also the default when no role is set).
- `hr` user → `UserProfile(role='hr')`; `staff` user → `UserProfile(role='staff')`.

### Seed records (timestamped, unique — never reuse across scenarios)
- **Office**: `name` is unique — use `QA-HO-<epoch>` and `QA-BR-<epoch>`. Create via `/finance/offices/create/` or the API.
- **ExpenseCategory**: `name` is unique — use `QA-Rent-<epoch>` (e.g. `category_type='rent'`). Create via `/finance/expense-categories/create/` or the API.
- **Project**: `properties.Project` requires `location` — use `QA-Proj-<epoch>` + any `location`. Create via the properties module or Django shell; needed for project cost/budget/investment.
- Money fields are `Decimal(15,2)`; assert amounts **exactly** (e.g. `25000.00`), never loosely.

### URLs exercised (relative to `http://127.0.0.1:8000`)
- HTML: `/finance/ledger/`, `/finance/offices/`, `/finance/offices/create/`, `/finance/offices/<pk>/delete/`, `/finance/expense-categories/`, `/finance/expense-categories/create/`, `/finance/office-expenses/`, `/finance/office-expenses/create/`, `/finance/office-expenses/<pk>/edit/`, `/finance/office-expenses/<pk>/approve/`, `/finance/office-expenses/<pk>/pay/`, `/finance/office-expense-report/`, `/finance/project-costs/`, `/finance/project-costs/create/`, `/finance/project-costs/<pk>/edit/`, `/finance/project-costs/<pk>/delete/`, `/finance/projects/`, `/finance/projects/<pk>/budget/`, `/finance/projects/<pk>/investment/`.
- API: `/api/account-transactions/`, `/api/offices/`, `/api/expense-categories/`, `/api/office-expenses/`, `/api/office-expenses/{id}/approve/`, `/api/office-expenses/{id}/pay/`, `/api/project-costs/`, `/api/project-budgets/`, `/api/project-investments/`.

### Environment
- Run with `DJANGO_DEBUG=True` (else `SECURE_SSL_REDIRECT` 301s every request). Login `/login/`; staff land on `/dashboard/`.
- For API repro steps, use session-auth CSRF (GET `/auth/csrf/` then pass `X-CSRFToken`) or the DRF browsable API as the logged-in role; note all state-changing DRF actions are POST and CSRF-enforced.

## 3. Scenario catalog

### HP — happy path

#### FIN-HP-01 — Create office
- **Preconditions:** Logged in as `admin` (super_admin). No `Office` named `QA-HO-<epoch>` exists.
- **Steps:** 1) Go to `/finance/offices/`. 2) Click "Add Office" (`/finance/offices/create/`). 3) Fill name `QA-HO-<epoch>`, `office_type=head_office`, address text. 4) Submit.
- **Expected result:** Redirect to `/finance/offices/` with success message; new office appears in the list with the entered name/type. `Office` row persisted. `AuditLog` row `action=create, model_name=Office` exists.
- **Evidence on failure:** 400/re-render with field errors (duplicate name), or missing row, or no AuditLog entry.

#### FIN-HP-02 — Create office expense with status "paid" posts exactly one ledger row (create-time posting)
- **Preconditions:** `admin` logged in. Office `QA-HO-<epoch>` and category `QA-Rent-<epoch>` exist. `AccountTransaction` count for this office is captured before the step.
- **Steps:** 1) Go to `/finance/office-expenses/create/`. 2) Select office + category, `amount=25000.00`, `expense_date=<today>`, `status=paid`. 3) Submit.
- **Expected result:** Expense saved with `status=paid`; exactly **one** new `AccountTransaction` with `reference_type='OfficeExpense'`, `reference_id=<expense.pk>`, `direction='out'`, `amount=25000.00`, `transaction_type='office_expense'`, `category='QA-Rent-<epoch>'` (category name), `office` set. No duplicate row.
- **Evidence on failure:** ledger row count increased by 0 or >1; wrong `reference_type`/`reference_id`/`amount`/`category`.

#### FIN-HP-03 — Approve then Pay office expense posts ledger exactly once (idempotent)
- **Preconditions:** `management` user logged in. Office expense `EXP` created with default `status=pending` (not yet in ledger).
- **Steps:** 1) On `/finance/office-expenses/` open `EXP` approve action → POST `/finance/office-expenses/<pk>/approve/` (form `action=approve`). 2) Confirm `EXP.status=approved`, `approved_by=<management user>`, and **no** ledger row yet. 3) POST `/finance/office-expenses/<pk>/pay/`. 4) POST `/finance/office-expenses/<pk>/pay/` a second time.
- **Expected result:** After step 3, exactly one ledger row (`reference_type='OfficeExpense'`, `reference_id=EXP.pk`). After step 4 (double pay), still exactly one row — `post_to_ledger()` is idempotent via `update_or_create`.
- **Evidence on failure:** ledger row missing after approve→pay; two rows after double pay; `approved_by` not stamped.

#### FIN-HP-04 — Create project cost (default "paid") posts ledger immediately
- **Preconditions:** `admin` logged in. Project `QA-Proj-<epoch>` exists. `AccountTransaction` count captured.
- **Steps:** 1) Go to `/finance/project-costs/create/`. 2) Select project, `cost_category=material`, `amount=40000.00`, `cost_date=<today>` (leave `status` at its default `paid`). 3) Submit.
- **Expected result:** `ProjectCost` saved with `status=paid`; exactly one `AccountTransaction` with `reference_type='ProjectCost'`, `reference_id=<cost.pk>`, `direction='out'`, `amount=40000.00`, `project` set.
- **Evidence on failure:** no ledger row, or wrong reference/amount/project.

#### FIN-HP-05 — Project budget: remaining = total − paid costs
- **Preconditions:** `admin` logged in. Project `QA-Proj-<epoch>` has a paid `ProjectCost` of `40000.00` (from FIN-HP-04).
- **Steps:** 1) Go to `/finance/projects/<pk>/budget/`. 2) Set `total_budget=100000.00` (leave components 0). 3) Submit. 4) Go to `/finance/projects/`.
- **Expected result:** Row for the project shows `total_budget=100000.00`, `total_actual=40000.00`, `remaining_budget=60000.00` (i.e. `total − paid costs`, draft costs excluded).
- **Evidence on failure:** `remaining_budget` not equal to `100000.00 − 40000.00`; draft costs counted in `total_actual`.

#### FIN-HP-06 — Project investment recorded and shown
- **Preconditions:** `admin` logged in. Project `QA-Proj-<epoch>` exists.
- **Steps:** 1) Go to `/finance/projects/<pk>/investment/`. 2) Set `total_investment=1500000.00` and a note. 3) Submit. 4) Go to `/finance/projects/`.
- **Expected result:** Investment `1500000.00` persisted and displayed on the project finance view; `profit = revenue − total_cost` computed without error.
- **Evidence on failure:** investment not saved/displayed, or profit/loss computation crashes/misstates.

#### FIN-HP-07 — Ledger list: totals and filters
- **Preconditions:** `admin` logged in. Ledger contains at least one `out` (`office_expense`) and one `in` row (create an `in` row via `/api/account-transactions/` with `direction='in'`, `amount=1000.00`).
- **Steps:** 1) Go to `/finance/ledger/`. 2) Note `total_in` and `total_out`. 3) Filter `?type=office_expense`.
- **Expected result:** List shows every transaction ordered `-date, -created_at`; `total_out` = sum of `direction='out'` rows, `total_in` = sum of `direction='in'` rows. Filter narrows to `transaction_type='office_expense'` and recomputes totals.
- **Evidence on failure:** totals wrong (double-count, wrong direction), or filter returns unrelated types.

### EC — edge case / boundary

#### FIN-EC-01 — Status demotion orphans the ledger (paid → draft leaves the row)
- **Preconditions:** `admin` logged in. Office expense `EXP` is `paid` and has a ledger row (from FIN-HP-02/03). Capture ledger row count.
- **Steps:** 1) Go to `/finance/office-expenses/<pk>/edit/`. 2) Change `status` from `paid` to `draft`. 3) Submit.
- **Expected result (correct behavior):** demoting a paid record should remove/void the ledger row (or be blocked). **Observed bug:** `EXP.status=draft` but the `AccountTransaction` row remains; money stays booked out while the source object is no longer paid.
- **Evidence on failure:** ledger row still present with `reference_type='OfficeExpense'`, `reference_id=EXP.pk` after the object is `draft` — orphaned spend. (Capture both the object status and the ledger row.)

#### FIN-EC-02 — Delete paid ProjectCost leaves orphaned AccountTransaction
- **Preconditions:** `management` user logged in. Paid `ProjectCost` `COST` with a ledger row exists.
- **Steps:** 1) Go to `/finance/project-costs/<pk>/delete/`. 2) Confirm delete (POST).
- **Expected result (correct behavior):** deleting the cost should also delete its ledger row. **Observed bug:** `ProjectCost` deleted, but the `AccountTransaction` (`reference_type='ProjectCost'`, `reference_id=COST.pk`) survives because `reference_id` is a plain int (no FK/cascade).
- **Evidence on failure:** after deletion, `AccountTransaction.objects.filter(reference_type='ProjectCost', reference_id=COST.pk).exists()` is `True` — phantom spend in `total_out`.

#### FIN-EC-03 — Editing a paid office expense re-dates/re-amounts the historical ledger row
- **Preconditions:** `admin` logged in. Paid expense `EXP` (amount `25000.00`, date `<D1>`) with ledger row.
- **Steps:** 1) Edit `/finance/office-expenses/<pk>/edit/`. 2) Change `amount` to `50000.00` and `expense_date` to a backdate `<D0>`. 3) Submit.
- **Expected result (correct behavior):** historical paid transactions should be immutable. **Observed bug:** `post_to_ledger()` `update_or_create` rewrites the existing ledger row's `amount`/`date`/`category`/`description` — retroactive rewrite of history with no delta record.
- **Evidence on failure:** ledger row for `EXP.pk` now shows `amount=50000.00`, `date=<D0>` (old values gone); `total_out` retroactively changed.

#### FIN-EC-04 — Editing a paid project cost re-dates/re-amounts the historical ledger row
- **Preconditions:** `admin` logged in. Paid `ProjectCost` with ledger row.
- **Steps:** 1) Edit `/finance/project-costs/<pk>/edit/`. 2) Change `amount` and `cost_date`. 3) Submit.
- **Expected result (correct behavior):** immutable history. **Observed bug:** same as FIN-EC-03 for `reference_type='ProjectCost'` — ledger row silently rewritten.
- **Evidence on failure:** ledger row for the cost shows the new amount/date; no trace of the original.

#### FIN-EC-05 — Approval bypass: `accounts` user creates an already-paid office expense (posts ledger without management gate)
- **Preconditions:** `accounts` user (finance role, below management) logged in. Office + category exist. Ledger count captured.
- **Steps:** 1) Go to `/finance/office-expenses/create/`. 2) Fill office/category/`amount=100000.00` and set `status=paid`. 3) Submit.
- **Expected result (correct behavior):** a below-management user should not be able to post money out of the ledger without an approve/pay gate. **Observed bug:** form exposes `status`; `status=paid` triggers `post_to_ledger()` on create — a `100000.00` ledger entry posts with no management approval.
- **Evidence on failure:** `AccountTransaction` with `reference_type='OfficeExpense'`, `amount=100000.00` created by the `accounts` user; no `approved_by`. (Repeat via API `POST /api/office-expenses/` with `status='paid'` to confirm the same bypass.)

#### FIN-EC-06 — Approval bypass: project cost defaults to `paid` and posts to ledger without management gate
- **Preconditions:** `accounts` user logged in. Project exists.
- **Steps:** 1) Go to `/finance/project-costs/create/`. 2) Fill project/`cost_category`/`amount=200000.00` and leave `status=paid` (the default). 3) Submit.
- **Expected result (correct behavior):** a project cost should require approval before posting spend. **Observed bug:** default `paid` posts immediately — no approval path exists at all.
- **Evidence on failure:** `AccountTransaction` `reference_type='ProjectCost'` `amount=200000.00` created by `accounts`; the only "gate" is the `status` form field.

#### FIN-EC-07 — Negative total_budget → IntegrityError / HTTP 500 (no form/serializer validation)
- **Preconditions:** `admin` logged in. Project exists with no budget. Confirm the DB `CheckConstraint total_budget__gte=0` is migrated (`finance/migrations/0003`).
- **Steps:** 1) Go to `/finance/projects/<pk>/budget/`. 2) Enter `total_budget=-1`. 3) Submit. (Also POST `{"project": <id>, "total_budget": -1}` to `/api/project-budgets/`.)
- **Expected result (correct behavior):** a clean 400 with a field error. **Observed bug:** `ProjectBudgetForm` has no `clean()`; the model constraint raises `IntegrityError` → **HTTP 500** (HTML) and a 500/exception (API).
- **Evidence on failure:** 500 response; traceback shows `CheckConstraint` violation on `total_budget__gte=0`; no friendly message.

#### FIN-EC-08 — Negative total_investment → IntegrityError / HTTP 500 (no form/serializer validation)
- **Preconditions:** `admin` logged in. Project exists.
- **Steps:** 1) Go to `/finance/projects/<pk>/investment/`. 2) Enter `total_investment=-1`. 3) Submit. (Also POST `{"project": <id>, "total_investment": -1}` to `/api/project-investments/`.)
- **Expected result (correct behavior):** clean 400. **Observed bug:** model-only `gte=0` constraint → `IntegrityError` → **HTTP 500**.
- **Evidence on failure:** 500; traceback shows `total_investment__gte=0` violation.

#### FIN-EC-09 — Budget remaining goes negative (no guard)
- **Preconditions:** `admin` logged in. Project with `total_budget=100000.00`; add a paid cost of `150000.00`.
- **Steps:** 1) Go to `/finance/projects/`. 2) Inspect `remaining_budget`.
- **Expected result:** `remaining_budget = 100000.00 − 150000.00 = -50000.00` — allowed (no constraint) and rendered (ideally red). No crash.
- **Evidence on failure:** value clamped instead of negative, or page errors. Flag: product decision whether negative remaining should be blocked/clamped at entry.

#### FIN-EC-10 — Office delete guard exists only in the HTML view
- **Preconditions:** `management` user logged in. Office `OA` has one expense + one ledger row; office `OB` has none.
- **Steps:** 1) POST `/finance/offices/<OA.pk>/delete/`. 2) POST `/finance/offices/<OB.pk>/delete/`.
- **Expected result:** `OA` deletion refused with error message ("Cannot delete office … still has …"); `OB` deleted. **Observation:** the dependency guard (`office.expenses`/`office.transactions`) lives only in `office_delete_view` — no corresponding enforcement in DRF or admin (see FIN-SEC-02).
- **Evidence on failure:** `OA` deleted despite dependents; or `OB` blocked.

#### FIN-EC-11 — Zero amount rejected at all layers (defense-in-depth)
- **Preconditions:** `admin` logged in. Office + category exist.
- **Steps:** 1) HTML create expense with `amount=0`. 2) API `POST /api/office-expenses/` with `amount=0`. 3) API `POST /api/account-transactions/` with `amount=0`.
- **Expected result:** each returns a validation error (form `clean_amount` / serializer `validate_amount`; model `CheckConstraint amount__gt=0` as backstop). No row persisted, no 500.
- **Evidence on failure:** row persisted with 0, or a 500 instead of a 400.

#### FIN-EC-12 — Deleted category leaves expense.category=None and stale ledger category string
- **Preconditions:** `management` user logged in. Expense `EXP` has `category=CAT` and a ledger row with `category='<CAT.name>'`.
- **Steps:** 1) Delete `CAT` via `/finance/expense-categories/<pk>/delete/` (POST). 2) Inspect `EXP.category` and the ledger row.
- **Expected result:** `EXP.category` becomes `None` (FK SET_NULL); the ledger's denormalized `category` string is now stale (still shows the deleted name). Document as accepted/known.
- **Evidence on failure:** expense category FK points to a deleted id (if it errored), or ledger category not denormalized.

### SEC — negative & security

#### FIN-SEC-01 — Any authenticated staff can GET the finance API (leaks amounts) — contradicts HTML gate
- **Preconditions:** `sales` user (default role) logged in via session; at least one office expense, project cost, and account transaction exist (with `amount`, `description`, `paid_to`/`vendor`).
- **Steps:** 1) As `sales`, GET `/api/office-expenses/`. 2) GET `/api/project-costs/`. 3) GET `/api/account-transactions/`. 4) GET `/api/project-budgets/` and `/api/project-investments/`. 5) Repeat as `hr` and `staff`.
- **Expected result (correct behavior):** 403 — finance data is gated by `finance_or_above` on the HTML side and the `can_view_expenses` flag (`FINANCE_ROLES` only). **Observed bug:** `IsFinanceOrAbove.has_permission` returns `True` for all `SAFE_METHODS`, so GET returns **200** with full serialized amounts/descriptions.
- **Evidence on failure:** 200 response body contains `amount`, `description`, `paid_to`, `vendor`, `invoice_ref` for `sales`/`hr`/`staff` — sensitive data exposure. Capture role + endpoint + a redacted sample of the leaked fields.
- **Repro note (precise):** log in as a user whose `UserProfile.role='sales'` (or no profile), fetch `/auth/csrf/`, then GET any finance endpoint; observe 200 vs the expected 403.

#### FIN-SEC-02 — OfficeViewSet / admin DELETE has no guard (cascades expenses, bypasses HTML guard)
- **Preconditions:** `accounts` user (finance role; note HTML delete requires `management_or_above`) logged in via API session. Office `OA` has one `OfficeExpense` and one ledger row.
- **Steps:** 1) As `accounts`, `DELETE /api/offices/<OA.pk>/`. 2) Inspect `OfficeExpense` and `AccountTransaction` after.
- **Expected result (correct behavior):** delete should be refused (dependents exist) or at minimum management-only. **Observed bug:** `OfficeViewSet` is a plain `ModelViewSet` (no `destroy` override) → `DELETE` succeeds for any finance role, `CASCADE`-deletes `OA`'s expenses and `SET_NULL`s its ledger rows — the HTML dependency guard is bypassed. Django admin (`finance/admin.py`) also has no guard.
- **Evidence on failure:** 204 returned; office + its expenses gone; ledger rows orphaned (`office_id` set null). Capture office id and before/after counts.
- **Repro note (precise):** use `accounts` (below management) to prove both the role bypass and the missing dependency guard in one call.

#### FIN-SEC-03 — No status-transition guards on approve/pay (illegal draft→paid, paid→approved)
- **Preconditions:** `management` user logged in. Expense `D` is `draft` (no ledger row); expense `P` is `paid` (has ledger row).
- **Steps:** 1) POST `/finance/office-expenses/<D.pk>/pay/` (draft → paid directly). 2) POST `/finance/office-expenses/<P.pk>/approve/` (paid → approved demotion). 3) Repeat via API `POST /api/office-expenses/{id}/pay/` and `/approve/`.
- **Expected result (correct behavior):** transitions should be validated (`pay` only from `approved`; `approve` only from `pending`). **Observed bug:** no guard — `pay` jumps `draft → paid` (posts ledger), and `approve` demotes an already-`paid` expense back to `approved` (or `pending` via the HTML `action` param), leaving the ledger row in place.
- **Evidence on failure:** `D` becomes `paid` with a ledger row despite never being approved; `P` becomes `approved` while its ledger row remains (orphaned spend).

#### FIN-SEC-04 — Ledger integrity gaps misstate financial reports
- **Preconditions:** Reproduce at least one orphan (FIN-EC-01 or FIN-EC-02). Ledger has a phantom `out` row.
- **Steps:** 1) Go to `/finance/ledger/`. 2) Note `total_out`. 3) Recompute the sum from live source objects (paid expenses + paid costs).
- **Expected result (correct behavior):** `total_out` should reconcile to actual paid spend. **Observed bug:** orphaned rows (from demotion/deletion) inflate `total_out` and `project_finance_view` profit figures — financial reports misstate spend.
- **Evidence on failure:** `total_out` includes the orphaned `reference_type='ProjectCost'`/`'OfficeExpense'` row whose source object no longer exists or is not `paid`.

#### FIN-SEC-05 — Non-finance staff write to finance API → 403 (control assertion)
- **Preconditions:** `sales` user logged in via session.
- **Steps:** 1) `POST /api/office-expenses/` with a valid body. 2) `POST /api/project-costs/`. 3) `DELETE /api/offices/<id>/`.
- **Expected result:** 403 on all non-safe methods (this is the one path `IsFinanceOrAbove` enforces correctly).
- **Evidence on failure:** any 2xx/201/204 → write allowed for non-finance (regression).

#### FIN-SEC-06 — Non-finance staff denied finance HTML pages (redirect to /dashboard/)
- **Preconditions:** `sales` user logged in.
- **Steps:** 1) GET `/finance/ledger/`. 2) GET `/finance/offices/`. 3) GET `/finance/project-costs/`. 4) GET `/finance/projects/`.
- **Expected result:** each redirects to `/dashboard/` with a permission-denied message (decorator `finance_or_above`).
- **Evidence on failure:** any page renders with data (leak) or 500s instead of redirecting.

### API — API contract

#### FIN-API-01 — GET /api/office-expenses/ list + filters
- **Preconditions:** `admin` session-auth. Two expenses in different offices/statuses exist.
- **Steps:** 1) GET `/api/office-expenses/`. 2) GET `?office=<id>`. 3) GET `?status=paid`.
- **Expected result:** 200; list includes `office_name`, `category_name`, `status_display`; filters narrow by `office_id` and `status` respectively. Amounts are Decimal strings with 2 places.
- **Evidence on failure:** wrong/missing `*_display`/`*_name` fields; filter returns unfiltered rows; 500.

#### FIN-API-02 — POST /api/office-expenses/ (finance) + status=paid posts ledger
- **Preconditions:** `admin` session-auth with CSRF token. Office + category ids known.
- **Steps:** 1) POST body `{office, category, amount: "25000.00", expense_date: "<today>", status: "paid"}`. 2) Inspect ledger.
- **Expected result:** 201; `created_by` set; exactly one ledger row via `perform_create` (`status=='paid'` → `post_to_ledger()`).
- **Evidence on failure:** no ledger row; 400 for `amount<=0`; `created_by` null.

#### FIN-API-03 — POST /api/office-expenses/{id}/approve/
- **Preconditions:** `management`-role user (or admin) session-auth. A `pending` expense exists.
- **Steps:** 1) POST `/api/office-expenses/<id>/approve/`.
- **Expected result:** 200; `status='approved'`, `approved_by=<user>`; **no** ledger row posted. (Correct behavior would also reject approving a non-`pending` expense — currently absent; see FIN-SEC-03.)
- **Evidence on failure:** status unchanged; ledger row posted (wrong); `approved_by` null.

#### FIN-API-04 — POST /api/office-expenses/{id}/pay/ (posts ledger, idempotent)
- **Preconditions:** `management`-role user session-auth. An `approved` expense exists.
- **Steps:** 1) POST `/api/office-expenses/<id>/pay/`. 2) POST again.
- **Expected result:** 200; `status='paid'`; exactly one ledger row after step 1, still one after step 2 (`post_to_ledger` idempotent).
- **Evidence on failure:** two ledger rows; status not `paid`.

#### FIN-API-05 — GET/POST /api/project-costs/
- **Preconditions:** `admin` session-auth. Project id known.
- **Steps:** 1) GET `/api/project-costs/` and `?project=<id>`/`?category=material`. 2) POST `{project, cost_category:"material", amount:"40000.00", cost_date:"<today>", status:"paid"}`.
- **Expected result:** GET 200 with `project_name`, `cost_category_display`, `status_display`; filters narrow. POST 201 + exactly one ledger row (`reference_type='ProjectCost'`) when `status='paid'`.
- **Evidence on failure:** missing display fields; filter ignored; no ledger row; 400 on `amount<=0` misreported.

#### FIN-API-06 — GET/POST/DELETE /api/offices/
- **Preconditions:** `admin` session-auth.
- **Steps:** 1) GET `/api/offices/`. 2) POST `{name:"QA-HO-<epoch>", office_type:"head_office"}`. 3) DELETE `/api/offices/<id>/` on an office **with** expenses.
- **Expected result:** GET 200; POST 201 (duplicate `name` → 400); DELETE on a dependent office **should** be refused/guarded — **observed bug:** 204 with cascade (see FIN-SEC-02).
- **Evidence on failure:** DELETE returns 204 and removes dependents; POST duplicate not rejected.

#### FIN-API-07 — GET/POST /api/account-transactions/ (direction validation + filters)
- **Preconditions:** `admin` session-auth.
- **Steps:** 1) GET with `?transaction_type=office_expense` / `?direction=out` / `?date_from=&date_to=`. 2) POST `{date, amount:"1000.00", direction:"in", transaction_type:"salary"}`. 3) POST with `direction:"sideways"`.
- **Expected result:** GET 200 filtered correctly. POST 201 for valid body; POST with invalid `direction` → 400 (`validate_direction`); `amount<=0` → 400.
- **Evidence on failure:** filter ignored; invalid `direction` accepted; `amount<=0` accepted.

#### FIN-API-08 — GET/POST /api/project-budgets/ (negative total_budget → 500)
- **Preconditions:** `admin` session-auth. Project id known.
- **Steps:** 1) GET `/api/project-budgets/` (verify read-only `total_actual`, `remaining_budget` present). 2) POST `{project, total_budget:"100000.00"}` → 201. 3) POST `{project, total_budget:"-1"}`.
- **Expected result (correct):** negative → 400. **Observed bug:** `ProjectBudgetSerializer` has no `validate_total_budget` → `IntegrityError` → **500**.
- **Evidence on failure:** 500 traceback on the `total_budget__gte=0` CheckConstraint.

#### FIN-API-09 — GET/POST /api/project-investments/ (negative → 500)
- **Preconditions:** `admin` session-auth. Project id known.
- **Steps:** 1) GET `/api/project-investments/`. 2) POST `{project, total_investment:"1500000.00"}` → 201. 3) POST `{project, total_investment:"-1"}`.
- **Expected result (correct):** negative → 400. **Observed bug:** no `validate_total_investment` → `IntegrityError` → **500**.
- **Evidence on failure:** 500 traceback on the `total_investment__gte=0` CheckConstraint.

## 4. Data isolation rules

- **Unique names:** `Office.name` and `ExpenseCategory.name` are DB-unique — every scenario uses a fresh `QA-…-<epoch>` name. Never reuse across scenarios.
- **Ledger uniqueness:** `AccountTransaction` is unique on `(reference_type, reference_id)` when `reference_id` is set — always create a fresh source object (expense/cost) per scenario so `reference_id` never collides.
- **Projects:** create a fresh `QA-Proj-<epoch>` per scenario needing a project (Project requires `location`).
- **Cleanup:** orphan- and 500-scenarios must not leave negative-budget/investment rows or phantom ledger rows that other scenarios could sum into `total_in`/`total_out`. Delete created `QA-*` objects (and any orphaned `AccountTransaction` rows) at scenario teardown.
- **Roles:** assign an explicit `UserProfile.role` for `sales`/`hr`/`staff`/`accounts`/`management` users; do not rely on the default except to verify the default is `sales`.

## 5. Coverage checklist

- FIN-HP-01 — Create office
- FIN-HP-02 — Create office expense with status "paid" posts exactly one ledger row (create-time posting)
- FIN-HP-03 — Approve then Pay office expense posts ledger exactly once (idempotent)
- FIN-HP-04 — Create project cost (default "paid") posts ledger immediately
- FIN-HP-05 — Project budget: remaining = total − paid costs
- FIN-HP-06 — Project investment recorded and shown
- FIN-HP-07 — Ledger list: totals and filters
- FIN-EC-01 — Status demotion orphans the ledger (paid → draft leaves the row)
- FIN-EC-02 — Delete paid ProjectCost leaves orphaned AccountTransaction
- FIN-EC-03 — Editing a paid office expense re-dates/re-amounts the historical ledger row
- FIN-EC-04 — Editing a paid project cost re-dates/re-amounts the historical ledger row
- FIN-EC-05 — Approval bypass: accounts user creates an already-paid office expense (posts ledger without management gate)
- FIN-EC-06 — Approval bypass: project cost defaults to paid and posts to ledger without management gate
- FIN-EC-07 — Negative total_budget → IntegrityError / HTTP 500 (no form/serializer validation)
- FIN-EC-08 — Negative total_investment → IntegrityError / HTTP 500 (no form/serializer validation)
- FIN-EC-09 — Budget remaining goes negative (no guard)
- FIN-EC-10 — Office delete guard exists only in the HTML view
- FIN-EC-11 — Zero amount rejected at all layers (defense-in-depth)
- FIN-EC-12 — Deleted category leaves expense.category=None and stale ledger category string
- FIN-SEC-01 — Any authenticated staff can GET the finance API (leaks amounts) — contradicts HTML gate
- FIN-SEC-02 — OfficeViewSet / admin DELETE has no guard (cascades expenses, bypasses HTML guard)
- FIN-SEC-03 — No status-transition guards on approve/pay (illegal draft→paid, paid→approved)
- FIN-SEC-04 — Ledger integrity gaps misstate financial reports
- FIN-SEC-05 — Non-finance staff write to finance API → 403 (control assertion)
- FIN-SEC-06 — Non-finance staff denied finance HTML pages (redirect to /dashboard/)
- FIN-API-01 — GET /api/office-expenses/ list + filters
- FIN-API-02 — POST /api/office-expenses/ (finance) + status=paid posts ledger
- FIN-API-03 — POST /api/office-expenses/{id}/approve/
- FIN-API-04 — POST /api/office-expenses/{id}/pay/ (posts ledger, idempotent)
- FIN-API-05 — GET/POST /api/project-costs/
- FIN-API-06 — GET/POST/DELETE /api/offices/
- FIN-API-07 — GET/POST /api/account-transactions/ (direction validation + filters)
- FIN-API-08 — GET/POST /api/project-budgets/ (negative total_budget → 500)
- FIN-API-09 — GET/POST /api/project-investments/ (negative → 500)
