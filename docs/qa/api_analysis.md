# API Module — QA Analysis

> DRF auth + portal surface. Covers `api/views.py`, `api/urls.py`, `core/api_views.py`
> (permission classes + settings singleton), and the `permission_classes` / `@action`
> surface of every app ViewSet. Read together with `_shared-context.md`.

## 1. Business purpose & user journeys

The `api` module is the DRF REST surface of the ERP: a session-based (cookie +
CSRF) JSON API consumed by the SPA, the corporate homepage, and the customer
portal. It authenticates users (csrf → login → session → me), serves the
customer self-service dashboard, and exposes CRUD ViewSets for every domain
model (customers, properties, bookings, payments, finance, HR). It is also the
corporate site's data feed (`plots/list` for homepage inventory,
`company-settings` for branding, `company-settings/summary` for public stats).

User journeys:

- **Any visitor** — `GET /api/auth/csrf/` seeds the CSRF cookie → SPA sends
  `X-CSRFToken` on unsafe calls (`api/views.py:64-69`).
- **Any visitor** — `GET /api/plots/list/` fetches up to 20 *available* plots for
  the homepage (`properties/api_views.py:147-161`).
- **Staff / admin** — `POST /api/auth/login/` → `_user_payload` (role, is_staff,
  is_superuser) → SPA gates UI on `role` (`api/views.py:72-107`).
- **Customer** — `POST /api/auth/login/` with their portal account → SPA calls
  `GET /api/portal/` → their own bookings/payments/installments
  (`api/views.py:129-220`).
- **Admin** — `POST /api/customer-profiles/` creates a portal login linked to a
  Customer (`customers/api_views.py:135-160`).
- **Admin** — `GET/PATCH /api/company-settings/` reads/edits the singleton
  (`core/api_views.py:265-278`).

## 2. Data model

This module owns no models of its own. It is the transport over the domain apps.
The auth-specific model it depends on:

- **`core.LoginAttempt`** (`core/models.py:43-50`) — `username` (Char 150),
  `ip_address` (GenericIPAddressField, null/blank), `is_success` (bool default
  False), `timestamp` (auto_now_add), `Meta.ordering = ['-timestamp']`. Fed by
  `_record_login_attempt` (`api/views.py:40-44`).
- **`core.CompanySettings`** — a singleton (`CompanySettings.load()`,
  `core/api_views.py:270-278`).
- **`core.UserProfile.role`** — `CharField(choices=ROLE_CHOICES, default='sales')`
  with NO save() guard; `super_admin` is a valid choice (`core/models.py:14-27`).
  This is the crux of the privilege-escalation finding in §3.

No `save()` hooks, `unique_together`, or validation live in the api module
itself; all invariants belong to the domain apps.

## 3. Roles & permissions

### DRF permission classes (definitions)

| Class | Location | READ (SAFE) | WRITE (unsafe) |
|---|---|---|---|
| `IsAdminOrReadOnly` | `core/api_views.py:13-24` | any authenticated | super_admin/admin (or is_superuser) |
| `IsSuperAdmin` | `core/api_views.py:27-37` | super_admin only | super_admin only — **defined but UNUSED** |
| `IsStaffOrAbove` (core) | `core/api_views.py:40-49` | super_admin/admin only | super_admin/admin — **defined but UNUSED** |
| `IsAdminOrSuperAdmin` | `customers/api_views.py:15-25`, `properties/api_views.py:15-25` | any authenticated | super_admin/admin |
| `ReadOnlyForLowerRoles` | `properties/api_views.py:28-39` | any authenticated | super_admin/admin/management |
| `IsStaffOrAbove` (bookings) | `bookings/api_views.py:27-48` | any authenticated | super_admin/admin/management/sales; DELETE limited to management+ (object perm) |
| `IsStaffReadAdminWrite` | `payments/api_views.py:15-35` | any authenticated | super_admin/admin/management/accounts; DELETE limited to management+ (object perm) |
| `IsFinanceOrAbove` | `finance/api_views.py:15-25` | any authenticated | super_admin/admin/management/accounts |
| `IsHRManagement` | `hr/api_views.py:23-33` | any authenticated | super_admin/admin/management/hr |

### Global default

`REST_FRAMEWORK` (`settings.py:220-227`): `SessionAuthentication` only, default
permission `IsAuthenticated`. **No `TokenAuthentication`.** Every override below
is per-ViewSet.

### Permission matrix (ViewSet → effective permission)

