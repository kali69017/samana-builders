# Expenses Module — QA Analysis

> Deep module analysis for the `expenses` app. Read with
> `docs/qa/_shared-context.md` (roles/permissions/URLs are not re-derived here).
> Status of findings reflects code at 2026-09-13.

---

## 1. Business purpose & user journeys

The `expenses` module tracks **company / project overhead expenses** — day-to-day
running costs (marketing, admin, utilities, procurement, miscellaneous) that are
each linked to a `Project`. It is deliberately distinct from `finance.ProjectCost`
(construction costs against a budget) and `finance.OfficeExpense` (physical office
running costs); the list page carries a user-guide call-out making this distinction
explicit (`templates/expenses.html:24-40`).

The module's real substance is the **approval workflow**: an expense is recorded as
`pending`, then approved (which posts it to the unified financial ledger) and later
marked `paid`, or rejected. Expenses are **web-only** — there is no DRF ViewSet or
serializer for `Expense` (confirmed by `api/tests_audit_money.py:370-371` "Expenses
are web-only (no API viewset)" and the absence of `expenses/serializers.py` /
`api_views.py`).

Real user journeys (all restricted to `finance_or_above` = super_admin, admin,
management, accounts):

- **Accounts clerk records an expense** — `/expenses/create/` → fills project,
  description, amount, type, paid-to, date, optional payment reference + receipt →
  saved as `pending` with `created_by` stamped and an AuditLog `create` entry
  (`expenses/views.py:77-93`).
- **Manager approves** — from the list or detail page POSTs `/expenses/<pk>/approve/`
  → status `approved`, `approved_by`/`approved_at` stamped, posted to ledger exactly
  once, AuditLog `verify` entry (`expenses/views.py:116-138`).
- **Accounts marks paid** — POSTs `/expenses/<pk>/mark-paid/` → status `paid`, ledger
  (idempotent) re-post, AuditLog entry (`expenses/views.py:141-164`).
- **Manager rejects** — POSTs `/expenses/<pk>/reject/` → status `rejected`
  (`expenses/views.py:167-178`).
- **Finance reviews the dashboard** — `/expenses/` totals by month, by type, and a
  revenue-vs-expense per-project bar chart (`expenses/views.py:25-74`).

---

## 2. Data model

Single model: `Expense` (`expenses/models.py:6-105`).

| Field | Type | null/blank | Default | Notes |
|---|---|---|---|---|
| `project` | FK `properties.Project` | — | — | `on_delete=CASCADE`, `related_name='expenses'` (`models.py:20-23`) |
| `description` | `TextField` | not blank | — | required (`models.py:24`) |
| `amount` | `DecimalField(15,2)` | — | — | `CheckConstraint amount__gt=0` (`models.py:25`, `100-105`) |
| `expense_type` | `CharField(20)` choices | — | `'internal'` | `EXPENSE_TYPES` internal/external/miscellaneous (`models.py:7-11,26`) |
| `paid_to` | `CharField(200)` | blank | — | vendor free-text (`models.py:27`) |
| `expense_date` | `DateField` | — | `timezone.localdate` | (`models.py:28`) |
| `created_by` | FK `User` | null | — | `SET_NULL`, `expenses_created` (`models.py:29`) |
| `created_at` / `updated_at` | `DateTimeField` auto | — | — | (`models.py:30-31`) |
| `payment_reference` | `CharField(100)` | blank | — | cheque/bank ref (`models.py:34-38`) |
| `receipt_attachment` | **`FileField`** | blank/null | — | `upload_to='expenses/receipts/'` (`models.py:39-43`) |
| `status` | `CharField(20)` choices | — | `'pending'` | `db_index=True` (`models.py:44-47`) |
| `approved_by` | FK `User` | null/blank | — | `SET_NULL`, `expenses_approved` (`models.py:48-51`) |
| `approved_at` | `DateTimeField` | null/blank | — | (`models.py:52`) |

- **Status choices**: `pending` → `approved` → `paid` / `rejected`
  (`STATUS_CHOICES`, `models.py:13-18`).
- **No `clean()` / model-level `full_clean` override.** Amount positivity is enforced
  only by the DB `CheckConstraint` (`models.py:100-105`) and surfaced to the form by
  Django's automatic `validate_constraints()` (see §5).
