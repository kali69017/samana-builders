# Finance Module — QA Analysis

> Module: `finance` (unified ledger + office expenses + project costs/budget/investment).
> Read with `docs/qa/_shared-context.md` (roles, permission groups, money/Decimal, invariants).

## 1. Business purpose & user journeys

The finance module is the company's **unified money-out ledger**. Every expense, project
cost, contractor payment, payroll run and refund writes an `AccountTransaction` row so
reporting has a single source of truth (`finance/models.py:1-7`). Alongside the ledger it
holds the office hierarchy (`Office`), office expense categories (`ExpenseCategory`), office
expenses (`OfficeExpense`), project construction costs (`ProjectCost`), per-project budgets
(`ProjectBudget`) and manual investment figures (`ProjectInvestment`).

Real user journeys (role in parentheses):

- **(accounts / admin / management)** Login → Finance → Offices → Add Office → fill name/type/address → Office appears in the list (`offices_view`).
- **(accounts)** Login → Finance → Company Expenses → Add Expense → pick office/category/amount/date → expense saved as `pending` → awaits approval (`office_expense_create_view`).
- **(management)** Login → Finance → Company Expenses → Approve (pending expense) → then Pay → expense posts to the ledger once (`office_expense_approve_view`, `office_expense_pay_view`).
- **(accounts)** Login → Finance → Project Costs → Add Cost → pick project/category/amount → cost defaults to `paid` and posts to ledger immediately (`project_cost_create_view`).
- **(accounts)** Login → Finance → Project Investment & Finance → Budget / Investment button → set per-project numbers → view shows costs, remaining, revenue, profit/loss (`project_finance_view`).
- **(accounts / admin)** Login → Finance → Ledger → filter by type → see total in/out and every transaction (`ledger_view`).

## 2. Data model

### AccountTransaction (ledger) — `finance/models.py:12-79`
- Fields: `date` (DateField, required), `amount` (Decimal 15,2, required), `direction` (`in`/`out`, default `out`), `transaction_type` (7 choices), `category` (Char 100, blank), `reference_type` (Char 50, blank), `reference_id` (PositiveIntegerField, null/blank), `employee`/`project`/`office` (FKs, all `SET_NULL`, null/blank), `description` (Text, blank), `created_by` (FK User, SET_NULL), `created_at` (auto_now_add).
- Constraints: `amount__gt=0` (CheckConstraint, `models.py:65-68`); unique on `(reference_type, reference_id)` **only when `reference_id` is not null** (`models.py:69-78`). NULL `reference_id` (ad-hoc entries) is intentionally exempt from de-dup.
- Indexes on `transaction_type`, `date`, `direction` (`models.py:59-63`). `Meta.ordering = ['-date', '-created_at']` (`models.py:58`).
- **No running-balance column.** This is a journal, not a balance ledger — see §5.

### Office — `models.py:82-97`
`name` (Char 150, **unique**), `office_type` (`head_office`/`branch`), `address` (Text, blank), `is_active` (bool). Ordering `['office_type','name']`.

### ExpenseCategory — `models.py:100-120`
`name` (Char 100, **unique**), `category_type` (7 choices), `is_active`. Ordering `['category_type','name']`.

### OfficeExpense — `models.py:123-177`
- `office` (FK **CASCADE**, related `expenses`), `category` (FK **SET_NULL**, null), `amount` (Decimal 15,2), `expense_date`, `paid_to` (blank), `payment_method` (4 choices), `status` (choices `draft/pending/approved/paid`, default `pending`), `approved_by` (FK User, SET_NULL), `description`, `created_by` (FK User, SET_NULL, related `office_expenses_created`), `created_at`, `updated_at`.
- Constraint `amount__gt=0` (`models.py:172-177`). Index `(office, expense_date)`.
- `post_to_ledger()` (`models.py:154-167`): `AccountTransaction.objects.update_or_create(reference_type='OfficeExpense', reference_id=self.pk, defaults={date=expense_date, amount, direction='out', transaction_type='office_expense', category=category.name or 'Office Expense', office, description, created_by})`.
- **`STATUS_CHOICES` has NO `rejected`** — unlike the sibling `expenses` app (per CLAUDE.md). No rejection path.

