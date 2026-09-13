# Expenses — Test Plan

> Generated from `docs/qa/expenses_analysis.md` (findings at 2026-09-13) and verified against
> `expenses/views.py`, `expenses/models.py`, `expenses/forms.py`, `expenses/urls.py`, and the
> `expenses.html` / `expense_form.html` / `expense_detail.html` templates.
>
> Scenario IDs are the contract Phase C test names must match. Prefix: `EXP`.

## 1. Scope & roles

This plan covers the **expenses** module: the approval workflow (`pending → approved → paid | rejected`),
ledger posting, the list/dashboard, create/edit/detail/delete views, and the security surface
(GET-mutation CSRF, stored XSS via the receipt `FileField`, unauthenticated media serving, IDOR /
missing maker-checker, and project-CASCADE ledger orphans). It also pins down the **absence** of a
DRF API for `Expense` (the module is web-only).

Roles that exercise the module (all pass `finance_or_above` = super_admin, admin, management,
accounts):

- **accounts** (or superuser) — primary actor for create / approve / mark-paid / reject / delete.
- **sales** (or any non-finance role) — expected to be **denied** (302 → `/dashboard/`) on every route.
- **anonymous** — expected 302 → `/login/`.

## 2. Preconditions & fixtures

- **Seed roles**: a `superuser` (or an `accounts`-profile user) for the happy/edge/security flows; a
  `sales`-profile user for the authorization denials. Default login `admin` / `admin123` is superuser.
- **Seed data**: one **active** `Project` and one **inactive** `Project` (to assert the form excludes
  inactive projects — `ExpenseForm.__init__` sets `Project.objects.exclude(status='inactive')`).
- **Status fixtures**: create expenses in each status — `pending`, `approved`, `paid`, `rejected`.
  Expenses have no unique business key; identify rows by `pk` and a **timestamped, unique
  `description`** (e.g. `EXP-HP-01 <UTC-now>`). Amounts are `DecimalField(15,2)` PKR — assert exact
  values, never floored.
- **Ledger assertions**: filter `AccountTransaction` on `reference_type='Expense'` AND
  `reference_id=<pk>` (the unique pair from `finance.models` `UniqueConstraint`).
- **URLs exercised** (relative to `http://127.0.0.1:8000`; all names from `expenses/urls.py`):
  - `GET /expenses/` — `expenses`
  - `GET/POST /expenses/create/` — `expense_create`
  - `GET/POST /expenses/<pk>/edit/` — `expense_edit`
  - `GET /expenses/<pk>/` — `expense_detail`
  - `GET/POST /expenses/<pk>/delete/` — `expense_delete`
  - `GET/POST /expenses/<pk>/approve/` — `expense_approve`  ⚠ mutates on GET
  - `GET/POST /expenses/<pk>/reject/` — `expense_reject`  ⚠ mutates on GET
  - `GET/POST /expenses/<pk>/mark-paid/` — `expense_mark_paid`  ⚠ mutates on GET
- **Dev-server note**: run with `DJANGO_DEBUG=True` (else `SECURE_SSL_REDIRECT` 301s the test client).

---

## 3. Scenario catalog

### HP — happy path

#### EXP-HP-01 — Create expense lands as `pending`
- **Preconditions**: finance user logged in; ≥1 active project exists.
- **Steps**:
  1. Navigate to `/expenses/` → click **+ Add Expense** (or open `/expenses/create/`).
  2. Fill: Project (active one), Expense Type (Internal), Amount `5000.00`, Expense Date (today),
     Description (timestamped unique), Paid To `ACME`.
  3. Submit (POST).
- **Expected result**: 302 → `/expenses/`. New row exists with `status='pending'`, `created_by` =
  acting user, `amount=5000.00`; one `AuditLog` with `action='create'`, `model_name='Expense'`.
  No ledger row exists yet (`AccountTransaction` filtered on `('Expense', pk)` is empty). Success
  message "Expense recorded successfully. It is now Pending Approval." shown.
