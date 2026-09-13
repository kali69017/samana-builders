# Bookings Module — QA Analysis

> Module: `bookings/` (+ booking views in `core/views.py`). Companion to
> `docs/qa/_shared-context.md` — roles/permissions/URLs/revenue semantics are
> not re-derived here.

## 1. Business purpose & user journeys

Bookings are the commercial heart of the ERP: a **Booking** binds a **Customer**
to a **Plot** at a `total_amount`, records an `advance_paid` (which is the single
source of truth for revenue — see shared context), drives an installment schedule
(`InstallmentPlan`/`Installment`), and is the parent of `Payment` rows. The module
also handles reservations (pre-booking holds), transfers, amendments, early
settlement, and a cancellation policy.

Real user journeys:

- **Sales / admin / management** — create a booking: `/bookings/create/` →
  pick customer + plot + amount → `Booking` saved, plot flips `available→booked`,
  an optional installment plan is auto-generated, the advance is posted as a
  verified `Payment` (+ receipt), a booking notification is sent, then redirect
  to `/bookings/`. (`core/views.py:1042`)
- **Management+** — confirm a booking: `/bookings/<pk>/confirm/` → requires
  `advance_paid > 0` → `pending→confirmed` → approval notification (email +
  WhatsApp). (`core/views.py:1329`)
- **Management+** — cancel a booking: `/bookings/<pk>/cancel/` → blocked while
  verified payments exist → `status=cancelled`, plot released to `available`.
  (`core/views.py:1247`)
- **Management+** — reopen a cancelled booking: `/bookings/<pk>/reopen/` →
  `cancelled→pending`, plot re-reserved. (`core/views.py:1298`)
- **Management+** — transfer a booking: `/bookings/<pk>/transfer/` → create a
  `BookingTransfer`, repoint `booking.customer`. (`core/views.py:1402`)
- **Finance+** — manage installments: `/installment-plans/…` and
  `/installments/<pk>/mark-paid/` (advance bumps, plan recalculates).
  (`bookings/views_installments.py`)
- **Staff via API** — full CRUD + `confirm`/`cancel`/`convert`/`mark_paid`
  actions on `/api/bookings/`, `/api/installments/`, `/api/reservations/`.
  (`bookings/api_views.py`)

## 2. Data model

Files: `bookings/models.py`.

### BookingGroup (models.py:7)
- `group_id` (unique, editable=False, auto `GRP-00001` in `save()` 15–20),
  `customer` FK(CASCADE), `total_amount`, `discount_amount`, `payment_plan`,
  `created_at`.
- **ID race**: `save()` parses the last id with **no** `select_for_update()`/
  `transaction.atomic()` (unlike `Booking.save()`), so two concurrent creates can
  derive the same `group_id` → `IntegrityError` on the unique column.

### Reservation (models.py:44)
- `customer`, `plot` (both FK CASCADE), `token_amount` (CheckConstraint
  `token_amount__gt=0`), `reserved_at`, `expires_at`, `status`
  (`active/converted/expired/cancelled`), `created_by` (SET_NULL).

### Booking (models.py:72)
- `booking_id` (unique, auto `BKG-00001` in `save()` 115–124, **inside**
  `transaction.atomic()` + `select_for_update()` — correct).
- `customer` FK(CASCADE), `plot` FK(CASCADE), `group` FK(SET_NULL),
  `booking_date` (auto_now_add), `total_amount`, `advance_paid` (default 0),
  `status` (`pending/confirmed/active/cancelled/completed`, default `pending`),
  `source`, `agent` (SET_NULL), `cancellation_policy` (SET_NULL),
  `cancellation_fee`, `possession_date`, `is_possession_taken`, `notes`,
  `created_by` (SET_NULL), `cancelled_at/by/reason`, `reopened_at`.
- **`save()` side effect (126–136)**: on an existing row it fetches
  `Booking.objects.get(pk=self.pk)` and writes an `AuditLog` on status change —
  an extra query + a read-modify-write outside the ID lock, so a status change
  raced by two writers can double-log.
