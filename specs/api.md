# API Module — Test Plan

> DRF auth + portal surface. Covers `api/views.py`, `api/urls.py`, `core/api_views.py`
> (permission classes + User/AuditLog/Profile/CompanySettings ViewSets), and the
> `permission_classes` / `@action` surface of every app ViewSet.
> Source of truth for findings: `docs/qa/api_analysis.md` and `docs/qa/_shared-context.md`.

## 1. Scope & roles

This plan tests the session-based (cookie + CSRF) DRF JSON surface: the auth
handshake (`csrf → login → me → logout`), the customer portal dashboard, the
public corporate feed (`plots/list`, `company-settings/summary`), and the
permission model of every registered ViewSet (users, customers, properties,
bookings, payments, finance, HR). The two headline risk areas are:

1. **Privilege escalation** — `ProfileViewSet.update_profile` (`IsAuthenticated`)
   with a writable `role` field lets any authenticated user (including a
   customer) PATCH their own role to `super_admin`.
2. **Read-open authorization** — every permission class returns `True` for
   `SAFE_METHODS` on any authenticated user, so a customer portal account can
   dump staff/customer PII and financials across all endpoints.

Roles exercised (seeded per §2): `super_admin`, `admin`, `management`,
`accounts`, `sales`, `hr`, and `customer` (a `User` linked via `Customer.user`).
Anonymous is exercised on `plots/list` and the login/csrf endpoints.

Expected-denied roles: `customer` (and low staff roles) must be **denied** all
writes and **denied** cross-tenant reads. Today they are not — these are the
failure assertions.

## 2. Preconditions & fixtures

### Base URL & flags

- Base: `http://127.0.0.1:8000` (run `DJANGO_DEBUG=True python manage.py runserver`
  — without it `SECURE_SSL_REDIRECT` 301s every request).
- Default admin: `admin` / `admin123`.

### Seed roles (create cleanly, timestamped)

Seed one `User` + `UserProfile` per role via Django shell (or an admin-gated
`UserCreateSerializer` POST):

```python
from django.contrib.auth.models import User
from core.models import UserProfile
def seed(u, role):
    usr = User.objects.create_user(username=u, password='Passw0rd!x', email=f'{u}@test.local')
    UserProfile.objects.create(user=usr, role=role)
    return usr
seed('qa_super', 'super_admin')   # plus rely on `admin`/admin123 (is_superuser => super_admin)
seed('qa_admin', 'admin')
seed('qa_mgmt', 'management')
seed('qa_acct', 'accounts')
seed('qa_sales', 'sales')
seed('qa_hr', 'hr')
```

Seed a **customer portal user** (the critical actor for SEC scenarios):

```python
from django.contrib.auth.models import User
from customers.models import Customer
u = User.objects.create_user(username='qa_cust', password='Passw0rd!x', email='cust@test.local',
                             first_name='Portal', last_name='Customer')
Customer.objects.create(user=u, first_name='Portal', last_name='Customer',
                        cnic='35202-1234567-1', phone='03001234567', email='cust@test.local')
```

Also seed a **second customer** (`qa_cust2`) with a distinct CNIC/phone, plus at
least one `Booking` + verified `Payment` on each customer (for `portal_dashboard`
scoping). For the `total_amount` crash case, create a `Booking` with
`total_amount=None`.

### CSRF handshake (used by every unsafe call)

```bash
curl -s -c cj.txt http://127.0.0.1:8000/api/auth/csrf/      # -> {"detail":"CSRF cookie set"}
CSRF=$(awk '/csrftoken/{print $7}' cj.txt)                   # read cookie value
```

Reuse `-b cj.txt` on every subsequent call and send `-H "X-CSRFToken: $CSRF"`
on unsafe methods. Logins also write the `sessionid` cookie into the jar.

### URLs exercised

`/api/auth/csrf/`, `/api/auth/login/`, `/api/auth/logout/`, `/api/auth/me/`,
`/api/portal/`, `/api/plots/list/`, `/api/company-settings/`,
`/api/company-settings/summary/`, `/api/customer-profiles/`, and router prefixes
`/api/users/`, `/api/audit-logs/`, `/api/profile/`, `/api/customers/`,
`/api/bookings/`, `/api/payments/`, `/api/receipts/`, `/api/refunds/`,
`/api/employees/`, `/api/leaves/`, `/api/offices/`.