- **Evidence on failure**: row `status` != `pending` (e.g. create persisted a non-pending status);
  `created_by` NULL; missing AuditLog; ledger row unexpectedly present.

#### EXP-HP-02 — Approve a pending expense posts the ledger exactly once
- **Preconditions**: a `pending` expense (from EXP-HP-01); note its `pk` and `amount`.
- **Steps**:
  1. On the list (or detail) page, submit the **Approve** form (POST `/expenses/<pk>/approve/` with CSRF).
  2. Query the DB.
- **Expected result**: 302 → `/expenses/`. Expense `status='approved'`, `approved_by` = acting user,
  `approved_at` set. Exactly **one** `AccountTransaction` with `reference_type='Expense'`,
  `reference_id=<pk>`, `direction='out'`, `transaction_type='project_cost'`, `amount` = expense amount.
  One AuditLog `action='verify'`. Success message mentions "Posted to Financial Ledger".
- **Evidence on failure**: `approved_by`/`approved_at` NULL; ledger row count != 1 (0 = never posted,
  >1 = not idempotent); wrong `direction`/`transaction_type`.

#### EXP-HP-03 — Mark-paid on an approved expense keeps ledger at one row
- **Preconditions**: an `approved` expense that already posted its ledger row (EXP-HP-02 result).
- **Steps**:
  1. Submit **Mark Paid** (POST `/expenses/<pk>/mark-paid/` with CSRF).
  2. Query the DB.
- **Expected result**: 302 → `/expenses/`. `status='paid'`. Ledger row count for
  `('Expense', pk)` is **still exactly one** (idempotent `update_or_create`). `approved_by`/
  `approved_at` **unchanged** (was already approved). One AuditLog `action='update'` with
  "(marked PAID…)" text.
- **Evidence on failure**: second/duplicate ledger row; `approved_by` overwritten to the payer when it
  was already set; missing AuditLog.

#### EXP-HP-04 — Reject a pending expense writes no ledger row
- **Preconditions**: a fresh `pending` expense.
- **Steps**: submit **Reject** (POST `/expenses/<pk>/reject/`).
- **Expected result**: 302 → `/expenses/`. `status='rejected'`. **No** `AccountTransaction` for
  `('Expense', pk)`. One AuditLog `action='reject'`. Message "Expense rejected."
- **Evidence on failure**: ledger row present; `status` != `rejected`; missing AuditLog.

#### EXP-HP-05 — Edit a pending expense
- **Preconditions**: a `pending` expense.
- **Steps**:
  1. Open `/expenses/<pk>/` → click **Edit** (or `/expenses/<pk>/edit/`).
  2. Change Description and Amount to new values; submit.
- **Expected result**: 302 → `/expenses/`. Fields updated; `status` **still `pending`** (form excludes
  `status`; view never resets it). One AuditLog `action='update'`. No ledger row yet.
- **Evidence on failure**: `status` changed by edit; fields not persisted; duplicate/missing AuditLog.

#### EXP-HP-06 — Expenses dashboard aggregates correctly
- **Preconditions**: ≥2 projects (one inactive), expenses across multiple types/dates/statuses,
  ≥1 verified `Payment` on a project's booking for revenue.
- **Steps**: load `/expenses/` as finance user.
- **Expected result**: 200. "Total Expenses" = sum of all expense amounts; "This Month" = sum where
  `expense_date >= first-of-month`; per-type totals/counts correct; per-project table shows revenue
  (verified payments via `booking__plot__project`) vs expenses vs net. **Inactive project excluded**
  from the per-project summary. Chart labels render without breaking the JS (`|escapejs`).
- **Evidence on failure**: totals mismatch raw sums (assert exact Decimal); inactive project appears;
  chart renders blank/JS error.

#### EXP-HP-07 — Mark-paid on a pending expense is one-step approve + pay
- **Preconditions**: a `pending` expense with **no** prior approval.
- **Steps**: submit **Mark Paid** directly on the pending row (POST `/expenses/<pk>/mark-paid/`).
- **Expected result**: `status='paid'`; `approved_by` = acting user and `approved_at` set (the view's
  one-step path stamps them because `was_pending and not approved_by`); ledger row count for
  `('Expense', pk)` == 1.
