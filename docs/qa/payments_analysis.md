# Payments Module — QA Analysis

> Module: `payments/` (models, forms, serializers, DRF API, workflow views, PDFs)
> plus the payment/receipt/refund views living in `core/views.py`.
> Read `docs/qa/_shared-context.md` first — roles/permissions/URLs are not re-derived here.

## 1. Business purpose & user journeys

The payments module is the money-in and money-out spine of the ERP. It records
customer payments against bookings, tracks installment allocation, verifies
(reconciles) payments, handles bounced cheques and reversals, generates fiscal
receipts (with a July–June `receipt_number`), and runs the full refund lifecycle
(approve → process → one ledger row). Money correctness here is the highest-risk
area of the system: `Booking.advance_paid` (not the raw `Payment` rows) is the
single source of truth for headline revenue (`dashboard_view`), so every
verify/reverse/refund must keep `advance_paid`, installment `paid_amount`, the
receipt set, and the `AccountTransaction` ledger consistent.

User journeys (role in parens):

- Record a payment against a booking (accounts/management/admin/super_admin) →
  `payment_create_view` immediately verifies it, bumps `advance_paid`, updates
  the linked installment, auto-generates a receipt, and sends confirmation +
  receipt notifications. **No pending state is produced by this path.**
- Verify / reject a pending payment (admin/super_admin only) →
  `payment_verify_view` / `payment_reject_view` (web) or `PaymentViewSet.verify`
  (API). This is the only path that touches `status='pending'` records (which
  come from the API create flow).
- Bounce a cheque (admin web / any finance role via API) → `payment_bounce_view`
  / `PaymentViewSet.mark_bounced`; a verified payment is reversed.
- Reverse a verified payment (admin) → `payment_reverse_view`.
- Refund lifecycle (accounts view/create; admin approve; management process) →
  `refunds_view` / `refund_create_view` / `refund_approve_view` /
  `refund_process_view`, mirrored by `RefundViewSet.approve/reject/process`.
- Print / download / share a receipt (accounts/management/admin) →
  `receipt_detail_view` / `receipt_pdf_view`.

## 2. Data model

All money fields are `DecimalField(max_digits=15, decimal_places=2)` (PKR, no
sub-paisa) — see `_shared-context.md` "Money / decimal".

### Payment (`payments/models.py:7-94`)
- Fields: `payment_id` (unique, auto), `booking` FK CASCADE, `installment` FK
  SET_NULL, `amount` (Decimal), `payment_date`, `payment_method`
  (`cash/bank_transfer/cheque/online/jazzcash/easypaisa/raast`), `payment_type`
  (`down_payment/installment/full_payment/advance/final_payment/late_fee/
  adjustment/other`), `reference_number`, `status` (see §4), cheque fields
  (`bank_name/cheque_number/cheque_date/clearance_date/bounce_reason/bounce_fee`),
  `method_data` JSON, `unallocated_amount`, `notes`, `receipt_generated`,
  `created_by`, `verified_by`, `verified_at`.
- `save()` auto-ID `PAY-00001` by parsing the last row's numeric suffix under
  `select_for_update()` (`models.py:68-78`).
- Constraint `payment_amount_positive` (`amount__gt=0`) at `models.py:89-94`; index
  on `status` and `payment_date`. `Meta.ordering = ['-created_at']`.

### PaymentAllocation (`payments/models.py:97-105`)
- `payment` FK CASCADE, `installment` FK CASCADE, `amount`, `allocated_at`,
  `allocated_by`. `unique_together = ['payment', 'installment']` (`models.py:105`) —
  one allocation row per (payment, installment) pair.

### Refund (`payments/models.py:108-307`)
- Fields: `booking` FK CASCADE, `original_payment` FK SET_NULL, `amount`, `reason`
  (`cancellation/overpayment/booking_transfer/other`), `refund_method`,
  `refund_date`, `supporting_document` FileField, `status`, `approved_by`,
  `processed_by`, `processed_date`, `notes`.
- Computed: `total_paid` = sum of **verified** payments (`models.py:156-163`);
  `total_refunded` = sum of non-rejected refunds **excluding self**
  (`models.py:165-181`); `refundable_amount = max(total_paid - total_refunded, 0)`
  (`models.py:183-186`); `refund_percentage` (`models.py:188-193`).
