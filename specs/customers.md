# Customers — Test Plan

> Source of truth: `docs/qa/customers_analysis.md` (file:line citations) and
> `docs/qa/_shared-context.md`. Scenario IDs are the contract: Phase C test names
> must match `CUS-<CATEGORY>-<NN>` exactly.

## 1. Scope & roles

This plan covers the customer system of record: create / edit / view / search /
nominee management, the customer-portal login (profile-create), the customer
profile PDF, the DRF customer + ledger endpoints, and the associated security
surface. It exercises both the HTML views (which live in `core/views.py`, the
monolith view layer) and the DRF API (`customers/api_views.py`).

Roles exercised and what each is expected to be allowed/denied:

| Role | Create/edit/detail/nominee/PDF (HTML) | Profile-create (HTML) | Delete (HTML) | API GET | API POST/PUT/DELETE |
|---|---|---|---|---|---|
| `super_admin` / `admin` | allowed | allowed | allowed | allowed | allowed |
| `management` | allowed | **denied** (`@admin_or_above`) | allowed (`@management_or_above`) | allowed | **denied** |
| `sales` | allowed | denied | denied | allowed | denied |
| `accounts` / `staff` | allowed | denied | denied | allowed | denied |
| **customer-portal user** (non-staff `User` linked to a `Customer`) | **allowed (BUG — see SEC)** | denied | denied | **allowed (BUG — see SEC)** | denied |
| anonymous | denied (→ `/login/`) | denied | denied | denied (401/403) | denied |

The important caveat the whole SEC group is built around: `customer_create_view`,
`customer_edit_view`, `customer_nominee_manage_view`, `customer_detail_view`,
`customer_profile_pdf_view`, and `customers_view` are gated only on
`@login_required` (`core/views.py:603,627,693,732,809,1811`) — there is **no**
role check and **no** object-level check. `created_by` is recorded but never
enforced. Only profile-create (`@admin_or_above`, `core/views.py:667`) and
delete (`@management_or_above`, `core/views.py:784`) carry a role decorator.

## 2. Preconditions & fixtures

**Server**: `DJANGO_DEBUG=True python manage.py runserver` (without `DEBUG`
every request 301s via `SECURE_SSL_REDIRECT`). Base URL `http://127.0.0.1:8000`.

**Default login**: `admin` / `admin123` (a superuser → always treated as
`super_admin`).

**Users to create** (each needs a `UserProfile` unless noted):
- `qa_sales` — role `sales` (the default role on a new profile).
- `qa_mgmt` — role `management`.
- `qa_acct` — role `accounts`.
- `qa_portal` — a **non-staff** `User` (no `is_staff`, **no** `UserProfile`)
  linked to a `Customer` via `Customer.user`, so login routes to `/portal`.

**Customers to create**:
- `qa_clean` — no bookings, no ledger, optionally a nominee (delete must succeed).
- `qa_rich` — has ≥1 booking and ≥1 ledger entry (delete must be blocked).
- `qa_inactive` — `is_active=False`.

**Unique value recipe** (CNIC/email/phone/`customer_id` are global across runs):
```python
import time
raw_cnic = '37405' + str(int(time.time()))[-8:]          # 13 digits
cnic     = f'{raw_cnic[:5]}-{raw_cnic[5:12]}-{raw_cnic[12:]}'  # dashed 15-char
phone    = '+92-300-' + str(int(time.time()))[-7:]       # +92-XXX-XXXXXXX
email    = f'qa+{int(time.time())}@example.com'
```

**URLs exercised** (relative to base):
- `/customers/`, `/customers/create/`, `/customers/create-profile/`
- `/customers/<pk>/`, `/customers/<pk>/edit/`, `/customers/<pk>/nominee/`,
  `/customers/<pk>/delete/`, `/customers/<pk>/pdf/`
- `/api/customers/`, `/api/customers/<id>/`, `/api/customers/<id>/ledger/`,
  `/api/customers/<id>/bookings/`, `/api/customers/search/`,
  `/api/customer-ledger/`, `/api/customer-profiles/`