- **Evidence on failure**: `approved_by`/`approved_at` left NULL after one-step pay; ledger missing.

#### EXP-HP-08 — Detail page renders full record
- **Preconditions**: an `approved` expense with receipt attachment and `approved_by` set.
- **Steps**: open `/expenses/<pk>/`.
- **Expected result**: 200. Shows Amount, Type, Date, Status badge, Project, Paid To, Payment
  Reference, Receipt link, **Approved By** (username + timestamp), **Recorded By**. Approve/Reject
  buttons hidden (status != pending); Mark Paid shown (status == approved).
- **Evidence on failure**: a field missing; wrong status-conditioned action buttons.

---

### EC — edge case / boundary

#### EXP-EC-01 — approve/reject/mark-paid mutate on GET (no method check)
- **Preconditions**: a `pending` expense; finance user logged in.
- **Steps**:
  1. For a `pending` expense, issue a **GET** to `/expenses/<pk>/approve/` (no POST, no CSRF token).
  2. Repeat with a second pending expense and GET `/expenses/<pk>/reject/`.
  3. Repeat with a third pending expense and GET `/expenses/<pk>/mark-paid/`.
- **Expected result (secure)**: GET must **not** change state (views should require `request.method ==
  'POST'`, like `expense_create_view`/`expense_edit_view`/`expense_delete_view` do).
- **Actual (defect)**: each GET performs the mutation — status flips to `approved`/`rejected`/`paid`,
  ledger rows are written, AuditLog entries appended.
- **Evidence on failure**: DB status changed after a GET; ledger row present after GET; AuditLog
  timestamp matches the GET. This is the functional root of EXP-SEC-01…03.

#### EXP-EC-02 — approved → rejected is legal but the ledger row is never reversed (orphan)
- **Preconditions**: an `approved` expense whose ledger row exists (EXP-HP-02).
- **Steps**:
  1. Directly POST (or GET — see EXP-EC-01) `/expenses/<pk>/reject/`.
  2. Query `AccountTransaction` for `('Expense', pk)`.
- **Expected result (correct):** either reject-on-approved is blocked, **or** the ledger row is
  reversed/removed.
- **Actual (defect):** `status='rejected'`, but the `project_cost` **debit remains** in the ledger —
  a stale expense that no longer represents an approved cost. Reject writes no reverse/delete of the
  `AccountTransaction`.
- **Evidence on failure**: expense `status='rejected'` AND ledger row still present (the orphan).

#### EXP-EC-03 — Delete a paid/approved expense (no status guard; ledger survives)
- **Preconditions**: an `approved` or `paid` expense with a ledger row.
- **Steps**:
  1. Directly POST `/expenses/<pk>/delete/` (the delete view checks method but has **no status guard**).
  2. Query `AccountTransaction` for `('Expense', pk)`.
- **Expected result (correct):** deletion of a ledgered expense is blocked (like `finance.Office`,
  which is protected), **or** the ledger row is removed with it.
- **Actual (defect):** the expense is deleted, but because `AccountTransaction.reference_id` is a plain
  `PositiveIntegerField` with **no FK**, the ledger row silently outlives it (orphan). An AuditLog
  `action='delete'` is written.
- **Evidence on failure**: expense gone but ledger row still present. Note: no Delete button exists in
  the UI (list/detail), so this is reachable only by direct POST.

#### EXP-EC-04 — No re-open path (rejected stays rejected; re-approval impossible)
- **Preconditions**: a `rejected` expense.
- **Steps**:
  1. Attempt to approve it: POST/GET `/expenses/<pk>/approve/`.
  2. Attempt to edit it and change description (edit is allowed for `rejected`), then re-check status.
  3. Attempt to mark it paid.