- `clean()` and `validate_refund_limit()` reject `amount > refundable_amount`
  (`models.py:196-214`).
- Workflow methods: `apply_approval` reduces `booking.advance_paid` by the refund
  amount (floored at 0) and sets `status='approved'` (`models.py:216-236`);
  `reject()` (`models.py:238-242`); `post_to_ledger()` idempotent via
  `update_or_create(reference_type='Refund', reference_id=self.pk)`
  (`models.py:244-269`); `process()` guards `status=='approved'`, checks whether a
  ledger row already exists, then sets `status='processed'` and posts exactly once
  (`models.py:271-291`).
- Constraint `refund_amount_positive` (`models.py:302-307`).

### Receipt (`payments/models.py:310-369`)
- `receipt_id` auto (`RCP-00001`), `receipt_number` **unique** + blank
  (`models.py:313`), `payment` FK CASCADE, `receipt_date`, `generated_by`,
  `is_duplicate`, `cancellation_reason`, `pdf_file`.
- `save()`: `receipt_date` defaults to `payment.payment_date` else today
  (`models.py:333-338`); `receipt_number` is generated per fiscal year
  (`RCP-FY{yy}-{yy}/00001`) with July–June boundary (`month >= 7` → start = year,
  else start = year-1) and a per-prefix `select_for_update()` + max-suffix lookup
  (`models.py:340-361`).

### PaymentAttachment (`payments/models.py:372-387`)
- `payment` FK CASCADE, `file`, `attachment_type`, `filename`, `uploaded_by`.

### Ledger (`finance/models.py:12-79`)
- `AccountTransaction` unique on `(reference_type, reference_id)` where
  `reference_id IS NOT NULL` (`finance/models.py:69-78`,
  `account_transaction_reference_unique`) — the root-cause guard that makes
  refund/expense/payroll posting idempotent.

## 3. Roles & permissions

Web (decorators in `core/permissions.py`, all redirect to `/dashboard/` on denial):

| Action | Allowed roles | Enforced by |
|---|---|---|
| List payments | super_admin, admin, management, accounts | `@payments_access` (`core/views.py:1542`) |
| Record payment | same | `@payments_access` (`core/views.py:1542`) |
| Payment detail | same | `@payments_access` (`core/views.py:1697`) |
| Receipt detail / PDF | same | `@payments_access` (`core/views.py:1746,1773`) |
| Verify / reject / bounce payment | super_admin, admin | `@admin_or_above` (`views_workflow.py:61,89,108`) |
| Reverse payment | super_admin, admin | `@admin_or_above` (`views_workflow.py:126`) |
| Refunds list / create | super_admin, admin, management, accounts | `@finance_or_above` (`views_workflow.py:159,178`) |
| Refund approve/reject | super_admin, admin | `@admin_or_above` (`views_workflow.py:194`) |
| Refund process | super_admin, admin, management | `@management_or_above` (`views_workflow.py:216`) |

API (DRF):

| Endpoint | Permission |
|---|---|
| `/api/payments/` (PaymentViewSet) | `IsStaffReadAdminWrite` — any auth user can GET; write for super_admin/admin/management/accounts; DELETE only super_admin/admin/management (`api_views.py:15-35`) |
| `/api/payments/{pk}/verify/` | explicit in-method check: super_admin/admin only (`api_views.py:85-93`) |
| `/api/payments/{pk}/mark_bounced/` | **no explicit role check** — inherits class write perms (accounts can bounce) |
| `/api/payments/{pk}/upload_attachment/` | no explicit role check — inherits class write perms |
| `/api/refunds/` (RefundViewSet) + approve/reject/process | `IsStaffReadAdminWrite` — approve/process allowed for **accounts** via API |
| `/api/payment-allocations/` | `IsStaffReadAdminWrite` |
| `/api/receipts/` (ReceiptViewSet) | **`permissions.IsAuthenticated`** (`api_views.py:266`) |

### IDOR / role-gating gaps (important)