- CheckConstraints (204–215): `total_amount__gt=0`, `advance_paid__gte=0`.
  **There is NO `advance_paid <= total_amount` constraint** — the "remaining
  balance never negative" invariant is only enforced in forms/serializers.
- Properties: `remaining_balance` (143–145, `total - advance`, **not** clamped to
  0), `payment_progress` (147–151, `int(advance/total*100)`, **not** capped at
  100), `agent_commission` (153–158), `payment_plan` (160–169), `amount_paid`
  (177–192 — sum of **verified** payments if `> 0`, else `advance_paid`),
  `total_charges` (194–197).

### BookingTransfer (models.py:218)
- `booking`, `from_customer`, `to_customer`, `transfer_fee`, `previous_payments_handling`
  (`transfer/refund`), `approved_by` (SET_NULL), `transfer_date`, `notes`.
  No model-level validation (same-customer / negative-fee checks live only in the
  API serializer).

### InstallmentPlanTemplate (models.py:249) / InstallmentPlan (models.py:274)
- Plan is `OneToOne` to `Booking`. Fields: `total_installments` (default 12),
  `installment_amount` (default **0**), `down_payment_amount`, `start_date`,
  `frequency`, `due_day` (default 1), `late_fee_per_day`, `grace_period_days`,
  `is_active`.
- `auto_generate()` (300–335): deletes all installments, loops 1..N, shifts
  `start_date` by month/quarter/half-year/year, clamps `due.replace(day=min(due_day,28))`
  (fallback `day=28`), optionally applies balloon. Notes:
  - `remaining = total_amount - down_payment_amount` (305) is computed but **never
    used** — installments use the fixed `installment_amount`, so the generated
    schedule does NOT sum to the booking balance unless the caller set
    `installment_amount` correctly (web create does; API does not).
  - balloon `amount *= template.balloon_multiplier` (327): `TypeError` if
    `balloon_multiplier` is `None` (field is nullable); silently skipped if
    `balloon_installment_number` is `None`.
- `recalculate()` (337–383): spreads `booking.remaining_balance` evenly over
  unpaid installments, quantized to 2dp, last installment absorbs rounding. Risk:
  `base = (target_total/n).quantize('0.01')` can be `0.00` for large `n` → sets
  non-last installments to `amount=0.00`, violating `Installment`'s
  `amount__gt=0` CheckConstraint → `IntegrityError`.

### Installment (models.py:425)
- `plan` FK, `installment_number`, `due_date`, `amount`, `late_fee`,
  `paid_amount`, `status` (`pending/paid/overdue/partial`), `paid_date`,
  `payment_allocation` JSON.
- `unique_together (plan, installment_number)`; CheckConstraints `amount__gt=0`,
  `paid_amount__gte=0`. `remaining_amount` property (448–450).

### EarlySettlement (models.py:483) — plan FK, remaining/amount/discount fields,
`approved`, `settled_at`. No settlement execution logic in this module.

## 3. Roles & permissions

| Action | Allowed role(s) | Enforced by |
|---|---|---|
| List bookings `/bookings/` | **any authenticated user** (incl. customers) | `@login_required` only (`core/views.py:1014`) |
| Create `/bookings/create/` | **any authenticated user** | `@login_required` only (`1041`) |
| Detail `/bookings/<pk>/` | **any authenticated user** | `@login_required` only (`1176`) |
| Edit `/bookings/<pk>/edit/` | **any authenticated user** | `@login_required` only (`1193`) |
| Confirm `/bookings/<pk>/confirm/` | management+ | `@management_or_above` (`1327`) |
| Cancel `/bookings/<pk>/cancel/` | management+ | `@management_or_above` (`1245`) |
| Reopen `/bookings/<pk>/reopen/` | management+ | `@management_or_above` (`1296`) |
| Delete `/bookings/<pk>/delete/` | management+ | `@management_or_above` (`1215`) |
| Transfer `/bookings/<pk>/transfer/` | management+ | `@management_or_above` (`1400`) |
| Invoice PDF `/bookings/<pk>/invoice/` | finance+ (sales excluded) | `@payments_access` (`1792`) |
| Installment plans (web) | finance+ | `@finance_or_above` (`views_installments.py`) |
| API `BookingsViewSet` & co. | read: any authenticated; write: super_admin/admin/management/sales; delete: super_admin/admin/management | `IsStaffOrAbove` (`bookings/api_views.py:27`) |

