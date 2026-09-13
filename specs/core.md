# core — Test Plan

> Source of truth: `docs/qa/core_analysis.md` (all findings with file:line). Shared context: `docs/qa/_shared-context.md`.
> Scenario IDs are the contract — Phase C test names must match them exactly.

## 1. Scope & roles

This plan covers the `core` module: authentication (login/logout/password-reset), the staff dashboard and revenue aggregation, user management (create/edit/role/toggle-active), audit logs, DB backup (create + download + restore), the self-service profile page, the DRF `core` ViewSets (`/api/users/`, `/api/audit-logs/`, `/api/profile/`, `/api/leads/`, `/api/agents/`), and the auth endpoints (`/api/auth/*`). It also exercises the `core/` authorization model end-to-end, because `core` is where every role check and every `@login_required`-only endpoint lives — a wrong check here exposes money-mutating and PII endpoints.

Roles exercised:

- **Anonymous** — login, password reset (request/verify), corporate lead form.
- **`super_admin`** (or Django `is_superuser`) — full access; backup; user management.
- **`admin`** — user management, backup, company settings.
- **`management`** — users list (read), audit logs, booking confirm/cancel/transfer.
- **`accounts`** — payments, revenue trend/reports.
- **`sales`** — customer/booking/property create; dashboard (revenue/payment charts hidden by `can_view_payments`).
- **Customer-portal user** (`is_staff=False`, **no** `UserProfile`, linked to a `Customer`) — the essential negative actor for the IDOR / privilege-escalation scenarios; should only reach `/portal/` and its own records.

Expected-denied roles: `sales` and the customer-portal user must be **denied** every `management_or_above` / `admin_or_above` / `payments_access` / `finance_or_above` page, and must **never** be able to read/edit another tenant's PII or money.

## 2. Preconditions & fixtures

Run the app with `DJANGO_DEBUG=True` (otherwise `SECURE_SSL_REDIRECT` 301s every request) using the shared venv with `env -u PYTHONPATH`. Base URL `http://127.0.0.1:8000`.

Seed roles — one user per role (all `is_staff=True` with a matching `UserProfile`):

| username | password | role |
|---|---|---|
| `superadmin1` | `Super12345` | `super_admin` (or Django `is_superuser`) |
| `admin1` | `Admin12345` | `admin` |
| `mgr1` | `Mgmt12345` | `management` |
| `acct1` | `Acct12345` | `accounts` |
| `sales1` | `Sales12345` | `sales` |

Plus a **customer-portal user** (`portal_cust`, `Portal12345`, `is_staff=False`, **no** `UserProfile`) linked to a `Customer` via `Customer.user` (create through `customer_profile_create_view` / `CustomerProfileForm.save` — it deliberately creates a non-staff, profile-less `User`). This account lands on `/portal/` after login.

Seed domain data (use `populate_dummy_data.py` then mutate): one active `Project` → `ProjectPhase` → `Plot` with `price`, `development_charge`, `lease_charge`, `other_charges`, `holding_deposit` set; one `Customer` with `cnic`/`phone`/`email`/`address`; one `Booking` with `advance_paid` and `total_amount`; one `Payment` in `verified` and one in `pending`; one `Receipt`; one `Lead`. Note the pk values for IDOR scenarios (e.g. target `Customer` pk, target `Booking` pk, target `Plot` pk).

URLs exercised (relative to base):

- `/login/`, `/logout/`, `/password-reset/`, `/password-reset/verify/`
- `/dashboard/`, `/dashboard/revenue-trend/`, `/reports/financial/`
- `/profile/`, `/api/save-theme/`
- `/users/`, `/users/create/`, `/users/<pk>/edit/`, `/users/<pk>/role/`, `/users/<pk>/toggle-active/`
- `/audit-logs/`
- `/backup/`, `/backup/download/`, `/backup/restore/upload/`
- `/customers/<pk>/`, `/customers/<pk>/pdf/`, `/bookings/<pk>/edit/`, `/bookings/<pk>/transfer/`, `/properties/plot/<pk>/edit/`
- `/leads/<pk>/status/`
- `/api/auth/csrf/`, `/api/auth/login/`, `/api/auth/logout/`, `/api/auth/me/`
- `/api/profile/`, `/api/profile/update_profile/`
- `/api/users/`, `/api/audit-logs/`, `/api/leads/`, `/api/agents/`