- **`ReceiptViewSet` uses `IsAuthenticated`**, not a finance permission. Any
  authenticated account — including `sales` (excluded from web payments), `staff`,
  `contractor`, `project_manager`, and any customer with a portal session — can
  list and retrieve **every** receipt, which contains customer name, CNIC, phone,
  address, booking/plot info and amounts (`receipt_detail.html:80-103`). This is
  the largest exposure in the module.
- **API vs web mismatch on refund approve/process.** Web `refund_approve_view` is
  `admin_or_above` and `refund_process_view` is `management_or_above`, but the
  API `RefundViewSet.approve/reject/process` only require
  `IsStaffReadAdminWrite` (so `accounts` can approve/process via API, which the
  web UI forbids).
- **API vs web mismatch on bounce.** Web `payment_bounce_view` is `admin_or_above`
  and refuses already-verified payments; API `mark_bounced` has no role check and
  **does** reverse verified payments.
- **Template flag vs view gap on refunds list.** `refunds.html:100-119` renders the
  Approve/Reject/Process buttons with no `{% if can_manage_users %}` guard, so an
  `accounts` user sees buttons that route to `admin_or_above`/`management_or_above`
  views and gets a silent `/dashboard/` redirect on click.
- **Object-level authorization is absent everywhere.** `payment_detail_view`,
  `receipt_detail_view`, `receipt_pdf_view`, and the refund views resolve by `pk`
  with no ownership check. This is role-based (not object-based) access — by
  design for staff finance roles, but it means the only thing standing between a
  low-privilege authenticated user and arbitrary payment/receipt data is the
  decorator/DRF permission above.

## 4. Business rules, state machines, invariants

### Payment status transitions

`STATUS_CHOICES` (`models.py:8-17`): `draft`, `pending`, `under_clearing`,
`verified`, `rejected`, `bounced`, `reversed`, `partially_applied`.

- Web record (`payment_create_view`) → **`verified` immediately** (`core/views.py:1559`).
- API create → **`pending`** (default). Only this path feeds the verify/reject UI.
- `pending/draft → verified` (verify) — advances booking + installment.
- `pending/draft → rejected` (reject) — no financial effect.
- `pending/draft → bounced` (web `payment_bounce_view`) — **refuses** if already
  `verified/rejected/reversed`; records `bounce_reason`, no financial effect.
- `verified → bounced` (API `mark_bounced` only) — reverses installment +
  `advance_paid`, cancels receipts.
- `verified → reversed` (`payment_reverse_view`) — **no status guard**, see §5.
- `under_clearing` / `partially_applied` are declared but **unused** by any
  workflow; they only appear as a substring in the `payment_detail.html:45`
  template gate.

Guard in verify/reject (web `views_workflow.py:64,92` and API
`api_views.py:99-103`): refuse when status is already `verified/rejected/reversed`
so `advance_paid` is never double-counted.

### Refund status transitions

`pending → approved → processed | rejected` (`models.py:125-130`).

- `apply_approval` reduces `booking.advance_paid` by `amount` at **approval** time
  (not process time) — `models.py:229-231`.
- `process()` requires `status=='approved'` and posts **exactly one** ledger row,
  guarded by `update_or_create` + `reference_type/reference_id` unique
  (`models.py:271-291`).

### Invariants

- `Payment.amount > 0` (DB check + form/serializer validation).
- `Refund.amount > 0` (DB check + form/serializer validation).
- `Refund.amount ≤ refundable_amount` where
  `refundable = Σ verified payments − Σ non-rejected refunds` (model property,
  form `clean`, serializer `validate`).
- Cheque payment requires `cheque_number` + `bank_name` (form `forms.py:54-58`,
  create serializer `serializers.py:163-168`).
- `installment.plan.booking_id == payment.booking.id` when an installment is
  selected (form `forms.py:63-65`, create serializer `serializers.py:171-177`).
- `PaymentAllocation` unique per (payment, installment).
- `AccountTransaction` unique per (reference_type, reference_id) — ledger
  de-duplication root guard.
- Revenue = `Σ Booking.advance_paid` (see `_shared-context.md`); every verify
  adds and every reverse/refund-approval subtracts from `advance_paid`.

### Side effects

- Verify → `advance_paid += amount` (capped at `total_amount`), installment
  `paid_amount`/`status`, `booking.status='completed'` when `remaining_balance <= 0`,
  installment-plan `recalculate()`, auto `Receipt`, `AuditLog`, (web only)
  notifications.
