# Bookings — Test Plan

> Module: `bookings/` (+ booking views in `core/views.py`, installment views in `bookings/views_installments.py`, DRF surface in `bookings/api_views.py`). Companion to `docs/qa/_shared-context.md` and `docs/qa/bookings_analysis.md` — line-number references below point into those files.

## 1. Scope & roles

This plan covers the full booking lifecycle and its money/state side-effects: create (auto `BKG-xxxxx` id, plot→`booked`, verified `Payment` + `Receipt`, `advance_paid`), confirm, edit, detail, cancel (blocked while verified payments exist), reopen, transfer, installment-plan auto-generation (monthly / quarterly / balloon / `due_day` clamp), and the invoice PDF. It also covers the documented edge cases (reopen conflict, web double-create race, cancel-without-verified-payment, installment amount/rounding crashes, unclamped balance/progress, broken transfer form, stale template fields) and the security surface (IDOR on the `@login_required` booking views, the read-open `IsStaffOrAbove` API, the update-price-guard gap, and `Reservation.convert` under-selling). API contract scenarios cover the DRF `BookingViewSet` and `InstallmentPlanViewSet`/`ReservationViewSet` actions.

Roles exercised:

| Role | Expects access | Expects denial |
|---|---|---|
| `super_admin` / `admin` / `management` | list, create, detail, edit, confirm, cancel, reopen, delete, transfer, invoice PDF | — |
| `accounts` (finance) | list, detail, invoice PDF, installment plans/installments | confirm/cancel/reopen/delete/transfer (management-only) |
| `sales` | list, create, detail, edit | confirm/cancel/reopen/delete/transfer, invoice PDF (`payments_access` excludes sales) |
| **customer portal user** (a `User` linked to a `Customer`, **no** `UserProfile`) | should be denied everything booking-related | must NOT reach list/detail/edit/create, must NOT read `/api/bookings/` |

A Django `is_superuser` is always `super_admin` regardless of profile.

## 2. Preconditions & fixtures

Seed data (mirrors `api/tests_booking_pricing.py:24–40`):

- `Project` `QA Proj` (location Karachi) + `ProjectPhase` `P1` (launch_date `2026-01-01`).
- `Plot` `QA-<ts>` — unique `plot_number` per project (timestamped), `size_marla='5'`,
  `price='100000.00'`, `holding_deposit='10000.00'`, `development_charge='5000.00'`,
  `lease_charge='2000.00'`, `other_charges='1000.00'`, `status='available'`.
  → `total_charges = 8000.00`, `total_cost = 108000.00` (assert these exactly once per run).
- `Customer` with unique phone (`+92-3<ts>`) / cnic / email, and an `InstallmentPlanTemplate`
  for the balloon path (`balloon_installment_number`, `balloon_multiplier` set).
- **Customer portal user**: a `User` with a `Customer.user` OneToOne link and **no** `UserProfile`
  (create the `Customer` first; `customers/serializers.py:103` links only `customer.user`, so this
  user is authenticated but role-less). Used by every `SEC` scenario.

Create helpers once per run; never reuse booking IDs across tests (IDs are parsed from the last row's
numeric suffix, not a DB sequence — see Data isolation).

URLs (relative to `http://127.0.0.1:8000`):

| Purpose | Web URL | API URL |
|---|---|---|
| list / create | `/bookings/`, `/bookings/create/` | `GET/POST /api/bookings/` |
| detail / edit | `/bookings/<pk>/`, `/bookings/<pk>/edit/` | `GET/PATCH /api/bookings/<pk>/` |
| confirm | `/bookings/<pk>/confirm/` | `POST /api/bookings/<pk>/confirm/` |
| cancel | `/bookings/<pk>/cancel/` | `POST /api/bookings/<pk>/cancel/` |
| reopen | `/bookings/<pk>/reopen/` | *(no API action — web only)* |
| delete / transfer | `/bookings/<pk>/delete/`, `/bookings/<pk>/transfer/` | `DELETE /api/bookings/<pk>/` |
| invoice PDF | `/bookings/<pk>/invoice/` | — |
| payment summary | — | `GET /api/bookings/<pk>/payment_summary/` |
| installment plans | `/installment-plans/…`, `/installments/<pk>/mark-paid/` | `/api/installment-plans/`, `/api/installments/<pk>/mark_paid/` |
| reservation convert | — | `POST /api/reservations/<pk>/convert/` |