## 3. Scenario catalog

---

### Category HP — happy path

---

#### API-HP-01 — CSRF → login → session handshake

- **Preconditions:** dev server running; `admin`/`admin123`.
- **Steps:**
  1. `curl -si -c cj.txt http://127.0.0.1:8000/api/auth/csrf/`
  2. `CSRF=$(awk '/csrftoken/{print $7}' cj.txt)`
  3. `curl -si -b cj.txt -c cj.txt -H "Content-Type: application/json" -H "X-CSRFToken: $CSRF" -d '{"username":"admin","password":"admin123"}' http://127.0.0.1:8000/api/auth/login/`
  4. Inspect `cj.txt` for `sessionid`.
- **Expected result:** step 1 → `200`, body `{"detail":"CSRF cookie set"}`, `Set-Cookie: csrftoken=…`. Step 3 → `200`, JSON body with keys `id, username, email, full_name, is_staff, is_superuser, is_customer, role`; `role` == `"super_admin"` (superuser), `is_superuser` == `true`. Cookie jar contains `sessionid`.
- **Evidence on failure:** status code ≠ 200; missing `csrftoken`/`sessionid` cookie; body missing `role`/`is_superuser` keys.

---

#### API-HP-02 — `current_user`/`me` returns the role

- **Preconditions:** logged-in admin session from API-HP-01.
- **Steps:**
  1. `curl -s -b cj.txt http://127.0.0.1:8000/api/auth/me/`
- **Expected result:** `200`, body == `_user_payload`: `{"id":…,"username":"admin",…,"is_staff":true,"is_superuser":true,"is_customer":false,"role":"super_admin"}`.
- **Evidence on failure:** 401 (session lost); `role` null/wrong; missing keys.

---

#### API-HP-03 — `portal_dashboard` scoped to `request.user`

- **Preconditions:** `qa_cust` (1 booking + 1 verified payment) and `qa_cust2`
  (1 booking) exist. Log in as `qa_cust`.
- **Steps:**
  1. Login `qa_cust` (same handshake as API-HP-01).
  2. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/portal/`
  3. Assert every `bookings[].booking_id` and `payments[].booking_id` belongs to `qa_cust` only (none from `qa_cust2`).
- **Expected result:** `200`; top-level keys `customer, summary, bookings, payments, installments`. `summary.total_paid` == sum of `qa_cust` verified payments. **No** `qa_cust2` rows appear.
- **Evidence on failure:** a `qa_cust2` booking/payment appears → cross-tenant data leak; 403 `{"detail":"No customer profile linked…"}` for a customer that should have one.

---

#### API-HP-04 — `api_logout` ends the session

- **Preconditions:** logged-in admin session.
- **Steps:**
  1. `CSRF=$(awk '/csrftoken/{print $7}' cj.txt)`
  2. `curl -s -b cj.txt -H "X-CSRFToken: $CSRF" -X POST http://127.0.0.1:8000/api/auth/logout/`
  3. `curl -s -b cj.txt http://127.0.0.1:8000/api/auth/me/`
- **Expected result:** step 2 → `200` `{"detail":"Logged out."}`; step 3 → `401` (or `403`) because session is flushed.
- **Evidence on failure:** step 3 still `200` (logout did not invalidate session).

---

#### API-HP-05 — public `plots/list` (anonymous)

- **Preconditions:** some plots in `status='available'` and some non-available.
- **Steps:**
  1. `curl -s http://127.0.0.1:8000/api/plots/list/`
- **Expected result:** `200` without any auth cookie; JSON array of ≤ 20 rows, all with `status == "available"`.
- **Evidence on failure:** 401/403 (regression to auth-gated); a non-available plot present; > 20 rows.

---

### Category EC — edge case / boundary

---

#### API-EC-01 — `summary.next_due` is a full installment dict, not a date

- **Preconditions:** `qa_cust` has a pending or overdue installment.
- **Steps:**
  1. Log in `qa_cust`; `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/portal/`
  2. Inspect `$.summary.next_due`.
- **Expected result:** `next_due` is a **JSON object** with keys `id, booking_id, installment_number, due_date, amount, late_fee, paid_amount, remaining_amount, status` — NOT a string/date. Document this contract; the SPA must treat it as an object.
- **Evidence on failure:** `next_due` serialized as a date string (contract regression) or `null` when an installment exists.