**Object-level gating — ABSENT (IDOR):**

- `bookings_view`, `booking_create_view`, `booking_detail_view`,
  `booking_edit_view` are guarded **only** by `@login_required`. Customer portal
  users are real `auth.User` rows (`customers/models.py:35`
  `Customer.user = OneToOneField(User)`) and are authenticated, so a customer who
  logs in can browse `/bookings/`, open any booking's detail (customer phone,
  plot, amounts, notes), and — worst — **edit any booking's amounts** via
  `/bookings/<pk>/edit/`. There is no staff-vs-customer check on these four
  views (the role-gated actions are fine, but the read/edit surface is open).
- API: `IsStaffOrAbove.has_permission` returns `True` for **SAFE_METHODS for any
  authenticated user** (`api_views.py:32–33`), and `has_object_permission`
  returns `True` for every non-DELETE verb (`40–48`). A customer user (no
  `UserProfile` — see `customers/serializers.py:103` which only sets
  `customer.user`, never a profile) can therefore `GET /api/bookings/`,
  `/api/bookings/<pk>/`, `/api/installments/`, `/api/installment-plans/`,
  `/api/reservations/` and read every customer's booking data (amounts, notes,
  phone via related names). Write is blocked for them (`hasattr(profile)` guard
  fails), but the read surface is a full cross-customer data leak. This is the
  same pattern across all `IsStaffOrAbove` ViewSets, not just bookings.

## 4. Business rules, state machines, invariants

### Booking status machine

```
pending ──confirm──▶ confirmed           (requires advance_paid > 0)
pending ──cancel───▶ cancelled           (blocked while verified payments exist)
cancelled ─reopen──▶ pending             (re-reserves plot to 'reserved')
confirmed ─mark_paid(remaining<=0)──▶ completed   (set in api_views.mark_paid &
                                        views_installments.installment_mark_paid_view)
```
- `active` exists as a choice but **nothing transitions into it** (dead state).
- `completed` is only reachable via installment/payment paths, never the confirm
  view. There is no `completed→` outgoing transition.

### Plot status side-effects (Plot statuses: `available/reserved/on_hold/booked/sold/cancelled`, `properties/models.py:70`)

- create booking → `booked` (`core/views.py:1063`; API `api_views.py:73`)
- cancel → `available` (`core/views.py:1274`)
- reopen → `reserved` (`core/views.py:1307`)
- delete → `available` (`core/views.py:1231`)
- reservation create → `reserved` (`core/views.py:1462`); convert → `booked`
  (`api_views.py:435`)

### Invariants (and where enforced)

| Invariant | Enforced at | Gap |
|---|---|---|
| `total_amount > 0` | model CheckConstraint | — |
| `total_amount >= plot.total_cost` | form `BookingForm.clean` (69–74), serializer `validate` (146–153) | **not** model-level; admin/direct save bypasses |
| `advance_paid >= plot.holding_deposit` | form (80–87), serializer (156–162) | not model-level |
| `advance_paid <= total_amount` | form `clean_advance_paid` (44–51), serializer `validate_advance_paid` (123–129), capped in `mark_paid` (`min(..., total)`) | **no DB constraint** — admin/shell can set advance > total |
| confirm requires `advance_paid > 0` | web view (1336), API (208) | — |
| cancel blocked while verified payments exist | web view (1260–1267), API (168–174) | only checks **verified** payments |
| delete blocked while payments exist | web view (1221–1226), API `destroy` (132–138) | — |
| `remaining_balance >= 0` | (implied) | property has **no clamp**; broken if advance > total |
| `payment_progress <= 100` | (expected) | property has **no cap**; can exceed 100 |
| no double-booking (one active booking per plot) | API serializer (175–180) + `perform_create` `select_for_update` | **web create has no lock** (see §5) |

