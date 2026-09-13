# Payments — Test Plan

> Module: `payments/` (models, forms, serializers, DRF ViewSets, workflow views, PDFs)
> plus the payment/receipt/refund views in `core/views.py`. Scenario IDs are the
> contract Phase C test names must match. Prefix `PAY`.

## 1. Scope & roles

This plan covers the money-in / money-out spine of the ERP: recording, verifying,
rejecting, bouncing and reversing customer payments; installment allocation;
fiscal receipts (July–June `receipt_number`) and their PDFs; and the full refund
lifecycle (create → approve → process → exactly one ledger row). It also covers
the DRF API surface and the authorization/IDOR gaps unique to this module.

The single most important invariant under test: **`Booking.advance_paid` is the
source of truth for revenue** (`dashboard_view`). Every verify adds to it; every
reverse / bounce-of-verified / refund-approval subtracts from it. All scenarios
that touch these paths assert `advance_paid` and installment `paid_amount`
exactly (Decimal(15,2), no loose flooring).

Roles exercised (each is both a positive and a negative case where noted):

| Role | Expected access |
|---|---|
| `super_admin` / `admin` (incl. Django `is_superuser`) | full web + API: list/detail/record, verify/reject/bounce/reverse, refund approve/process |
| `management` | list/detail/record payments, refunds list/create, refund **process** (web); NOT verify/reject/bounce/reverse, NOT refund approve (web) |
| `accounts` | list/detail/record payments, refunds list/create; NOT verify/reject/bounce/reverse, NOT refund approve/process (web) |
| `sales` (also default role) | **denied** everything on web (`payments_access` excludes it) — but see SEC-01/SEC-02/SEC-05 where `IsAuthenticated`/`@login_required` leaks data |
| `staff` / `contractor` / `project_manager` / portal customer | denied web payments; only the `IsAuthenticated`/`@login_required` leaks apply |

## 2. Preconditions & fixtures