---

#### API-EC-02 — `sum(total_amount)` crashes on null `total_amount`

- **Preconditions:** `qa_cust` has one active booking with `total_amount=None`
  (created directly in DB bypassing serializer validation).
- **Steps:**
  1. Log in `qa_cust`; `curl -si -b cj_cust.txt http://127.0.0.1:8000/api/portal/`
- **Expected result (current, buggy):** `500 Internal Server Error`; server logs a `TypeError: unsupported operand type(s) for +: 'decimal.Decimal' and 'NoneType'` (or similar) at `api/views.py:142`.
- **Intended result:** `200` with `total_amount` treated as `0`/skipped.
- **Evidence on failure:** server traceback; the whole portal 500s because one booking has a null amount.

---

#### API-EC-03 — no pagination (full tables returned)

- **Preconditions:** a payments table with many rows (e.g. > 100 via `populate_dummy_data.py`).
- **Steps:**
  1. Log in as `admin`; `curl -s -b cj.txt http://127.0.0.1:8000/api/payments/ | python -c "import sys,json; d=json.load(sys.stdin); print(len(d))"`
  2. Compare to `Payment.objects.count()`.
- **Expected result (current):** the response is a bare JSON array with **no** `count`/`next`/`previous` envelope; `len(d)` == full table row count (unbounded).
- **Evidence on failure:** response truncated or paginated (would indicate a default paginator was introduced); huge latency on large tables.

---

#### API-EC-04 — `float()` coercion of Decimal money in portal

- **Preconditions:** `qa_cust` with a booking of a precise 2-dp amount (e.g. `total_amount=1234567.89`).
- **Steps:**
  1. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/portal/`
  2. Assert `summary.total_amount`, `summary.total_paid`, `summary.remaining_balance`, `bookings[].total_amount` types.
- **Expected result:** values are Python `float` (JSON numbers), i.e. `float(expected)` equals the JSON value exactly; `remaining_balance` can be negative when `total_paid > total_amount`. Money precision beyond 2dp is lost (documented).
- **Evidence on failure:** value returned as a string (e.g. `"1234567.89"`), or off-by-fraction-of-paisa that breaks an exact-money assertion.

---

#### API-EC-05 — `portal_dashboard` for an account with no linked Customer → 403

- **Preconditions:** log in as a staff user with no `Customer.user` link (e.g. `qa_sales`).
- **Steps:**
  1. `curl -s -b cj_sales.txt http://127.0.0.1:8000/api/portal/`
- **Expected result:** `403` `{"detail":"No customer profile linked to this account."}`.
- **Evidence on failure:** 200 (portal serving non-customer), or 500.

---

#### API-EC-06 — malformed JSON / wrong method

- **Preconditions:** logged-in session (for the 405 cases).
- **Steps:**
  1. `curl -si -H "Content-Type: text/plain" -d 'username=admin' http://127.0.0.1:8000/api/auth/login/`
  2. `curl -si -X DELETE -b cj.txt -H "X-CSRFToken: $CSRF" http://127.0.0.1:8000/api/company-settings/`
  3. `curl -si -X POST http://127.0.0.1:8000/api/plots/list/`
  4. `curl -si -X POST -b cj_cust.txt -H "X-CSRFToken: $CSRF" http://127.0.0.1:8000/api/portal/`
- **Expected result:** step 1 → `415` (unsupported media type); step 2 → `405` (DELETE not routed); step 3 → `405` (GET-only view); step 4 → `405` (`portal_dashboard` is GET-only).
- **Evidence on failure:** any of these returning 200/500 instead of the expected 4xx.

---

### Category SEC — negative & security

---

#### API-SEC-01 — CRITICAL: `update_profile` privilege escalation by a customer

- **Preconditions:** `qa_cust` exists with NO `UserProfile` row (portal-only
  customer). Log in as `qa_cust`.