### Side effects

- Booking create (web + API): plot→booked, advance posted as **verified Payment**
  + Receipt, `AuditLog` "create", `NotificationService.send_booking_notification`
  (failure-safe). (`core/views.py:1096–1130`, `api_views.py:75–120`)
- Confirm (web): `AuditLog` + email/WhatsApp approval notification (failure-safe).
  (`core/views.py:1353–1390`)
- Cancel: `AuditLog` "cancel". Reopen: `AuditLog` "update". Transfer: `AuditLog`
  "transfer". `Booking.save()` additionally auto-logs every status change.

## 5. Edge cases (deep)

1. **Double-submit / concurrent confirm** — `booking_confirm_view` reads status
   then writes `confirmed` with no `select_for_update`; two simultaneous POSTs
   both pass `status != 'pending'`? No — the guard `if booking.status != 'pending'`
   (1346) is evaluated on the *fetched* instance before save; both requests can
   pass it and both call `save()`. Result is benign (idempotent `confirmed`), but
   two "confirmed" `AuditLog` entries and two approval notifications fire.
   EXPECTED: confirm should be idempotent and send at most one notification.
2. **Double-booking race on create (web)** — `booking_create_view` relies on the
   form's plot queryset (`status='available'`, evaluated at GET) and does **not**
   lock the plot before saving. Two concurrent creates for the same plot both
   validate and both save → two active `Booking`s on one plot, plot left `booked`.
   The API path is safe (`select_for_update`, `api_views.py:69`), so web and API
   are **inconsistent**. EXPECTED: web create must also lock/check plot atomically.
3. **`advance_paid = 0` confirm** — blocked in web (`1336`) and API (`208`).
   Correct. But `advance_paid` can be negative via API `BookingCreateSerializer`?
   No — `validate_advance_paid` rejects `< 0`; model constraint `>= 0`. OK.
4. **`total_amount` below `plot.total_cost`** — blocked in form and serializer.
   EXPECTED behavior correct; note the price-guard is duplicated in two places
   (form + serializer) and absent from the model, so a direct
   `Booking.objects.create(...)` (e.g. admin shell, `Reservation.convert` uses
   `total_amount=plot.price` at `api_views.py:429` **without** charges!) bypasses it.
   `convert` books at `plot.price`, ignoring `development/lease/other` charges —
   inconsistent with the "total_cost is source of truth" rule.
5. **Transfer to the same customer** — API serializer rejects
   (`from_customer.pk == to_customer.pk`, `serializers.py:216`); the **web view
   does not** — it only excludes the source customer from the dropdown
   (`core/views.py:1439`) and trusts `POST to_customer`, so a forged POST can
   transfer a booking to its own customer (no-op repoint + `BookingTransfer`
   record). EXPECTED: web view should reject same-customer.
6. **Cancel a booking with partial / non-verified money** — the guard only counts
   `status='verified'` payments. A booking with `advance_paid > 0` but no verified
   `Payment` row (e.g. the advance `Payment` was reversed, or `advance_paid` was
   set directly in admin) **can** be cancelled: plot is released to `available`
   while `advance_paid` still contributes to revenue. EXPECTED: cancel should
   also block (or force reconciliation) when `advance_paid > 0` regardless of
   payment rows.
7. **Reopen a cancelled booking whose plot was re-sold** — `booking_reopen_view`
   unconditionally sets `plot.status = 'reserved'` (1307) with **no check** that
   the plot is still `available`/`cancelled`. If the plot was re-booked (or sold)
   after cancellation, reopening produces **two active bookings on one plot** and
   silently overwrites the newer booking's `booked` status to `reserved`.
   The API `convert` and `ReservationSerializer` both guard against this
   (`api_views.py:418`, `serializers.py:68`), but reopen does not. EXPECTED:
   reopen must verify the plot has no other active booking.
