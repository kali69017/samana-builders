# Customers Module — QA Analysis

> Module: `customers/` (models, forms, serializers, DRF API) + the customer
> views that live in `core/views.py` (the monolith view layer). Prepared
> against `docs/qa/_shared-context.md` and `docs/qa/_analysis-template.md`.

---

## 1. Business purpose & user journeys

The customers module is the system of record for every person/entity that buys
(or may buy) a plot. A `Customer` is the anchor for bookings, payments, a
customer portal login (`User`), a nominee (legal successor), a per-customer
ledger, and receivable-aging snapshots. Customer CNIC (national ID) is the
primary de-duplication key; `CUS-XXXXX` is the human-facing ID; revenue, in
turn, flows from bookings that reference these customers.

Real journeys (role → action → outcome):

- **sales / admin / management** — *create a customer*: `/customers/create/`
  → fill first/last name, CNIC, phone, optional nominee → `CUS-XXXXX` is
  auto-assigned, welcome email is attempted (failure-safe), `AuditLog` row is
  written.
- **sales / admin** — *edit a customer*: `/customers/<pk>/edit/` → update
  contact/address/nominee → `AuditLog(update)` written.
- **admin** — *create a portal login*: `/customers/create-profile/` → pick an
  active customer, set username/email/password → a `User` is created and linked
  to the customer via `Customer.user` (OneToOne).
- **customer (self-service)** — *log in to portal*: `/login/` → redirected to
  `/portal` (React SPA) where they see their own bookings/payments/nominee.
- **management** — *delete a customer*: `/customers/<pk>/delete/` → blocked
  with an error if the customer has bookings or ledger entries; otherwise a
  hard delete.
- **any staff** — *search/list*: `/customers/?search=...` filters by ID, name,
  phone, or CNIC (substring).

---

## 2. Data model

### `Customer` (`customers/models.py:28-112`)

| Field | Type | Null/blank | Notes |
|---|---|---|---|
| `customer_id` | CharField(20) | unique, `editable=False` | `CUS-00001` auto-generated |
| `user` | OneToOne(User) | `null=True, blank=True`, `SET_NULL` | portal login link |
| `first_name` | CharField(100) | required | |
| `last_name` | CharField(100) | required | |
| `email` | EmailField | `unique=True, null=True, blank=True` | |
| `phone` | CharField(20) | required | **no validator at model level** |
| `alternate_phone` | CharField(20) | `blank=True` | |
| `cnic` | CharField(15) | `unique=True`, required | canonical dashed form `XXXXX-XXXXXXX-X` |
| `occupation` / `occupation_other` | Char(20)/Char(100) | `blank=True` | choice `business/salaried/other` |
| `address` / `city` / `notes` | Text/Char/Text | `blank=True` | |
| `document` / `image` | File/ImageField | `null=True, blank=True` | |
| `is_active` | Boolean | default True | soft-deactivation flag (NOT soft-delete) |
| `created_by` | FK(User) | `null=True`, `SET_NULL` | recorded but **never used for scoping** |
| timestamps | `created_at`/`updated_at` | auto | |

- `save()` hook (`models.py:54-64`): generates `CUS-XXXXX` by parsing the
  numeric suffix of the last row ordered by `-id` inside `transaction.atomic()`
  + `select_for_update()`. **Not concurrency-safe on SQLite** (no real row
  lock); the `unique=True` on `customer_id` is the only backstop. Reuses a
  deleted customer's suffix (no monotonic guarantee).
- Properties (`models.py:69-105`): `full_name`, `formatted_phone`,
  `formatted_alternate_phone`, `formatted_cnic` (all via `format_phone`/
  `format_cnic`), `occupation_display_value`, `total_bookings`, `total_paid`
  (sum of **verified** payments across bookings), `current_balance`
  (= `SUM(bookings.total_amount)` − `total_paid`).
- `Meta`: `ordering=['-created_at']`, indexes on `cnic` and `phone`.

### `CustomerLedgerEntry` (`models.py:115-147`)