- **Steps:**
  1. `curl -s -c cj_cust.txt http://127.0.0.1:8000/api/auth/csrf/`
  2. `CSRF=$(awk '/csrftoken/{print $7}' cj_cust.txt)`
  3. `curl -s -b cj_cust.txt -c cj_cust.txt -H "Content-Type: application/json" -H "X-CSRFToken: $CSRF" -d '{"username":"qa_cust","password":"Passw0rd!x"}' http://127.0.0.1:8000/api/auth/login/`
  4. `curl -si -b cj_cust.txt -H "Content-Type: application/json" -H "X-CSRFToken: $CSRF" -X PATCH -d '{"role":"super_admin"}' http://127.0.0.1:8000/api/profile/update_profile/`
  5. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/auth/me/`
  6. (Optional) attempt an admin-only write, e.g. `POST /api/users/` with a new user body.
- **Expected result (current, VULNERABLE):** step 4 → `200` with `"role":"super_admin"` (serializer `role` is writable; model has no guard); step 5 → `"role":"super_admin"`; step 6 → `201` (a customer now creates users). **Intended:** step 4 → `403` and role unchanged.
- **Evidence on failure:** step 4 response body showing `"role":"super_admin"`; `auth/me` role flipped; any subsequent admin action succeeding. Capture `core/models.py:27` (`role` with no guard) and `core/serializers.py:14` (writable field) as traceability.

---

#### API-SEC-02 — CRITICAL: escalation by a low-privilege staff user (generalizes)

- **Preconditions:** `qa_sales` (role `sales`, has a `UserProfile`). Log in as `qa_sales`.
- **Steps:**
  1. Repeat API-SEC-01 steps 4–6 with `qa_sales`.
- **Expected result (VULNERABLE):** `200` + `"role":"super_admin"`; `is_active` also writable (self-lockout) and `phone`/`cnic` writable.
- **Evidence on failure:** same as API-SEC-01, proving the flaw is not specific to portal customers but any authenticated principal with a profile.

---

#### API-SEC-03 — CRITICAL: customer reads `/api/users/` (staff PII)

- **Preconditions:** `qa_cust` logged in; several staff users with `phone`/`cnic` set.
- **Steps:**
  1. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/users/`
- **Expected result (VULNERABLE):** `200` + full array of every user, each with `username, email, first_name, last_name, is_active` and nested `profile.phone`, `profile.cnic`. **Intended:** `403` for non-management.
- **Evidence on failure:** response containing staff `cnic`/`phone`/`email` while authenticated only as a customer.

---

#### API-SEC-04 — CRITICAL: customer reads `/api/customers/` (customer CNIC/phone/address)

- **Preconditions:** `qa_cust` logged in; multiple customers with CNIC/phone.
- **Steps:**
  1. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/customers/`
  2. Optionally `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/customers/<pk>/` for ledger summary.
- **Expected result (VULNERABLE):** `200` + full roster incl. `cnic`, `phone`, `alternate_phone`, `address`, `notes`; detail adds `total_paid`/`current_balance`/`ledger_summary`. **Intended:** `403` for non-staff.
- **Evidence on failure:** other customers' `cnic`/`phone` visible to a customer.

---

#### API-SEC-05 — customer reads `/api/bookings/` (all bookings/amounts)

- **Preconditions:** `qa_cust` logged in; other customers' bookings exist.
- **Steps:**
  1. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/bookings/`
- **Expected result (VULNERABLE):** `200` + all bookings (amounts, statuses, plot refs) regardless of owner. **Intended:** `403` or row-level filter to own bookings.
- **Evidence on failure:** another customer's booking `id`/amounts present.

---

#### API-SEC-06 — customer reads `/api/payments/` (all payments)

- **Preconditions:** `qa_cust` logged in; other customers' payments exist.
- **Steps:**
  1. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/payments/`
- **Expected result (VULNERABLE):** `200` + full payments table (amount, method, status). **Intended:** `403`/filtered.
- **Evidence on failure:** other customers' payment rows returned.

---

#### API-SEC-07 — customer reads `/api/employees/` (HR PII)

- **Preconditions:** `qa_cust` logged in; employees with CNIC/phone/salary components.
- **Steps:**
  1. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/employees/`
- **Expected result (VULNERABLE):** `200` + employee CNIC/phone/salary component data. **Intended:** `403`.
- **Evidence on failure:** employee PII in the response body.

---

#### API-SEC-08 — customer reads `/api/audit-logs/` (IP addresses)