8. **`due_day` = 31 (or 0)** — form clamps 1–28 (`forms.py:138`); `auto_generate`
   clamps `min(due_day, 28)` with a `ValueError→28` fallback (319–322), so 0 and
   31 are handled gracefully at generation time. But the **model and
   `InstallmentPlanSerializer` do not validate `due_day` at all**, so an API-created
   plan with `due_day=31` is stored and only clamped when `auto_generate` runs.
   Inconsistent validation surface.
9. **Zero / negative installment amounts** — `Installment` has
   `amount__gt=0`. `InstallmentPlanForm` validates `total_installments` and
   `due_day` but **not** `installment_amount` or `down_payment_amount`. So a
   negative `installment_amount` via form/API → `auto_generate` creates
   `Installment(amount=<negative or 0>)` → `IntegrityError` (500). API
   `InstallmentPlanViewSet.perform_create` with default `installment_amount=0`
   and `generate_now=True` crashes the same way.
10. **`recalculate()` rounding → zero amounts** — for a large `n` and small
    remaining balance, `base` quantizes to `0.00` for all but the last
    installment → non-last installments get `amount=0.00` → violates
    `amount__gt=0` → `IntegrityError`. Triggered by
    `mark_paid`/`installment_mark_paid_view` after `recalculate()`.
11. **Float precision** — `BookingCreateSerializer.validate_advance_paid`
    compares `value > float(total)` (serializers.py:127) — converts a Decimal
    total to `float`, risking mis-compare for large PKR values. `payment_summary`
    action serializes every money value with `float(...)` (`api_views.py:258–292`)
    — precision loss in API output (shared-context rule: money is exact
    `Decimal(15,2)`; assert exactly). `payment_progress` uses Decimal division +
    `int()`, so it truncates (floor) rather than rounding — 99.7% shows 99%.
12. **`remaining_balance` negative / `payment_progress > 100`** — reachable via
    admin or direct save because there is no `advance_paid <= total_amount`
    DB constraint. The properties themselves have no `min()`/`cap`. EXPECTED:
    clamp in the property and/or add the DB constraint.