- **Expected result (correct):** a rejected expense can be corrected and re-submitted for approval.
- **Actual (defect):** approve is blocked ("already Rejected"), mark-paid is blocked ("rejected …
  cannot be marked paid"), and editing does **not** reset `status` (form excludes `status`; view never
  resets). The only recovery is delete + recreate.
- **Evidence on failure**: `status` remains `rejected` after an edit that should re-open it; approve
  still redirects with the "already Rejected" error.

#### EXP-EC-05 — Double-approve re-stamps approved_at and writes a duplicate AuditLog
- **Preconditions**: a `pending` expense.
- **Steps**:
  1. POST `/expenses/<pk>/approve/`.
  2. Replay the **same** request (double-click / direct URL replay) `/expenses/<pk>/approve/`.
  3. Query `approved_at` and AuditLog count (`action='verify'`).
- **Expected result (correct):** a second approve is rejected (idempotent no-op).
- **Actual (defect):** the view only blocks `paid`/`rejected`, not an already-`approved` state, so the
  second approve **re-stamps `approved_by`/`approved_at`** and appends a **second** `verify` AuditLog.
  The ledger itself stays single (safe via `update_or_create`).
- **Evidence on failure**: `approved_at` equals the second click's timestamp; two `verify` AuditLog
  entries for the same expense.

#### EXP-EC-06 — Negative / zero amount rejected with a raw technical message
- **Preconditions**: finance user on the create form.
- **Steps**:
  1. Submit `/expenses/create/` with Amount `-1500` (and again with `0`).