- **Preconditions:** `qa_cust` logged in; audit rows exist with `ip_address`.
- **Steps:**
  1. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/audit-logs/`
- **Expected result (VULNERABLE):** `200` + up to 100 rows including `ip_address`, `user_username`, `action`, `description`. **Intended:** `403` (audit is management-only per `can_audit`).
- **Evidence on failure:** `ip_address`/actor data visible to a customer.

---

#### API-SEC-09 — login CSRF (unauthenticated POST to `api_login` unprotected)

- **Preconditions:** none.
- **Steps:**
  1. `curl -si -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' http://127.0.0.1:8000/api/auth/login/` (no CSRF token, no cookie).
- **Expected result (VULNERABLE, low–medium):** `200` + `_user_payload` and a `sessionid` — login proceeds with no CSRF token. DRF `APIView` is `csrf_exempt`, and `SessionAuthentication.enforce_csrf` only guards *authenticated* unsafe requests, so the unauthenticated login is open to login-CSRF/forced-login. (`auth_login` rotates the session key, mitigating fixation.)
- **Evidence on failure:** `200` without any `X-CSRFToken` header (confirming the gap); note in report that this is expected-by-design but should be risk-accepted or fixed.

---

#### API-SEC-10 — user enumeration (403 deactivated vs 400 invalid)

- **Preconditions:** one active user, one deactivated (`is_active=False`) user with known usernames.
- **Steps:**
  1. `curl -si -H "Content-Type: application/json" -d '{"username":"deactivated_user","password":"wrong"}' http://127.0.0.1:8000/api/auth/login/`
  2. `curl -si -H "Content-Type: application/json" -d '{"username":"no_such_user","password":"wrong"}' http://127.0.0.1:8000/api/auth/login/`
- **Expected result (VULNERABLE):** step 1 → `403` `{"detail":"Your account has been deactivated…"}`; step 2 → `400` `{"detail":"Invalid username or password."}`. The distinct status codes reveal which usernames exist. **Intended:** identical `400` for both.
- **Evidence on failure:** the 403-vs-400 divergence itself (confirmed at `api/views.py:88-97`).

---

#### API-SEC-11 — brute-force throttle weakness (5/15 min, IP-rotatable)

- **Preconditions:** a target username.
- **Steps:**
  1. Loop 5×: `curl -s -o /dev/null -w "%{http_code}\n" -H "Content-Type: application/json" -d '{"username":"admin","password":"wrong"}' http://127.0.0.1:8000/api/auth/login/`
  2. 6th attempt with correct password from the same IP.
- **Expected result (VULNERABLE):** attempts 1–5 → `400`; attempt 6 → `429` `{"detail":"Too many failed attempts. Try again after 15 minutes."}` even with the correct password. The IP threshold is `15` (3× username), keyed on `REMOTE_ADDR`, so rotating source IPs or a small botnet evades it; no CAPTCHA; success does not reset the failed counter. Document as a weakness (and note the DoS side: a shared IP behind 15 failures locks out the legitimate username).
- **Evidence on failure:** 6th attempt returns `200` (lockout not enforced) or lockout never triggers.

---

#### API-SEC-12 — customer reads `/api/company-settings/summary/` (revenue/profit)

- **Preconditions:** `qa_cust` logged in; bookings/expenses present.
- **Steps:**
  1. `curl -s -b cj_cust.txt http://127.0.0.1:8000/api/company-settings/summary/`
- **Expected result (VULNERABLE):** `200` with `revenue`, `expenses`, `net_profit`, `total_customers`, etc. (READ branch of `IsAdminOrReadOnly`). **Intended:** `403` for a customer.
- **Evidence on failure:** financial aggregates in the body for a customer session.

---

#### API-SEC-13 — receipts write-open (`IsAuthenticated`) — customer can POST

- **Preconditions:** `qa_cust` logged in; a `Booking` owned by `qa_cust`.
- **Steps:**
  1. `curl -si -b cj_cust.txt -H "Content-Type: application/json" -H "X-CSRFToken: $CSRF" -X POST -d '{"booking":<booking_pk>,"amount":"1000.00","payment_method":"cash","status":"pending"}' http://127.0.0.1:8000/api/receipts/`