Login `admin` / `admin123`; staff land on `/dashboard/`, customers on `/portal/`. Run any server-backed
check with `DJANGO_DEBUG=True` (else `SECURE_SSL_REDIRECT` 301s every request).

## 3. Scenario catalog

### HP — happy path

#### BOOK-HP-01 — Create booking: auto BKG id, plot→booked, verified Payment + Receipt, advance_paid set
- **Preconditions:** `super_admin` logged in; one available `Plot` (`total_cost=108000`), one `Customer`.
- **Steps:**
  1. GET `/bookings/create/` — confirm the plot appears in the plot dropdown (form queryset filters `status='available'`).
  2. POST with `customer`, `plot`, `total_amount=108000.00`, `advance_paid=10000.00`, `source=walk_in`.
  3. After redirect to `/bookings/`, fetch the created `Booking` (latest `BKG-*`).
- **Expected result:**
  - `booking_id` matches `^BKG-\d{5}$` (assert format, not the exact number).
  - `status='pending'`, `total_amount=Decimal('108000.00')`, `advance_paid=Decimal('10000.00')`, `booking_date` set.
  - `plot.status == 'booked'`.
  - Exactly one `Payment` with `amount == 10000.00` and `status='verified'`; exactly one `Receipt` referencing it.
  - An `AuditLog` row with action `create` and the booking referenced.
  - A `NotificationLog` row for the booking notification (failure-safe — assert the log exists, not delivery).
- **Evidence on failure:** missing/extra `Payment`/`Receipt`; `plot.status != 'booked'`; `booking_id` format wrong; no `AuditLog`.

#### BOOK-HP-02 — Confirm booking requires advance_paid > 0 and transitions pending→confirmed
- **Preconditions:** `management` user; a `pending` booking from BOOK-HP-01 with `advance_paid=10000`.
- **Steps:** POST `/bookings/<pk>/confirm/`; then GET `/bookings/<pk>/`.
- **Expected result:** HTTP 302 → detail; `status='confirmed'`; an `AuditLog` "confirm" (and the `save()` status-change log); an approval notification logged (email + WhatsApp, failure-safe).
- **Evidence on failure:** status unchanged; no audit/notification; confirm of a `0`-advance booking succeeding (covered explicitly in EC/API).

#### BOOK-HP-03 — Edit booking: price guards re-applied, plot/status preserved
- **Preconditions:** `management`/`sales`; a `pending` booking (`total_cost=108000`).
- **Steps:**
  1. POST `/bookings/<pk>/edit/` with `total_amount=110000.00`, `advance_paid=12000.00`.
  2. Attempt an edit with `total_amount=107000.00` (below `total_cost`) — expect rejection.
  3. Attempt an edit with `advance_paid=5000.00` (below `holding_deposit=10000`) — expect rejection.
- **Expected result:** valid edit persists new amounts and leaves `plot.status` and `status` unchanged; invalid edits render the form again with the specific guard errors ("below the plot total cost" / "below the required holding deposit") and do not persist.
- **Evidence on failure:** under-cost / under-deposit edit persisted; plot status changed by edit.

#### BOOK-HP-04 — Booking detail renders customer/plot/amounts/notes
- **Preconditions:** any staff; an existing booking.
- **Steps:** GET `/bookings/<pk>/`.
- **Expected result:** 200; page shows customer name + phone, plot number + project/phase, `total_amount`, `advance_paid`, `remaining_balance`, `payment_progress`, status badge, and notes.
- **Evidence on failure:** missing fields; 500; blank financial values.

#### BOOK-HP-05 — Cancel blocked while verified payments exist; after refund/reversal releases plot to available
- **Preconditions:** `management`; booking with a **verified** `Payment`.
- **Steps:**
  1. POST `/bookings/<pk>/cancel/` while the verified payment exists.
  2. Reverse/refund that payment (via payments workflow) so no verified payments remain, then POST cancel again.
- **Expected result:** step 1 is refused (302 + error message, `status` unchanged, `plot` still `booked`); step 2 succeeds: `status='cancelled'`, `plot.status='available'`, `cancelled_at`/`cancelled_by`/`cancelled_reason` recorded, `AuditLog` "cancel" written.
- **Evidence on failure:** cancel succeeded with verified payments still present; plot not released; cancel metadata missing.