## 3. Scenario catalog

### HP — happy path

**CUS-HP-01 — Create customer: auto CUS-XXXXX ID + failure-safe welcome email**
- **Preconditions**: logged in as `admin`.
- **Steps**:
  1. GET `/customers/create/`.
  2. Submit `first_name=Ali`, `last_name=Khan`, `cnic=<raw 13 digits>`,
     `phone=+92-300-1234567`, `email=<unique>`.
  3. Note the redirect target and success message.
  4. Repeat once with email left blank (still valid).
  5. Repeat with `EMAIL_ENABLED=False` / broken SMTP (simulate) and confirm
     creation still succeeds.
- **Expected result**: customer persisted with `customer_id` matching
  `^CUS-\d{5}$` (next suffix after existing rows); `cnic` stored dashed
  `XXXXX-XXXXXXX-X`; `AuditLog(action='create', model_name='Customer')` written;
  `NotificationService.send_customer_welcome` called but a failure there never
  prevents creation or shows a 500 (redirect to `/customers/` + success message
  in every case, including blank email and broken email).
- **Evidence on failure**: no `CUS-` row / non-matching id, `cnic` stored raw,
  missing audit row, or an HTTP 500 / no redirect when email delivery raises.

**CUS-HP-02 — Edit customer**
- **Preconditions**: logged in as `admin`; customer `qa_clean` exists.
- **Steps**: GET `/customers/<pk>/edit/`, change `phone` and `city`, submit.
- **Expected result**: fields updated, `updated_at` advanced,
  `AuditLog(action='update')` written, redirect to `/customers/` + success
  message. CNIC field pre-fills as raw 13 digits (dashes stripped).
- **Evidence on failure**: stale values, missing audit row, form re-renders with
  errors on valid input.

**CUS-HP-03 — View detail (CNIC / bookings)**
- **Preconditions**: logged in as `admin`; `qa_rich` has a booking + a verified
  payment.
- **Steps**: GET `/customers/<pk>/`.
- **Expected result**: page renders full name, dashed CNIC, phone, email,
  address, nominee (if any), list of bookings, and latest payment.
- **Evidence on failure**: 404, missing fields, empty bookings/payments when they
  should render.

**CUS-HP-04 — Search by name / phone / CNIC**
- **Preconditions**: logged in as `admin`; customers with known first name,
  phone, and dashed CNIC exist.
- **Steps**: GET `/customers/?search=<first_name>`, then
  `?search=<phone fragment>`, then `?search=<dashed cnic fragment>`.
- **Expected result**: each query returns the matching customer(s); list
  filtered case-insensitively (substring) across `customer_id`, `first_name`,
  `last_name`, `phone`, `cnic`.
- **Evidence on failure**: matching customer absent from list, or search returns
  empty on a known value.

**CUS-HP-05 — Add nominee**
- **Preconditions**: logged in as `admin`; customer with no nominee.
- **Steps**: GET `/customers/<pk>/nominee/`, submit `nominee_name`,
  `nominee_cnic=<13 raw digits>`, `relationship`.
- **Expected result**: `CustomerNominee` created (OneToOne) with CNIC stored
  dashed; redirect to `/customers/<pk>/`; `AuditLog(action='update',
  model_name='CustomerNominee')`.
- **Evidence on failure**: no nominee row, CNIC stored raw, wrong redirect.

**CUS-HP-06 — Edit nominee**
- **Preconditions**: logged in as `admin`; customer already has a nominee.
- **Steps**: GET `/customers/<pk>/nominee/`, change `nominee_phone`, submit.
- **Expected result**: same nominee row updated (no second row), redirect to
  detail with success message.
- **Evidence on failure**: duplicate nominee (would violate OneToOne → 500), or
  values unchanged.

**CUS-HP-07 — Remove nominee**
- **Preconditions**: logged in as `admin`; customer has a nominee.
- **Steps**: GET `/customers/<pk>/nominee/`, clear `nominee_name`, submit.
- **Expected result**: nominee deleted, redirect to detail, `AuditLog` with
  "Removed nominee" description.