- **Expected result (VULNERABLE):** `201` — `ReceiptViewSet` uses `permissions.IsAuthenticated` (`payments/api_views.py:266`), so **any** authenticated user can create receipts, unlike every other payments ViewSet (`IsStaffReadAdminWrite`). **Intended:** `403` for a customer.
- **Evidence on failure:** a receipt row created by a customer; `201` response body.

---

#### API-SEC-14 — IDOR: write-role user acts on another's object (no ownership check)

- **Preconditions:** `qa_sales` (write on bookings) logged in; a booking owned by `qa_cust` in `pending` status.
- **Steps:**
  1. `curl -si -b cj_sales.txt -H "Content-Type: application/json" -H "X-CSRFToken: $CSRF" -X POST http://127.0.0.1:8000/api/bookings/<cust_booking_pk>/confirm/`
- **Expected result (VULNERABLE):** `200`/`201` — `get_object()` fetches by `pk` with no owner filter; any user with WRITE (sales included) can transition any booking. **Intended:** `403` (or ownership check).
- **Evidence on failure:** the target booking's `status` changed to `confirmed` in DB despite belonging to another customer.

---

### Category API — API contract / permission matrix

The following matrix is the **source of truth** for the contract scenarios. "any auth" means any authenticated principal (staff or customer). Anonymous is `401`/`403` everywhere except `plots/list`.

| Endpoint | Permission class | GET (SAFE) | POST / PATCH / PUT | DELETE |
|---|---|---|---|---|
| `/api/users/` | `IsAdminOrReadOnly` | any auth | super_admin / admin | super_admin / admin |
| `/api/audit-logs/` | `IsAdminOrReadOnly` | any auth (read-only) | — (no route) | — |
| `/api/profile/` | `IsAuthenticated` | any auth (list) | **any auth** (`update_profile`; `role` writable) | — |
| `/api/leads/`, `lead-notes/`, `agents/` | `IsAdminOrReadOnly` | any auth | super_admin / admin | super_admin / admin |
| `/api/customers/`, `customer-ledger/` | `IsAdminOrSuperAdmin` | any auth | super_admin / admin | super_admin / admin |
| `/api/customer-profiles/` | `IsAdminOrSuperAdmin` | — | super_admin / admin (POST) | — |
| `/api/projects/`, `phases`, `plots`, `features`, `milestones` | `ReadOnlyForLowerRoles` | any auth | super_admin / admin / management | super_admin / admin / management |
| `/api/price-history/` | `IsAuthenticated` | any auth (read-only) | — | — |
| `/api/plots/list/` | `AllowAny` | anonymous | — | — |
| `/api/bookings/`, `installments`, `reservations`, etc. | `IsStaffOrAbove` (bookings) | any auth | super_admin / admin / management / **sales** | super_admin / admin / management |
| `/api/payments/`, `refunds/`, `payment-allocations/` | `IsStaffReadAdminWrite` | any auth | super_admin / admin / management / accounts | super_admin / admin / management |
| `/api/receipts/` | `IsAuthenticated` | any auth | **any auth** | **any auth** |
| `/api/account-transactions/`, `offices/`, `expenses/`, budgets/costs/investments | `IsFinanceOrAbove` | any auth | super_admin / admin / management / accounts | super_admin / admin / management / accounts |
| `/api/departments/` … `/api/leaves/` | `IsHRManagement` | any auth | super_admin / admin / management / hr | super_admin / admin / management / hr |
| `/api/company-settings/` | `IsAdminOrReadOnly` | any auth | super_admin / admin | — (405) |

---

#### API-API-01 — users: SAFE open, write admin-only

- **Preconditions:** sessions for `qa_cust`, `qa_sales`, `qa_admin`.
- **Steps:** for each actor run `GET`, `POST` (create user), `PATCH /api/users/{pk}/`, `DELETE /api/users/{pk}/` (with CSRF on writes).
- **Expected result:** GET → `200` for all three; POST/PATCH/DELETE → `200/201/204` for `qa_admin`, `403` for `qa_sales` and `qa_cust`.
- **Evidence on failure:** a write succeeding for a non-admin (would indicate `IsAdminOrReadOnly` regressed).

---

#### API-API-02 — customers: SAFE open, write admin-only