- **Methods**:
  - `status_label` property → `get_status_display()` (`models.py:57-59`).
  - `can_be_posted()` (`models.py:61-63`) — **dead code** (never called by any view);
    also contains a redundant clause: `status in ('approved','paid') and not status ==
    'rejected'` — the second conjunct can never be false when the first is true.
  - `post_to_ledger(user=None)` (`models.py:65-87`) — idempotent
    `AccountTransaction.update_or_create(reference_type='Expense', reference_id=pk)`;
    writes `direction='out'`, `transaction_type='project_cost'`.
  - `is_posted_to_ledger()` (`models.py:89-93`) — **dead code** (no view calls it).
- **Meta**: ordering `['-expense_date','-created_at']`; index `(project, expense_date)`
  (`models.py:95-99`).

---

## 3. Roles & permissions

| Action | Allowed roles | Enforced by |
|---|---|---|
| List / dashboard | super_admin, admin, management, accounts | `@finance_or_above` (`expenses/views.py:26`); sidebar link gated by `can_view_expenses` (`includes/sidebar.html:47`) |
| Create | same | `@finance_or_above` (`expenses/views.py:78`) |
| Edit | same (locked by status at runtime) | `@finance_or_above` (`expenses/views.py:97`) |
| Approve | same | `@finance_or_above` (`expenses/views.py:117`) |
| Mark paid | same | `@finance_or_above` (`expenses/views.py:142`) |
| Reject | same | `@finance_or_above` (`expenses/views.py:168`) |
| Detail | same | `@finance_or_above` (`expenses/views.py:192`) |
| Delete | same | `@finance_or_above` (`expenses/views.py:192` → `expense_delete_view`) |

- `finance_or_above` = `FINANCE_ROLES` (super_admin, admin, management, accounts)
  (`core/permissions.py:131-146`); unauthenticated → redirect `/login/`; superuser
  always allowed.
- **No object-level / ownership gating anywhere.** Every view uses
  `get_object_or_404(Expense, pk=pk)` with no check that the caller owns the record.
  This is consistent with the ERP's global-role model (expenses are not per-user
  scoped; `created_by` is informational and `SET_NULL`), so it is low-severity, but
  there is **no separation between recording and approving** — any `accounts` user can
  approve/pay their own recorded expense. Noted as an IDOR-shaped gap (§6).
- **Template flag vs view consistency is correct**: sidebar hides "Expenses" for
  non-finance roles and the views independently enforce `finance_or_above`, so the
  UI-hides-but-view-unguarded pattern does **not** apply here.
- **Missing role distinction**: `delete` is gated only by `finance_or_above`, but
  `expense_delete_view` has **no status guard** — a paid/approved expense that has
  already posted to the ledger can be deleted (see §4/§6).

---

## 4. Business rules, state machines, invariants

### State machine (`status`)

Legal transitions as implemented:

```
pending ──approve──▶ approved ──mark-paid──▶ paid
   │                    │
   │ mark-paid          │ reject (ALLOWED)
   │ (one-step)         ▼
   ▼                 rejected
 paid ◀─────────────────┘
pending ──reject──▶ rejected
```

- `expense_approve_view` blocks `paid` and `rejected` (`views.py:120-125`) but **does
  not block re-approving an already-`approved` expense** — a second approve re-stamps
  `approved_by`/`approved_at` and appends a second AuditLog entry (ledger is safe via
  `update_or_create`). Reachable only via direct URL replay/double-click, since the
  UI hides Approve unless `status == 'pending'` (`expenses.html:165`).
- `expense_mark_paid_view` blocks only `rejected` (`views.py:145-147`). It implements
  the documented **one-step approve+pay** when called on a `pending` expense
  (`views.py:149-156`). Calling it on an already-`paid` expense is idempotent for the
  ledger but adds a duplicate AuditLog.
- `expense_reject_view` blocks only `paid` (`views.py:171-173`), so **`approved` →
  `rejected` is legal** — but see the ledger-orphan issue below.