| Endpoint (router prefix) | ViewSet | Permission | Notes |
|---|---|---|---|
| `/api/users/` | UserViewSet | `IsAdminOrReadOnly` | `me` (get/patch), `toggle_active` (post) |
| `/api/audit-logs/` | AuditLogViewSet | `IsAdminOrReadOnly` | ReadOnly; `[:100]` cap |
| `/api/profile/` | ProfileViewSet | `IsAuthenticated` | `list`, `update_profile` (patch) |
| `/api/leads/`, `lead-notes/`, `agents/` | … | `IsAdminOrReadOnly` | `set_status`, `convert`, `bookings` actions |
| `/api/customers/`, `customer-ledger/` | Customer… | `IsAdminOrSuperAdmin` | `search`, `ledger`, `bookings` actions |
| `/api/customer-profiles/` | CustomerProfileCreateView | `IsAdminOrSuperAdmin` | POST only |
| `/api/projects/`, `phases`, `plots`, `features`, `milestones` | … | `ReadOnlyForLowerRoles` | `change_status`, `set_status` actions |
| `/api/price-history/` | PriceHistoryViewSet | `IsAuthenticated` | ReadOnly |
| `/api/plots/list/` | `plots_list_api` | **`AllowAny`** | public |
| `/api/bookings/`, `installments`, `reservations`, `transfers`, `settlements` | … | `IsStaffOrAbove` (bookings) | `cancel`, `confirm`, `payment_summary`, `mark_paid`, `convert` |
| `/api/payments/`, `receipts`, `refunds`, `allocations` | … | `IsStaffReadAdminWrite` / `IsAuthenticated` (receipts) | `verify`, `upload_attachment`, `mark_bounced`, `approve/reject/process` |
| `/api/account-transactions/`, `offices`, `expenses`, `budgets`, `costs`, `investments` | … | `IsFinanceOrAbove` | `approve`, `pay` |
| `/api/departments/` … `/api/leaves/` | HR ViewSets | `IsHRManagement` | `generate`, `process`, `pay`, `approve`, `reject` |
| `/api/company-settings/` | CompanySettingsViewSet | `IsAdminOrReadOnly` | GET list + PATCH/PUT update; `summary` GET |

### Critical findings on permissions

1. **Every ViewSet grants READ to *any authenticated* user** — including
   customer portal accounts. None of the permission classes gates on
   `is_staff`/role for SAFE_METHODS; all return `True` for
   `request.user.is_authenticated`. See §6 (sensitive data exposure).
2. **`ProfileViewSet.update_profile` is `IsAuthenticated`** (`core/api_views.py:121-138`)
   and `UserProfileSerializer` leaves `role` **writable**
   (`core/serializers.py:9-15`), with no guard on the model
   (`core/models.py:27`). **Any authenticated user (including a customer) can
   PATCH `/api/profile/update_profile/` with `{"role": "super_admin"}`** and
   escalate their own role. This is a privilege-escalation vulnerability.
3. **Two different `IsStaffOrAbove` classes exist** — `core/api_views.py:40`
   (admin-only) and `bookings/api_views.py:27` (sales included). The core one
   (plus `IsSuperAdmin`) is **dead code** — `grep` shows no ViewSet imports it;
   `CLAUDE.md:125` references them as the DRF equivalents, which is misleading.
   The naming collision invites a future "fix" that silently changes semantics.
4. `@action` methods (e.g. `toggle_active`, `change_status`, `approve`,
   `process`, `convert`) **do not add their own permission classes** — they
   inherit the ViewSet-level class. That is mostly fine for write actions
   (method = POST, so the WRITE branch applies), but any GET `@action` (e.g.
   `AgentViewSet.bookings`, `CustomerViewSet.search`/`ledger`/`bookings`,
   `PaymentViewSet.payment_summary`) is READ-gated → accessible to any
   authenticated user.

## 4. Business rules, state machines, invariants

The api module enforces only a small subset directly; the rest lives in the
domain apps (serializers + `perform_*`/`@action` methods):

- **Login lockout** — 5 failed attempts per username (or 15 per IP) within 15
  minutes → 429 (`api/views.py:19-44, 79-84`). A success does not reset the
  failed counter (no reset path — records persist but are time-windowed).
- **Deactivated vs bad credentials** — `authenticate()` returns None for both;
  explicit `is_active` check returns 403 vs 400 (`api/views.py:88-97`).
  *Side effect:* user enumeration.
- **Login/logout audit** — every login/logout writes an `AuditLog`
  (`api/views.py:101-106, 113-118`).
- **Lead → customer conversion** — `convert` validates CNIC length, uniqueness,
  phone presence, fires `send_customer_welcome`, writes audit
  (`core/api_views.py:180-231`).
- **Customer deletion guard** — `destroy` blocks deletion when bookings or
  ledger entries exist (`customers/api_views.py:33-41`).