### ProjectBudget — `models.py:180-207`
OneToOne `project` (CASCADE, related `budget`), `total_budget` + five component budgets (all Decimal 15,2, default 0), `updated_at`.
- `total_actual` property = `sum(c.amount for c in project.costs.filter(status='paid'))` (`models.py:193-195`).
- `remaining_budget` property = `total_budget - total_actual` (`models.py:197-199`) — **may go negative**, no constraint.
- Constraint `total_budget__gte=0` only (`models.py:202-206`). Component budgets are unconstrained (can be negative, can exceed total).

### ProjectCost — `models.py:210-263`
`project` (FK CASCADE, related `costs`), `cost_category` (5 choices), `amount` (Decimal 15,2), `cost_date`, `vendor`/`invoice_ref` (blank), `status` (choices `draft/approved/paid`, **default `paid`**), `description`, `created_by`/`created_at`/`updated_at`.
- `post_to_ledger()` (`models.py:240-253`) mirrors OfficeExpense with `reference_type='ProjectCost'`.
- Constraint `amount__gt=0` (`models.py:258-263`). Index `(project, cost_category)`.

### ProjectInvestment — `models.py:266-282`
OneToOne `project` (CASCADE, related `investment`), `total_investment` (Decimal 15,2, default 0), `notes`, `updated_at`. Constraint `total_investment__gte=0` (`models.py:274-279`).

## 3. Roles & permissions

| Action | Allowed role(s) | Enforced by |
|---|---|---|
| View office/expense/cost/ledger/budget pages (HTML) | super_admin, admin, management, accounts | `@finance_or_above` (`finance/views.py:34,100,150,171,190,236,256,306,329,346,364,380`) |
| Create/edit office, category, expense, cost | finance roles | `@finance_or_above` (`views.py:42,57,107,122,171,190,256,275`) |
| Delete office | management roles | `@management_or_above` (`views.py:72`) + dependency guard (`views.py:78-90`) |
| Delete expense category / project cost | management roles | `@management_or_above` (`views.py:137,292`) |
| Approve / Pay office expense | management roles | `@management_or_above` (`views.py:208,222`) |
| API write (POST/PUT/PATCH/DELETE) | finance roles or superuser | `IsFinanceOrAbove` (`api_views.py:15-25`) |
| **API read (GET/HEAD/OPTIONS)** | **any authenticated staff** | `IsFinanceOrAbove` returns `True` for `SAFE_METHODS` (`api_views.py:20-21`) |

**Inconsistency / IDOR-adjacent gap:** the DRF `IsFinanceOrAbove` grants READ access to
**every authenticated user** (including `sales`, `hr`, `project_manager`, `contractor`,
`staff`) for all finance ViewSets — `AccountTransaction`, `Office`, `ExpenseCategory`,
`OfficeExpense`, `ProjectCost`, `ProjectBudget`, `ProjectInvestment` (`api_views.py:20-21`).
The HTML views require `finance_or_above` for the same data (`views.py:34` etc.), and the
template flag `can_view_expenses` is `FINANCE_ROLES`-only (`_shared-context.md`). So the UI
hides finance from non-finance roles but the API leaks amounts/descriptions to them. This is
a real sensitive-data exposure + permission inconsistency. See §6.

**Object-level gating:** none, and none is strictly needed — finance data is company-global,
not per-user. The residual risk is the role-elevation above, not classic cross-tenant IDOR.

**Note:** `OfficeViewSet` / `ProjectCostViewSet` are plain `ModelViewSet`s — they expose
`DELETE` with **no** dependency guard (the guard lives only in the HTML view). See §5/§6.

## 4. Business rules, state machines, invariants

### OfficeExpense status machine
`draft → pending → approved → paid` (no `rejected`). Default `pending`.

- Approve (HTML) sets `approved` (or back to `pending` if `action != 'approve'`) and stamps `approved_by` (`views.py:210-215`).
- Pay (HTML) sets `paid` and posts ledger (`views.py:223-229`).
- API `approve` action sets `approved` (`api_views.py:82-88`); `pay` action sets `paid` + posts (`api_views.py:90-96`).

**Illegal transitions are NOT prevented.** `pay` can jump `draft → paid` directly; `approve`
can be called on an already-`paid` expense and demote it back to `approved` (or `pending` via
the HTML `action` param). No guard checks the current status in either surface.