- **No re-open path.** A `rejected` expense can be edited (`expense_edit_view` blocks
  only `approved`/`paid`, `views.py:100`), but the edit form excludes `status` and the
  view never resets it, so `rejected` is a dead end. Re-approving a corrected expense
  requires deleting and re-creating it.

### Invariants

- `amount > 0` — enforced at DB via `CheckConstraint expense_amount_positive`
  (`models.py:100-105`) **and** at the form level via Django's
  `validate_constraints()` (verified: `ExpenseForm` returns `__all__` =
  "Constraint 'expense_amount_positive' is violated." for `-1500`; the create view
  re-renders 200, no row written). Direct `Expense.objects.create(amount<=0)` bypasses
  `full_clean()` and raises `IntegrityError` (covered by
  `api/tests_audit_money.py:348-363`).
- **Ledger posted exactly once** — `post_to_ledger` uses `update_or_create` keyed on
  `('Expense', pk)` (`models.py:73-87`), and the ledger backstops with
  `UniqueConstraint(reference_type, reference_id)` (`finance/models.py:69-78`).

### Side effects

- **Approve / mark-paid** → one ledger row (idempotent) + `AuditLog` (`verify` /
  `update`) + `messages`.
- **Reject / delete → ledger is NOT touched.** This is the module's central integrity
  hole: a ledger row written at approval time is **never reversed** when the expense
  is later rejected (`views.py:167-178`) or deleted (`views.py:191-211`). Because
  `AccountTransaction.reference_id` is a plain `PositiveIntegerField` with no FK
  (`finance/models.py:35-36`), the row silently outlives the expense.
- **Create / edit / approve / reject / delete** each write an `AuditLog`
  (`_expense_log`, `views.py:15-22`); `mark_paid` reuses action `update`.

---

## 5. Edge cases (go deep)

For each: expected vs actual.

1. **Zero / negative amount (web form)** — *Expected*: friendly field error, 200
   re-render. *Actual*: rejected via `validate_constraints()` as a **non-field**
   `__all__` error with the raw technical message `Constraint "expense_amount_positive"
   is violated.` (verified empirically). Shown in `expense_form.html:26-31` (it renders
   `form.non_field_errors`), but the copy is developer-facing, not user-friendly.
2. **Zero / negative amount (direct ORM / admin / script)** — raises `IntegrityError`
   (DB check). The Django admin (`expenses/admin.py`) does not expose `status`/
   `approved_*` but would surface the raw DB error on a bad amount.
3. **Double approve (replay / double-click)** — ledger stays single (idempotent), but
   `approved_at` is re-stamped to the second click and a duplicate `verify` AuditLog
   is written. No `approved`-guard in `expense_approve_view` (`views.py:120`).
4. **Reject an approved (already-ledgered) expense** — allowed; ledger row is left
   orphaned (stale `project_cost` debit). No reverse/delete of the `AccountTransaction`
   on reject.
5. **Reject then re-approve** — impossible; no re-open action exists. Rejected expenses
   can only be edited (status stays `rejected`) or deleted.
6. **Edit a locked expense** — `approved`/`paid` edits are blocked server-side with a
   message redirect (`views.py:100-102`), but the detail page **still renders the Edit
   button** for every status (`expense_detail.html:19`), so a locked edit click
   round-trips to an error. `rejected` expenses remain editable (intended-ish, but
   editing does not reset status).
7. **Delete a paid/approved (ledgered) expense** — allowed (no status guard,
   `views.py:193-211`); ledger row orphaned. Delete is not exposed in the UI (no Delete
   button on list/detail) but reachable by direct POST.
8. **File upload — non-image / huge file** — `receipt_attachment` is a `FileField`, not
   `ImageField` (`models.py:39-43`); no content-type or per-file size validation.
   Request body is capped by Django's global `DATA_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB
   default) → oversized POSTs raise `RequestDataTooBig` (unhandled 400/413), but a
   single small `.exe`/`.html`/`.svg`/`.zip` uploads freely. `.svg`/`.html` served
   same-origin is a stored-XSS vector (see §6).
9. **Duplicate project delete cascade** — `project` is `CASCADE`
   (`models.py:20-23`): deleting a `Project` silently deletes its expenses (and the
   expense rows are ledger-orphaned). Confirmed by `api/tests_audit_money.py:365-368`.
   Note the **inconsistency** with `finance.Office`: offices are protected from
   deletion when expenses/ledger rows exist (per CLAUDE.md), but projects carrying
   `Expense` rows are **not** protected (the project guard only checks plots).