- **Expected result (correct):** a friendly per-field validation message ("Amount must be greater than
  zero").
- **Actual (defect):** `ExpenseForm` has no `min_value`/`clean_amount`; the DB `CheckConstraint`
  (`expense_amount_positive`) surfaces via `validate_constraints()` as a **non-field** `__all__` error
  with the raw text `Constraint "expense_amount_positive" is violated.` Re-rendered 200, no row written.
- **Evidence on failure**: the page shows `form.non_field_errors` = the raw constraint string. Also
  assert no `Expense` row and no ledger row. (Direct `Expense.objects.create(amount<=0)` raises
  `IntegrityError` — the DB backstop.)

#### EXP-EC-07 — Locked edit is blocked server-side but the Edit button still renders
- **Preconditions**: an `approved` (or `paid`) expense.
- **Steps**:
  1. Open `/expenses/<pk>/` — note the **Edit** button is still rendered (it renders for every status).
  2. Click it → GET `/expenses/<pk>/edit/`.
- **Expected result (correct):** no Edit affordance for a locked record, or the view 404s/denies.
- **Actual (defect):** the view redirects back to detail with message "An approved/paid expense can no
  longer be edited." — the click is a dead round-trip, but the status guard itself works.
- **Evidence on failure**: edit form renders for a locked expense (status guard bypassed), OR the Edit
  button is missing when the bug is fixed (regression check).

#### EXP-EC-08 — Rejected expense is editable but editing does not reset status
- **Preconditions**: a `rejected` expense.
- **Steps**: edit it and change `paid_to`/`amount`; submit.
- **Expected result**: fields update; `status` remains `rejected` (documented dead-end; see EXP-EC-04).
- **Evidence on failure**: edit unexpectedly resets `status` to `pending` (would contradict the
  "no re-open path" behavior — a behavior change to flag).

#### EXP-EC-09 — Illegal transitions are blocked (mark-paid on rejected; reject on paid)
- **Preconditions**: one `rejected` and one `paid` expense.
- **Steps**:
  1. POST `/expenses/<rejected_pk>/mark-paid/` → expect "A rejected expense cannot be marked paid."
  2. POST `/expenses/<paid_pk>/reject/` → expect "A paid expense cannot be rejected."
- **Expected result**: `status` unchanged in both cases; redirect to detail with the error message.
- **Evidence on failure**: status changed despite the guard; or wrong redirect target.

#### EXP-EC-10 — Inactive project excluded from the form's project queryset
- **Preconditions**: one active and one inactive project.
- **Steps**: open `/expenses/create/`; inspect the Project `<select>` options. Then POST with the
  inactive project's id as `project`.
- **Expected result**: the select omits the inactive project; a direct POST with its id is rejected as
  an invalid choice (form error, 200 re-render, no row).
- **Evidence on failure**: inactive project present in the dropdown; or the POST succeeds.

#### EXP-EC-11 — Oversized receipt upload is not handled gracefully
- **Preconditions**: finance user; a file > `DATA_UPLOAD_MAX_MEMORY_SIZE` (Django default 2.5 MB).
- **Steps**: submit `/expenses/create/` with the oversized file as `receipt_attachment`.
- **Expected result (correct):** a friendly "file too large" validation message.
- **Actual (defect):** Django raises `RequestDataTooBig` before form validation; unhandled → 413/400
  (or debug 500). No user-facing copy.
- **Evidence on failure**: non-200 response with no friendly message; stack trace/HTML error page.

#### EXP-EC-12 — Concurrent double-submit of approve (race) may 500 on the loser
- **Preconditions**: a `pending` expense; a way to fire two parallel approve requests.
- **Steps**: send two concurrent POSTs to `/expenses/<pk>/approve/`.
- **Expected result (correct):** both return cleanly; ledger stays single.
- **Actual (risk):** `post_to_ledger`'s `update_or_create` is not race-proof; the `UniqueConstraint`
  backstop can raise `IntegrityError` on the loser, and there is no `try/except` → the losing request
  500s. Integrity preserved (one ledger row), but the request fails ugly.
- **Evidence on failure**: a 500 traceback referencing the `UniqueConstraint` on
  `(reference_type, reference_id)`. (Lower priority / unit-level; hard to repro in a browser.)

---

### SEC — negative & security

> Priority ordering: EXP-SEC-01…03 (CSRF via GET) and EXP-SEC-04 (stored XSS) are the HIGH items.

#### EXP-SEC-01 — CSRF via GET on approve (HIGH)
- **Preconditions**: a finance user is logged into the ERP; an attacker knows (or guesses) a `pending`
  expense `pk`. `expense_approve_view` has **no `request.method` check** and mutates on GET; Django's
  CSRF middleware validates only unsafe methods (POST/PUT/…), **not GET**.
- **Steps (precise repro)**:
  1. Log in as the finance user (session cookie set).
  2. Create a pending expense; note its `pk` (e.g. `5`).
  3. In the **same** browser, navigate directly to `http://127.0.0.1:8000/expenses/5/approve/`
     (a plain GET — no POST body, no `csrfmiddlewaretoken`).
  4. Observe status + ledger. Then simulate the real attack: load an attacker page containing
     `<img src="http://127.0.0.1:8000/expenses/5/approve/">` — the browser silently fetches it.
- **Expected result (secure)**: the GET is a no-op (or the view requires POST and returns 405/redirect
  without mutating).
- **Actual (defect)**: the expense is **approved**: `status='approved'`, `approved_by`/`approved_at`
  stamped, ledger row written, AuditLog `verify` appended — all triggered by an image load with no CSRF
  token.
- **Evidence on failure**: status changed to `approved` after a token-less GET; ledger row present;
  AuditLog entry whose time equals the GET.

#### EXP-SEC-02 — CSRF via GET on reject (HIGH)
- **Preconditions**: logged-in finance user; a `pending` expense (or `approved` — reject-on-approved is
  legal, EXP-EC-02).
- **Steps**: navigate (or `<img src=…>`) to `http://127.0.0.1:8000/expenses/<pk>/reject/` as a GET.
- **Expected result (secure)**: no mutation on GET.
- **Actual (defect)**: `status='rejected'`, AuditLog `reject` appended, no CSRF token required.
- **Evidence on failure**: status flipped to `rejected` after token-less GET.

#### EXP-SEC-03 — CSRF via GET on mark-paid (HIGH)
- **Preconditions**: logged-in finance user; a `pending` or `approved` expense.
- **Steps**: navigate (or `<img src=…>`) to `http://127.0.0.1:8000/expenses/<pk>/mark-paid/` as a GET.
- **Expected result (secure)**: no mutation on GET.
- **Actual (defect)**: `status='paid'` (and one-step approve stamping if pending), ledger posted, all
  without a CSRF token.
- **Evidence on failure**: status flipped to `paid` + ledger row after token-less GET.

#### EXP-SEC-04 — Stored XSS via SVG receipt upload (HIGH)
- **Preconditions**: `receipt_attachment` is a `FileField` (not `ImageField`) — no extension,
  content-type, or per-file size validation. Uploaded files are served at
  `expense.receipt_attachment.url` on the same origin; the download link uses `target="_blank"`, so the
  browser navigates to and renders the file.
- **Steps (precise repro)**:
  1. Create `/tmp/poc.svg`:
     ```svg
     <svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)">
       <script>fetch('/expenses/').then(r=>r.text()).then(t=>document.title=t.length)</script>
     </svg>
     ```
  2. As a finance user, create an expense and upload `poc.svg` as the receipt.
  3. Note the attachment URL (e.g. `http://127.0.0.1:8000/media/expenses/receipts/poc.svg`).
  4. In a logged-in browser, open that URL directly (or click the 📎 "Download" link, which opens it in
     a new tab same-origin).
  5. Observe whether `onload`/`<script>` executes.
- **Expected result (secure)**: the upload is rejected (allow-list `image/png`, `image/jpeg`, `pdf`
  only), **or** the file is served with `Content-Disposition: attachment` + a neutral content-type so it
  never renders as active content, **or** media is stored/served outside the app origin.
- **Actual (defect)**: `Django` stores the file and serves `.svg` as `image/svg+xml` (active content) on
  the same origin → the `onload` handler / inline script executes in the victim's authenticated session
  (session/CSRF-token theft, same-origin request forgery).
- **Evidence on failure**: the alert/`fetch` fires on the `/media/…` URL; or the server responds
  `Content-Type: image/svg+xml` (not `application/octet-stream`/`attachment`) for the uploaded file.

#### EXP-SEC-05 — Stored XSS via HTML receipt upload
- **Preconditions**: as EXP-SEC-04.
- **Steps**: upload `poc.html` (`<script>alert(document.domain)</script>`) as the receipt; open its URL.
- **Expected result (secure)**: rejected or served inert.
- **Actual (defect)**: `.html` served same-origin executes in the victim's session (same stored-XSS
  class as SVG).