- Reverse / bounce(verified) → `advance_paid -= amount` (floored 0), installment
  `paid_amount -= amount` (floored 0), `booking.status='completed' → 'active'`,
  plan `recalculate()`, receipts cancelled.
- Refund approve → `advance_paid -= amount` (floored 0). Refund process →
  one `AccountTransaction` (direction `out`, type `refund`).

## 5. Edge cases (deep)

### Payment verify / reverse / bounce

- **Verify twice / reject after verify** — blocked by the status guard
  (`views_workflow.py:64`, `api_views.py:99-103`). *Expected:* second attempt is a
  no-op with a message; *actual:* correct in the single-threaded case.
- **Concurrent double-verify (race)** — the status guard is read **before** the
  transaction, and neither the web view nor the API action takes
  `select_for_update()` on the payment row. Two simultaneous verifies can both
  observe `pending` and both run `_apply_payment_effects`, double-counting
  `advance_paid` and installment `paid_amount`. The web view wraps in
  `transaction.atomic()` (`views_workflow.py:69`) but without a row lock the
  atomic block does not prevent the lost-update. *Expected:* at-most-once
  financial effect.
- **Reverse a draft/pending payment** — `payment_reverse_view` has **no status
  guard** (`views_workflow.py:127-153`). Reversing a payment that was never
  verified still subtracts `payment.amount` from the linked installment's
  `paid_amount` and from `advance_paid` (floored at 0). For a draft/pending
  payment this corrupts balances that were legitimately accumulated by *other*
  verified payments. The UI hides the button (`payment_detail.html:63`), but a
  direct POST is not blocked. *Expected:* reversing a non-verified payment should
  be rejected or a no-op.
- **Reverse/bounce a payment with no installment** — installment block is skipped
  (guarded by `if payment.installment`), so only `advance_paid` is reduced.
  Correct.
- **Reverse a payment already fully reversing `advance_paid`** — floored at 0, no
  negative balances. Correct, but it can mask double-reversal.
- **Bounce a verified payment via web** — `payment_bounce_view` refuses verified
  payments (`views_workflow.py:111`), so the web cannot bounce a cleared cheque
  (must use reverse). The API `mark_bounced` does allow it and reverses. This is
  an inconsistency, not a crash.
- **`mark_bounced` `bounce_fee` type** — `request.data.get('bounce_fee', 0)` is
  not coerced (`api_views.py:214`); a non-numeric string raises at save. *Expected:*
  a 400, not a 500.

### Refund

- **Refund amount > refundable** — rejected by model `clean`, form `clean`
  (`forms.py:104-121`), and serializer `validate` (`serializers.py:101-116`).
  *Expected:* 400 / form error.
- **Refund on a booking with no payments** — `total_paid = 0` → `refundable = 0`
  → any positive amount rejected. Correct.
- **Serializer `validate` does NOT exclude self** — on a PATCH/PUT of an existing
  refund via the API, `total_refunded` includes the refund's own amount
  (`serializers.py:108-109`), unlike the model property (`models.py:178-179`) and
  the form (`forms.py:112-113`). Editing an existing refund (e.g. changing
  `refund_date` or `notes` without changing `amount`) can be rejected because the
  refund appears to exceed its own `refundable_amount`. *Expected:* partial
  updates to already-approved/processed refunds should succeed.
- **Double-approve race** — `refund_approve_view` does **not** check
  `status=='pending'` before calling `apply_approval` (`views_workflow.py:193-212`),
  and `apply_approval` does not guard status either (`models.py:216-236`). A
  double POST (double-click / two tabs) reduces `advance_paid` **twice**. The API
  `approve` action does guard (`api_views.py:302-307`), so only the web path is
  vulnerable. *Expected:* approve is idempotent.
- **Concurrent refund process** — `process()` checks `already_posted` then saves
  then posts (`models.py:271-291`); two concurrent processes can both pass the
  `already_posted` check, but `update_or_create` + the DB unique constraint means
  only one ledger row survives. Ledger is safe; the redundant second
  `status='processed'` save is harmless. Note this safety depends on the DB
  enforcing the unique constraint — on SQLite dev, concurrent write behavior is
  not the same as PostgreSQL.