### ProjectCost status machine
`draft → approved → paid`, default `paid`. There are **no approve/pay views/actions** —
status is changed only through the create/edit form (`status` is a form field,
`forms.py:59`). Create with default `paid` posts to ledger immediately
(`views.py:260-264`, `api_views.py:114-117`).

### Ledger invariants
- One ledger row per source object: enforced by `update_or_create` (`models.py:155,241`) and the conditional unique constraint (`models.py:69-78`). Idempotent.
- Amounts must be > 0 at three layers: model CheckConstraint, form `clean_amount`, serializer `validate_amount`.
- `direction` validated to `in`/`out` in the serializer only (`serializers.py:18-21`); the model has no constraint on `direction`.

### Budget / investment invariants
- `remaining_budget = total_budget - total_actual(paid costs)`; may be negative (allowed, rendered red).
- `total_budget ≥ 0` and `total_investment ≥ 0` via CheckConstraint only — **no form/serializer validation**, so negatives 500 instead of a clean error (§5).
- Component budgets (material/labor/…) have **no** non-negativity or sum ≤ total constraint.

### Side effects
- Ledger post on: expense/cost create when `status == 'paid'`; expense/cost edit when `status == 'paid'`; expense `pay` action/view.
- AuditLog written on create/update/delete via `_log` (`views.py:24-29`) for every HTML mutation.
- No notifications are sent from this module.

## 5. Edge cases (go deep)

- **Double-post (idempotency):** `update_or_create` on `(reference_type, reference_id)` means repeated `post_to_ledger()` / `pay` / duplicate POSTs do not create a second row — the existing row is updated (`models.py:155,241`). Verified path exists; no test asserts the "no duplicate" property directly, only "a row exists" (`tests.py:26-43,70-90`).
- **Out-of-order / running balance:** there is **no running balance** at all — the ledger is a journal ordered `-date, -created_at` (`models.py:58`); `ledger_view` only shows `total_in`/`total_out` sums (`views.py:372-373`). An entry backdated to a prior date just re-sorts; no balance is corrupted because none is stored. There is also no opening balance or reconciliation notion.
- **Re-date / re-amount a paid record:** editing a paid expense/cost updates the ledger row's `amount`, `date`, `category`, `description` via `update_or_create` (`views.py:195-197,280-282`). This silently rewrites the historical ledger row (retroactive re-dating/amount change) with only a generic AuditLog on the object, not the ledger delta. No immutability for paid transactions.
- **Status demotion orphans the ledger:** the edit form includes `status` (`forms.py:31-32,59`). Editing a `paid` expense/cost to `draft`/`pending`/`approved` keeps the ledger row (nothing deletes it on demotion), leaving a "not paid" object with money already booked out. Same result if `approve` demotes a paid expense back to `approved`/`pending` (`views.py:210-215`).
- **Delete a paid project cost orphans the ledger:** `project_cost_delete_view` deletes the `ProjectCost` (`views.py:296`) but never removes the matching `AccountTransaction`. `reference_id` is a plain integer (no FK), so no cascade. Ledger shows phantom spend. (There is no office-expense delete view at all.)
- **Delete office bypass:** the dependency guard (`views.py:78-90`) lives only in the HTML view. `OfficeViewSet.destroy` (DRF, no override) will `CASCADE`-delete the office's `OfficeExpense`s and `SET_NULL` its ledger rows with no guard (`api_views.py:50-53`), and the Django admin (`admin.py:16-20`) has no guard either. TOCTOU race also exists between `exists()` check and `delete()` in the HTML view.
- **Approval bypass via status field:** create/edit forms expose `status`, so an `accounts` user (finance role, but below `management`) can create an expense/cost already `paid` (ProjectCost defaults to `paid`, `models.py:231`) and post it to the ledger without management approval (`views.py:178-179,263-264`; `api_views.py:77-80,114-117`). The approve/pay gate is optional.
- **Zero / negative amounts:** `0` and negative are rejected by model CheckConstraint + form `clean_amount` + serializer `validate_amount` for expense/cost/transaction (`models.py:65-68,172-177,258-263`; `forms.py:49-53,78-82`; `serializers.py:13-16,62-65,80-83`). Tested for zero (`tests.py:78-82`).
- **Negative budget / investment:** model-only `gte=0` constraint, no form/serializer validation → an HTML or API submit of a negative budget/investment raises `IntegrityError` → **HTTP 500** instead of a friendly 400 (`forms.py:85-107`, `serializers.py:86-105`). Component budgets have no validation at all.
- **Nonexistent office/project/category:** form/API `office`/`project`/`category` are FK-backed — invalid IDs fail form validation (400) or 404 via `get_object_or_404` in pk views. `category` is SET_NULL so a deleted category silently leaves expense `category=None` and the ledger's denormalized `category` string stale (`models.py:139`).
- **Money precision:** all monetary fields are `DecimalField(15,2)`. Storage is exact. Templates render with `floatformat:0` (integer display) on amounts and totals (`office_expenses.html:63`, `ledger.html:48`, `project_finance.html:56-61`), so row displays round and may not visibly sum to the rounded total — display-only, no data corruption.
- **Date/fiscal boundaries:** the expense report parses `YYYY-MM` by slicing `month[:4]`/`month[5:7]` with a try/except fallback to today (`views.py:381-385`). Empty string → falls back; an out-of-range month like `2026-13` yields an empty result set (no crash).
- **Wrong verb / CSRF on state changes:** all state-changing HTML endpoints gate on `request.method == 'POST'` (`views.py:75,210,224,295,140`) and templates include `{% csrf_token %}` (`base_form.html:41`, `confirm_delete.html:36`, `offices.html:35`, `office_expenses.html:69,72`). No `@csrf_exempt` in the module. GET to delete/approve/pay just redirects. Sound.