- **Preconditions:** `qa_cust`, `qa_sales`, `qa_admin`.
- **Steps:** `GET /api/customers/`, `POST /api/customers/`, `PATCH /api/customers/{pk}/`, `DELETE /api/customers/{pk}/`.
- **Expected result:** GET `200` all; writes `403` for `qa_cust`/`qa_sales`, allowed for `qa_admin`.
- **Evidence on failure:** customer or sales creating/editing a customer.

---

#### API-API-03 — bookings: sales can write, customer cannot; DELETE management+

- **Preconditions:** `qa_cust`, `qa_sales`, `qa_mgmt`, `qa_admin`.
- **Steps:** `GET` all; `POST /api/bookings/` and `PATCH /api/bookings/{pk}/` for each; `DELETE /api/bookings/{pk}/` for each.
- **Expected result:** GET `200` all; POST/PATCH `200/201` for `qa_admin`/`qa_mgmt`/`qa_sales`, `403` for `qa_cust`; DELETE `204` for `qa_admin`/`qa_mgmt`, `403` for `qa_sales` and `qa_cust` (object-level branch, `bookings/api_views.py:40-48`).
- **Evidence on failure:** customer writing a booking, or sales deleting one.

---

#### API-API-04 — payments: accounts write, sales/customer denied; DELETE management+

- **Preconditions:** `qa_cust`, `qa_sales`, `qa_acct`, `qa_mgmt`.
- **Steps:** `GET`; `POST /api/payments/`; `PATCH /api/payments/{pk}/`; `DELETE /api/payments/{pk}/`.
- **Expected result:** GET `200` all; writes `200/201` for `qa_acct`/`qa_mgmt`, `403` for `qa_sales`/`qa_cust`; DELETE `204` for `qa_mgmt`, `403` for `qa_acct` (no delete), `qa_sales`, `qa_cust`.
- **Evidence on failure:** sales writing a payment, or accounts deleting one.

---

#### API-API-05 — employees/leaves (HR): hr writes, others denied

- **Preconditions:** `qa_cust`, `qa_sales`, `qa_acct`, `qa_hr`.
- **Steps:** `GET /api/employees/`; `POST /api/employees/`; `PATCH /api/employees/{pk}/`; `GET /api/leaves/`; `POST /api/leaves/`.
- **Expected result:** GET `200` all; writes `201/200` for `qa_hr`, `403` for `qa_acct`/`qa_sales`/`qa_cust`.
- **Evidence on failure:** a non-HR role creating an employee or leave.

---

#### API-API-06 — refunds: accounts write, customer denied

- **Preconditions:** `qa_cust`, `qa_sales`, `qa_acct`.
- **Steps:** `GET /api/refunds/`; `POST /api/refunds/`; `POST /api/refunds/{pk}/process/`.
- **Expected result:** GET `200` all; writes `200/201` for `qa_acct`, `403` for `qa_sales`/`qa_cust`.
- **Evidence on failure:** customer/sales creating or processing a refund.

---

#### API-API-07 — offices (finance): accounts write, customer denied

- **Preconditions:** `qa_cust`, `qa_sales`, `qa_acct`.
- **Steps:** `GET /api/offices/`; `POST /api/offices/`; `PATCH /api/offices/{pk}/`; `DELETE /api/offices/{pk}/`.
- **Expected result:** GET `200` all; writes `200/201` for `qa_acct`, `403` for `qa_sales`/`qa_cust`; DELETE `204` for `qa_acct` (no object-level delete guard here).
- **Evidence on failure:** a non-finance role mutating an office.

---

#### API-API-08 — receipts anomaly: any authenticated user can write

- **Preconditions:** `qa_cust`, `qa_sales`.
- **Steps:** `POST /api/receipts/` for both.
- **Expected result (VULNERABLE):** `201` for **both** `qa_cust` and `qa_sales` (permission is `IsAuthenticated`, not `IsStaffReadAdminWrite`). **Intended:** `403` for both.
- **Evidence on failure:** `201` from a customer receipt creation (see also API-SEC-13).

---

#### API-API-09 — audit-logs: any authenticated user reads (intended management-only)

- **Preconditions:** `qa_cust`, `qa_sales`, `qa_mgmt`.
- **Steps:** `GET /api/audit-logs/` for each.
- **Expected result (VULNERABLE):** `200` for all three. **Intended:** `403` for customer and sales (audit gated by `can_audit` = management+ in the template layer).
- **Evidence on failure:** audit rows (incl. `ip_address`) returned to a customer.