- **`apply_approval` reduces `advance_paid` at approval** — if the booking was
  overpaid (capped) or already fully refunded, it floors at 0, which can silently
  absorb an over-refund relative to `advance_paid` even though `refundable_amount`
  (verified-payment based) would have allowed it. Not a crash, but the two money
  views (`advance_paid` vs `Σ verified payments`) can drift after refunds.
- **Refund with `refund_date` missing** — `post_to_ledger` falls back to
  `processed_date.date()` else today (`models.py:253-255`). Correct.

### Receipt / fiscal year

- **June vs July boundary** — `month >= 7` → FY starts this year, else last year
  (`models.py:344-349`). A 30-June payment lands in the ending FY; a 1-July
  payment starts the new FY. Correct.
- **Sequential number per FY** — max-suffix lookup is lexicographic
  `order_by('-receipt_number')` (`models.py:353`). With `zfill(5)` this is correct
  up to 99,999; past that, `100000` sorts before `99999`, so the next number would
  be mis-computed. Extreme-but-real once receipt counts grow.
- **Uniqueness race** — `receipt_number` is `unique=True` (`models.py:313`).
  Concurrent receipt creation for the same FY can both read the same "last" and
  collide on the unique constraint. `select_for_update()` serializes under
  PostgreSQL but is a **no-op under SQLite**. *Expected:* one transaction should
  retry or lock so numbering is collision-free in all backends.
- **`receipt_id` (RCP-00001) auto-ID** uses a separate `select_for_update()` block
  (`models.py:324-331`) — same concurrency caveat.

### Forms / amounts / precision

- **Zero / negative amount** — rejected by `payment_amount_positive` and
  `refund_amount_positive` DB checks, plus `clean_amount`/`validate_amount`.
  *Expected:* reject with a clear message; *actual:* correct.
- **Money precision** — all Decimal(15,2); `advance_paid` capped at `total_amount`.
  Client-side JS compares with `parseFloat` (`payment_form.html:609-611`) — float
  precision is fine for a UI guard, but the authoritative check must stay
  server-side (it does, loosely — see below).
- **Overpayment beyond `remaining_balance`** — the JS blocks it
  (`payment_form.html:609-622`) but the server form explicitly allows it
  (`forms.py:67-71`, "Allow but warn — overpayment is valid for advance", a `pass`
  with no warning), and `advance_paid` is then **silently capped** at
  `total_amount` (`core/views.py:1617-1620`). With an installment, the excess goes
  to `unallocated_amount`; without one, the excess is recorded on the raw Payment
  row but reflected nowhere else. *Expected:* overpayment should be surfaced
  (warning + explicit unallocated handling), not silently discarded.
- **Duplicate payment heuristic** — same booking+amount+date+method within 60s is
  blocked with a message (`core/views.py:1576-1586`). It is a heuristic only, not
  a DB constraint, and is checked before the transaction; changing date/method, or
  two legitimately identical payments >60s apart, bypass it. *Expected:* a real
  idempotency key for true double-submit protection.
- **Cheque requires number/bank** — enforced on create (form + create serializer);
  **not** enforced on `PaymentSerializer.update` (PATCH/PUT via API) nor on the
  model `clean()`, so an existing payment can be switched to `cheque` with no
  cheque number. *Expected:* validation consistent across create and update.
- **`installment` FK deleted / mismatched** — `SET_NULL` on Payment.installment and
  `SET_NULL` on Refund.original_payment; form/serializer validate the installment
  belongs to the booking. `installment.plan` could itself be `None` (SET_NULL on
  Installment.plan?) — the create serializer dereferences
  `installment.plan.booking_id` (`serializers.py:174`) and would raise
  `AttributeError` on a plan-less installment → 500 instead of a clean 400.
- **`amount_in_words` precision** — `int(round(amount))` (`utils.py:4`) drops paisa
  and rounds. For amounts ≥ `10^11` the crore component exceeds 99 and
  `_num_to_words` falls through to `str(n)` (`utils.py:45`), emitting raw digits
  like "100000 Crore". Pakistani Crore/Lakh handling is correct for the typical
  range. *Expected:* defined behaviour for paisa and very large sums.