## 6. Cross-cutting risks

- **Sensitive data exposure (HIGH):** `IsFinanceOrAbove` permits any authenticated staff to GET all finance endpoints (`api_views.py:20-21`). Amounts, `description`, `paid_to`, `vendor`, `invoice_ref` (via `ProjectCostSerializer`/`OfficeExpenseSerializer`, `serializers.py:50-83`) are readable by `sales`/`hr`/`staff`, contradicting the HTML `finance_or_above` gate and the `can_view_expenses` template flag.
- **XSS (LOW):** all user content (`description`, `notes`, `address`, `vendor`, `paid_to`, `invoice_ref`, `name`) is rendered with Django auto-escaping; no `|safe` / `mark_safe` / `innerHTML` appears in any finance template or the shared `confirm_delete.html` (`{{ object }}` is escaped). Residual risk only if a future template adds `|safe`.
- **CSRF (LOW):** tokens present on every POST form; state changes are POST-only; DRF `SessionAuthentication` enforces CSRF on the non-safe `approve`/`pay` actions. No `@csrf_exempt`.
- **IDOR / broken object-level authorization (MEDIUM for role elevation, LOW otherwise):** no per-user ownership exists (global data), but the API read-all for any staff is a role-bypass data leak; and `OfficeViewSet` DELETE bypasses the office-deletion guard.
- **Ledger integrity (MEDIUM):** orphaned ledger rows on status demotion and on project-cost deletion; retroactive rewrite of paid transactions on edit; approval bypass posts to ledger without a management gate.
- **Accessibility (LOW):** shared `base_form.html` renders labels for most fields, but the `textarea`/input floating-group pattern in `base_form.html:77-103` is fine; filters use `<select>`/`<input type="month">` without visible `<label>`s on `office_expense_report.html` and list filter bars. Not tab-keyboard-trapped. No finance-specific a11y regression.

## 7. API surface

All under `/api/...` via DRF `DefaultRouter` (`api/urls.py:85-91`). Permission: `IsFinanceOrAbove` (read = any authenticated; write = finance/superuser).