- **Evidence on failure**: script executes on the `/media/…` URL; or the server returns `text/html`.

#### EXP-SEC-06 — Unauthenticated media serving of vendor invoices
- **Preconditions**: an expense with a receipt attachment; note its `/media/expenses/receipts/<file>`
  URL. (Media is wired via `static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` in
  `samana_erp/urls.py`.)
- **Steps**:
  1. In a **fresh incognito window** (no login), navigate directly to the attachment URL.
- **Expected result (secure)**: 302 → `/login/`, or 403 (media is auth-gated / private-served).
- **Actual (defect)**: the vendor invoice/bill downloads with **no authentication** to anyone holding or
  guessing the URL.
- **Evidence on failure**: the file is returned (200) with no session. Verify with a known attachment
  URL from a prior test.

#### EXP-SEC-07 — IDOR / no maker-checker (any finance user can approve/pay/reject/delete any expense)
- **Preconditions**: two distinct finance users **A** and **B** (e.g. two `accounts` profiles). A
  records an expense.
- **Steps**:
  1. As **B**, approve A's expense; as **B**, mark a second of A's expenses paid; as **B**, reject a
     third; as **B**, POST-delete a fourth.
- **Expected result (correct):** either B cannot act on A's records, or a maker-checker rule prevents a
  user approving their **own** record.
- **Actual (defect):** every view is `get_object_or_404(Expense, pk=pk)` with **no ownership check** and
  a single `finance_or_above` role — B can approve/pay/reject/delete **any** expense, and a user can
  approve their own (no separation between recording and approving).