13. **Transfer fee parse** — `Decimal(request.POST.get('transfer_fee', '0'))`
    (`core/views.py:1409`) raises `decimal.InvalidOperation` on a non-numeric
    value → unhandled 500. Negative fee accepted (API rejects it, web doesn't).
    Missing `to_customer` → `Customer.objects.get(pk='')` → `ValueError` 500.
14. **Transfer form renders no fields** — `booking_transfer.html` loops
    `{% for field in form %}` but the view passes `{'booking', 'customers'}` with
    **no `form`** (`core/views.py:1440–1443`). The `customers` context is also
    never used. The transfer page shows a submit button and a warning but no
    selectable target customer — the web transfer UI is effectively broken.
15. **Booking ID auto-gen** — `Booking.save()` uses `select_for_update`
    (correct); `BookingGroup.save()` does **not** (race → duplicate `group_id`
    → IntegrityError). Both parse the numeric suffix of the last row, so a
    manually-deleted highest ID causes a **reused** id (e.g. `BKG-00009` deleted,
    next is `BKG-00009` again). No monotonic guarantee.
16. **`amount_paid` understates** — returns verified-payment sum whenever it is
    `> 0`, even if it is **less** than `advance_paid` (partial verification
    lag); the docstring's "uses advance_paid unless verified exceeds it" intent
    (models.py:177–192) does not match the `if verified > 0` branch.
17. **`booking_detail.html` references non-existent fields** —
    `booking.completed_date` (line 277) and `booking.cancelled_date` (line 284)
    are not fields/properties (model has `cancelled_at`, no `completed_date`).
    Django silently renders empty strings, so the timeline shows blank dates for
    completed/cancelled bookings. Cosmetic bug, no crash.
18. **Concurrent `recalculate()` vs `auto_generate()`** — neither is wrapped in
    `transaction.atomic()`/row locks at the model level; a payment
    (`mark_paid`) and an `auto_generate` racing can interleave installments.

## 6. Cross-cutting risks

- **XSS — LOW (safe by default).** `booking.notes` is rendered with
  `{{ booking.notes }}` (auto-escaped) in `booking_detail.html:132`; no `|safe`/
  `mark_safe` on booking fields found. The only `innerHTML` use is
  `booking_form.html:154` writing `data-info` derived from numbers, and
  `templateInfo.innerHTML` is fed from that numeric `data-info`, so low risk —
  but template **names** are echoed into the option text (`{{ template.name }}`,
  escaped) and would need to be verified if ever rendered with `|safe`.
- **CSRF — OK.** All state-changing web forms include `{% csrf_token %}`
  (`booking_form.html:33`, `booking_cancel.html:34`, `booking_reopen.html:26`,
  `booking_confirm.html:58`); DRF session auth goes through
  `rest_framework.urls` CSRF. No `@csrf_exempt` in this module.
- **IDOR / broken object-level authorization — HIGH.** See §3. Booking list/
  detail/edit/create are only `@login_required`; API `IsStaffOrAbove` grants
  read to any authenticated user (incl. customer-portal users). Customers can
  enumerate all bookings and their amounts/notes/phones.
- **Sensitive data exposure — MEDIUM/HIGH.** Booking detail and list render
  customer phone (`booking_detail.html:64`) and all financial amounts; combined
  with the IDOR above, this leaks a full customer/booking/amount ledger to any
  authenticated portal user. CNIC is not shown on the booking screens, but the
  phone + amounts are PII.
- **Accessibility — LOW.** Custom `floating-group` labels lack `for`/`id`
  association in several templates (e.g. `booking_transfer.html` label without
  `for`), and status badges rely on color alone; low severity for a staff ERP.

## 7. API surface

Router: `api/urls.py:58–64` registers `bookings`, `installment-plans`,
`installments`, `installment-plan-templates`, `reservations`, `booking-transfers`,
`early-settlements`. All use `IsStaffOrAbove`.

| Method + path | View/action | Permission | Key request fields | Response / notes |
|---|---|---|---|---|
| `GET /api/bookings/` | `BookingViewSet.list` | any authenticated | `?status=`, `?customer=`, `?project=` | `BookingSerializer`; **leaks to customers** |
| `POST /api/bookings/` | `create` | staff roles | customer, plot, total_amount, advance_paid, source, agent, notes | `BookingCreateSerializer`; locks plot, posts verified advance payment + receipt |
| `GET /api/bookings/<pk>/` | `retrieve` | any authenticated | — | `BookingDetailSerializer` (customer + plot + plan nested) |
| `PUT/PATCH /api/bookings/<pk>/` | `update` | staff roles | as create | `BookingSerializer` (no price guards on update) |
| `DELETE /api/bookings/<pk>/` | `destroy` | admin/management/super_admin | — | blocked if verified payments; releases plot |
| `POST /api/bookings/<pk>/confirm/` | `confirm` | staff roles | — | 400 if cancelled or `advance_paid<=0`; idempotent for confirmed/active/completed |
| `POST /api/bookings/<pk>/cancel/` | `cancel` | staff roles | reason, notes | 400 if verified payments; releases plot |
| `GET /api/bookings/<pk>/payment_summary/` | `payment_summary` | any authenticated | — | float-serialized summary (precision loss) |
| `POST /api/installments/<pk>/mark_paid/` | `mark_paid` | staff roles | paid_amount, paid_date, payment_method | validates 0..total; posts verified Payment, bumps advance (capped), recalculates plan |
| `POST /api/reservations/<pk>/convert/` | `convert` | staff roles | — | 400 if not active / plot taken; creates confirmed booking at `plot.price` |
| CRUD `installment-plans` | `InstallmentPlanViewSet` | staff roles | … | `perform_create` auto-generates if `generate_now` (default true) — crashes if `installment_amount` unset/0 |

Serializer validation rules worth noting: `BookingCreateSerializer` enforces the
full price-guard set (§4); plain `BookingSerializer` (used for update) does
**not** re-apply the `total_cost` / `holding_deposit` guards — only
`total_amount>0` and `advance_paid>=0` — so an edit can under-sell or under-deposit
after create.

## 8. Test data & fixtures needed

- **Roles:** super_admin (for all), management (confirm/cancel/reopen/delete/
  transfer), sales (create/edit only), and a **customer portal user** (a `User`
  with a `Customer.user` link and no `UserProfile`) to prove the IDOR in §3.
- **Seed records:** a `Project` (`booking_open`), `ProjectPhase`, and a `Plot`
  with explicit `price`, `development_charge`, `lease_charge`, `other_charges`,
  `holding_deposit` (e.g. 100000 / 5000 / 2000 / 1000 / 10000 → `total_cost =
  108000`, `total_charges = 8000`, as in `api/tests_booking_pricing.py:28`); a
  `Customer` (with phone, cnic, email); an `InstallmentPlanTemplate` for the
  plan-generation path.
- **Isolation:** `booking_id`/`group_id` are parsed from the last row (not DB
  sequences) — tests must not assume IDs reset per test; use unique
  `plot_number` (unique per project), unique customer phones/emails, and
  timestamped names. The ID-reuse edge (§5.15) means assertions on exact
  `booking_id` values are brittle.
- **Fixtures for edge cases:** a booking with a **pending (non-verified)**
  payment and `advance_paid>0` (cancel bypass, §5.6); a cancelled booking whose
  plot was re-booked (reopen conflict, §5.7); a plan with
  `installment_amount=0` (API create crash, §5.9); a plan with `due_day=31`.

## 9. Key files (traceability)

- `bookings/models.py` — all booking-domain models, save hooks, state props,
  `auto_generate`/`recalculate`.
- `bookings/forms.py` — `BookingForm` price guards, `ReservationForm`,
  `InstallmentPlanForm` (due_day clamp).
- `bookings/serializers.py` — `BookingCreateSerializer` price guards,
  `BookingTransferSerializer` same-customer guard.
- `bookings/api_views.py` — `IsStaffOrAbove`, `BookingViewSet`
  (create/destroy/cancel/confirm/payment_summary), `InstallmentViewSet.mark_paid`,
  `ReservationViewSet.convert`.
- `bookings/views_installments.py` — installment plan list/detail, mark-paid,
  reschedule (finance-gated).
- `bookings/admin.py` — admin registrations (readonly ID/timestamps).
- `core/views.py` — `bookings_view`, `booking_create/edit/detail/delete/cancel/
  reopen/confirm/transfer_view`, `invoice_pdf_view` (1014–1443, 1792–1808).
- `properties/models.py` — `Plot` statuses, `total_charges`/`total_cost`
  (110–129), `holding_deposit` (99).
- `samana_erp/urls.py` — booking + installment URL wiring (47–68, 110–113).
- `api/urls.py` — router registration (58–64).
- `api/views.py` — `api_login`/`_is_customer_user` (15–16, 74–107) — evidence
  customers are authenticated API users.
- `customers/models.py:35`, `customers/serializers.py:103` — customer↔User link
  (no `UserProfile` created → role-less).
- `api/tests_booking_pricing.py` — existing coverage for pricing/cancel/reopen
  guards (not the IDOR or installment edge cases).
- Templates: `templates/booking_list` = `bookings.html`, `booking_form.html`,
  `booking_detail.html`, `booking_confirm.html`, `booking_cancel.html`,
  `booking_reopen.html`, `booking_transfer.html`, `invoice_pdf.html`.