| Method + path | ViewSet | Write permission | Notable request fields | Response / validation |
|---|---|---|---|---|
| GET/POST `/api/account-transactions/` | `AccountTransactionViewSet` | finance | `date`, `amount`, `direction`, `transaction_type`, `category`, `reference_type`, `reference_id`, `employee`, `project`, `office`, `description` | `amount>0`, `direction in/out` validated; filters `transaction_type/direction/date_from/date_to` |
| GET/POST/PUT/PATCH/DELETE `/api/offices/` | `OfficeViewSet` | finance | `name`, `office_type`, `address`, `is_active` | **no delete guard** |
| GET/POST/PUT/PATCH/DELETE `/api/expense-categories/` | `ExpenseCategoryViewSet` | finance | `name`, `category_type`, `is_active` | |
| GET/POST/PUT/PATCH/DELETE `/api/office-expenses/` | `OfficeExpenseViewSet` | finance | `office`, `category`, `amount`, `expense_date`, `paid_to`, `payment_method`, `status`, `description` | `amount>0`; `perform_create` posts ledger if `status=='paid'`; filters `office/status` |
| POST `/api/office-expenses/{id}/approve/` | `OfficeExpenseViewSet.approve` | finance | — | sets `approved`, stamps `approved_by`; **no transition guard** |
| POST `/api/office-expenses/{id}/pay/` | `OfficeExpenseViewSet.pay` | finance | — | sets `paid` + posts ledger; **no transition guard** |
| GET/POST/PUT/PATCH/DELETE `/api/project-costs/` | `ProjectCostViewSet` | finance | `project`, `cost_category`, `amount`, `cost_date`, `vendor`, `invoice_ref`, `status`, `description` | `amount>0`; `perform_create` posts ledger if `status=='paid'`; filters `project/category` |
| GET/POST/PUT/PATCH/DELETE `/api/project-budgets/` | `ProjectBudgetViewSet` | finance | `project`, `total_budget` + components | read-only `total_actual`, `remaining_budget`; **negative total_budget → 500** |
| GET/POST/PUT/PATCH/DELETE `/api/project-investments/` | `ProjectInvestmentViewSet` | finance | `project`, `total_investment`, `notes` | **negative → 500** |

Serializer validation gaps: `ProjectBudgetSerializer`/`ProjectInvestmentSerializer` have no `validate_total_budget`/`validate_total_investment`; `OfficeExpenseSerializer`/`ProjectCostSerializer`/`AccountTransactionSerializer` validate only `amount` (+ `direction`), not `status` transitions.

## 8. Test data & fixtures needed

- **Roles:** need a superuser/admin for happy paths and a `sales` (or `hr`) `UserProfile` to prove the API read leak and write-403 (`tests.py:105-112` already covers write-403, not read-200-for-sales).
- **Seed records:** `Office` (`Head Office`), `ExpenseCategory` (`Rent`), `Project` (needs `location` — `tests.py:24`), optionally `Bookings`/`plots` for the project-finance revenue figure.
- **Uniqueness/isolation:** `Office.name` and `ExpenseCategory.name` are unique (`models.py:88,111`) — use timestamped/unique names. Ledger unique on `(reference_type, reference_id)` only when `reference_id` set; use fresh source objects per test to avoid collisions.
- **Recommended new tests (gap list):** ledger no-duplicate on double `post_to_ledger()`; ledger orphan on `ProjectCost` delete; ledger orphan on paid→draft demotion; negative budget/investment returns 400 (not 500); `sales` role GET finance API returns 403 (currently returns 200); office delete guard blocks (and API delete does **not** block); approve/pay illegal transitions.

## 9. Key files (for traceability)

- `finance/models.py` — 7 models; ledger unique/positive constraints; `post_to_ledger()`; budget properties.
- `finance/forms.py` — `OfficeExpenseForm`/`ProjectCostForm` expose `status` and validate `amount>0`; budget/investment forms have no `clean()`.
- `finance/serializers.py` — serializers with `amount`/`direction` validation only; budget/investment lack validation.
- `finance/api_views.py` — `IsFinanceOrAbove` (SAFE_METHODS leak); ViewSets incl. `approve`/`pay` actions (no transition guards).
- `finance/views.py` — HTML views; office deletion guard; approval/pay; ledger; report.
- `finance/urls.py` — URL map (`/finance/...`).
- `finance/admin.py` — admin registrations (no delete guard for Office).
- `finance/tests.py` — 12 tests (model + API), no duplicate/delete/demotion/permission-read coverage.
- `finance/migrations/0003` & `0004` — the CHECK + unique constraints are actually migrated.
- `finance/management/commands/seed_finance.py` — default office + 7 categories.
- `templates/finance/*.html` (13 files) — list/form/report templates; no `|safe`.
- `templates/base_form.html`, `templates/confirm_delete.html` — shared form/delete templates (CSRF, escaping).
- `api/urls.py:85-91`, `samana_erp/urls.py:89` — router registration and URL include.