CSRF: all browser POSTs must include the CSRF token from the rendered form. For raw API calls, either send `X-CSRFToken` (from the `csrftoken` cookie set by `/api/auth/csrf/`) with session auth, or use the Django test client (`enforce_csrf_checks=False`) / a `SessionAuthentication` client that supplies the header.

## 3. Scenario catalog

### Happy path

#### CORE-HP-01 — Staff login lands on dashboard
- **Preconditions:** `admin`/`admin123` exists (project default) or `admin1` seeded. No active session.
- **Steps:**
  1. Navigate to `/login/`.
  2. Enter username `admin`, password `admin123`.
  3. Submit the form.
- **Expected result:** HTTP 302 to `/dashboard/`; following it returns 200 and renders the dashboard (stats cards, quick actions). A `LoginAttempt(is_success=True)` and an `AuditLog(action='login', model_name='User')` row are created with the caller's IP. Session cookie is set.
- **Evidence on failure:** screenshot of `/login/` with error toast; the `LoginAttempt` / `AuditLog` rows (or their absence); final URL ≠ `/dashboard/`.

#### CORE-HP-02 — Logout clears session and audits
- **Preconditions:** logged in as `admin`.
- **Steps:**
  1. From any page, follow the logout link (GET `/logout/`).
- **Expected result:** HTTP 302 to `/login/`; session is cleared (subsequent GET `/dashboard/` redirects to `/login/`). An `AuditLog(action='logout', model_name='User')` row is created with IP.
- **Evidence on failure:** still authenticated (accessing `/dashboard/` returns 200 after logout); missing logout `AuditLog` row.

#### CORE-HP-03 — Password reset full flow (request → verify → login)
- **Preconditions:** a staff user with a known email; email backend in console mode (capture the code from the console/`NotificationLog`).
- **Steps:**
  1. GET `/password-reset/`, submit the user's email.
  2. Retrieve the 6-digit code (console email or `PasswordResetCode.objects.latest()`).
  3. GET `/password-reset/verify/`, enter the code, new password `NewPass123`, and matching confirm.
  4. Log out, then log in with the new password.
- **Expected result:** Step 1 shows the generic "If an account exists…" message and redirects to `/password-reset/verify/`; step 3 marks the code `used` (with `used_at`), resets the password, writes an `AuditLog(action='update', description='Password reset …')`, clears the reset session keys, and redirects to `/login/`; step 4 login succeeds with the new password and the old password no longer works.
- **Evidence on failure:** the reset page's error toast; `PasswordResetCode` row state; the audit row; login failure after reset.

#### CORE-HP-04 — Dashboard revenue equals Σ advance_paid
- **Preconditions:** logged in as `admin`; at least two bookings with known `advance_paid` (e.g. 1,000,000.00 and 500,000.00).
- **Steps:**
  1. GET `/dashboard/`.
  2. Read the headline "Revenue" figure.
- **Expected result:** headline revenue = `Decimal('1500000.00')` — exactly `Sum(Booking.advance_paid)`, not the sum of `Payment.amount`.
- **Evidence on failure:** screenshot of the revenue stat; a DB query `SELECT SUM(advance_paid) FROM bookings_booking;` vs the displayed value; confirm the value does **not** equal `SUM(Payment.amount)`.

#### CORE-HP-05 — Create user (admin)
- **Preconditions:** logged in as `admin1`.
- **Steps:**
  1. GET `/users/create/`, fill username `new_sales`, email, password `Pass12345`, confirm, first/last name, role `sales`.
  2. Submit.
- **Expected result:** redirect to `/users/` with success message; a `User` + `UserProfile(role='sales')` row are created; `AuditLog(action='create', model_name='User', object_id='new_sales')` written. New user can log in.
- **Evidence on failure:** validation error on the form (e.g. username/email/role rejected); missing `UserProfile`; missing audit row.

#### CORE-HP-06 — Edit user (admin)
- **Preconditions:** logged in as `admin1`; target non-super_admin user `sales1` exists.
- **Steps:**
  1. GET `/users/<sales1 pk>/edit/`, change first name and email, optionally set a new password ≥ 8 chars + confirm.
  2. Submit.
- **Expected result:** redirect to `/users/`; `User` fields updated; `AuditLog(action='update')` written; if password changed, the old password no longer works and the new one does.
- **Evidence on failure:** form errors; unchanged DB row; missing audit.