#### BOOK-HP-06 — Reopen a cancelled booking returns it to pending and re-reserves the plot
- **Preconditions:** `management`; a `cancelled` booking whose plot is still `available` (no re-sale).
- **Steps:** POST `/bookings/<pk>/reopen/`.
- **Expected result:** `status='pending'`, `reopened_at` set, `plot.status='reserved'`, `AuditLog` "update" written.
- **Evidence on failure:** status/plot not updated; `reopened_at` null; plot left `available`.

#### BOOK-HP-07 — Installment plan auto-generate: 12 monthly installments
- **Preconditions:** `accounts`; a booking (`total_amount=108000`, `advance_paid=10000` → balance 98000).
- **Steps:** create a plan via `/installment-plans/…` with `total_installments=12`, `frequency=monthly`, `down_payment_amount=0`, `installment_amount=8166.67` (or use `recalculate`), `due_day=1`, `start_date=2026-02-01`.
- **Expected result:** 12 `Installment` rows, `installment_number` 1..12, `due_date`s exactly one month apart, `amount>0`, plan `is_active=True`.
- **Evidence on failure:** wrong count/dates; zero amounts; `IntegrityError`.

#### BOOK-HP-08 — Installment plan auto-generate: quarterly frequency
- **Preconditions:** as BOOK-HP-07 but `frequency=quarter`.
- **Steps:** generate plan with `frequency='quarter'`.
- **Expected result:** due dates are 3 months apart (Feb→May→Aug→…).
- **Evidence on failure:** dates shifted by the wrong interval.

#### BOOK-HP-09 — Installment plan auto-generate: balloon
- **Preconditions:** an `InstallmentPlanTemplate` with `balloon_installment_number=12`, `balloon_multiplier=1.5`; plan otherwise as BOOK-HP-07.
- **Steps:** generate the plan with the template applied.
- **Expected result:** installment 12's `amount == base * 1.5`; installments 1..11 unchanged.
- **Evidence on failure:** balloon not applied, or `TypeError` from a null `balloon_multiplier`.

#### BOOK-HP-10 — Installment plan auto-generate: due_day clamp
- **Preconditions:** plan form `due_day` clamp (1–28).
- **Steps:** attempt `due_day=31` via the web form (expect form rejection), then generate a plan directly with `due_day=31` / `due_day=0` through `auto_generate`.
- **Expected result:** web form rejects out-of-range `due_day`; `auto_generate` clamps every due date to day 28 (fallback `day=28`) without error.
- **Evidence on failure:** `ValueError`; due dates with day 31/0.

#### BOOK-HP-11 — Invoice PDF
- **Preconditions:** an `accounts` (finance) user and a `sales` user.
- **Steps:** `accounts` GET `/bookings/<pk>/invoice/`; then `sales` GET the same URL.
- **Expected result:** `accounts` → 200 `application/pdf` with booking/customer/plot/amounts rendered; `sales` → redirected to `/dashboard/` with a permission message (no PDF).
- **Evidence on failure:** finance 500s / empty PDF; sales receives the PDF.

### EC — edge cases / boundaries

#### BOOK-EC-01 — Reopen conflict: plot re-sold → two active bookings (PRIORITY)
- **Preconditions:** `management`; `Plot P`; `Booking B1` on P with `advance_paid=10000` and a **verified** `Payment` auto-posted at create.
- **Steps (precise):**
  1. Reverse `B1`'s advance `Payment` (payments workflow → `reversed`), so `B1` has `advance_paid>0` but **no verified payments**.
  2. POST `/bookings/<pk>/cancel/` for `B1` → succeeds; `P` → `available`, `B1.status='cancelled'`.
  3. Create `Booking B2` on the same `P` (advance 10000, verified payment) → `P` → `booked`, `B2.status='pending'` (optionally confirm it).
  4. POST `/bookings/<pk>/reopen/` for `B1`.