- **Payment `verify` / refund `process` / expense `approve`+`pay` / booking
  `confirm`/`cancel`** — each performs domain transitions (ledger post,
  plot release, etc.) inside `@action` handlers; invariants (advance_paid ≥
  holding_deposit, refund ≤ refundable, idempotent ledger) are enforced in the
  domain serializers/models (see `_shared-context.md`), NOT re-checked here.
- **`portal_dashboard`** — scoped strictly to `Customer.objects.filter(user=request.user)`
  (`api/views.py:133-136`); active statuses = `pending/confirmed/active`
  (`api/views.py:138`); `total_paid` = verified payments only
  (`api/views.py:143-145`).

## 5. Edge cases (go deep)

- **Unauthenticated access** — `plots_list_api` is the only anonymous endpoint
  and is filtered to `status='available'` with a 20-row cap
  (`properties/api_views.py:157-159`). Everything else returns 401/403 via
  `IsAuthenticated` or the local classes (`has_permission` short-circuits on
  `is_authenticated`).
- **Customer account accessing staff endpoints** — allowed for all GETs (see §3).
  A customer calling `GET /api/customers/` receives the full customer roster
  (CNIC/phone/address/notes). **EXPECTED: 403.** Actual: 200.
- **Privilege escalation via `role` PATCH** — `update_profile` with
  `{"role":"super_admin"}` succeeds because the serializer field is writable and
  the model has no guard. **EXPECTED: forbidden.** Actual: 200 + escalated role.
- **Login brute force** — IP lockout is 3× the username threshold (15), so a
  botnet or rotating proxies bypass it; no CAPTCHA; no lockout on the
  `csrf_token` endpoint (harmless GET). Lockout is per username *or* IP, so a
  legitimate user on a shared IP behind 15 failures is locked out (DoS on the
  username, not the attacker).
- **User enumeration** — 403 ("deactivated") vs 400 ("invalid") reveals valid
  usernames (`api/views.py:88-97`). **EXPECTED:** identical response.
- **`next_due` data shape** — `portal_dashboard` assigns the *entire* installment
  dict (not a date) to `summary.next_due` via `min(..., key=...)`
  (`api/views.py:186-187`). The SPA must know it's a dict; fragile contract.
- **Decimal → float coercion** — `float(b.total_amount)`, `float(p.amount)`,
  `float(total_amount - total_paid)` (`api/views.py:164-166, 200-202, 212`)
  discard `Decimal` precision (PKR, 2dp — loss is small but the shared context
  says assert money EXACTLY). Summary `remaining_balance` can go negative.
- **`total_amount` could be None** — `sum((b.total_amount for ...), 0)` crashes
  on any booking with a null `total_amount` (`api/views.py:142`); no guard.
- **No pagination** — `DEFAULT_PAGINATION_CLASSES` is unset, so every list
  endpoint (except `AuditLogViewSet.get_queryset()[:100]` at
  `core/api_views.py:115` and `plots_list_api[:20]`) returns the **entire table**
  in one response. `CustomerViewSet.search` calls `self.paginate_queryset`
  (`customers/api_views.py:111`) but returns `None` with no paginator configured
  → effectively unpaginated. Large tables (payments, ledger) → huge responses.
- **Malformed JSON / wrong method** — `api_login` does
  `request.data.get('username','')`; with non-JSON body DRF's parsers raise a
  415/400 (negotiation). No custom handling — acceptable default, but a
  `Content-Type: application/json` with `null` body yields `request.data = {}`
  → 400 invalid credentials (fine). `@action` handlers read `request.data.get`
  without schema checks → missing key → 400 "Invalid status" style errors.
- **Wrong verb** — `plots_list_api` is `@api_view(['GET'])`; POST → 405. `company-settings`
  routes GET→`list`, PATCH/PUT→`update`, but **DELETE** is not mapped → 405
  (fine). `portal_dashboard` GET-only → 405.
- **Expired/invalid session** — SessionAuthentication reads the session; a
  deleted/expired session → unauthenticated → 401 for IsAuthenticated endpoints.
- **IDOR on `@action` detail routes** — `payment_summary`, `payment_summary` on
  Booking, `mark_paid` on Installment, `approve/reject/process` on Refund all
  take `pk` and call `self.get_object()`; object-level auth is only the
  DELETE branch of `IsStaffOrAbove`/`IsStaffReadAdminWrite`
  (`bookings/api_views.py:40-48`, `payments/api_views.py:28-35`). There is no
  per-object ownership check, so any authenticated user with WRITE access can
  act on any `pk` — but because WRITE is role-gated, the residual risk is
  cross-customer *read* (no object-level read gating at all).