#### CORE-HP-07 — Role update via inline dropdown (admin)
- **Preconditions:** logged in as `admin1`; target `sales1`.
- **Steps:**
  1. On `/users/`, change `sales1`'s role dropdown to `management` and POST to `/users/<pk>/role/`.
- **Expected result:** `sales1`'s `UserProfile.role` becomes `management`; `AuditLog(action='update', description='Changed role …')` written; `sales1` now reaches `/audit-logs/`.
- **Evidence on failure:** role unchanged; error message; missing audit.

#### CORE-HP-08 — Toggle active / deactivate (admin)
- **Preconditions:** logged in as `admin1`; target `sales1` (active).
- **Steps:**
  1. GET `/users/<sales1 pk>/toggle-active/` (confirmation page), confirm POST.
- **Expected result:** `sales1.is_active=False`; `AuditLog(action='update', description='Deactivated …')`; `sales1` can no longer log in (login returns "deactivated" message). A second toggle re-activates.
- **Evidence on failure:** `is_active` unchanged; login still succeeds; missing audit.

#### CORE-HP-09 — Audit logs list (management)
- **Preconditions:** logged in as `mgr1`; at least one prior action (e.g. the login itself) exists.
- **Steps:**
  1. GET `/audit-logs/`.
- **Expected result:** 200; table shows the most recent audit entries (user, action, model, object id, description, IP, timestamp), newest first.
- **Evidence on failure:** 302 redirect to `/dashboard/` (access denied); empty list when rows exist.

#### CORE-HP-10 — Backup create + download (admin)
- **Preconditions:** logged in as `admin1`.
- **Steps:**
  1. GET `/backup/` — confirm it lists last backups + restore form.
  2. GET `/backup/download/`.
- **Expected result:** Step 1 returns 200. Step 2 returns 200 with `Content-Type: application/zip` and a `samana_backup_YYYYMMDD_HHMMSS.zip` attachment; the file is written under `backups/` and is a valid ZIP containing CSV table dumps and the `media/` manifest. `AuditLog(action='create'/'download')` written.
- **Evidence on failure:** 302 denial; non-ZIP or corrupt body; no file on disk; missing audit.

### Edge cases / boundary

#### CORE-EC-01 — Password reset code expiry
- **Preconditions:** a reset code requested; its `expires_at` is now in the past (advance the clock with freezegun or wait, or manually backdate the row).
- **Steps:**
  1. On `/password-reset/verify/` submit the (now-expired) correct code + valid new password.
- **Expected result:** "Invalid or expired verification code." error; password **unchanged**; code not marked used; redirect stays on verify page.
- **Evidence on failure:** password changed; code marked used; login works with new password.

#### CORE-EC-02 — Password reset code reuse
- **Preconditions:** a code already consumed (`used=True`).
- **Steps:**
  1. Submit the same code again on `/password-reset/verify/`.
- **Expected result:** rejected with "Invalid or expired verification code."; password unchanged.
- **Evidence on failure:** password reset again with the old code.

#### CORE-EC-03 — Wrong password reset code
- **Preconditions:** a valid, unused code `123456` exists.
- **Steps:**
  1. Submit `999999` (or any non-matching 6-digit) with a valid new password.
- **Expected result:** "Invalid or expired verification code."; password unchanged; `used` stays False.
- **Evidence on failure:** password changed.

#### CORE-EC-04 — Password minimum length boundary (6 chars)
- **Preconditions:** a valid, unused reset code; target user.
- **Steps:**
  1. Submit new password `abcde` (5 chars) + confirm → expect rejection.
  2. Submit new password `abcdef` (6 chars) + confirm → expect success.
- **Expected result:** Step 1 rejected with "Password must be at least 6 characters."; step 2 accepted (current code floor is 6 — this documents the weak minimum). See SEC note in §4: a hardened build should reject `abcdef` too.
- **Evidence on failure:** 5-char password accepted, or 6-char rejected contrary to code.

#### CORE-EC-05 — Revenue chart vs advance_paid divergence
- **Preconditions:** logged in as `acct1`; seed bookings so `Sum(advance_paid)` ≠ `Sum(verified Payment.amount)` (e.g. a booking with `advance_paid` but no verified `Payment`, or vice-versa).
- **Steps:**
  1. GET `/dashboard/` and record headline revenue.
  2. GET `/dashboard/revenue-trend/` (JSON) and `/reports/financial/`.