- **Evidence on failure**: B's actions on A's records succeed (status changes + B stamped as
  `approved_by`/`created_by` where applicable).

#### EXP-SEC-08 — Authorization: non-finance roles and anonymous are denied
- **Preconditions**: a `sales`-profile user; an anonymous session.
- **Steps**: as `sales` (and separately anonymous), request each route:
  `/expenses/`, `/expenses/create/`, `/expenses/<pk>/`, `/expenses/<pk>/edit/`,
  `/expenses/<pk>/approve/`, `/expenses/<pk>/reject/`, `/expenses/<pk>/mark-paid/`,
  `/expenses/<pk>/delete/`.
- **Expected result**: `sales` → 302 to `/dashboard/` (with an error message) and **no mutation**;
  anonymous → 302 to `/login/`.
- **Evidence on failure**: any route returns 200 to a non-finance role, or state was mutated before the
  denial.

#### EXP-SEC-09 — Project CASCADE deletes expenses → orphaned ledger rows
- **Preconditions**: a `Project` that (a) has no plots (so the project-deletion guard does not block it)
  and (b) has ≥1 expense with a posted ledger row.
- **Steps**:
  1. Delete the project (via the project delete path, which only guards against plots).
  2. Query `Expense` and `AccountTransaction` for the deleted project.
- **Expected result (correct):** deletion is blocked while ledgered expenses exist (parity with
  `finance.Office`), **or** ledger rows are cleaned up with the cascade.
- **Actual (defect):** `on_delete=CASCADE` silently deletes the expenses; their `AccountTransaction`
  rows (keyed by `reference_id` with no FK) remain — orphaned `project_cost` debits referencing a
  now-deleted project.
- **Evidence on failure**: `Expense` rows gone but `AccountTransaction` rows (filtered by the deleted
  project / `reference_type='Expense'`) still present.

#### EXP-SEC-10 — XSS in text fields: negative control (auto-escaped)
- **Preconditions**: an expense whose `description`/`paid_to`/`payment_reference` contain
  `<script>alert(1)</script>` (or `<img src=x onerror=…>`).
- **Steps**: view the list and detail pages.
- **Expected result**: the payload renders as **literal text**, no script execution — templates use
  `{{ … }}` auto-escaping and `|escapejs` for chart labels; no `|safe`/`mark_safe` on user content.
- **Evidence on failure**: script executes (would indicate an introduced `|safe`/`innerHTML`); or the
  payload is double-escaped to the point of being unreadable (regression in escaping).

---

### API — API contract (web-only module)

#### EXP-API-01 — No DRF endpoint for Expense
- **Preconditions**: the DRF router at `api/urls.py` is loaded.
- **Steps**:
  1. `GET /api/expenses/` (and `/api/expense/`, `/api/expenses/<pk>/`) as a superuser.
  2. Enumerate `/api/` root (or `api/urls.py`) and confirm no `Expense` ViewSet/route is registered.
- **Expected result**: no expense endpoint exists — 404/route-not-found; the router registers only
  `OfficeExpenseViewSet`/`ExpenseCategoryViewSet` (finance), **not** `Expense`. The module is
  template-only (no `expenses/serializers.py` / `api_views.py`).
- **Evidence on failure**: an `/api/expenses/…` route returns data (an unintended ViewSet was added).

#### EXP-API-02 — Document the URL route table and verb behavior
- **Preconditions**: none (static).
- **Steps**: assert each named route in `expenses/urls.py` resolves to its view and document verb
  behavior:
  | Name | Path | Allowed verbs | Mutates on |
  |---|---|---|---|
  | `expenses` | `/expenses/` | GET | — |
  | `expense_create` | `/expenses/create/` | GET/POST | POST |
  | `expense_edit` | `/expenses/<pk>/edit/` | GET/POST | POST |
  | `expense_detail` | `/expenses/<pk>/` | GET | — |
  | `expense_delete` | `/expenses/<pk>/delete/` | GET/POST | POST only |
  | `expense_approve` | `/expenses/<pk>/approve/` | GET/POST | **GET and POST** ⚠ |
  | `expense_reject` | `/expenses/<pk>/reject/` | GET/POST | **GET and POST** ⚠ |
  | `expense_mark_paid` | `/expenses/<pk>/mark-paid/` | GET/POST | **GET and POST** ⚠ |