10. **State change via GET (no `request.method` check)** — `approve` / `reject` /
    `mark_paid` mutate state on **any** verb (`views.py:116-178`); only `delete`
    (`views.py:195`) and `edit`/`create` check the method. See §6 (CSRF).
11. **Concurrent double-submit of approve** — `update_or_create` is not race-proof at
    the DB level; the `UniqueConstraint` backstop (`finance/models.py:69-78`) would
    raise `IntegrityError` on the loser. No `try/except` in `post_to_ledger`, so the
    losing thread 500s. Integrity is preserved (one row), but the request fails ugly.
12. **Money precision** — `DecimalField(15,2)` throughout; templates display with
    `floatformat:0` (rounds paisa for display only). Chart data is `float(revenue)`
    (`views.py:61-62`) — lossy for very large sums, but chart-only.
13. **Missing referenced record** — `get_object_or_404` on expense → 404; form
    `project` queryset excludes `inactive` projects (`forms.py:24`), but a POST with an
    inactive/foreign `project` id is simply an invalid choice (form error).
14. **Wrong HTTP verb on delete** — GET renders `confirm_delete.html` (no mutation),
    POST deletes (`views.py:195-207`). Correct.

---

## 6. Cross-cutting risks

- **CSRF via GET — HIGH.** `expense_approve_view`, `expense_reject_view`, and
  `expense_mark_paid_view` do **not** check `request.method`, so a `GET
  /expenses/<pk>/approve/` performs the state change. Django's CSRF middleware only
  validates unsafe methods (POST/PUT/…), **not GET**, so these endpoints are
  CSRF-unprotected. A logged-in finance user who loads an attacker-controlled page
  containing `<img src="https://erp/expenses/5/approve/">` would silently approve the
  expense. Same for reject and mark-paid. This is the top security finding
  (`expenses/views.py:116-138`, `141-164`, `167-178`).
- **IDOR / broken object-level authorization — LOW/MEDIUM.** All views are `pk`-based
  with no ownership check (`views.py:99,119,144,170,184,194`). Consistent with the
  ERP's global-role model (no per-user scoping), but it means **any** `accounts`/
  `management`/`admin` user can approve, pay, reject, or delete **any** expense,
  including their own — there is no maker/checker separation.
- **Stored XSS via file upload — MEDIUM.** `receipt_attachment` accepts any file type;
  an uploaded `.svg` or `.html` is served back at
  `expense.receipt_attachment.url` (`expenses.html:159`,
  `expense_detail.html:35`) on the same origin → script execution in the victim's
  browser (same-origin stored XSS). No extension/content-type allow-list.
- **XSS in text fields — LOW.** `description`, `paid_to`, `payment_reference`,
  `project.name` are all rendered auto-escaped (`{{ … }}`, `|truncatechars`,
  `white-space:pre-wrap` in `expense_detail.html:56`); chart labels use `|escapejs`
  (`expenses.html:223`). No `|safe`/`mark_safe`/`innerHTML` on user content found.
- **Sensitive data exposure — MEDIUM.** (a) `approved_by.username` /
  `created_by.username` and amounts are visible to all finance roles (by design).
  (b) **Receipt/bill attachments are served unauthenticated**: `urlpatterns +=
  static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)`
  (`samana_erp/urls.py:160`, `settings.py:212-213`), so any party with a
  known/guessable `/media/expenses/receipts/<file>` URL can download vendor invoices
  without login. Recommend auth-gating or private media serving.
- **Accessibility** — the list Approve/Reject/Mark-Paid buttons are icon+text but
  adequately labelled; forms use `floating-group` labels; the "download receipt" link
  is an emoji `📎` (`expenses.html:159`) with only a `title` (thin accessible name).
  No keyboard trap found. Minor.

---

## 7. API surface

**There is no DRF API for `Expense`.** The module is web-template-only; no ViewSet,
serializer, or router entry exists (the `api/urls.py` router registers only the
finance `OfficeExpenseViewSet`/`ExpenseCategoryViewSet`, not `Expense`). All
interaction is via the server-rendered routes below.