- **Expected result (documented divergence):** headline = Σ advance_paid; the trend endpoint and financial report sum **verified `Payment.amount`** and therefore differ when the two totals differ. This is the known inconsistency (`revenue_trend_view` views.py:469, `financial_reports_view` views.py:556) — assert the **actual** numbers to pin the divergence; the fix should reconcile them to Σ advance_paid.
- **Evidence on failure:** capture the three numbers and the underlying `SUM`s to show the discrepancy.

#### CORE-EC-06 — booking_transfer_view 500 on empty transfer_fee
- **Preconditions:** logged in as `mgr1`; a `Booking` and a second `Customer` exist.
- **Steps:**
  1. POST `/bookings/<pk>/transfer/` with `to_customer=<other customer pk>`, `transfer_fee=` (empty string), `payment_handling=transfer`.
- **Expected result:** a graceful validation error (or the field treated as 0) and the transfer does **not** crash — no HTTP 500. (Currently `Decimal('')` raises `decimal.InvalidOperation` → 500.)
- **Evidence on failure:** HTTP 500 traceback (`decimal.InvalidOperation` at views.py:1409); screenshot of the error page.

#### CORE-EC-07 — booking_transfer_view 500 on non-numeric transfer_fee
- **Preconditions:** same as CORE-EC-06.
- **Steps:**
  1. POST `/bookings/<pk>/transfer/` with `transfer_fee=abc`.
- **Expected result:** validation error, no 500, no `BookingTransfer` row, booking unchanged.
- **Evidence on failure:** HTTP 500; partial `BookingTransfer` created; booking customer mutated.

#### CORE-EC-08 — Audit-log filter controls are non-functional
- **Preconditions:** logged in as `mgr1`; multiple audit rows with varied `action`/`model_name`.
- **Steps:**
  1. GET `/audit-logs/?action=login&model=User` (or use the search/filter UI controls).
- **Expected result (documented bug):** the view (`audit_logs_view` views.py:1996-1998) ignores the GET params and returns the unfiltered latest 100 — the filter UI is decorative. Assert the **actual** response shows the bug (all rows returned, no filtering); the fix should apply the filters.
- **Evidence on failure:** capture response showing all rows returned despite filters; note the filter controls exist but have no effect.

### Security / negative

#### CORE-SEC-01 — Privilege escalation via profile_view (staff with existing profile) — CRITICAL
- **Preconditions:** logged in as `sales1` (`UserProfile.role='sales'` exists).
- **Steps:**
  1. GET `/profile/` — confirm the page renders name/email/theme but does **not** expose `role`/`is_active` fields.
  2. POST `/profile/` with CSRF token and body including `first_name=Sales`, `last_name=One`, `email=sales1@example.com`, `role=super_admin`, `theme=professional-blue`, `is_active=on`. (Craft via DevTools/burp/curl — the HTML form does not contain these fields, but `UserProfileForm.Meta.fields=['role','theme','is_active']` accepts them.)
  3. GET `/api/auth/me/` and read `role`.
  4. GET `/backup/` (an `admin_or_above` page).
- **Expected result:** `/profile/` ignores `role` and `is_active`; the user's role stays `sales`; `/api/auth/me/` returns `"role":"sales"`; `/backup/` returns 302 to `/dashboard/` (denied).
- **Evidence on failure:** `/api/auth/me/` shows `"role":"super_admin"`; `/backup/` returns 200; DB `UserProfile.role='super_admin'`; full vertical escalation. Capture the exact POST body and response.

#### CORE-SEC-02 — Portal customer self-creates super_admin profile — CRITICAL
- **Preconditions:** logged in as `portal_cust` (`is_staff=False`, **no** `UserProfile`, linked to a `Customer`).
- **Steps:**
  1. Log in; confirm landing on `/portal/`.
  2. GET `/profile/` — renders with an empty `UserProfileForm` (no profile instance).
  3. POST `/profile/` with `role=super_admin`, `is_active=on` plus the `UserForm` fields. Because no profile exists, `profile_form.save(commit=False)` + `profile.user = user` **creates** a `UserProfile` with the chosen role.
  4. GET `/api/auth/me/` and read `role`.
  5. GET `/users/` (a `management_or_above` page).