Seed data (create fresh per run; never assume exact auto-IDs — they derive from
the last row's numeric suffix):

- A `Project` → `Plot` (with `total_cost` set) → `Booking` in status `active` with
  `total_amount = 1,000,000` and `advance_paid = 0`.
- An `InstallmentPlan` (1:1 to the booking) with at least one `Installment`
  (`status='pending'`, `amount = 500,000`, `paid_amount = 0`).
- A second `Booking` with **no** payments (for the refund-zero / no-installment cases).
- Users: one each of `sales`, `accounts`, `management`, `admin`, `super_admin`,
  plus one Django `is_superuser`. Timestamp/unique-suffix the created objects
  (e.g. `QA-PAY-{timestamp}` customer) so parallel runs never collide.
- Money assertions: assert Decimal values exactly (`==`), never `>=`/`<=` alone.

Web URLs (relative to `http://127.0.0.1:8000`):

| Path | View | Permission |
|---|---|---|
| `/payments/` | `payments_view` | `payments_access` |
| `/payments/create/` | `payment_create_view` (auto-verify) | `payments_access` |
| `/payments/<pk>/` | `payment_detail_view` | `payments_access` |
| `/payments/<pk>/verify/` | `payment_verify_view` | `admin_or_above` |
| `/payments/<pk>/reject/` | `payment_reject_view` | `admin_or_above` |
| `/payments/<pk>/bounce/` | `payment_bounce_view` | `admin_or_above` |
| `/payments/<pk>/reverse/` | `payment_reverse_view` | `admin_or_above` |
| `/receipts/<pk>/` | `receipt_detail_view` | `payments_access` |
| `/receipts/<pk>/pdf/` | `receipt_pdf_view` | `payments_access` |
| `/refunds/` | `refunds_view` | `finance_or_above` |
| `/refunds/create/` | `refund_create_view` | `finance_or_above` |
| `/refunds/<pk>/approve/` | `refund_approve_view` (handles `action=reject` too) | `admin_or_above` |
| `/refunds/<pk>/process/` | `refund_process_view` | `management_or_above` |
| `/customers/<pk>/pdf/` | `customer_profile_pdf_view` | `login_required` only |

API URLs (DRF router, session-auth):

| Method + path | Permission |
|---|---|
| GET/POST `/api/payments/` | `IsStaffReadAdminWrite` (read: any auth) |
| GET/PUT/PATCH `/api/payments/{pk}/` | same |
| POST `/api/payments/{pk}/verify/` (`action`=verify\|reject) | in-method: super_admin/admin only |
| POST `/api/payments/{pk}/mark_bounced/` | write roles, **no explicit role check** |
| POST `/api/payments/{pk}/upload_attachment/` | write roles |
| GET/POST `/api/refunds/`, POST `/api/refunds/{pk}/approve\|reject\|process/` | `IsStaffReadAdminWrite` |
| GET `/api/receipts/`, GET `/api/receipts/{pk}/` | **`IsAuthenticated`** (read-open) |

## 3. Scenario catalog

### HP — happy path

#### PAY-HP-01 — Record payment (web) verifies immediately
- **Preconditions:** `admin` session; booking B1 (`total_amount=1,000,000`, `advance_paid=0`) with installment I1 (`amount=500,000`, `paid_amount=0`).
- **Steps:**
  1. Login as `admin`.
  2. GET `/payments/create/`; fill amount `300,000`, method `bank_transfer`, type `down_payment`, select booking B1 and installment I1.
  3. Submit (POST `/payments/create/`).
- **Expected result:** Payment row created with `status='verified'` (NOT `pending`); `B1.advance_paid == 300,000`; `I1.paid_amount == 300,000`, `I1.status='partial'`; a `Receipt` row exists for the payment with a generated `receipt_number`; `receipt_generated=True`; an `AuditLog` entry and a confirmation + receipt notification are created.
- **Evidence on failure:** booking detail / dashboard revenue still shows `advance_paid=0` or a `pending` payment; missing Receipt row in admin; empty `NotificationLog` when `EMAIL_ENABLED`.

#### PAY-HP-02 — Verify a pending payment (adds advance_paid, receipt, installment recalc)
- **Preconditions:** a `pending` payment P1 (`amount=200,000`, booking B1, installment I1) created via `POST /api/payments/`; `admin` session.
- **Steps:**
  1. GET `/payments/<P1>/`; confirm status shows `pending`.
  2. POST `/payments/<P1>/verify/`.
- **Expected result:** `P1.status='verified'`, `verified_by=admin`, `verified_at` set; `B1.advance_paid += 200,000`; `I1.paid_amount += 200,000`; `I1.status` recalculated; a `Receipt` is auto-generated (`receipt_number` set); installment plan `recalculate()` reflects the paid amount; `B1.status` flips to `completed` if `remaining_balance <= 0`.
- **Evidence on failure:** `advance_paid` or `I1.paid_amount` unchanged/incorrect; no Receipt; plan totals stale.

#### PAY-HP-03 — Reject a pending payment
- **Preconditions:** a `pending` payment P1 on booking B1; `admin` session; note B1's `advance_paid` before the step.
- **Steps:** POST `/payments/<P1>/reject/`.
- **Expected result:** `P1.status='rejected'`; `B1.advance_paid` and `I1.paid_amount` are **unchanged** (no financial effect); no Receipt generated; `AuditLog` entry written.
- **Evidence on failure:** `advance_paid` moved despite rejection; Receipt created for a rejected payment.

#### PAY-HP-04 — Bounce a pending cheque (no financial effect)
- **Preconditions:** a `pending` cheque payment P1 (with `cheque_number`, `bank_name`) on booking B1; `admin` session.
- **Steps:** POST `/payments/<P1>/bounce/` with `bounce_reason='insufficient funds'`.
- **Expected result:** `P1.status='bounced'`, `bounce_reason` stored; `B1.advance_paid`/`I1.paid_amount` unchanged; no Receipt; `AuditLog` entry.
- **Evidence on failure:** balance changed; reason not persisted.

#### PAY-HP-05 — Reverse a verified payment (restores advance_paid, cancels receipt)
- **Preconditions:** booking B1 with a verified payment P1 (`amount=200,000`, installment I1); `advance_paid=200,000`, `I1.paid_amount=200,000`, `B1.status='completed'` if it closed the balance; a Receipt exists for P1.
- **Steps:** POST `/payments/<P1>/reverse/`.
- **Expected result:** `P1.status='reversed'`; `B1.advance_paid == 0` (floored, never negative); `I1.paid_amount == 0`, `I1.status='pending'`, `paid_date=None`; `B1.status` back to `active` when `remaining_balance > 0`; the linked Receipt is cancelled; `AuditLog` entry.
- **Evidence on failure:** `advance_paid`/`I1.paid_amount` not restored; receipt still active; booking left `completed`.

#### PAY-HP-06 — Receipt PDF renders and downloads
- **Preconditions:** a verified payment with an auto-generated Receipt; `accounts` session (allowed by `payments_access`).
- **Steps:** GET `/receipts/<pk>/` then GET `/receipts/<pk>/pdf/`.
- **Expected result:** detail page shows `receipt_number` (e.g. `RCP-FY25-26/00001`), customer name/CNIC/phone/address, booking/plot, amount; PDF endpoint returns HTTP 200 with `Content-Type: application/pdf` and non-empty body; amount matches the payment exactly.
- **Evidence on failure:** 500 from xhtml2pdf; PDF blank/garbled; wrong amount or fiscal-year string.

#### PAY-HP-07 — Refund create → approve → process (advance_paid reduced once; exactly one ledger row)
- **Preconditions:** booking B1 with `advance_paid=500,000` from verified payments; `accounts` session to create, `admin` to approve, `management` to process.
- **Steps:**
  1. As `accounts`, POST `/refunds/create/` with amount `100,000`, reason `cancellation`, `refund_method`.
  2. As `admin`, POST `/refunds/<pk>/approve/`.
  3. As `management`, POST `/refunds/<pk>/process/`.
- **Expected result:** refund created `status='pending'`; on approve `status='approved'`, `approved_by=admin`, **`B1.advance_paid == 400,000`** (reduced at approve, floored ≥0); on process `status='processed'`, `processed_by`/`processed_date` set, and **exactly one** `AccountTransaction` row with `reference_type='Refund'`, `reference_id=<pk>`, direction `out`, type `refund`. Re-running process does not create a second ledger row (idempotent).
- **Evidence on failure:** `advance_paid` reduced twice; `AccountTransaction.objects.filter(reference_type='Refund', reference_id=<pk>).count() != 1`.

#### PAY-HP-08 — amount_in_words (Pakistani Crore/Lakh)
- **Preconditions:** any verified payment.
- **Steps:** for representative amounts, call the helper (via receipt/invoice PDF or shell): `12,345,678` → "Twelve Crore Thirty Four Lakh Fifty Six Thousand Seven Hundred Seventy Eight"; `9,99,999` (999999) → "Nine Lakh Ninety Nine Thousand Nine Hundred Ninety Nine".
- **Expected result:** correct Crore/Lakh grouping (not million/billion); `1,000` → "One Thousand"; `0` → "Zero".
- **Evidence on failure:** western grouping words ("Million"/"Billion") or digit strings leaking into the receipt PDF.

### EC — edge case / boundary

#### PAY-EC-01 — Reverse a draft/pending payment corrupts balances (no status guard) — CRITICAL
- **Preconditions:** booking B1 already has a verified payment P1 (`amount=500,000`) so `advance_paid=500,000` and `I1.paid_amount=500,000`. Create a second payment P2 via `POST /api/payments/` → `status='pending'`, `amount=100,000` (never verified, zero financial effect so far).
- **Steps:**
  1. Note `B1.advance_paid=500,000` and `I1.paid_amount=500,000`.
  2. As `admin`, POST directly to `/payments/<P2>/reverse/` (bypass the UI, which hides the button).
- **Expected result (correct):** reversing a non-verified payment is rejected or a no-op — balances stay at 500,000.
- **Actual observed defect:** `payment_reverse_view` has no status guard; it sets `P2.status='reversed'`, subtracts `P2.amount` from `I1.paid_amount` (→ `400,000`) and from `B1.advance_paid` (→ `400,000`), corrupting balances that belong to P1.
- **Evidence on failure:** `B1.advance_paid == 400,000` and `I1.paid_amount == 400,000` with only P1 ever verified; dashboard revenue drops by 100,000 with no matching reversal of a verified payment; no error message shown.

#### PAY-EC-02 — Concurrent double-verify race (no select_for_update) — CRITICAL
- **Preconditions:** a `pending` payment P1 (`amount=200,000`) on booking B1 (`advance_paid=0`, installment I1). Run against PostgreSQL (SQLite `select_for_update` is a no-op, so reproduce there for a reliable race).
- **Steps:**
  1. Fire two concurrent `POST /api/payments/<P1>/verify/` (two threads / two tabs) simultaneously.
- **Expected result:** at-most-once financial effect — `P1.status='verified'`, `B1.advance_paid == 200,000`, `I1.paid_amount == 200,000`, one Receipt.
- **Actual observed defect:** the status guard is read before the transaction and neither view nor API locks the row; both requests observe `pending` and both run `_apply_payment_effects`.
- **Evidence on failure:** `B1.advance_paid == 400,000` (double-counted), `I1.paid_amount == 400,000`, two Receipts / two `AuditLog` entries for one payment.

#### PAY-EC-03 — Double-approve refund reduces advance_paid twice — CRITICAL
- **Preconditions:** booking B1 `advance_paid=500,000`; a `pending` refund R1 (`amount=100,000`).
- **Steps:**
  1. As `admin`, POST `/refunds/<R1>/approve/` twice (double-click, or two tabs).
- **Expected result:** idempotent — `advance_paid == 400,000` and one approve in the audit log.
- **Actual observed defect:** `refund_approve_view` does not check `status=='pending'` before `apply_approval`, and `apply_approval` does not guard status; each POST subtracts again.
- **Evidence on failure:** `B1.advance_paid == 300,000` (reduced twice); two `AuditLog` "approved" entries for the same refund.

#### PAY-EC-04 — Serializer validate double-counts self on update (editing an existing refund rejected)
- **Preconditions:** booking B1 with `total_paid = 100,000` (one verified payment); a refund R1 (`amount=100,000`) already created. Approve R1 via web so it is `approved`.
- **Steps:** as a write role, `PATCH /api/refunds/<R1>/` changing only `notes` (or `refund_date`) without changing `amount`.
- **Expected result:** partial update succeeds (200).
- **Actual observed defect:** `RefundSerializer.validate` computes `total_refunded` including R1's own amount (unlike the model property and form, which exclude self), so `refundable = 100,000 − 100,000 = 0` and `amount 100,000 > 0` → rejected as over-refundable.
- **Evidence on failure:** HTTP 400 with "exceeds refundable amount" on a note-only edit; a refund that cannot be amended after approval.

#### PAY-EC-05 — Overpayment silently capped
- **Preconditions:** booking B1 `total_amount=1,000,000`, `advance_paid=0`.
- **Steps:** POST `/payments/create/` with amount `1,200,000` (bypass the client JS guard via direct form POST).
- **Expected result:** overpayment is surfaced (warning + explicit `unallocated_amount` handling), not silently discarded.
- **Actual observed defect:** server form allows it ("Allow but warn" is a no-op `pass`), and `advance_paid` is silently capped at `1,000,000`; the excess `200,000` is only reflected in `unallocated_amount` if an installment exists, otherwise recorded nowhere.
- **Evidence on failure:** `B1.advance_paid == 1,000,000` with no warning and the excess `200,000` unaccounted for; no `unallocated_amount` row when no installment was selected.

#### PAY-EC-06 — Refund amount > refundable rejected
- **Preconditions:** booking B1 with `total_paid=300,000` (verified), `total_refunded=0`.
- **Steps:** attempt refund of `350,000` via web form and via `POST /api/refunds/`.
- **Expected result:** rejected by model `clean`, form `clean`, and serializer `validate` — HTTP 400 / form error; no refund row created.
- **Evidence on failure:** a refund row with `amount > refundable_amount` persists, or `advance_paid` later drops below 0.

#### PAY-EC-07 — Receipt fiscal-year June/July boundary
- **Preconditions:** a booking with two payments whose `payment_date`s are `2026-06-30` and `2026-07-01`.
- **Steps:** record/verify each and read the generated `receipt_number`.
- **Expected result:** 30-June receipt lands in the ending FY (`RCP-FY25-26/…`); 1-July receipt starts the new FY (`RCP-FY26-27/…`).
- **Evidence on failure:** both receipts share one FY prefix, or the boundary is off by one year.

#### PAY-EC-08 — Receipt sequential numbering per FY + uniqueness
- **Preconditions:** several payments in the same FY.
- **Steps:** generate 3 receipts in one FY.
- **Expected result:** `receipt_number` suffixes `…/00001`, `…/00002`, `…/00003` (zero-padded, lexicographically ordered) and all unique; a different FY restarts at `00001`.
- **Evidence on failure:** non-sequential suffix, duplicate `receipt_number` (unique-constraint IntegrityError), or mis-ordered numbering past 99,999 (lexicographic `order_by('-receipt_number')` puts `100000` before `99999`).

#### PAY-EC-09 — Duplicate-payment 60s heuristic
- **Preconditions:** booking B1; `admin` session.
- **Steps:** record payment (amount `250,000`, method `bank_transfer`, same date) twice within 60 seconds; then record a third with a changed `payment_date` (or method) within 60s.
- **Expected result:** the identical second submit within 60s is blocked with a "possible duplicate" message; the third (differing date/method) is allowed.
- **Actual observed defect:** heuristic only — no DB idempotency key; two legitimately identical payments >60s apart, or a changed field, bypass it.
- **Evidence on failure:** a true double-submit (same booking/amount/date/method) within 60s creates two verified payments and double-counts `advance_paid`.

#### PAY-EC-10 — Refund on a booking with no payments
- **Preconditions:** booking B2 with zero payments (`total_paid=0`).
- **Steps:** attempt a refund of any positive amount.
- **Expected result:** rejected — `refundable_amount=0`, HTTP 400 / form error.
- **Evidence on failure:** a refund row created against a booking with no verified payments.

#### PAY-EC-11 — mark_bounced non-numeric bounce_fee → 400 not 500
- **Preconditions:** a verified payment P1 (or pending).
- **Steps:** `POST /api/payments/<P1>/mark_bounced/` with `bounce_fee="abc"` (string, not coerced).
- **Expected result:** HTTP 400 validation error.
- **Actual observed defect:** `request.data.get('bounce_fee', 0)` is not coerced; the string raises at save.
- **Evidence on failure:** HTTP 500 (server error) with a Decimal coercion traceback.

#### PAY-EC-12 — Cheque method without cheque_number on update (API PATCH)
- **Preconditions:** a non-cheque payment P1.
- **Steps:** `PATCH /api/payments/<P1>/` setting `payment_method='cheque'` with no `cheque_number`/`bank_name`.
- **Expected result:** rejected — cheque requires `cheque_number` + `bank_name` on create **and** update.
- **Actual observed defect:** cheque validation exists only in `PaymentCreateSerializer` and the form; `PaymentSerializer.update` (and model `clean`) do not enforce it.
- **Evidence on failure:** P1 becomes `cheque` with a null cheque number.

#### PAY-EC-13 — amount_in_words very large sum (≥ 10^11)
- **Preconditions:** none (unit-level).
- **Steps:** call `amount_in_words(100_000_000_000)` (10^11).
- **Expected result:** defined behaviour — either full words or an explicit guard.
- **Actual observed defect:** the crore component exceeds 99 and `_num_to_words` falls through to `str(n)`, emitting raw digits like "100000 Crore".
- **Evidence on failure:** receipt/invoice PDF shows raw digits embedded in the words line.

#### PAY-EC-14 — Reverse a payment with no installment
- **Preconditions:** a verified payment P1 with `installment=None` on booking B1 (`advance_paid=200,000`).
- **Steps:** POST `/payments/<P1>/reverse/`.
- **Expected result:** only `B1.advance_paid` is reduced (→ 0); no installment block executes (guarded by `if payment.installment`); no error.
- **Evidence on failure:** an `AttributeError`/500, or `advance_paid` not reduced.

### SEC — negative & security

#### PAY-SEC-01 — ReceiptViewSet IsAuthenticated leaks CNIC/phone/address/amounts — CRITICAL
- **Preconditions:** at least one Receipt exists; a low-privilege authenticated user with role `sales` (excluded from web `payments_access`) and a portal customer session.
- **Steps:**
  1. Login as `sales`.
  2. `GET /api/receipts/` and `GET /api/receipts/<pk>/`.
  3. Repeat with a portal customer session.
- **Expected result:** `sales` and portal customers are denied (403) — receipts are finance-only data.
- **Actual observed defect:** `ReceiptViewSet.permission_classes = [IsAuthenticated]`, so any authenticated session lists and retrieves **every** receipt, exposing customer name, CNIC, phone, address, booking/plot info and amounts.
- **Evidence on failure:** HTTP 200 with the full `ReceiptSerializer` body containing CNIC/phone/address/amounts under a `sales` or customer session.

#### PAY-SEC-02 — IDOR on payment/receipt/refund detail + PDF views (role-based only)
- **Preconditions:** two bookings B1 (owned by staff A) and B2 (owned by staff B); an `accounts` session (a shared finance role).
- **Steps:** as `accounts`, directly GET `/payments/<pk>/`, `/receipts/<pk>/`, `/receipts/<pk>/pdf/`, and the refund detail for any booking (no ownership relation required).
- **Expected result (acceptable per design):** finance roles may read cross-object — BUT confirm a non-finance role is denied at the decorator layer.
- **Actual observed defect:** no object-level ownership check anywhere; the only gate is role. The key negative: confirm `sales`/portal cannot reach these via direct URL.
- **Evidence on failure:** a non-finance role receives a 200 (not a `/dashboard/` redirect/403) on these detail/PDF URLs.

#### PAY-SEC-03 — API looser than web: accounts can approve/process refunds via API
- **Preconditions:** a `pending` refund R1; an `accounts` session.
- **Steps:** `POST /api/refunds/<R1>/approve/` then `POST /api/refunds/<R1>/process/` as `accounts`.
- **Expected result:** denied — web `refund_approve_view` is `admin_or_above` and `refund_process_view` is `management_or_above`.
- **Actual observed defect:** `RefundViewSet` only requires `IsStaffReadAdminWrite`, so `accounts` approves and processes via API.
- **Evidence on failure:** HTTP 200 and `B1.advance_paid` reduced / a ledger row posted by an `accounts` action that the web UI forbids.

#### PAY-SEC-04 — API looser than web: accounts can mark_bounced (reverse verified) via API
- **Preconditions:** a verified payment P1 on booking B1; an `accounts` session.
- **Steps:** `POST /api/payments/<P1>/mark_bounced/` as `accounts`.
- **Expected result:** denied — web `payment_bounce_view` is `admin_or_above` and refuses verified payments.
- **Actual observed defect:** `mark_bounced` has no explicit role check and does reverse verified payments (unlike the web bounce).
- **Evidence on failure:** HTTP 200, `P1.status='bounced'`, and `B1.advance_paid` reduced by an `accounts` user.

#### PAY-SEC-05 — customer_profile_pdf_view is @login_required only
- **Preconditions:** a customer with CNIC/phone/address; a `sales` or portal customer session.
- **Steps:** GET `/customers/<pk>/pdf/` as `sales` (or a portal customer).
- **Expected result:** denied for non-finance/non-authorized roles.
- **Actual observed defect:** `@login_required` only — any authenticated user downloads a full customer profile PDF (CNIC, phone, address).
- **Evidence on failure:** HTTP 200 PDF containing PII returned to a `sales`/customer session.

#### PAY-SEC-06 — Payment/Refund serializers leak method_data, cheque_number, notes
- **Preconditions:** a payment with `method_data` containing bank account/mobile numbers, `cheque_number`, `bank_name`, `reference_number`, `notes`; a refund with `notes`, `supporting_document_url`.
- **Steps:** as any authenticated read-only user (e.g. `sales`), `GET /api/payments/<pk>/` and `GET /api/refunds/<pk>/`.
- **Expected result:** sensitive fields masked/omitted for non-finance readers.
- **Actual observed defect:** `IsStaffReadAdminWrite` returns True for all SAFE_METHODS, so any authenticated user receives the full serializers including `method_data`, `cheque_number`, `bank_name`, `reference_number`, `notes`, and refund `notes`/`supporting_document_url`.
- **Evidence on failure:** response body contains account numbers / cheque numbers under a `sales` session.

#### PAY-SEC-07 — sales denied web payments (positive control)
- **Preconditions:** a `sales` session.
- **Steps:** GET `/payments/`, `/payments/create/`, `/payments/<pk>/`.
- **Expected result:** each redirects to `/dashboard/` with an access-denied message (HTTP 302, not 200).
- **Evidence on failure:** 200 rendered page; no redirect; ability to record a payment.

#### PAY-SEC-08 — refunds.html shows Approve/Reject/Process buttons without can_manage_users guard
- **Preconditions:** an `accounts` session (finance role that can list refunds but not approve/process).
- **Steps:** GET `/refunds/` and click the visible Approve/Process button.
- **Expected result:** buttons hidden for `accounts`, or a clear "not authorized" message.
- **Actual observed defect:** template renders Approve/Reject/Process with no `{% if can_manage_users %}` guard; clicking routes to an `admin_or_above`/`management_or_above` view and silently redirects to `/dashboard/`.
- **Evidence on failure:** Approve/Process buttons visible to `accounts`; click produces a silent `/dashboard/` redirect with no action taken.

### API — API contract

#### PAY-API-01 — POST /api/payments/ creates pending (vs web verified)
- **Preconditions:** a write role session; booking B1, installment I1.
- **Steps:** `POST /api/payments/` with `{booking, installment, amount: 200000, payment_method: 'bank_transfer', payment_type: 'installment', payment_date}`.
- **Expected result:** HTTP 201; `status='pending'` (NOT verified); no `advance_paid`/installment change; no Receipt yet; `payment_id` `PAY-…` auto-assigned. `amount<=0` → 400; cheque without `cheque_number`/`bank_name` → 400; installment of a different booking → 400.
- **Evidence on failure:** created as `verified`; `advance_paid` bumped on create; validation bypassed.

#### PAY-API-02 — GET /api/payments/ list + retrieve (any auth read)
- **Preconditions:** `sales` session (read-only).
- **Steps:** `GET /api/payments/` and `GET /api/payments/<pk>/`.
- **Expected result:** HTTP 200 (read-open by design) — but confirm the response includes exactly the documented fields and the filters (`status`, `method`, `booking`, `date_from`, `date_to`, `search`) work. Cross-check the exposure against SEC-06.
- **Evidence on failure:** 403 on a read for an authenticated user, or missing/filter-broken fields.

#### PAY-API-03 — verify/reject action (role + status guard)
- **Preconditions:** a `pending` payment P1; `accounts` session (write role but not admin).
- **Steps:**
  1. `POST /api/payments/<P1>/verify/` with `{action:'verify'}` as `accounts`.
  2. Repeat as `super_admin`, then verify again (double-verify).
- **Expected result:** `accounts` → 403; `super_admin` first verify → 200 + financial effect applied once; second verify → rejected/no-op (status guard).
- **Evidence on failure:** `accounts` verify succeeds (200); double-verify double-counts `advance_paid`.

#### PAY-API-04 — mark_bounced action reverses a verified payment
- **Preconditions:** a verified payment P1; `accounts` session.
- **Steps:** `POST /api/payments/<P1>/mark_bounced/` with `{bounce_reason}`.
- **Expected result (per web parity):** refused — web cannot bounce a verified payment.
- **Actual observed defect:** API reverses the verified payment (installment + `advance_paid` reduced, receipts cancelled) with no role check.
- **Evidence on failure:** HTTP 200; `advance_paid` reduced; `P1.status='bounced'`.

#### PAY-API-05 — Refund create + approve/reject/process actions
- **Preconditions:** booking B1 `total_paid=500,000`; `accounts` and `management` sessions.
- **Steps:** `POST /api/refunds/` (amount 100,000) → `approve` → `process`; also exercise `reject` on a second refund.
- **Expected result:** create 201 (`pending`); approve reduces `advance_paid` once; process posts exactly one `AccountTransaction`; reject → `rejected` with no financial effect. Cross-check the role looseness against SEC-03.
- **Evidence on failure:** wrong status transitions; ledger count != 1; `advance_paid` reduced at the wrong stage.

#### PAY-API-06 — GET /api/receipts/ read-open (IsAuthenticated)
- **Preconditions:** a receipt exists; a `sales` session and an unauthenticated client.
- **Steps:** `GET /api/receipts/` authenticated as `sales`; `GET /api/receipts/` with no session.
- **Expected result:** unauthenticated → 401/403. Authenticated `sales` → should be 403 for finance data (see SEC-01).
- **Actual observed defect:** authenticated `sales` → 200 with full receipt data (IsAuthenticated).
- **Evidence on failure:** HTTP 200 with CNIC/phone/address/amounts returned to `sales`.

#### PAY-API-07 — PATCH /api/refunds/{pk} update does not exclude self (serializer bug)
- **Preconditions:** booking B1 `total_paid=100,000`; refund R1 (`amount=100,000`) approved.
- **Steps:** `PATCH /api/refunds/<R1>/` with `{notes: 'amended'}` only.
- **Expected result:** 200 (note-only edit).
- **Actual observed defect:** `validate` double-counts R1's own amount → `refundable=0` → 400 "over refundable".
- **Evidence on failure:** HTTP 400 on a note-only edit (also covered as EC-04).

#### PAY-API-08 — No reverse action on PaymentViewSet (reverse is web-only)
- **Preconditions:** a verified payment P1.
- **Steps:** attempt `POST /api/payments/<P1>/reverse/` (or discover the router action list).
- **Expected result:** documented parity — reverse exists as an API action, or is explicitly web-only.
- **Actual observed defect:** `PaymentViewSet` exposes `verify`/`mark_bounced`/`upload_attachment` only; there is no `reverse` action, so API clients cannot reverse (web-only). Confirm the router does not 500/404 unexpectedly.
- **Evidence on failure:** unexpected 404/405 vs documented behavior; or an undocumented reverse action present.

## 4. Data isolation rules

- All seeded entities use a timestamped unique suffix (e.g. `QA-PAY-20260913-<hhmmss>`), and money amounts are chosen per-scenario so parallel runs cannot cross-contaminate.
- **Never assert exact auto-IDs** (`PAY-00001`, `RCP-00001`, `receipt_number` suffix) — they derive from the last row's numeric suffix. Assert format/uniqueness instead, except where a test explicitly truncates the table first.
- Concurrency scenarios (EC-02, EC-03, EC-08) must run against **PostgreSQL** to reproduce `select_for_update`/unique-constraint behaviour; SQLite makes `select_for_update` a no-op and its write locking differs.
- Clean up per run: delete created payments, refunds, receipts, `AccountTransaction` rows (reference_type='Refund'), and the seeded bookings/plots/installments, in FK order, or run in an isolated test DB.
- Assert `advance_paid` and installment `paid_amount` as exact Decimals (`==`), never loose bounds.

## 5. Coverage checklist (for the master map)

- PAY-HP-01 — Record payment (web) verifies immediately
- PAY-HP-02 — Verify a pending payment (adds advance_paid, receipt, installment recalc)
- PAY-HP-03 — Reject a pending payment
- PAY-HP-04 — Bounce a pending cheque (no financial effect)
- PAY-HP-05 — Reverse a verified payment (restores advance_paid, cancels receipt)
- PAY-HP-06 — Receipt PDF renders and downloads
- PAY-HP-07 — Refund create → approve → process (advance_paid reduced once; exactly one ledger row)
- PAY-HP-08 — amount_in_words (Pakistani Crore/Lakh)
- PAY-EC-01 — Reverse a draft/pending payment corrupts balances (no status guard)
- PAY-EC-02 — Concurrent double-verify race (no select_for_update)
- PAY-EC-03 — Double-approve refund reduces advance_paid twice
- PAY-EC-04 — Serializer validate double-counts self on update (editing existing refund rejected)
- PAY-EC-05 — Overpayment silently capped
- PAY-EC-06 — Refund amount > refundable rejected
- PAY-EC-07 — Receipt fiscal-year June/July boundary
- PAY-EC-08 — Receipt sequential numbering per FY + uniqueness
- PAY-EC-09 — Duplicate-payment 60s heuristic
- PAY-EC-10 — Refund on a booking with no payments
- PAY-EC-11 — mark_bounced non-numeric bounce_fee → 400 not 500
- PAY-EC-12 — Cheque method without cheque_number on update (API PATCH)
- PAY-EC-13 — amount_in_words very large sum (≥ 10^11)
- PAY-EC-14 — Reverse a payment with no installment
- PAY-SEC-01 — ReceiptViewSet IsAuthenticated leaks CNIC/phone/address/amounts
- PAY-SEC-02 — IDOR on payment/receipt/refund detail + PDF views (role-based only)
- PAY-SEC-03 — API looser than web: accounts can approve/process refunds via API
- PAY-SEC-04 — API looser than web: accounts can mark_bounced (reverse verified) via API
- PAY-SEC-05 — customer_profile_pdf_view is @login_required only
- PAY-SEC-06 — Payment/Refund serializers leak method_data, cheque_number, notes
- PAY-SEC-07 — sales denied web payments (positive control)
- PAY-SEC-08 — refunds.html shows Approve/Reject/Process buttons without can_manage_users guard
- PAY-API-01 — POST /api/payments/ creates pending (vs web verified)
- PAY-API-02 — GET /api/payments/ list + retrieve (any auth read)
- PAY-API-03 — verify/reject action (role + status guard)
- PAY-API-04 — mark_bounced action reverses a verified payment
- PAY-API-05 — Refund create + approve/reject/process actions
- PAY-API-06 — GET /api/receipts/ read-open (IsAuthenticated)
- PAY-API-07 — PATCH /api/refunds/{pk} update does not exclude self (serializer bug)
- PAY-API-08 — No reverse action on PaymentViewSet (reverse is web-only)