- `customer` FK CASCADE, `booking` FK CASCADE nullable, `transaction_type`
  (10 choices incl. `refund`, `adjustment`, `reversal`), `reference_id` (plain
  CharField, **no uniqueness/idempotency**), `debit`/`credit` Decimal(15,2)
  default 0, `running_balance` Decimal(15,2) **required, no default**,
  `entry_date`, `created_by`.
- `Meta.ordering = ['entry_date', 'created_at']`.
- **No `save()` hook** — `running_balance` is only computed in the DRF
  `perform_create` (`api_views.py:168-178`), which looks up the last entry with
  a strictly earlier `entry_date` and adds `debit - credit`. Same-day entries,
  edits/deletes of prior entries, and out-of-order inserts are **not**
  reconciled → the stored balance can silently drift from the true running sum.

### `ReceivableAging` (`models.py:150-162`)

- Snapshot: `customer`/`booking` FK CASCADE, `current_balance`, `days_overdue`,
  `aging_bucket`, `computed_at` (`auto_now_add`). **No `save()` computation**;
  populated by seed/tests/report code. Read-only in admin.

### `CustomerNominee` (`models.py:165-179`)

- **OneToOne** to `Customer` (CASCADE), `nominee_name` (required, 200),
  `nominee_cnic` (15, blank), `nominee_phone` (20, blank), `relationship`
  (blank). One nominee per customer (enforced by OneToOne).

---

## 3. Roles & permissions

| Action | Allowed role(s) | Enforced by |
|---|---|---|
| List customers (`/customers/`) | **any authenticated user** | `@login_required` only (`core/views.py:603`) |
| Detail (`/customers/<pk>/`) | **any authenticated user** | `@login_required` only (`core/views.py:809`) |
| Create (`/customers/create/`) | **any authenticated user** | `@login_required` only (`core/views.py:627`) |
| Edit (`/customers/<pk>/edit/`) | **any authenticated user** | `@login_required` only (`core/views.py:693`) |
| Nominee manage | **any authenticated user** | `@login_required` only (`core/views.py:732`) |
| Profile PDF | **any authenticated user** | `@login_required` only (`core/views.py:1811`) |
| Create portal login | admin/super_admin | `@admin_or_above` (`core/views.py:667`) |
| Delete customer | management+ | `@management_or_above` (`core/views.py:784`) |
| API list/retrieve/search/ledger/bookings | **any authenticated user (GET)** | `IsAdminOrSuperAdmin.has_permission` allows SAFE_METHODS for all (`customers/api_views.py:19-20`) |
| API create/update/delete | super_admin/admin | `IsAdminOrSuperAdmin` (`customers/api_views.py:21-25`) |
| API ledger-entry create | super_admin/admin | same class |
| API profile-create | super_admin/admin | `IsAdminOrSuperAdmin` on `CustomerProfileCreateView` (`api_views.py:137`) |

**Object-level gating: absent.** `created_by` is recorded but never enforced.
There is no "sales can only see/edit their own customers" rule anywhere in the
module. Every `pk`-based view and every GET API endpoint is gated only on
"is logged in" — a `sales` user can view/edit any customer, and (see §6) a
customer-portal login can too.

**UI vs view mismatch:** `customers.html` and `customer_detail.html` show the
Delete link only when `can_delete` (management flag) is set, and hide payment
buttons behind `can_view_payments` — but the underlying `customer_edit_view`,
`customer_detail_view`, `customer_profile_pdf_view` have **no** role check, so
hiding the button is cosmetic only.

---

## 4. Business rules, state machines, invariants

- **Customer status**: `is_active` is a simple boolean flag (active/inactive);
  there is no formal lifecycle. Inactive customers are **still** returned by
  `customers_view` and the API (no default `is_active` filter), and still
  appear in the profile-create dropdown is filtered (`is_active=True`).
- **ID invariant**: `customer_id` is `unique` and generated in `save()`.
- **CNIC invariant**: canonical dashed form `XXXXX-XXXXXXX-X` (5-7-1, 13
  digits). `cnic` is `unique=True` at the model level.
- **Delete invariant** (`core/views.py:789`, `api_views.py:36`): a customer
  with any `bookings` or `ledger_entries` cannot be deleted — must deactivate.
  Note this is a **hard delete** otherwise (no soft-delete); related `Nominee`
  and `ReceivableAging` cascade.