- **Evidence on failure**: nominee still present, or error on submit.

**CUS-HP-08 — Create portal login (profile-create)**
- **Preconditions**: logged in as `admin`; active customer `qa_clean` with no
  `user`.
- **Steps**: GET `/customers/create-profile/`, select the customer, set
  username/email/password/confirm (password ≥ 6, matching), submit.
- **Expected result**: a `User` created with `is_staff=False`, `Customer.user`
  linked (OneToOne), `AuditLog(action='create', model_name='CustomerProfile')`,
  redirect to `/customers/` + success message. New login lands on `/portal/`.
- **Evidence on failure**: no `User`, customer not linked, login lands on
  `/dashboard/` instead of `/portal/`.

**CUS-HP-09 — Customer profile PDF**
- **Preconditions**: logged in as `admin`; customer with a booking + verified
  payment + nominee.
- **Steps**: GET `/customers/<pk>/pdf/`.
- **Expected result**: `200` with `Content-Type: application/pdf`,
  `Content-Disposition` `attachment; filename="customer_profile_CUS-XXXXX.pdf"`;
  PDF body includes customer name/CNIC, bookings, verified-payments total, and
  nominee.
- **Evidence on failure**: non-PDF response, redirect to detail with "Failed to
  generate customer profile PDF", or missing content in the PDF.

### EC — edge case / boundary

**CUS-EC-01 — Duplicate CNIC rejected**
- **Preconditions**: customer `qa_rich` exists with a known dashed CNIC.
- **Steps**: as `admin`, create (or edit `qa_clean` to) the same CNIC.
- **Expected result**: rejected — form re-renders with a uniqueness error on
  `cnic`; no new/updated row with the duplicate CNIC.
- **Evidence on failure**: two customers sharing the CNIC, or success message.

**CUS-EC-02 — Duplicate email rejected**
- **Preconditions**: customer `qa_rich` has email `a@b.com`.
- **Steps**: as `admin`, create (or edit) another customer with email `a@b.com`.
- **Expected result**: rejected with uniqueness error on `email` (form and
  serializer both enforce via model `unique=True`).
- **Evidence on failure**: two customers sharing the email. (Note: multiple
  NULL emails remain allowed — not an error.)

**CUS-EC-03 — Phone format divergence (form strict vs serializer loose)**
- **Preconditions**: none beyond login.
- **Steps**:
  1. HTML: submit `phone=-----------` (11 dashes) via `/customers/create/`.
  2. API: `POST /api/customers/` as `admin` with `phone="-----------"`.
- **Expected result**: HTML form **rejects** it (`^\+92-\d{3}-\d{7}$` after
  `format_phone`); the API **accepts** it (`^\+?[\d\-]{10,15}$`,
  `serializers.py:49-54`) and stores `"-----------"` verbatim.
- **Evidence on failure**: HTML accepts the garbage (form validator not applied)
  or API rejects it (serializer tightened) — either is a regression from current
  behavior; record which layer diverges.

**CUS-EC-04 — CNIC format asymmetry (form normalizes 13-digit, serializer requires dashed)**
- **Preconditions**: none.
- **Steps**:
  1. HTML: submit raw 13 digits → must succeed and store dashed.
  2. API: `POST /api/customers/` with raw 13 digits (no dashes).
  3. API: `POST /api/customers/` with the dashed 15-char form.
- **Expected result**: HTML normalizes to dashed; API **rejects** raw 13 digits
  (`^\d{5}-\d{7}-\d{1}$`) and accepts only the dashed form. The same logical
  CNIC must be submitted differently to each surface.
- **Evidence on failure**: API accepting raw 13 digits (normalization added), or
  HTML rejecting raw digits (normalization removed).