| Method + path | View | Guard | Notes |
|---|---|---|---|
| GET `/expenses/` | `expenses_view` | `finance_or_above` | dashboard + list |
| GET/POST `/expenses/create/` | `expense_create_view` | `finance_or_above` | POST forces `status='pending'` |
| GET/POST `/expenses/<pk>/edit/` | `expense_edit_view` | `finance_or_above` | locks `approved`/`paid` |
| GET `/expenses/<pk>/` | `expense_detail_view` | `finance_or_above` | |
| GET/POST `/expenses/<pk>/delete/` | `expense_delete_view` | `finance_or_above` | POST deletes; **no status guard** |
| **GET/POST** `/expenses/<pk>/approve/` | `expense_approve_view` | `finance_or_above` | **mutates on GET (CSRF gap)** |
| **GET/POST** `/expenses/<pk>/reject/` | `expense_reject_view` | `finance_or_above` | **mutates on GET (CSRF gap)** |
| **GET/POST** `/expenses/<pk>/mark-paid/` | `expense_mark_paid_view` | `finance_or_above` | **mutates on GET (CSRF gap)** |

URLs defined in `expenses/urls.py:4-13`, mounted at `expenses/` via
`samana_erp/urls.py:83`.

---

## 8. Test data & fixtures needed

- **Roles**: a `superuser` (or `accounts`/`management` profile user) for
  `finance_or_above`; a `sales`-profile user to assert 302 → `/dashboard/` denial on
  every route.
- **Seed**: one `Project` (active) and one `inactive` Project (to assert it's excluded
  from the form's project queryset, `forms.py:24`); expenses in each status
  (`pending`, `approved`, `paid`, `rejected`).
- **Existing coverage**: `api/tests_audit_money.py:333-377` (ExpenseTests — create,
  negative/zero via ORM `assertRaises`, project cascade, audit) and
  `api/tests_audit_web.py:185-201` (web create + negative rejected with 200).
  **Gaps to add**: approve/reject/mark-paid transitions; GET-vs-POST on approve;
  approved→reject orphan ledger; delete-a-paid-expense orphan ledger; reject-then-reapprove
  (missing re-open); oversized/`.svg` receipt upload; locked-edit for `rejected`.
- **Isolation**: `Expense` has no unique business keys, so tests must create their own
  projects/expenses and assert by `description`/`pk`; timestamps auto-generate, no
  collision risk. Ledger assertions must filter `reference_type='Expense'` +
  `reference_id=<pk>` (the unique pair).

---

## 9. Key files (for traceability)

- `expenses/models.py` — `Expense` model, `STATUS_CHOICES`, `post_to_ledger`,
  `can_be_posted`/`is_posted_to_ledger` (dead code), amount CheckConstraint.
- `expenses/forms.py` — `ExpenseForm`; no `min_value`/`clean_amount`; project queryset
  excludes inactive; `payment_reference` optional.
- `expenses/views.py` — all 9 views; approval workflow; **GET-mutation + ledger-orphan
  risks live here**.
- `expenses/urls.py` — route table (approve/reject/mark-paid under `<int:pk>/`).
- `expenses/admin.py` — admin list; does not expose `status`/`approved_*`/`receipt`.
- `expenses/migrations/0002_expense_expense_amount_positive.py` — amount check
  constraint.
- `expenses/migrations/0003_..._approved_at_approved_by_and_more.py` — workflow fields.
- `finance/models.py` — `AccountTransaction` + `UniqueConstraint(reference_type,
  reference_id)`; the ledger `post_to_ledger` writes into.
- `templates/expenses.html`, `expense_form.html`, `expense_detail.html` — UI; button
  visibility rules; attachment download link; non_field_errors rendering.
- `core/permissions.py` (`finance_or_above`, `FINANCE_ROLES`) — authorization.
- `samana_erp/urls.py` (`:83` include, `:160` media static), `samana_erp/settings.py`
  (`:212-213` MEDIA) — routing + unauthenticated media serving.
- `api/tests_audit_money.py`, `api/tests_audit_web.py` — existing expense test coverage.