## 6. Cross-cutting risks

- **XSS** — no `|safe` / `mark_safe` / `autoescape off` found in the payment,
  refund, or receipt templates; `notes`, `method_data` values, `bounce_reason`,
  and `cancellation_reason` are all rendered through Django auto-escaping. The
  `get_item` filter (`payment_tags.py:6-11`) returns raw values that are still
  auto-escaped. `payment_form.html` uses `|escapejs` for customer/project strings
  injected into JS (`payment_form.html:309-313`). Low risk.
- **CSRF** — all state-changing web forms include `{% csrf_token %}` (verify/reject/
  bounce/reverse in `payment_detail.html:49-68`; refund approve/process in
  `refunds.html:102-117`). The DRF actions (`verify`, `mark_bounced`, `approve`,
  `reject`, `process`) are session-authenticated and subject to DRF's
  `SessionAuthentication` CSRF enforcement. No `@csrf_exempt` found in the module.
- **IDOR / BOLA** — `pk`-based detail/PDF/refund views have no object ownership
  check (role-based only). The standout is `ReceiptViewSet` = `IsAuthenticated`
  (`api_views.py:266`), exposing every receipt (CNIC, phone, address, amounts) to
  any authenticated user including non-finance roles and portal customers.
- **Sensitive data exposure** — `PaymentSerializer` returns `customer_name`,
  `booking_id_display`, `notes`, `reference_number`, `cheque_number`, `bank_name`,
  and full `method_data` (bank account numbers, mobile numbers) to any
  `IsStaffReadAdminWrite` reader (any authenticated user can GET via
  `has_permission` SAFE_METHODS return True, `api_views.py:20-21`). `RefundSerializer`
  exposes `supporting_document_url`, `notes`, `approved_by_name`,
  `processed_by_name`. `generate_customer_profile_pdf` (`pdf_utils.py:61-78`)
  renders CNIC/phone/address; its view `customer_profile_pdf_view` in
  `core/views.py:1811` is `@login_required` **only** — any authenticated user can
  download a full customer profile PDF.
- **Accessibility** — receipt and payment templates rely on emoji icons and
  inline `onclick` handlers; form labels exist but the `payment_form.html`
  floating-group inputs rely on `placeholder=" "` (label association present via
  `for=`). Contrast/branding tokens are theme-driven. Not exhaustively audited
  here; the WhatsApp/Print/Email share links on `receipt_detail.html:24-25` are
  keyboard-focusable anchors.

## 7. API surface

Router registration at `api/urls.py:66-70` (`payments`, `receipts`, `refunds`,
`payment-allocations`).

| Method + path | Handler | Permission | Notable request fields | Response |
|---|---|---|---|---|
| GET `/api/payments/` | PaymentViewSet.list | IsStaffReadAdminWrite (read: any auth) | filters `status`, `method`, `booking`, `date_from`, `date_to`, `search` (via queryset) | PaymentSerializer[] |
| POST `/api/payments/` | PaymentViewSet.create | write roles | PaymentCreateSerializer (amount>0, cheque requires cheque_number+bank_name, installment-belongs-to-booking) | PaymentSerializer (status `pending`) |
| GET `/api/payments/{pk}/` | retrieve | read: any auth | — | PaymentDetailSerializer (receipts/allocations/attachments nested) |
| PUT/PATCH `/api/payments/{pk}/` | update | write roles | PaymentSerializer (no cheque validation on update) | PaymentSerializer |
| POST `/api/payments/{pk}/verify/` | verify | super_admin/admin only | `action`=verify/reject, `notes` | PaymentSerializer |
| POST `/api/payments/{pk}/mark_bounced/` | mark_bounced | write roles (no explicit check) | `bounce_reason`, `bounce_fee` | PaymentSerializer |
| POST `/api/payments/{pk}/upload_attachment/` | upload_attachment | write roles | `file`, `attachment_type` | PaymentAttachmentSerializer |
| GET `/api/receipts/` | ReceiptViewSet.list | **IsAuthenticated** | `payment` filter | ReceiptSerializer[] |
| GET `/api/receipts/{pk}/` | retrieve | **IsAuthenticated** | — | ReceiptSerializer |
| GET/POST `/api/refunds/` | RefundViewSet | IsStaffReadAdminWrite | RefundSerializer (amount>0, amount≤refundable) | RefundSerializer |
| POST `/api/refunds/{pk}/approve/` | approve | write roles | — | RefundSerializer |
| POST `/api/refunds/{pk}/reject/` | reject | write roles | `notes` | RefundSerializer |
| POST `/api/refunds/{pk}/process/` | process | write roles | — | RefundSerializer |
| CRUD `/api/payment-allocations/` | PaymentAllocationViewSet | IsStaffReadAdminWrite | PaymentAllocationSerializer | PaymentAllocationSerializer |