**CUS-EC-05 — Ledger running_balance drift on same-date entries**
- **Preconditions**: as `admin`, a customer with no ledger entries.
- **Steps**:
  1. `POST /api/customer-ledger/` entry A: `debit=100`, `entry_date=D`.
     → `running_balance=100`.
  2. `POST /api/customer-ledger/` entry B: `debit=50`, `entry_date=D` (same day).
- **Expected result**: entry B's `running_balance` = **100**, not 150 — the
  lookup uses `entry_date__lt` (`api_views.py:171-174`) so same-day entries are
  ignored and the balance under-counts the true running sum (150).
- **Evidence on failure**: B shows 150 (lookup changed to `__lte`) — then the
  documented drift bug is fixed and this scenario becomes a regression check for
  the *correct* 150.

**CUS-EC-06 — Nominee validation errors silently swallowed**
- **Preconditions**: logged in as `admin`; customer with no nominee.
- **Steps**: create (or edit) a customer and submit a nominee with an invalid
  `nominee_phone` (e.g. `abc`) while customer fields are valid.
- **Expected result**: the customer saves and redirects with a **success**
  message; the invalid nominee is silently dropped (no nominee row, no error
  surfaced) — `nominee_form.is_valid()` is checked but errors are never rendered
  (`core/views.py:639,705`).
- **Evidence on failure**: an error is shown to the user (validation surfacing
  fixed), or a nominee with invalid phone is persisted.

**CUS-EC-07 — 14-digit CNIC in lead-convert slips through**
- **Preconditions**: logged in as `admin`; an unconverted `Lead` exists.
- **Steps**: `POST /api/leads/<id>/convert/` with `cnic` = 14 digits, a name,
  and a phone.
- **Expected result**: conversion succeeds and the customer's `cnic` is stored
  as the **raw 14-digit** string (un-dashed) — `format_cnic` only transforms
  exactly-13-digit input (`models.py:21-25`) and `LeadViewSet.convert` only
  guards `len(cnic_raw) < 13` (`core/api_views.py:191`), so 14 digits pass.
- **Evidence on failure**: conversion rejected (guard tightened to `!= 13`), or
  CNIC stored dashed.

**CUS-EC-08 — CNIC pasted with dashes/letters is normalized in the form**
- **Preconditions**: logged in as `admin`.
- **Steps**: in `/customers/create/`, paste `37405-1234567-1` (or
  `37405 1234567 1` with letters) into CNIC, submit.
- **Expected result**: `clean_cnic` strips `\D` then formats, storing the
  canonical dashed form; success.
- **Evidence on failure**: validation error on valid digits, or CNIC stored with
  stray characters.

### SEC — negative & security (prioritized)

**CUS-SEC-01 — IDOR: sales user reads any customer detail**
- **Preconditions**: `qa_sales` logged in; a customer owned by another actor
  exists (any `pk`).
- **Steps**:
  1. Login as `qa_sales`.
  2. Directly GET `/customers/<pk>/` for a customer `qa_sales` did not create.
  3. Also GET `/customers/<pk>/edit/` and `/customers/<pk>/nominee/`.
- **Expected result (current, vulnerable)**: **200** and full CNIC/phone/email/
  address render for any `pk`; the edit and nominee forms load. (`@login_required`
  only — `core/views.py:809,693,732`; `created_by` never checked.)
- **Evidence on failure (i.e. fixed)**: redirect to `/dashboard/` with a denial
  message, or 403/404 for cross-actor `pk`s.

**CUS-SEC-02 — IDOR: sales user edits any customer**
- **Preconditions**: `qa_sales` logged in; victim customer `qa_rich` exists.
- **Steps**: `qa_sales` POSTs to `/customers/<qa_rich pk>/edit/` changing the
  phone.
- **Expected result (vulnerable)**: change persists, `AuditLog(action='update')`
  written under `qa_sales`; victim's data mutated.
- **Evidence on failure (fixed)**: denied, data unchanged.

**CUS-SEC-03 — IDOR: sales user manages any customer's nominee**
- **Preconditions**: `qa_sales` logged in; victim customer with a nominee.
- **Steps**: `qa_sales` POSTs to `/customers/<victim pk>/nominee/` with a blank
  `nominee_name`.