- **Expected result**: `reverse()` for each name succeeds; the three ⚠ rows are flagged as
  GET-mutating (documented defect — see EXP-EC-01 / EXP-SEC-01…03).
- **Evidence on failure**: a named route fails to reverse; a mutation column disagrees with actual
  behavior (re-test against EXP-EC-01).

---

## 4. Data isolation rules

- Every expense fixture uses a **timestamped unique `description`** (e.g. `EXP-HP-01 2026-09-13T12:00:00Z`)
  and is located by `pk` + description, never by position in a list.
- Amounts are unique Decimals where helpful (e.g. `5000.00`, `5001.50`) so ledger assertions can filter
  by exact amount and avoid cross-test coupling.
- Ledger assertions always filter `reference_type='Expense'` AND `reference_id=<pk>` — the unique pair.
- No cross-test dependence on a shared project; tests create their own project(s) and clean up by
  deleting the project **before** any project-delete guard asserts run (EXP-SEC-09 must be run in
  isolation, before/after without residue).
- Cleanup order: delete created expenses first (or cascade via a dedicated throwaway project), then the
  throwaway project. Do not reuse the seed project across the orphan/delete scenarios.

## 5. Coverage checklist (for the master map)

- EXP-HP-01 — Create expense lands as `pending`
- EXP-HP-02 — Approve a pending expense posts the ledger exactly once
- EXP-HP-03 — Mark-paid on an approved expense keeps ledger at one row
- EXP-HP-04 — Reject a pending expense writes no ledger row
- EXP-HP-05 — Edit a pending expense
- EXP-HP-06 — Expenses dashboard aggregates correctly
- EXP-HP-07 — Mark-paid on a pending expense is one-step approve + pay
- EXP-HP-08 — Detail page renders full record
- EXP-EC-01 — approve/reject/mark-paid mutate on GET (no method check)
- EXP-EC-02 — approved → rejected legal but ledger row never reversed (orphan)
- EXP-EC-03 — Delete a paid/approved expense (no status guard; ledger survives)
- EXP-EC-04 — No re-open path (rejected stays rejected)
- EXP-EC-05 — Double-approve re-stamps approved_at + duplicate AuditLog
- EXP-EC-06 — Negative/zero amount rejected with raw technical message
- EXP-EC-07 — Locked edit blocked server-side but Edit button still renders
- EXP-EC-08 — Rejected expense editable but status not reset
- EXP-EC-09 — Illegal transitions blocked (mark-paid on rejected; reject on paid)
- EXP-EC-10 — Inactive project excluded from form's project queryset
- EXP-EC-11 — Oversized receipt upload not handled gracefully
- EXP-EC-12 — Concurrent double-submit of approve may 500 on the loser
- EXP-SEC-01 — CSRF via GET on approve (HIGH)
- EXP-SEC-02 — CSRF via GET on reject (HIGH)
- EXP-SEC-03 — CSRF via GET on mark-paid (HIGH)
- EXP-SEC-04 — Stored XSS via SVG receipt upload (HIGH)
- EXP-SEC-05 — Stored XSS via HTML receipt upload
- EXP-SEC-06 — Unauthenticated media serving of vendor invoices
- EXP-SEC-07 — IDOR / no maker-checker
- EXP-SEC-08 — Authorization: non-finance roles and anonymous denied
- EXP-SEC-09 — Project CASCADE deletes expenses → orphaned ledger rows
- EXP-SEC-10 — XSS in text fields (negative control)
- EXP-API-01 — No DRF endpoint for Expense
- EXP-API-02 — Document the URL route table and verb behavior