## 6. Cross-cutting risks

- **Sensitive data exposure (highest severity, non-anonymous).** With READ
  allowed for every authenticated user, a customer portal account can enumerate:
  - `/api/users/` → staff `username`, `email`, `phone`, `cnic`, `is_active`
    (`core/serializers.py:17-25`, profile via `UserProfileSerializer:9-15`).
  - `/api/customers/` → every customer's `cnic`, `phone`, `alternate_phone`,
    `address`, `notes` (`customers/serializers.py:20-34`); detail adds
    `total_paid`, `current_balance`, `ledger_summary`
    (`customers/serializers.py:115-131`).
  - `/api/bookings/`, `/api/payments/` → amounts, methods, statuses.
  - `/api/audit-logs/` → `ip_address` + actor/action (`core/serializers.py:60-66`).
  - `/api/employees/` + HR → CNIC/phone/salary components.
  - `/api/company-settings/summary/` → revenue/expenses/net-profit
    (`core/api_views.py:280-302`).
  These are effectively a full customer/staff PII dump to any logged-in
  customer. No `is_staff`/role check, no object-level row filtering.
- **Privilege escalation** — writable `role` via `ProfileViewSet.update_profile`
  (see §3.2). `is_active` is also writable there (self-lockout, minor).
- **CSRF** — DRF's `APIView.as_view()` wraps every view in `csrf_exempt`, so
  Django's `CsrfViewMiddleware` is bypassed; the *only* protection is
  `SessionAuthentication.enforce_csrf()`, which runs solely for **authenticated
  session requests on unsafe methods**. Consequences:
  - Authenticated POST/PUT/PATCH/DELETE on ViewSets → CSRF-enforced (good).
  - `api_login` (`AllowAny`, unauthenticated) → **not CSRF-protected** → login
    CSRF / forced-login (low–medium; `auth_login` does rotate the session key,
    mitigating session fixation).
  - `csrf_token` (`@ensure_csrf_cookie`) does force the cookie even on the
    csrf_exempt view (it calls `_get_token`, marking `CSRF_COOKIE_USED`), so the
    SPA handshake works.
- **XSS** — serializers return plain fields; the SPA must escape. No `|safe`
  usage here; low direct risk, but `full_name`/`notes`/`description` values are
  user-controlled strings returned verbatim.
- **IDOR / broken object-level authorization** — no row-level ownership filter
  anywhere; a low-privilege authenticated user with WRITE (e.g. `sales` on
  bookings) can act on any booking `pk`; a customer with READ can read any row.
- **Accessibility** — API only (JSON); no template rendering, so a11y N/A.

## 7. API surface

### Auth & portal (`api/views.py`, routes `api/urls.py:107-118`)

| Method + Path | Handler | Permission | Request | Response |
|---|---|---|---|---|
| GET `/api/auth/csrf/` | `csrf_token` | AllowAny | — | `{detail}` + sets `csrftoken` cookie |
| POST `/api/auth/login/` | `api_login` | AllowAny | `username`, `password` | 200 `_user_payload`; 400 invalid; 403 deactivated; 429 locked |
| POST `/api/auth/logout/` | `api_logout` | IsAuthenticated | — | `{detail:'Logged out.'}` |
| GET `/api/auth/me/` | `current_user` | IsAuthenticated | — | `_user_payload` (id, username, email, full_name, is_staff, is_superuser, is_customer, role) |
| GET `/api/portal/` | `portal_dashboard` | IsAuthenticated | — | customer + summary + bookings + payments + installments |
| GET `/api/plots/list/` | `plots_list_api` | AllowAny | — | ≤20 available PlotSerializer rows |
| GET/PATCH/PUT `/api/company-settings/` | CompanySettingsViewSet | IsAdminOrReadOnly | serializer fields | CompanySettingsSerializer |
| GET `/api/company-settings/summary/` | `summary` | IsAdminOrReadOnly (READ) | — | revenue/expenses/counts |
| POST `/api/customer-profiles/` | CustomerProfileCreateView | IsAdminOrSuperAdmin | customer, username, password, confirm_password | user id/username/email/customer_id/full_name |

### `_user_payload` shape (`api/views.py:47-61`)

`id, username, email, full_name, is_staff, is_superuser, is_customer, role`
(`role` = profile.role, or `'customer'` when a Customer is linked and no
profile role). Exposing `role`/`is_superuser` is acceptable for self-service but
confirms the escalation target in §3.2.

### ViewSet actions of note