- **Balance (two competing sources of truth)**:
  - `Customer.current_balance` = Σ booking `total_amount` − Σ **verified**
    payments (`models.py:102-105`). Refunds/ledger adjustments are **not**
    reflected.
  - `CustomerLedgerEntry.running_balance` = independent running sum.
  - `ReceivableAging.current_balance` = a third, snapshot-based figure.
  These three can diverge; nothing reconciles them.
- **Side effects**:
  - Create (UI + API): `NotificationService.send_customer_welcome()` (failure
    safe), `AuditLog(action='create', model='Customer')`.
  - Edit: `AuditLog(action='update')`.
  - Delete: `AuditLog(action='delete')`.
  - Profile create: `AuditLog(action='create', model='CustomerProfile')`.
  - Lead convert (`core/api_views.py:180-231`): creates Customer (dashed CNIC,
    dup-CNIC guarded), sends welcome, `AuditLog(update, model='Lead')`.

---

## 5. Edge cases (go deep)

**CNIC**
- 13 digits → normalized to dashed (`forms.py:57-66`); dashed input also
  accepted (digits stripped first). ✓
- Dashes/letters/spaces pasted → stripped client-side (`customer_form.html`
  JS) and server-side (`clean_cnic` strips `\D`). ✓
- **13 vs 15 digits**: the *model* stores the 15-char dashed string but the
  *form* and JS cap input at 13 raw digits; the *serializer* requires the
  15-char dashed form and does **not** normalize. The same logical CNIC must be
  submitted differently to the form (raw) vs the API (dashed). The
  `LeadViewSet.convert` path (`core/api_views.py:189-196`) only checks
  `len(cnic_raw) < 13` — a 14-digit raw CNIC slips through un-dashed.
- Duplicate CNIC: model `unique` + form `validate_unique` + serializer
  `UniqueValidator` (auto) all enforce, but against the **stored string**; a
  raw-13-digit value submitted straight to the API is rejected for format
  before uniqueness matters, so dedup is consistent for canonical inputs.

**Phone**
- Model: no validation (`max_length=20`). Form: strict `^\+92-\d{3}-\d{7}$`
  after `format_phone` normalization. Serializer: loose `^\+?[\d\-]{10,15}$`
  (`serializers.py:49-54`) — **accepts `"-----------"` (11 dashes)** and any
  dash/digit mix, storing garbage that the form would reject. Three-layer
  inconsistency.
- `format_phone` (`models.py:6-18`) normalizes `0`-prefixed (11-digit) and
  `92`-prefixed (12-digit) to `+92-XXX-XXXXXXX`; a 9-digit number is returned
  unchanged and then rejected by the form validator.

**Email**
- `unique=True` + `null=True` — multiple customers may have NULL email (fine),
  but two customers **cannot** share the same email string. Form and serializer
  both enforce. No normalization (case/whitespace) — `A@x.com` vs `a@x.com`
  are distinct, and `" a@x.com "` is stored verbatim (only `EmailField` format
  check applies).

**Auto ID**
- Concurrent creates under SQLite can race (no real `select_for_update` lock);
  the unique constraint raises `IntegrityError` rather than retrying — a
  double-submit/race shows a 500, not a friendly retry.
- Deleting the highest customer then creating reuses its suffix; if `id` order
  ever diverges from `customer_id` suffix order, `int(last.split('-')[1])`
  can collide or `ValueError`/`IndexError` on a malformed prior `customer_id`.

**Ledger running balance**
- Second entry on the **same `entry_date`** is ignored by the balance lookup
  (`entry_date__lt` only, `api_views.py:171-174`) → balance understated.
- Editing/deleting a prior entry never recomputes downstream balances.
- `running_balance` has **no default** and is excluded from
  `CustomerLedgerEntryForm`; creating via admin or `.objects.create()` without
  it raises `IntegrityError`.

**Nominee**
- OneToOne: `getattr(customer, 'nominee', None)` pattern is safe; a blank
  `nominee_name` removes the nominee (`core/views.py:751-754`).
- On `customer_edit_view` and `customer_create_view`, nominee validation errors
  are **silently swallowed** — the customer saves and redirects even when the
  nominee CNIC/phone is invalid, and no error is surfaced to the user.