- **Expected result:** a portal customer cannot create/upgrade a profile with any privileged role; `/api/auth/me/` returns `"role":"customer"` (or `null`); `/users/` returns 302 denial.
- **Evidence on failure:** a `UserProfile(role='super_admin')` row now exists for `portal_cust`; `/api/auth/me/` shows `"role":"super_admin"`; `/users/` returns 200. Capture the profile row (`SELECT role FROM core_userprofile WHERE user_id=<pk>`).

#### CORE-SEC-03 — IDOR: customer_detail_view readable by any authenticated user — HIGH
- **Preconditions:** logged in as `sales1` (then repeat as `portal_cust`); a target `Customer` (pk known) with CNIC/phone/email/address exists, **not** owned by the actor.
- **Steps:**
  1. GET `/customers/<target pk>/`.
- **Expected result:** 302 redirect to `/dashboard/` (staff) or `/portal/` (customer) with a denial message; no PII rendered.
- **Evidence on failure:** HTTP 200 page showing the target's CNIC, phone, email, address, nominee, bookings and ledger summary. Screenshot + the customer's `cnic` visible.

#### CORE-SEC-04 — IDOR: customer_profile_pdf_view downloads any customer PDF — HIGH
- **Preconditions:** logged in as `sales1` / `portal_cust`; target `Customer` pk known.
- **Steps:**
  1. GET `/customers/<target pk>/pdf/`.
- **Expected result:** 302 denial; no PDF bytes returned.
- **Evidence on failure:** HTTP 200 `application/pdf` containing the target's CNIC/phone/address/balances. Save the PDF.

#### CORE-SEC-05 — IDOR: booking_edit_view mutates any booking's money — HIGH
- **Preconditions:** logged in as `sales1` / `portal_cust`; a `Booking` (pk known) with `total_amount`/`advance_paid`.
- **Steps:**
  1. GET `/bookings/<pk>/edit/` — form renders with amount fields.
  2. POST a changed `advance_paid`/`total_amount` (respecting the `plot.total_cost`/`holding_deposit` floor so the form validates).
- **Expected result:** 302 denial; booking amounts unchanged; no `AuditLog`.
- **Evidence on failure:** booking `advance_paid`/`total_amount` changed in DB; `AuditLog(action='update', model_name='Booking')` with the actor's username. Capture before/after `SELECT` on the booking row.

#### CORE-SEC-06 — IDOR: plot_edit_view editable by any authenticated user — HIGH
- **Preconditions:** logged in as `sales1` / `portal_cust`; a `Plot` (pk known) with a `price`.
- **Steps:**
  1. GET `/properties/plot/<pk>/edit/` — form renders.
  2. POST a changed `price`.
- **Expected result:** 302 denial (consistent with `project_edit_view`/`plot_delete_view`); plot `price` unchanged.
- **Evidence on failure:** plot `price` changed; capture before/after price and note the changed pricing floor for future bookings.

#### CORE-SEC-07 — Open redirect in lead_status_update_view — HIGH
- **Preconditions:** logged in as a `can_view_leads` user (e.g. `mgr1`/`sales1`); a `Lead` (pk known).
- **Steps:**
  1. POST `/leads/<pk>/status/` with `status=contacted` and `next=//evil.com`.
  2. Inspect the `Location` header of the 302.
- **Expected result:** the redirect target is same-origin/allow-listed (e.g. `/leads/`), never an external or protocol-relative host.
- **Evidence on failure:** `Location: //evil.com` (or `http(s)://evil.com`). Capture the raw response headers.

#### CORE-SEC-08 — Backup zip-slip path traversal on restore — HIGH
- **Preconditions:** logged in as `admin1`; a crafted ZIP with an entry named `media/../../evil.txt` (or `../evil.txt`) plus enough valid CSV/manifest to reach the media-write path (`restore_from_backup` backup.py:333-344).
- **Steps:**
  1. POST `/backup/restore/upload/` with the malicious ZIP (CSRF token).
  2. Inspect the filesystem for files written outside `MEDIA_ROOT` (e.g. `BASE_DIR/evil.txt`).
- **Expected result:** restore rejects the archive with a validation error; **no** file is written outside `MEDIA_ROOT`.
- **Evidence on failure:** `evil.txt` present outside the media root; success message shown; screenshot + `find` output.