Serializer validation notes: `RefundSerializer.validate` computes `refundable`
but **does not exclude self on update** (bug, §5). `PaymentSerializer` lacks the
cheque-method validation present in `PaymentCreateSerializer`.

## 8. Test data & fixtures needed

- Roles: create users for each of `sales`, `accounts`, `management`, `admin`,
  `super_admin` (plus one `is_superuser`) to exercise every decorator/DRF branch.
  `sales` is the critical negative case (excluded from `payments_access` but
  **included** in `ReceiptViewSet`'s `IsAuthenticated`).
- Seed: a `Project` → `Plot` → `Booking` (status `active`/`confirmed`) with
  `total_amount` set and `advance_paid=0`; an `InstallmentPlan` with at least one
  `Installment` (`pending`); a `Booking` with **no** payments for the refund-zero
  case.
- Isolation: payment auto-IDs are derived from the last row's numeric suffix —
  tests must not assume `PAY-00001` unless the table is truncated; prefer
  asserting uniqueness/format, not exact IDs. Same for `RCP-*`/`receipt_number`
  (fiscal-year-scoped). Timestamp receipts (`receipt_date`) across the June/July
  boundary to cover FY rollover.
- Concurrency: to reproduce the double-verify / double-approve / receipt-number
  races, run against PostgreSQL (SQLite `select_for_update` is a no-op); use
  `TransactionTestCase` or threads hitting the same pk.

## 9. Key files

- `payments/models.py` — Payment / PaymentAllocation / Refund / Receipt /
  PaymentAttachment, auto-IDs, refund workflow, receipt fiscal numbering.
- `payments/forms.py` — PaymentForm (cheque + installment + amount validation),
  RefundForm (refundable cap, excludes self), PaymentFilterForm.
- `payments/serializers.py` — Payment(Detail/Create)Serializer, RefundSerializer
  (validate **does not** exclude self), ReceiptSerializer, AllocationSerializer,
  PaymentVerificationSerializer.
- `payments/api_views.py` — IsStaffReadAdminWrite, PaymentViewSet (verify,
  mark_bounced, upload_attachment), ReceiptViewSet (IsAuthenticated), RefundViewSet
  (approve/reject/process), PaymentAllocationViewSet.
- `payments/views_workflow.py` — verify/reject/bounce/reverse views + refund
  list/create/approve/process views (web, decorator-gated).
- `payments/pdf_utils.py` — xhtml2pdf render, receipt/invoice/customer-profile PDFs.
- `payments/utils.py` — `amount_in_words` (Pakistani Crore/Lakh), `_num_to_words`.
- `payments/admin.py` — Payment/Receipt/Refund/Allocation admin (readonly auto IDs,
  delete only superuser).
- `payments/views.py` — empty stub (all logic in `core/views.py`).
- `payments/templatetags/payment_tags.py` — `get_item` filter.
- `core/views.py` (1482–1822) — payments_view, payment_create_view (auto-verify +
  duplicate check + notifications), payment_detail_view, receipt_detail_view,
  receipt_pdf_view, invoice_pdf_view, customer_profile_pdf_view.
- `templates/payments.html`, `payment_detail.html`, `payment_form.html`,
  `refunds.html`, `refund_form.html`, `receipt_detail.html`, `receipt_pdf.html`.
- `finance/models.py` — AccountTransaction + `account_transaction_reference_unique`.
- `bookings/models.py` — Booking status/`remaining_balance`/`advance_paid`/
  `amount_paid` (revenue source of truth).
- `core/permissions.py` — role groups + decorators used by the web views.