**Delete**
- Guarded when bookings/ledger exist; otherwise **hard** delete. A customer
  with only a nominee (no bookings) deletes and the nominee cascades silently.

**Search/filter**
- CNIC is stored dashed; `icontains` search on the raw 13-digit string won't
  match (`customers.html` placeholder hints this). API exposes two different
  params: `search` (in `get_queryset`, `api_views.py:81`) vs `q` (in the
  `search` action, `api_views.py:99`) — redundant and inconsistent.
- No pagination on the HTML list (full queryset rendered); API list is
  unpaginated by default unless a pagination class is set elsewhere.

---

## 6. Cross-cutting risks

- **IDOR / broken object-level authorization (high)**: `customer_edit_view`,
  `customer_detail_view`, `customer_nominee_manage_view`,
  `customer_profile_pdf_view`, and all API GET endpoints are gated only on
  "authenticated". Any `sales` user — or a **customer-portal user** — can read
  or edit *any* customer by enumerating `pk`. `created_by` is never checked.
- **Sensitive data exposure (high)**: `CustomerSerializer` /
  `CustomerDetailSerializer` (`serializers.py:28-34, 124-131`) return `cnic`,
  `phone`, `alternate_phone`, `email`, `address`, `notes`, and `document`/`image`
  URLs to **any** authenticated GET caller (`IsAdminOrSuperAdmin` SAFE_METHODS
  path). `CustomerLedgerEntryViewSet` similarly exposes the full ledger. The
  HTML detail page (`customer_detail.html:84-98`) renders full CNIC + phone +
  email to any logged-in viewer. The HTML list page does *not* show CNIC/email.
- **Customer → ERP access (high)**: `_post_login_target` (`core/views.py:28-37`)
  routes portal customers to `/portal`, but nothing prevents them navigating to
  `/customers/`, `/customers/<pk>/`, or `/customers/<pk>/pdf/` — all
  `@login_required` only. No `is_staff` guard, no middleware (settings.py
  MIDDLEWARE, `samana_erp/settings.py:78-88`).
- **XSS (low)**: all customer fields render through Django auto-escaping
  (`{{ }}`); no `|safe`/`mark_safe`/`innerHTML` in customer templates; the form
  JS uses `textContent`/`.value` assignment. Mitigated.
- **CSRF (ok)**: all state-changing forms include `{% csrf_token %}`; DRF uses
  `SessionAuthentication` (settings.py:220-227) which enforces CSRF on
  non-safe methods. No `@csrf_exempt` in the customer views.
- **Profile-create overwrite (medium)**: neither `CustomerProfileForm.save`
  (`forms.py:135-142`) nor `CustomerProfileCreateSerializer.create`
  (`serializers.py:103-112`) checks whether the customer already has a `user`;
  re-creating a profile for a customer silently **orphans** the previous `User`
  (it remains active and can still log in) and re-links the customer.
- **Profile-create active filter inconsistency (low)**: the HTML form filters
  `is_active=True` (`forms.py:93`); the API serializer uses
  `Customer.objects.all()` (`serializers.py:86`).

---

## 7. API surface

| Method + path | Handler | Permission | Request fields | Notes |
|---|---|---|---|---|
| GET `/api/customers/` | `CustomerViewSet.list` | any auth (GET) | `?search=`, `?is_active=` | returns full PII + balances |
| POST `/api/customers/` | `CustomerViewSet.create` | super_admin/admin | `CustomerCreateSerializer`: `first_name`,`last_name`,`phone`,`cnic` (dashed) required; `email`,`alternate_phone`,`address`,`city`,`notes`,`is_active`,`document`,`image` optional | no `occupation`/`user` fields |
| GET `/api/customers/<id>/` | retrieve | any auth | — | `CustomerDetailSerializer` + `ledger_summary` |
| PUT/PATCH `<id>` | update/partial | super_admin/admin | `CustomerSerializer` | cnic must be dashed; phone loose |
| DELETE `<id>` | `destroy` | super_admin/admin | — | blocked if bookings/ledger |
| GET `/api/customers/?search=` vs `/api/customers/search/?q=` | list vs `search` action | any auth | `search` vs `q` | duplicated, different param names |
| GET `/api/customers/<id>/ledger/` | `ledger` action | any auth | — | all ledger entries (debit/credit/balance) |
| GET `/api/customers/<id>/bookings/` | `bookings` action | any auth | — | bookings serialized |
| POST `/api/customer-profiles/` | `CustomerProfileCreateView.post` | super_admin/admin | `username`,`email`,`password`,`confirm_password`,`customer`(pk) | creates `User`, links to customer |
| `/api/customer-ledger/` (full CRUD) | `CustomerLedgerEntryViewSet` | write: super_admin/admin, read: any auth | debit/credit/ref etc. | `perform_create` computes running balance |