#### CORE-SEC-09 — API read-open: /api/users/ exposes all users' PII — HIGH
- **Preconditions:** authenticated session as `sales1` (then `portal_cust`).
- **Steps:**
  1. GET `/api/users/` with the session (add `X-CSRFToken` not needed for GET).
- **Expected result:** non-admin read is denied (403) or, at minimum, does not return other users' `profile.phone`/`profile.cnic`. (Currently `IsAdminOrReadOnly` grants read to any authenticated user.)
- **Evidence on failure:** HTTP 200 JSON listing other users with nested `profile.phone` and `profile.cnic`. Capture the JSON.

#### CORE-SEC-10 — API read-open: /api/audit-logs/ exposes IPs and actions — HIGH
- **Preconditions:** authenticated as `sales1` / `portal_cust`.
- **Steps:**
  1. GET `/api/audit-logs/`.
- **Expected result:** 403 for non-management; or no `ip_address`/`description` leakage.
- **Evidence on failure:** HTTP 200 JSON with `ip_address`, `user_username`, and `description` fields. Capture the JSON.

#### CORE-SEC-11 — API read-open: /api/leads/ exposes lead PII — HIGH
- **Preconditions:** authenticated as `sales1` / `portal_cust`; at least one `Lead`.
- **Steps:**
  1. GET `/api/leads/`.
- **Expected result:** 403 for roles without lead access; no cross-tenant lead name/email/phone/budget.
- **Evidence on failure:** HTTP 200 JSON listing leads with `name`, `email`, `phone`, `budget`. Capture the JSON.

#### CORE-SEC-12 — API read-open: /api/agents/ exposes CNIC/commission — HIGH
- **Preconditions:** authenticated as `sales1` / `portal_cust`; at least one `Agent`.
- **Steps:**
  1. GET `/api/agents/`.
- **Expected result:** 403 for unauthorized roles; no agent `cnic`/`email`/`phone`/commission data.
- **Evidence on failure:** HTTP 200 JSON with `cnic`, `email`, `phone`, `commission_rate`. Capture the JSON.

### API contract

#### CORE-API-01 — /api/auth/csrf/ sets CSRF cookie
- **Preconditions:** none.
- **Steps:** 1. GET `/api/auth/csrf/`.
- **Expected result:** HTTP 200; body `{"detail": "CSRF cookie set"}`; a `csrftoken` cookie is set in the response.
- **Evidence on failure:** response body/status; missing `Set-Cookie: csrftoken`.

#### CORE-API-02 — /api/auth/login/ returns role in payload
- **Preconditions:** `admin1` seeded.
- **Steps:**
  1. POST `/api/auth/login/` with `{"username":"admin1","password":"Admin12345"}` (no CSRF — `AllowAny`).
  2. Repeat with a bad password; then 5+ bad attempts to trigger lockout.
- **Expected result:** success → HTTP 200 with `_user_payload` containing `id`, `username`, `email`, `is_staff`, `is_superuser`, `is_customer`, and `role` = `admin`. Bad password → 400 `{"detail":"Invalid username or password."}`. Lockout → 429 `{"detail":"Too many failed attempts…"}`. `LoginAttempt` + `AuditLog(login)` written.
- **Evidence on failure:** payload missing `role`; wrong status codes; capture response bodies.

#### CORE-API-03 — /api/auth/logout/ ends the session
- **Preconditions:** an authenticated session (via `/api/auth/login/` or browser login).
- **Steps:** 1. POST `/api/auth/logout/` (authenticated).
- **Expected result:** HTTP 200 `{"detail":"Logged out."}`; `AuditLog(action='logout')` written; subsequent GET `/api/auth/me/` returns 401/403.
- **Evidence on failure:** `/api/auth/me/` still 200 after logout; missing logout audit.

#### CORE-API-04 — /api/auth/me/ returns role in payload
- **Preconditions:** authenticated as `sales1`; then as `portal_cust`.
- **Steps:** 1. GET `/api/auth/me/`.
- **Expected result:** `sales1` → `"role":"sales"`, `"is_customer":false`; `portal_cust` (no profile) → `"role":"customer"` (or `null`), `"is_customer":true`. HTTP 200.
- **Evidence on failure:** wrong/absent `role`; capture the payload.