- **Expected result (correct):** reopen is refused because `P` already has an active booking (`B2`); no second active booking is created.
- **Actual result (bug, `core/views.py:1307`):** reopen unconditionally sets `P.status='reserved'` with no active-booking check → `B1.status='pending'` AND `B2` still active on the same plot, and `P.status` is silently overwritten to `reserved` (clobbering `B2`'s `booked`).
- **Evidence on failure:** query `Booking.objects.filter(plot=P, status__in=('pending','confirmed','active'))` → **2 rows**; `P.status == 'reserved'` while `B2` is active.

#### BOOK-EC-02 — Web double-create race: no `select_for_update` (PRIORITY)
- **Preconditions:** `sales` (or any authenticated user); one available `Plot P`; the API path is safe but the **web** create (`booking_create_view`) has no plot lock.
- **Steps (precise):**
  1. In two independent sessions (two browsers / two `requests` POSTs fired in parallel) both load `/bookings/create/` for `P` (both see it `available`).
  2. Submit both forms near-simultaneously with the same `customer`+`plot`.
- **Expected result (correct):** exactly one booking is created; the loser is rejected with a "plot no longer available" error.
- **Actual result (bug):** both validates pass and both `save()` → two active `Booking`s on `P`, `P` left `booked`. Timing-dependent — may need a threading harness or several attempts to reproduce.
- **Evidence on failure:** `Booking.objects.filter(plot=P).count() == 2`; no error surfaced on the second submit.

#### BOOK-EC-03 — Cancel with advance_paid>0 but no verified payment row (PRIORITY)
- **Preconditions:** `management`; a booking with `advance_paid=10000` whose advance `Payment` has been **reversed** (or `advance_paid` set directly in admin) — so no `status='verified'` payment exists.
- **Steps (precise):** POST `/bookings/<pk>/cancel/`.
- **Expected result (correct):** cancel is blocked (or forces reconciliation) because `advance_paid>0` still represents collected money.
- **Actual result (bug):** the guard only counts `verified` payments, so cancel succeeds → `P.status='available'` while `advance_paid=10000` still feeds revenue.
- **Evidence on failure:** after cancel, dashboard revenue still includes the 10000 (sum of `advance_paid`) while the plot shows `available`; no refund/reconciliation row exists.

#### BOOK-EC-04 — Zero/negative installment_amount → auto_generate IntegrityError/500
- **Preconditions:** `accounts`; an `InstallmentPlan` create path where `installment_amount` is omitted/`0` or negative.
- **Steps:**
  1. Web form: submit `installment_amount=-100` (form does not validate it).
  2. API: `POST /api/installment-plans/` with default `installment_amount=0` and `generate_now=True`.
- **Expected result (correct):** both are rejected with a validation message; no installments created.
- **Actual result (bug):** `auto_generate` creates `Installment(amount<=0)` → violates `amount__gt=0` CheckConstraint → `IntegrityError` (500).
- **Evidence on failure:** HTTP 500 / stack trace referencing `amount__gt=0`.

#### BOOK-EC-05 — payment_progress / remaining_balance unclamped
- **Preconditions:** a booking with `advance_paid > total_amount` (set directly via admin/shell — no DB constraint enforces `advance <= total`).
- **Steps:** read `booking.remaining_balance` and `booking.payment_progress` (and render the detail page).
- **Expected result (correct):** `remaining_balance` clamps to `>= 0` and `payment_progress` caps at `100`.
- **Actual result (bug):** `remaining_balance` goes **negative**; `payment_progress` exceeds `100` (and `payment_progress` uses `int()` so it floors — 99.7% renders 99%).
- **Evidence on failure:** detail page shows a negative balance / >100% progress bar.

#### BOOK-EC-06 — Transfer view 500 on non-numeric transfer_fee
- **Preconditions:** `management`; two customers; a booking.
- **Steps:** POST `/bookings/<pk>/transfer/` with `transfer_fee=abc` (non-numeric) and a valid `to_customer`.
- **Expected result (correct):** re-render with a "valid number" error.
- **Actual result (bug):** `Decimal('abc')` raises `decimal.InvalidOperation` → unhandled 500. Also POST without `to_customer` → `Customer.objects.get(pk='')` → `ValueError` 500.
- **Evidence on failure:** HTTP 500 / traceback.

#### BOOK-EC-07 — Transfer page renders no form fields (undefined `form` in context)
- **Preconditions:** `management`; GET `/bookings/<pk>/transfer/`.
- **Steps:** load the page and try to pick a target customer.
- **Expected result (correct):** a working form with a customer dropdown.
- **Actual result (bug):** the view passes `{'booking','customers'}` with **no `form`**; the template loops `{% for field in form %}` over nothing and `customers` is unused → page shows a submit button and a warning but no selectable customer.
- **Evidence on failure:** no `<select>`/input for `to_customer` in the rendered HTML.

#### BOOK-EC-08 — booking_detail.html references non-existent completed_date / cancelled_date
- **Preconditions:** a `completed` booking and a `cancelled` booking.
- **Steps:** render `/bookings/<pk>/` for each.
- **Expected result (correct):** the timeline shows the real completion/cancellation date (`cancelled_at`; completed has no stored date).
- **Actual result (bug):** `{{ booking.completed_date }}` / `{{ booking.cancelled_date }}` are not fields/properties → Django renders empty strings → blank dates in the timeline.
- **Evidence on failure:** timeline rows show empty date text.

#### BOOK-EC-09 — InstallmentPlan due_day not validated on model/serializer
- **Preconditions:** `accounts`; `POST /api/installment-plans/` with `due_day=31`.
- **Steps:** create the plan via API (bypassing the web form's 1–28 clamp).
- **Expected result (correct):** 400 on `due_day=31`.
- **Actual result (bug):** model + `InstallmentPlanSerializer` accept it; only clamped later inside `auto_generate`. Inconsistent validation surface.
- **Evidence on failure:** plan stored with `due_day=31`.

#### BOOK-EC-10 — recalculate() rounding → zero installment amount → IntegrityError
- **Preconditions:** a plan with a large `n` and a small `remaining_balance` (e.g. 30 installments, balance 100.00).
- **Steps:** trigger `recalculate()` via `/installments/<pk>/mark-paid/`.
- **Expected result (correct):** installments always `amount > 0`.
- **Actual result (bug):** `base = (target/n).quantize('0.01')` → `0.00` for non-last installments → `IntegrityError` on `amount__gt=0`.
- **Evidence on failure:** HTTP 500 / constraint traceback on mark-paid.

#### BOOK-EC-11 — Transfer to the same customer via forged POST (web)
- **Preconditions:** `management`; a booking and its own customer.
- **Steps:** POST `/bookings/<pk>/transfer/` with `to_customer=<same customer pk>`.
- **Expected result (correct):** rejected (API serializer rejects same-customer; web should too).
- **Actual result (bug):** web view only excludes the source customer from the dropdown and trusts `POST to_customer` → a no-op repoint plus a `BookingTransfer` record.
- **Evidence on failure:** a `BookingTransfer` row with `from_customer == to_customer`.

#### BOOK-EC-12 — booking_id reuse after deleting the highest ID (non-monotonic)
- **Preconditions:** two bookings `BKG-00008`, `BKG-00009`; delete the highest (`BKG-00009`).
- **Steps:** create a new booking.
- **Expected result (correct):** a fresh, never-reused id.
- **Actual result (bug):** the suffix parser reads the last row → new booking is `BKG-00009` again (reused id).
- **Evidence on failure:** new `booking_id` equals the deleted one; audit/history ambiguity.

#### BOOK-EC-13 — amount_paid understates when verified payments < advance_paid
- **Preconditions:** a booking with `advance_paid=10000` and a single verified payment of `2000` (partial verification lag).
- **Steps:** read `booking.amount_paid`.
- **Expected result (correct):** `amount_paid` reflects the true collected total (>= advance).
- **Actual result (bug):** the `if verified > 0` branch returns the verified sum (`2000`), understating the advance (`10000`).
- **Evidence on failure:** `amount_paid == 2000` while `advance_paid == 10000`.

### SEC — negative & security (auth / authorization / IDOR)

> All four web views below are guarded only by `@login_required` (list `core/views.py:1014`, create `1041`, detail `1176`, edit `1193`). The customer portal user is a real authenticated `User` with no `UserProfile`, so it passes `@login_required` and there is no staff-vs-customer check.

#### BOOK-SEC-01 — IDOR: booking list reachable by portal customer (PRIORITY)
- **Preconditions:** customer portal user (authenticated, role-less) logged in; multiple bookings exist.
- **Steps:** GET `/bookings/`.
- **Expected result (correct):** redirect to `/portal/` or `/dashboard/` with denial.
- **Actual result (bug):** 200 list of every booking (customer names, amounts).
- **Evidence on failure:** customer sees the full booking table.

#### BOOK-SEC-02 — IDOR: booking detail leaks amounts/notes/phone (PRIORITY)
- **Preconditions:** customer portal user; a booking with customer phone + notes.
- **Steps:** GET `/bookings/<pk>/` (any pk).
- **Expected result (correct):** denial.
- **Actual result (bug):** 200 showing customer phone, plot, `total_amount`/`advance_paid`, and notes.
- **Evidence on failure:** PII + financial amounts visible to the portal user.

#### BOOK-SEC-03 — IDOR: booking edit lets customer change any booking's amounts (PRIORITY)
- **Preconditions:** customer portal user; a booking.
- **Steps:** POST `/bookings/<pk>/edit/` with modified `total_amount`/`advance_paid` (within guard limits, e.g. `total_amount=110000`, `advance_paid=12000`).
- **Expected result (correct):** denial; amounts unchanged.
- **Actual result (bug):** the edit persists → the customer alters another booking's financials.
- **Evidence on failure:** booking amounts changed by the portal user's POST.

#### BOOK-SEC-04 — IDOR: booking create reachable by portal customer
- **Preconditions:** customer portal user; an available plot.
- **Steps:** POST `/bookings/create/` with a valid customer + plot + amounts.
- **Expected result (correct):** denial.
- **Actual result (bug):** a booking is created by the customer.
- **Evidence on failure:** new `Booking` with `created_by` = the portal user.

#### BOOK-SEC-05 — API read-open: GET /api/bookings/ for any authenticated user (PRIORITY)
- **Preconditions:** customer portal user; authenticate via `/api/auth/login/` (session).
- **Steps:** `GET /api/bookings/` (and `?status=&customer=&project=` variants).
- **Expected result (correct):** 403 (`IsStaffOrAbove` should deny non-staff).
- **Actual result (bug):** `has_permission` returns `True` for `SAFE_METHODS` for any authenticated user → 200 with the full `BookingSerializer` list (amounts, notes).
- **Evidence on failure:** 200 with cross-customer data.

#### BOOK-SEC-06 — API read-open: booking detail + installments + reservations
- **Preconditions:** customer portal user.
- **Steps:** `GET /api/bookings/<pk>/`, `GET /api/installments/`, `GET /api/installment-plans/`, `GET /api/reservations/`.
- **Expected result (correct):** 403 on all.
- **Actual result (bug):** all 200 — `has_object_permission` returns `True` for every non-DELETE verb; nested `BookingDetailSerializer` exposes customer + plot + plan.
- **Evidence on failure:** any of these returning 200 for the portal user.

#### BOOK-SEC-07 — BookingSerializer update lacks total_cost / holding_deposit guards (post-create under-sell)
- **Preconditions:** staff; a booking created at `total_cost=108000`, `advance_paid=10000`.
- **Steps:** `PATCH /api/bookings/<pk>/` with `total_amount=100000.00` and `advance_paid=5000.00`.
- **Expected result (correct):** 400 with price-guard errors (below `total_cost` / below `holding_deposit`).
- **Actual result (bug):** plain `BookingSerializer` (used for update) only enforces `total_amount>0` / `advance_paid>=0` → 200, booking now under-sold and under-deposited.
- **Evidence on failure:** 200 and `total_amount=100000` < `plot.total_cost=108000`.

#### BOOK-SEC-08 — Reservation.convert bypasses price guards (books at plot.price ignoring charges)
- **Preconditions:** staff; an `active` `Reservation` on plot `P` (`total_cost=108000`).
- **Steps:** `POST /api/reservations/<pk>/convert/`.
- **Expected result (correct):** booking `total_amount >= plot.total_cost` (108000).
- **Actual result (bug):** convert uses `total_amount=plot.price` (`api_views.py:429`) → books at `100000`, ignoring `development/lease/other` charges → under-sell vs. the "total_cost is source of truth" rule.
- **Evidence on failure:** `Booking.total_amount == 100000` while `P.total_cost == 108000`.

### API — API contract

#### BOOK-API-01 — POST /api/bookings/ create: plot booked + verified Payment + Receipt + BKG id
- **Preconditions:** staff; available plot, customer.
- **Steps:** `POST /api/bookings/` `{customer, plot, total_amount=108000, advance_paid=10000, source}`.
- **Expected result:** 201; `booking_id` matches `^BKG-\d{5}$`; `status='pending'`; `plot.status='booked'`; a verified `Payment` (amount 10000) + `Receipt` created; `AuditLog` create; booking notification logged.
- **Evidence on failure:** 4xx/5xx; missing Payment/Receipt; plot not booked.

#### BOOK-API-02 — POST /api/bookings/ create: price guard rejects under-sell / under-deposit
- **Preconditions:** staff; plot `total_cost=108000`, `holding_deposit=10000`.
- **Steps:** POST with `total_amount=107000` (expect 400); POST with `advance_paid=5000` (expect 400); POST with `advance_paid<0` (expect 400).
- **Expected result:** all 400 with specific guard errors; no booking/plot change.
- **Evidence on failure:** a 201 slipping past the guards.

#### BOOK-API-03 — POST /api/bookings/{id}/confirm/ action
- **Preconditions:** staff; pending booking with `advance_paid>0`; and another with `advance_paid=0`.
- **Steps:** confirm the first; confirm the second; confirm an already-`confirmed` booking.
- **Expected result:** first → 200/204 `confirmed`; `advance_paid=0` → 400; already-confirmed → idempotent success (no duplicate transition). Cancelled booking → 400.
- **Evidence on failure:** 0-advance confirm succeeding; duplicate notifications/audit on re-confirm.

#### BOOK-API-04 — POST /api/bookings/{id}/cancel/ action (blocked while verified payments exist)
- **Preconditions:** staff; booking with a verified payment; and one with none.
- **Steps:** cancel the one with a verified payment (expect 400); cancel the one without (expect success).
- **Expected result:** verified-payment booking → 400 + plot stays `booked`; no-verified → success, `status='cancelled'`, plot `available`.
- **Evidence on failure:** verified-payment cancel succeeding; plot not released on the successful path.

#### BOOK-API-05 — Reopen is web-only (no /api/bookings/{id}/reopen/ endpoint)
- **Preconditions:** staff; a cancelled booking.
- **Steps:** `POST /api/bookings/<pk>/reopen/`.
- **Expected result:** 404/405 — there is no reopen DRF action (`BookingViewSet` defines only `cancel`, `confirm`, `payment_summary`; reopen exists solely as `booking_reopen_view`).
- **Evidence on failure:** an unexpected 200/201 (would indicate a newly added action not in scope).

#### BOOK-API-06 — GET /api/bookings/ read-open (any authenticated user)
- **Preconditions:** customer portal user authenticated.
- **Steps:** `GET /api/bookings/`.
- **Expected result (correct):** 403.
- **Actual result (bug):** 200 with full list (see BOOK-SEC-05).
- **Evidence on failure:** 200 for the portal user.

#### BOOK-API-07 — PATCH /api/bookings/{id}/ guard gap (below-cost / under-deposit accepted)
- **Preconditions:** staff; booking at `total_cost=108000`.
- **Steps:** `PATCH /api/bookings/<pk>/` `{total_amount=100000, advance_paid=5000}`.
- **Expected result (correct):** 400 price-guard errors.
- **Actual result (bug):** 200 — plain serializer does not re-apply `total_cost`/`holding_deposit` guards (see BOOK-SEC-07).
- **Evidence on failure:** 200 and under-sold values persisted.

#### BOOK-API-08 — GET /api/bookings/{id}/payment_summary/ float precision
- **Preconditions:** staff; a booking with known amounts (e.g. 108000 / 10000).
- **Steps:** `GET /api/bookings/<pk>/payment_summary/`; compare numeric fields to the exact `Decimal(15,2)` source.
- **Expected result (correct):** every money value serialized exactly (no float rounding).
- **Actual result (bug):** `payment_summary` casts each money value through `float(...)` (`api_views.py:258–292`) → precision loss on large PKR values.
- **Evidence on failure:** a returned value differs from the exact Decimal (e.g. `100000.1` vs `100000.10`, or `0.30000000000000004`).

## 4. Data isolation rules

- **Never assume IDs reset.** `booking_id`/`group_id`/`payment_id`/`receipt_number` are parsed from the last row's numeric suffix (not DB sequences). Use unique `plot_number` (unique per project), timestamped customer phone/cnic/email, and timestamped names; assert `booking_id` **format** (`^BKG-\d{5}$`), not exact values.
- **Booking↔Plot↔Payment↔Receipt chains** must be asserted by reverse/related lookups on the specific `Booking` just created, not by "there is exactly one Payment in the DB".
- **Cleanup order:** delete bookings before plots (FK CASCADE on customer/plot); reverse/refund any verified payments before cancelling in EC-01/EC-03; a project with plots cannot be deleted.
- **Race/edge fixtures** (per the analysis): a booking with a reversed advance (cancel-bypass EC-03), a cancelled booking whose plot was re-booked (reopen-conflict EC-01), a plan with `installment_amount=0` (EC-04), a plan with `due_day=31` (EC-09), a booking with `advance_paid > total_amount` (EC-05).

## 5. Coverage checklist (for the master map)

- BOOK-HP-01 — Create booking: auto BKG id, plot→booked, verified Payment+Receipt, advance_paid set
- BOOK-HP-02 — Confirm requires advance_paid>0; pending→confirmed + audit/notification
- BOOK-HP-03 — Edit booking: price guards re-applied, plot/status preserved
- BOOK-HP-04 — Booking detail renders customer/plot/amounts/notes
- BOOK-HP-05 — Cancel blocked while verified payments exist; releases plot to available after reversal
- BOOK-HP-06 — Reopen returns cancelled→pending and re-reserves plot
- BOOK-HP-07 — Installment auto-generate: 12 monthly
- BOOK-HP-08 — Installment auto-generate: quarterly
- BOOK-HP-09 — Installment auto-generate: balloon
- BOOK-HP-10 — Installment auto-generate: due_day clamp
- BOOK-HP-11 — Invoice PDF (finance allowed, sales denied)
- BOOK-EC-01 — Reopen conflict: plot re-sold → two active bookings
- BOOK-EC-02 — Web double-create race (no select_for_update)
- BOOK-EC-03 — Cancel with advance_paid>0 but no verified payment row
- BOOK-EC-04 — Zero/negative installment_amount → auto_generate IntegrityError/500
- BOOK-EC-05 — payment_progress / remaining_balance unclamped
- BOOK-EC-06 — Transfer view 500 on non-numeric transfer_fee
- BOOK-EC-07 — Transfer page renders no form fields (undefined form)
- BOOK-EC-08 — booking_detail.html non-existent completed_date/cancelled_date
- BOOK-EC-09 — InstallmentPlan due_day not validated on model/serializer
- BOOK-EC-10 — recalculate() rounding → zero amount → IntegrityError
- BOOK-EC-11 — Transfer to same customer via forged POST (web)
- BOOK-EC-12 — booking_id reuse after deleting highest ID
- BOOK-EC-13 — amount_paid understates when verified < advance_paid
- BOOK-SEC-01 — IDOR: booking list @login_required (portal customer)
- BOOK-SEC-02 — IDOR: booking detail leaks amounts/notes/phone
- BOOK-SEC-03 — IDOR: booking edit lets customer change amounts
- BOOK-SEC-04 — IDOR: booking create reachable by portal customer
- BOOK-SEC-05 — API read-open: GET /api/bookings/ for any authenticated user
- BOOK-SEC-06 — API read-open: detail + installments + reservations
- BOOK-SEC-07 — BookingSerializer update lacks total_cost/holding_deposit guards
- BOOK-SEC-08 — Reservation.convert bypasses price guards (books at plot.price)
- BOOK-API-01 — POST /api/bookings/ create: plot booked + verified Payment+Receipt + BKG id
- BOOK-API-02 — POST /api/bookings/ create: price guard rejects under-sell/under-deposit
- BOOK-API-03 — POST /api/bookings/{id}/confirm/ action
- BOOK-API-04 — POST /api/bookings/{id}/cancel/ action (blocked w/ verified payments)
- BOOK-API-05 — Reopen is web-only (no /api/bookings/{id}/reopen/ endpoint)
- BOOK-API-06 — GET /api/bookings/ read-open
- BOOK-API-07 — PATCH /api/bookings/{id}/ guard gap
- BOOK-API-08 — GET /api/bookings/{id}/payment_summary/ float precision