Serializer validation rules:
- `validate_cnic` = `^\d{5}-\d{7}-\d{1}$` (both serializers).
- `validate_phone` = `^\+?[\d\-]{10,15}$` (both) — loose.
- Uniqueness (email/cnic) via DRF `UniqueValidator` auto-generated from model
  `unique=True`.

---

## 8. Test data & fixtures needed

- **Roles**: create `UserProfile` rows for `sales`, `management`, `admin`, and
  a bare non-staff `User` linked to a `Customer` (to exercise the
  customer-portal access hole). Login as each and assert access matrix.
- **Customers**: one with bookings+ledger (delete must be blocked), one clean
  (delete must succeed), one inactive (search/portal-dropdown behavior).
- **Uniqueness isolation**: CNIC/email/phone values must be globally unique per
  test run (timestamped) since `cnic`/`email` are `unique=True`; `customer_id`
  auto-increments from existing rows so tests must not assume a specific `CUS-`
  value.
- **CNIC matrix**: 13-digit raw, 15-char dashed, 14-digit (should be rejected
  by form/serializer but slips through `LeadViewSet.convert`), dashes pasted.
- **Phone matrix**: `+92-300-1234567`, `03001234567`, `92...`, `"-----------"`,
  9 digits — assert form vs serializer divergence.
- **Ledger**: two entries on the same `entry_date` to reproduce the running
  balance under-count.

---

## 9. Key files

- `customers/models.py` — `Customer`, `CustomerLedgerEntry`, `ReceivableAging`,
  `CustomerNominee`, `format_phone`/`format_cnic`.
- `customers/forms.py` — `validate_cnic`/`validate_phone`, `CustomerForm`,
  `CustomerProfileForm`, `CustomerLedgerEntryForm`, `CustomerNomineeForm`.
- `customers/serializers.py` — `CustomerSerializer`, `CustomerCreateSerializer`,
  `CustomerProfileCreateSerializer`, `CustomerDetailSerializer`,
  `CustomerLedgerEntrySerializer`.
- `customers/api_views.py` — `IsAdminOrSuperAdmin`, `CustomerViewSet`,
  `CustomerProfileCreateView`, `CustomerLedgerEntryViewSet`.
- `customers/admin.py` — admin registrations (ledger delete disabled; aging
  add/change disabled).
- `customers/views.py` — empty (no ERP views here; see core).
- `core/views.py` — `customers_view`, `customer_create_view`,
  `customer_profile_create_view`, `customer_edit_view`,
  `customer_nominee_manage_view`, `customer_delete_view`,
  `customer_detail_view`, `customer_profile_pdf_view`, `_post_login_target`.
- `core/api_views.py` — `IsAdminOrReadOnly`/`IsStaffOrAbove` (for contrast),
  `LeadViewSet.convert` (alternate customer-creation path).
- `core/permissions.py` — role decorators (only some customer views use them).
- `payments/pdf_utils.py` — `generate_customer_profile_pdf` (context: bookings,
  verified payments total, nominee).
- `templates/customers.html`, `customer_form.html`, `customer_detail.html`,
  `customer_profile_form.html`, `customer_nominee_form.html`,
  `customer_profile_pdf.html`.
- `samana_erp/settings.py` — `REST_FRAMEWORK` (SessionAuthentication,
  IsAuthenticated default), `MIDDLEWARE` (no staff gate).
- `samana_erp/urls.py` — customer routes (lines 27-33, 69).