---

#### API-API-10 — profile: PATCH role writable (assert actual vs intended read-only)

- **Preconditions:** `qa_sales` logged in.
- **Steps:** `PATCH /api/profile/update_profile/` with `{"role":"admin"}` and with `{"is_active":false}`.
- **Expected result (VULNERABLE):** `200`; `role` changes to `admin`; `is_active` flips (self-lockout possible). **Intended:** `403` or `role`/`is_active` read-only. Cross-references API-SEC-01/02; kept here as the explicit contract assertion.
- **Evidence on failure:** role/is_active reflected in the `200` response body.

---

## 4. Data isolation rules

- **Unique per run:** all seeded usernames/emails/CNICs/phones use a `qa_` prefix +
  a timestamp suffix (e.g. `qa_cust_20260913`); CNICs must be ≥ 13 digits and pass
  `format_cnic` normalization (`35202-1234567-1` form).
- **Cleanup:** after the run, delete created `User`, `UserProfile`, `Customer`,
  `Booking`, `Payment`, `Receipt`, `AuditLog`, and `LoginAttempt` rows by the
  `qa_` prefix. Reset any escalated roles (`role` back to `sales`) on `qa_sales`.
- **Don't depend on ordering:** auto-generated IDs (`CUS-…`, `BKG-…`, `PAY-…`,
  `RCP-…`) parse the last numeric suffix, so parallel runs must timestamp seeds to
  avoid collisions.
- **Money:** assert Decimal amounts EXACTLY on non-portal endpoints; for
  `portal_dashboard` the API coerces to `float`, so compare `float(expected)`.
- **CSRF jar:** use a separate cookie jar per actor (`cj_cust.txt`, `cj_sales.txt`,
  …) so sessions never bleed across scenarios.

## 5. Coverage checklist

- API-HP-01 — CSRF → login → session handshake
- API-HP-02 — current_user/me returns role
- API-HP-03 — portal_dashboard scoped to request.user
- API-HP-04 — api_logout ends the session
- API-HP-05 — public plots/list (anonymous)
- API-EC-01 — summary.next_due is a full installment dict not a date
- API-EC-02 — sum(total_amount) crashes on null total_amount
- API-EC-03 — no pagination (full tables returned)
- API-EC-04 — float() coercion of Decimal money in portal
- API-EC-05 — portal_dashboard for account with no linked Customer → 403
- API-EC-06 — malformed JSON / wrong method
- API-SEC-01 — CRITICAL: update_profile privilege escalation by a customer
- API-SEC-02 — CRITICAL: escalation by a low-privilege staff user
- API-SEC-03 — CRITICAL: customer reads /api/users/ (staff PII)
- API-SEC-04 — CRITICAL: customer reads /api/customers/ (CNIC/phone/address)
- API-SEC-05 — customer reads /api/bookings/ (all bookings/amounts)
- API-SEC-06 — customer reads /api/payments/ (all payments)
- API-SEC-07 — customer reads /api/employees/ (HR PII)
- API-SEC-08 — customer reads /api/audit-logs/ (IP addresses)
- API-SEC-09 — login CSRF (unauthenticated POST unprotected)
- API-SEC-10 — user enumeration (403 deactivated vs 400 invalid)
- API-SEC-11 — brute-force throttle weakness (5/15 min, IP-rotatable)
- API-SEC-12 — customer reads /api/company-settings/summary/ (revenue/profit)
- API-SEC-13 — receipts write-open (IsAuthenticated) — customer can POST
- API-SEC-14 — IDOR: write-role user acts on another's object
- API-API-01 — users: SAFE open, write admin-only
- API-API-02 — customers: SAFE open, write admin-only
- API-API-03 — bookings: sales write, customer denied; DELETE management+
- API-API-04 — payments: accounts write, sales/customer denied; DELETE management+
- API-API-05 — employees/leaves (HR): hr writes, others denied
- API-API-06 — refunds: accounts write, customer denied
- API-API-07 — offices (finance): accounts write, customer denied
- API-API-08 — receipts anomaly: any authenticated user can write
- API-API-09 — audit-logs: any authenticated user reads (intended management-only)
- API-API-10 — profile: PATCH role writable (actual vs intended read-only)