- **Expected result (vulnerable)**: victim's nominee deleted.
- **Evidence on failure (fixed)**: denied, nominee intact.

**CUS-SEC-04 — IDOR: any authenticated user downloads any customer profile PDF**
- **Preconditions**: `qa_sales` logged in; victim customer with bookings.
- **Steps**: GET `/customers/<victim pk>/pdf/`.
- **Expected result (vulnerable)**: **200** PDF containing the victim's full
  PII + financial history (`@login_required` only, `core/views.py:1811`).
- **Evidence on failure (fixed)**: denial / redirect.

**CUS-SEC-05 — Portal customer reaches /customers/* (no is_staff gate)**
- **Preconditions**: `qa_portal` (non-staff, non-profile, linked to a Customer)
  logged in; `_post_login_target` sends them to `/portal` but nothing enforces
  staying there.
- **Steps**:
  1. Login as `qa_portal`; confirm landing on `/portal/`.
  2. Manually navigate to `/customers/`, `/customers/<pk>/`,
     `/customers/<pk>/edit/`, `/customers/<pk>/pdf/`.
- **Expected result (vulnerable)**: all render (list, full detail incl. other
  customers' CNIC/phone/email, edit form, PDF). No `is_staff`/role guard exists
  in the views or middleware.
- **Evidence on failure (fixed)**: non-staff is redirected away from `/customers/*`.

**CUS-SEC-06 — API PII exposure: any authenticated user GETs full customer data**
- **Preconditions**: `qa_sales` (or `qa_portal`) has a session; ≥1 customer with
  CNIC/phone/email/address exists.
- **Steps**:
  1. Login as `qa_sales`.
  2. `GET /api/customers/` and `GET /api/customers/<id>/`.
  3. Inspect the JSON for `cnic`, `phone`, `alternate_phone`, `email`,
     `address`, `notes`, `document`, `image`.
- **Expected result (vulnerable)**: **200** with full PII + balances returned.
  `IsAdminOrSuperAdmin.has_permission` returns `True` for all `SAFE_METHODS`
  when authenticated (`api_views.py:16-20`).
- **Evidence on failure (fixed)**: 403 for non-admin GET, or PII fields redacted
  from the response.

**CUS-SEC-07 — Profile-create overwrite orphans the previous User**
- **Preconditions**: `admin` logged in; customer `qa_rich` already has a linked
  `User` (old login).
- **Steps**: run profile-create again for `qa_rich` (HTML or
  `POST /api/customer-profiles/`) with a new username/password.
- **Expected result (vulnerable)**: new `User` created and `Customer.user`
  re-linked; the **old `User` remains active and can still log in** (orphaned).
  Neither `CustomerProfileForm.save` (`forms.py:135-142`) nor
  `CustomerProfileCreateSerializer.create` (`serializers.py:103-112`) checks for
  an existing `user`.
- **Evidence on failure (fixed)**: re-create rejected ("customer already has a
  profile"), or the old `User` is deactivated/deleted.

**CUS-SEC-08 — Delete guard: blocked when bookings/ledger exist**
- **Preconditions**: `management` (or `admin`) logged in; `qa_rich` has
  bookings/ledger.
- **Steps**: GET then POST `/customers/<qa_rich pk>/delete/`.
- **Expected result**: deletion blocked with error "Cannot delete a customer
  with bookings or ledger history…", redirect to detail, customer intact
  (`core/views.py:789`).
- **Evidence on failure**: customer deleted, or 500.

**CUS-SEC-09 — Delete: hard delete when clean (nominee cascades)**
- **Preconditions**: `management` logged in; `qa_clean` has a nominee but no
  bookings/ledger.
- **Steps**: POST `/customers/<qa_clean pk>/delete/`.
- **Expected result**: customer **hard-deleted** (no soft-delete), nominee and
  any `ReceivableAging` cascade, `AuditLog(action='delete')` written, redirect
  to `/customers/`.
- **Evidence on failure**: customer still present (soft-delete), or orphaned
  nominee.

**CUS-SEC-10 — Unauthenticated access redirects to login (baseline)**
- **Preconditions**: logged out.
- **Steps**: GET `/customers/`, `/customers/<pk>/`, `/customers/<pk>/edit/`,
  `/customers/<pk>/pdf/`, and `GET /api/customers/`.
- **Expected result**: HTML views redirect to `/login/`; API returns 401/403
  (not 200).
- **Evidence on failure**: any 200 with data while unauthenticated.

### API — API contract

**CUS-API-01 — GET /api/customers/ (list)**
- **Preconditions**: `admin` (or any authenticated user) with a session.
- **Steps**: `GET /api/customers/`; then `?is_active=true`.
- **Expected result**: 200; full `CustomerSerializer` list (incl. `cnic`,
  `phone`, `email`, `total_bookings`, `total_paid`, `current_balance`);
  `is_active` filter narrows to active only. Unpaginated by default.
- **Evidence on failure**: non-200, missing fields, filter ignored.

**CUS-API-02 — POST /api/customers/ (create)**
- **Preconditions**: `admin` logged in.
- **Steps**: `POST /api/customers/` with `first_name`, `last_name`, `phone`,
  dashed `cnic` (required), optional `email`.
- **Expected result**: 201; `customer_id` auto-generated; welcome email attempted
  (failure-safe); `AuditLog(create)`. Missing required fields or non-dashed CNIC
  → 400 with field errors.
- **Evidence on failure**: 400 on valid input, no auto-ID, missing audit.

**CUS-API-03 — Search param names diverge (search vs q)**
- **Preconditions**: authenticated; a customer with known last name.
- **Steps**:
  1. `GET /api/customers/?search=<last_name>`.
  2. `GET /api/customers/search/?q=<last_name>`.
  3. `GET /api/customers/search/?search=<last_name>` (cross-wired).
- **Expected result**: (1) filters via `get_queryset` on `search`; (2) filters
  via the `search` action on `q`; (3) returns **all** customers (the `search`
  action ignores `search` and reads only `q` — `api_views.py:99`).
- **Evidence on failure**: (1) and (2) both honor the same param name, or (3)
  filters — either indicates the duplicated-param inconsistency was resolved.

**CUS-API-04 — customer_bookings action**
- **Preconditions**: authenticated; `qa_rich` with bookings.
- **Steps**: `GET /api/customers/<qa_rich id>/bookings/`.
- **Expected result**: 200; `BookingSerializer` list of that customer's bookings.
- **Evidence on failure**: 404/403, wrong customer's bookings, or non-booking
  payload.

**CUS-API-05 — customer_ledger action**
- **Preconditions**: authenticated; `qa_rich` with ledger entries.
- **Steps**: `GET /api/customers/<qa_rich id>/ledger/`.
- **Expected result**: 200; `CustomerLedgerEntrySerializer` list with
  `debit`/`credit`/`running_balance`/`transaction_type_display`.
- **Evidence on failure**: missing entries or fields.

**CUS-API-06 — Customer delete semantics**
- **Preconditions**: `admin` logged in; `qa_rich` (bookings) and `qa_clean`
  (none).
- **Steps**: `DELETE /api/customers/<qa_rich id>/` then
  `DELETE /api/customers/<qa_clean id>/`.
- **Expected result**: `qa_rich` → **400** with error body (guard,
  `api_views.py:36`); `qa_clean` → **204** hard delete + `AuditLog(delete)`.
- **Evidence on failure**: 204 on the guarded customer, or 400 on the clean one.

**CUS-API-07 — PUT/PATCH validation (dashed CNIC required, loose phone)**
- **Preconditions**: `admin` logged in; customer exists.
- **Steps**: `PATCH /api/customers/<id>/` with raw 13-digit `cnic` (expect 400),
  then dashed `cnic` (expect 200), then `phone="-----------"` (expect 200).
- **Expected result**: CNIC must be dashed (`^\d{5}-\d{7}-\d{1}$`); phone
  accepts dash-only (`^\+?[\d\-]{10,15}$`).
- **Evidence on failure**: opposite acceptance/rejection at either field.

**CUS-API-08 — POST /api/customer-profiles/ (portal login)**
- **Preconditions**: `admin` logged in; active customer without a `user`.
- **Steps**: `POST /api/customer-profiles/` with `username`, `email`,
  `password` (≥6), `confirm_password`, `customer=<pk>`.
- **Expected result**: 201 with `{id, username, email, customer_id, full_name}`;
  `User` created and linked; `AuditLog(CustomerProfile)`.
- **Evidence on failure**: 400 on valid input, no link, or 201 but customer not
  linked.

## 4. Data isolation rules

- All CNIC / email / phone / username values are **timestamped** so runs never
  collide with each other or with previously created rows (`cnic` and `email`
  are `unique=True`).
- `customer_id` (`CUS-XXXXX`) auto-increments from existing rows — never assert a
  specific suffix; assert the regex `^CUS-\d{5}$` and (when needed) the relative
  ordering to the last known row.
- Use dedicated fixture customers (`qa_clean`, `qa_rich`, `qa_inactive`) and
  dedicated users (`qa_sales`, `qa_mgmt`, `qa_acct`, `qa_portal`) and do not
  reuse them for mutation scenarios that change their state (create fresh ones
  per scenario or restore state).
- After destructive scenarios (delete, hard-delete, nominee removal), clean up
  any remaining rows so later scenarios don't depend on the outcome.

## 5. Coverage checklist (for the master map)

- CUS-HP-01 — Create customer: auto CUS-XXXXX ID + failure-safe welcome email
- CUS-HP-02 — Edit customer
- CUS-HP-03 — View detail (CNIC / bookings)
- CUS-HP-04 — Search by name / phone / CNIC
- CUS-HP-05 — Add nominee
- CUS-HP-06 — Edit nominee
- CUS-HP-07 — Remove nominee
- CUS-HP-08 — Create portal login (profile-create)
- CUS-HP-09 — Customer profile PDF
- CUS-EC-01 — Duplicate CNIC rejected
- CUS-EC-02 — Duplicate email rejected
- CUS-EC-03 — Phone format divergence (form strict vs serializer loose)
- CUS-EC-04 — CNIC format asymmetry (form normalizes, serializer requires dashed)
- CUS-EC-05 — Ledger running_balance drift on same-date entries
- CUS-EC-06 — Nominee validation errors silently swallowed
- CUS-EC-07 — 14-digit CNIC in lead-convert slips through
- CUS-EC-08 — CNIC pasted with dashes/letters is normalized in the form
- CUS-SEC-01 — IDOR: sales user reads any customer detail
- CUS-SEC-02 — IDOR: sales user edits any customer
- CUS-SEC-03 — IDOR: sales user manages any customer's nominee
- CUS-SEC-04 — IDOR: any authenticated user downloads any customer profile PDF
- CUS-SEC-05 — Portal customer reaches /customers/* (no is_staff gate)
- CUS-SEC-06 — API PII exposure: any authenticated user GETs full customer data
- CUS-SEC-07 — Profile-create overwrite orphans the previous User
- CUS-SEC-08 — Delete guard: blocked when bookings/ledger exist
- CUS-SEC-09 — Delete: hard delete when clean (nominee cascades)
- CUS-SEC-10 — Unauthenticated access redirects to login (baseline)
- CUS-API-01 — GET /api/customers/ (list)
- CUS-API-02 — POST /api/customers/ (create)
- CUS-API-03 — Search param names diverge (search vs q)
- CUS-API-04 — customer_bookings action
- CUS-API-05 — customer_ledger action
- CUS-API-06 — Customer delete semantics
- CUS-API-07 — PUT/PATCH validation (dashed CNIC required, loose phone)
- CUS-API-08 — POST /api/customer-profiles/ (portal login)