#### CORE-API-05 — /api/profile/update_profile/ must not write role — CRITICAL
- **Preconditions:** authenticated as `sales1` (profile `role='sales'` exists).
- **Steps:**
  1. PATCH `/api/profile/update_profile/` with body `{"role":"super_admin"}` (session auth + `X-CSRFToken`).
  2. GET `/api/profile/` (or `/api/auth/me/`) to read back.
- **Expected result:** role change is rejected (400/403) or ignored; role stays `sales`; `UserProfileSerializer.fields` should not include writable `role`/`is_active`. (Currently `update_profile` PATCHes the full `UserProfileSerializer`, which exposes `role`, `phone`, `cnic`, `is_active` — mirroring the HTML `profile_view` escalation.)
- **Evidence on failure:** response echoes `"role":"super_admin"` and the DB `UserProfile.role='super_admin'`. Capture request/response bodies.

## 4. Data isolation rules

- **Unique/timestamped values:** every created record uses a timestamped, unique suffix so parallel runs never collide (e.g. username `sales_20260913T1015`, customer email `cust+<ts>@example.com`, booking/lead names with `<ts>`). Assert on prefix/format, never on exact auto-ID (`CUS-…`, `BKG-…`, `PAY-…`, `AGT-…`) unless running on a clean DB.
- **Do not** create a second `CompanySettings` (forced pk=1 singleton).
- **Receipt numbers** are fiscal-year based (July–June); any assertion spanning June 30/July 1 must pin the clock (freezegun) or it will flake.
- **Cleanup:** after each SEC scenario, revert the escalated role / delete the created profile row and the malicious ZIP / outside-root file so later scenarios are unaffected. Run the privilege-escalation and IDOR scenarios against a freshly seeded role set.
- **Money:** assert `Decimal` values exactly (e.g. `Decimal('1500000.00')`), never via the `float()` chart payloads.
- **CSRF/SSL:** run with `DJANGO_DEBUG=True`; otherwise `SECURE_SSL_REDIRECT` 301s every test-client request.

## 5. Coverage checklist

- CORE-HP-01 — Staff login lands on dashboard
- CORE-HP-02 — Logout clears session and audits
- CORE-HP-03 — Password reset full flow (request → verify → login)
- CORE-HP-04 — Dashboard revenue equals Σ advance_paid
- CORE-HP-05 — Create user (admin)
- CORE-HP-06 — Edit user (admin)
- CORE-HP-07 — Role update via inline dropdown (admin)
- CORE-HP-08 — Toggle active / deactivate (admin)
- CORE-HP-09 — Audit logs list (management)
- CORE-HP-10 — Backup create + download (admin)
- CORE-EC-01 — Password reset code expiry
- CORE-EC-02 — Password reset code reuse
- CORE-EC-03 — Wrong password reset code
- CORE-EC-04 — Password minimum length boundary (6 chars)
- CORE-EC-05 — Revenue chart vs advance_paid divergence
- CORE-EC-06 — booking_transfer_view 500 on empty transfer_fee
- CORE-EC-07 — booking_transfer_view 500 on non-numeric transfer_fee
- CORE-EC-08 — Audit-log filter controls are non-functional
- CORE-SEC-01 — Privilege escalation via profile_view (staff with existing profile)
- CORE-SEC-02 — Portal customer self-creates super_admin profile
- CORE-SEC-03 — IDOR: customer_detail_view readable by any authenticated user
- CORE-SEC-04 — IDOR: customer_profile_pdf_view downloads any customer PDF
- CORE-SEC-05 — IDOR: booking_edit_view mutates any booking's money
- CORE-SEC-06 — IDOR: plot_edit_view editable by any authenticated user
- CORE-SEC-07 — Open redirect in lead_status_update_view
- CORE-SEC-08 — Backup zip-slip path traversal on restore
- CORE-SEC-09 — API read-open: /api/users/ exposes all users' PII
- CORE-SEC-10 — API read-open: /api/audit-logs/ exposes IPs and actions
- CORE-SEC-11 — API read-open: /api/leads/ exposes lead PII
- CORE-SEC-12 — API read-open: /api/agents/ exposes CNIC/commission
- CORE-API-01 — /api/auth/csrf/ sets CSRF cookie
- CORE-API-02 — /api/auth/login/ returns role in payload
- CORE-API-03 — /api/auth/logout/ ends the session
- CORE-API-04 — /api/auth/me/ returns role in payload
- CORE-API-05 — /api/profile/update_profile/ must not write role