- `UserViewSet.me` (get/patch) — PATCH gated by `IsAdminOrReadOnly` → admin only
  (`core/api_views.py:70-81`); `toggle_active` (post) blocks self-deactivation
  (`core/api_views.py:83-99`).
- `LeadViewSet.set_status` / `convert` (`core/api_views.py:163-231`).
- `AgentViewSet.bookings` (get) (`core/api_views.py:257-262`).
- `CustomerViewSet.search` (get) / `ledger` (get) / `bookings` (get)
  (`customers/api_views.py:97-132`).
- `PlotViewSet.change_status` (post) (`properties/api_views.py:115-127`);
  `ProjectMilestoneViewSet.set_status` (post) (`properties/api_views.py:176-187`).
- `BookingViewSet.cancel` / `confirm` / `payment_summary`
  (`bookings/api_views.py:160-297`); `InstallmentViewSet.mark_paid`
  (`bookings/api_views.py:326-378`); `ReservationViewSet.convert`
  (`bookings/api_views.py:394-447`).
- `PaymentViewSet.verify` / `upload_attachment` (multipart) / `mark_bounced`
  (`payments/api_views.py:82-262`); `RefundViewSet.approve` / `reject` / `process`
  (`payments/api_views.py:300-343`).
- `OfficeExpenseViewSet.approve` / `pay` (`finance/api_views.py:82-98`).
- `PayrollRunViewSet.generate` / `process` / `pay`; `LeaveViewSet.approve` /
  `reject` (`hr/api_views.py:105-141, 187-201`).

## 8. Test data & fixtures needed

- **Roles** — seed one user per role (`super_admin`, `admin`, `management`,
  `accounts`, `sales`, `hr`) plus a `customer` (a `User` linked via
  `Customer.user`). Use `UserProfile.objects.create(...)` directly or
  `UserCreateSerializer` (admin-gated). Superuser auto = super_admin.
- **Customer portal user** — `Customer.objects.create(user=user, cnic=..., phone=...)`
  then log in via `/api/auth/login/`.
- **CSRF token** — fetch `/api/auth/csrf/`, capture `csrftoken` cookie, send
  `X-CSRFToken` header on unsafe calls (or set `enforce_csrf` expectations).
- **Isolation** — customer CNICs and usernames must be unique per run; the
  `format_cnic`/`validate_cnic` normalizers reject <13-digit CNICs
  (`customers/serializers.py:42-55`). Timestamp any created Customers/Bookings so
  parallel runs don't collide on auto-generated IDs (see `_shared-context.md`).
- **Money** — assert Decimal values EXACTLY (not `assertAlmostEqual`) per shared
  context; note the API coerces to `float` in `portal_dashboard`, so portal tests
  should compare `float(expected)`.

## 9. Key files (for traceability)

- `api/views.py` — csrf/login/logout/me/portal_dashboard; lockout + `_user_payload`.
- `api/urls.py` — router registration, plots/list, company-settings singleton,
  auth + portal routes, `rest_framework.urls` include (DRF browsable login/logout).
- `core/api_views.py` — `IsAdminOrReadOnly`/`IsSuperAdmin`/`IsStaffOrAbove`
  (latter two unused), UserViewSet, AuditLogViewSet, ProfileViewSet (escalation),
  Lead/LeadNote/Agent ViewSets, CompanySettingsViewSet.
- `core/serializers.py` — `UserSerializer` (staff PII), `UserProfileSerializer`
  (writable `role`), `AuditLogSerializer` (ip_address).
- `customers/api_views.py` — `IsAdminOrSuperAdmin`, CustomerViewSet (+search/
  ledger/bookings), CustomerProfileCreateView.
- `customers/serializers.py` — CustomerSerializer/CustomerDetailSerializer
  (CNIC/phone/address/ledger summary).
- `properties/api_views.py` — `ReadOnlyForLowerRoles`, `plots_list_api`
  (AllowAny), Plot/Project/Milestone ViewSets.
- `bookings/api_views.py` — local `IsStaffOrAbove` (sales write), Booking/
  Installment/Reservation ViewSets + `@action`s.
- `payments/api_views.py` — `IsStaffReadAdminWrite`, Payment/Receipt/Refund/
  Allocation ViewSets + verify/approve/process actions.
- `finance/api_views.py` — `IsFinanceOrAbove`, ledger/office/expense ViewSets.
- `hr/api_views.py` — `IsHRManagement`, payroll/attendance/leave ViewSets.
- `samana_erp/settings.py` — `REST_FRAMEWORK` (SessionAuthentication only, no
  pagination, default IsAuthenticated), CSRF/SESSION_COOKIE_SECURE flags.
- `core/models.py` — `UserProfile` (unguarded `role`), `LoginAttempt`.
