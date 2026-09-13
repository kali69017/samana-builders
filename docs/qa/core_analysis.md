# core Module — QA Analysis

> Read `docs/qa/_shared-context.md` first — roles/permissions/URLs are not re-derived here.
> Author: QA analysis of `core/` (views, api_views, forms, serializers, views_crm, views_settings, backup, admin + owned templates/JS).

## 1. Business purpose & user journeys

`core/` is the hub of the Samana ERP. It hosts the monolith view layer (`core/views.py`, ~2400 lines) that `samana_erp/urls.py` routes nearly every ERP page to, plus the DRF permission classes and the User/Lead/Agent/CompanySettings/AuditLog ViewSets, the CRM views (leads/agents), the settings/reporting views, the backup/restore engine, and the shared `UserProfile`/`AuditLog`/`Lead`/`Agent`/`CompanySettings`/`PasswordResetCode`/approval-chain models. It owns authentication (login/logout/password-reset), the corporate marketing site + lead capture, the staff dashboard and revenue/analytics, the customer portal, and the AI assistant pages. It matters because it is the single place where every business transaction is initiated and audited — if an authorization check is wrong here, money-mutating and PII endpoints are exposed.

Real user journeys (role → action → outcome):

- **Anonymous visitor** → `lead_submit_view` (POST from `corporate/home.html` contact form) → creates a `Lead` row; success toast on the home page. No login needed.
- **Staff (any role incl. `sales`)** → login → `/dashboard/` → sees stats; "New Customer"/"New Booking"/"Add Plot" quick actions are visible to everyone, but revenue/payment charts are gated by `can_view_payments`.
- **`sales`** → `customer_create_view` → creates Customer (welcome email fires, failure-safe) → `booking_create_view` → booking + auto `Payment` (verified) + `Receipt` + optional installment plan + booking notification.
- **`accounts`/`management`/`admin`** → `payment_create_view` → record a verified payment (updates installment, bumps `booking.advance_paid`, auto receipt, payment-confirmation + receipt notifications).
- **`management`/`admin`/`super_admin`** → `booking_confirm_view` (requires `advance_paid > 0`) / `booking_cancel_view` (blocked while verified payments exist) / `booking_reopen_view` / `booking_transfer_view`.
- **`admin`/`super_admin`** → `users_view` + `user_create_view`/`user_edit_view`/`user_role_update_view`/`user_deactivate_view`; `backup_view` → download/restore full DB.
- **Customer (portal login)** → `/portal/` → own bookings/payments/installments/nominee (via `portal_view` and the `/api/.../portal` endpoint).
- **Any authenticated user** → `profile_view` → edit own name/email/theme.

## 2. Data model

All `core` models live in `core/models.py`.

- **UserProfile** (`core/models.py:5`) — `user` (OneToOne, CASCADE, `related_name='profile'`), `role` (CharField, `ROLE_CHOICES`, default `sales`), `theme` (CharField, `THEME_CHOICES`, default `professional-blue`), `phone`/`cnic` (CharField blank), `is_active` (Bool, default True), `created_at`/`updated_at`. No `clean()`; no uniqueness beyond the OneToOne. **There is no model-level protection that stops a user from being given `role='super_admin'` via a form** — enforcement is entirely in the views/forms (and it is missing in `profile_view`, see §3/§6).
- **LoginAttempt** (`core/models.py:43`) — `username`, `ip_address` (GenericIPAddress, null/blank), `is_success`, `timestamp` (auto_now_add). `Meta.ordering = ['-timestamp']`. Backs the login brute-force guard (thresholds live in `api/views.py:19-20`).
- **ApprovalChain / ApprovalStep / ApprovalRequest** (`core/models.py:53-95`) — generic approval-chain scaffolding (`model_name`, `trigger_field`/`trigger_value`; steps with `role`, `min_amount`/`max_amount`; requests with `object_id`/`object_type`, `status` pending/approved/rejected/cancelled). Present but no ERP workflow in `core/views.py` drives them (serializers exist but no ViewSet is registered for them in `core/api_views.py`).
- **Lead** (`core/models.py:97`) — `name`/`email`/`phone` (all blank), `source` (choices, default `hero`), `status` (choices new/contacted/qualified/converted/lost, default `new`), `assigned_to` (FK User, SET_NULL), `interest_project` (FK Project, SET_NULL), `budget` (Decimal, null/blank), `is_contacted`, `notes`, `converted_customer` (FK Customer, SET_NULL), timestamps. `display_name` property falls back name→email→phone→`Lead #pk`. Indexes on `status`, `source`.
- **LeadNote** (`core/models.py:151`) — `lead` (FK CASCADE, `related_name='lead_notes'`), `note`, `created_by` (FK User, SET_NULL), `created_at`.
- **Agent** (`core/models.py:164`) — `agent_id` (CharField, unique, `editable=False`, auto `AGT-00001` in `save()` via `select_for_update()`), `name`, `phone`/`email`/`cnic` (blank), `commission_rate` (Decimal(5,2), default 0), `is_active`, `notes`, timestamps. Properties: `total_commission_earned`, `commission_paid`, `commission_balance`.
- **AgentCommissionPayment** (`core/models.py:212`) — `agent` (FK CASCADE), `amount` (Decimal(15,2)), `payment_date` (nullable), `method`, `reference`, `paid_by` (FK User SET_NULL). `amount <= 0` guarded only in the form, not the model.
- **CompanySettings** (`core/models.py:235`) — singleton; `save()` forces `self.pk = 1`; `load()` = `get_or_create(pk=1)`. Fields: branding (`company_name`, `tagline`, `logo`), contact (`phone`, `email`, `address`, `website`), finance (`currency`, `currency_symbol`, `tax_rate`, `receipt_footer`), social (`facebook`, `instagram`, `twitter`), `ai_language`.
- **AuditLog** (`core/models.py:281`) — `user` (FK SET_NULL), `action` (choices incl. create/update/delete/login/logout/verify/reject/transfer/cancel), `model_name`, `object_id`, `description`, `ip_address`, `timestamp` (auto_now_add). Indexes on `(model_name, object_id)` and `timestamp`. Append-only in app code; admin allows delete (only `has_add_permission`/`has_change_permission` are set False — `has_delete_permission` is left default True).
- **PasswordResetCode** (`core/models.py:313`) — `user` (FK CASCADE), `code` (CharField(6)), `used` (Bool), `created_at`, `expires_at`, `used_at`. `is_expired` property = `now > expires_at`.

Notable model-level observations: no `clean()`/model validation on any `core` model; agent commission and reset-code logic are view/form-level only; `UserProfile.role` carries the entire authorization boundary but is writable through two forms (`UserProfileForm` and `UserEditForm`) that differ in their protections.

## 3. Roles & permissions

Decorators redirect to `/dashboard/` on denial (see `_shared-context.md`). DRF classes: `IsAdminOrReadOnly` (read = any authenticated, write = `super_admin`/`admin`), `IsSuperAdmin`, `IsStaffOrAbove` (`core/api_views.py:13-49`).

### 3.1 `core/views.py` — action → allowed role(s) → enforcement

| View (file:line) | Verbs | Decorator | Side effects |
|---|---|---|---|
| `login_view` (40) | GET/POST | none (AllowAny) | `LoginAttempt`, `AuditLog`, session login |
| `logout_view` (82) | GET/POST | none | `AuditLog`; `logout()` |
| `password_reset_request_view` (93) | GET/POST | none | `PasswordResetCode`, `EmailService.send` |
| `password_reset_verify_view` (129) | GET/POST | none | mark code used, `set_password`, `AuditLog` |
| `dashboard_view` (174) | GET | `login_required` | read-only aggregates |
| `revenue_trend_view` (462) | GET | `login_required` + `finance_or_above` | JSON |
| `financial_reports_view` (512) | GET | `login_required` + `finance_or_above` | read-only |
| `customers_view` (603) | GET | `login_required` | read-only (PII) |
| `customer_create_view` (627) | GET/POST | `login_required` | Customer + nominee + welcome email + `AuditLog` |
| `customer_profile_create_view` (666) | GET/POST | `login_required` + `admin_or_above` | creates portal User |
| `customer_edit_view` (693) | GET/POST | `login_required` | update Customer/nominee + `AuditLog` |
| `customer_nominee_manage_view` (732) | GET/POST | `login_required` | add/update/delete nominee + `AuditLog` |
| `customer_delete_view` (783) | GET/POST | `login_required` + `management_or_above` | delete Customer + `AuditLog` |
| `customer_detail_view` (809) | GET | `login_required` | read-only (PII + finances) |
| `properties_view` (831) | GET | `login_required` | read-only |
| `project_create_view` (855) | GET/POST | `login_required` | create Project + `AuditLog` |
| `project_edit_view` (876) | GET/POST | `login_required` + `management_or_above` | update + `AuditLog` |
| `project_delete_view` (899) | GET/POST | `management_or_above` | guarded delete + `AuditLog` |
| `plot_create_view` (927) | GET/POST | `login_required` | create Plot + `AuditLog` |
| `plot_edit_view` (948) | GET/POST | `login_required` | update Plot + `AuditLog` |
| `plot_delete_view` (970) | GET/POST | `management_or_above` | guarded delete + `AuditLog` |
| `plot_detail_view` (995) | GET | `login_required` | read-only |
| `bookings_view` (1014) | GET | `login_required` | read-only |
| `booking_create_view` (1041) | GET/POST | `login_required` | Booking + plot→booked + plan + verified Payment + Receipt + notifications + `AuditLog` |
| `plan_templates_api_view` (1148) | GET | `login_required` | JSON |
| `booking_detail_view` (1176) | GET | `login_required` | read-only (finances) |
| `booking_edit_view` (1193) | GET/POST | `login_required` | update Booking (money) + `AuditLog` |
| `booking_delete_view` (1215) | GET/POST | `management_or_above` | guarded delete + plot→available + `AuditLog` |
| `booking_cancel_view` (1245) | GET/POST | `management_or_above` | plot→available, status→cancelled, `AuditLog` |
| `booking_reopen_view` (1296) | GET/POST | `management_or_above` | plot→reserved, status→pending, `AuditLog` |
| `booking_confirm_view` (1327) | GET/POST | `management_or_above` | status→confirmed + notification |
| `booking_transfer_view` (1400) | GET/POST | `management_or_above` | `BookingTransfer` + re-point customer + `AuditLog` |
| `reservation_create_view` (1448) | GET/POST | `login_required` | Reservation + plot→reserved + `AuditLog` |
| `payments_view` (1480) | GET | `login_required` + `payments_access` | read-only |
| `payment_create_view` (1541) | GET/POST | `login_required` + `payments_access` | verified Payment + installment update + advance bump + Receipt + notifications + `AuditLog` |
| `payment_detail_view` (1696) | GET | `login_required` + `payments_access` | read-only |
| `receipt_detail_view` (1745) | GET | `login_required` + `payments_access` | read-only |
| `receipt_pdf_view` (1772) | GET | `login_required` + `payments_access` | PDF |
| `invoice_pdf_view` (1792) | GET | `login_required` + `payments_access` | PDF |
| `customer_profile_pdf_view` (1811) | GET | `login_required` | PDF (PII) |
| `users_view` (1830) | GET | `login_required` + `management_or_above` | read-only |
| `user_create_view` (1843) | GET/POST | `login_required` + `admin_or_above` | create User + UserProfile + `AuditLog` |
| `user_edit_view` (1877) | GET/POST | `login_required` + `admin_or_above` | update User/profile/password + `AuditLog` |
| `user_role_update_view` (1917) | POST | `login_required` + `admin_or_above` | change role + `AuditLog` |
| `user_deactivate_view` (1947) | GET/POST | `login_required` + `admin_or_above` | toggle `is_active` + `AuditLog` |
| `audit_logs_view` (1994) | GET | `login_required` + `management_or_above` | read-only (filter broken, §6) |
| `profile_view` (2003) | GET/POST | `login_required` | **self role/`is_active` write (privilege escalation)** |
| `save_theme_view` (2035) | POST | `login_required` | set own theme |
| `backup_view` (2058) | GET | `login_required` + `admin_or_above` | read-only |
| `backup_download_view` (2083) | GET | `login_required` + `admin_or_above` | write ZIP + `AuditLog` |
| `backup_restore_latest_view` (2153) | POST | `login_required` + `admin_or_above` | full DB restore |
| `backup_restore_upload_view` (2185) | POST | `login_required` + `admin_or_above` | full DB restore |
| `corporate_home_view` (2217) | GET | none | static |
| `lead_submit_view` (2221) | POST | none | create Lead |
| `portal_view` (2252) | GET | `login_required` | own customer data |
| `ai_assistant_page_view` (2334) | GET | `login_required` | read-only |
| `ai_insights_page_view` (2351) | GET | `login_required` + `finance_or_above` | read-only |
| `ai_hr_page_view` (2395) | GET | `login_required` + inline role check | read-only |

### 3.2 `core/views_crm.py` and `core/views_settings.py`

- `leads_view` (30), `lead_create_view` (64), `lead_detail_view` (78), `lead_edit_view` (91), `lead_status_update_view` (119), `lead_note_add_view` (140), `lead_convert_view` (154), `agents_view` (209), `agent_detail_view` (243) are all **`@login_required` only** — the template gate `can_view_leads` (`MANAGEMENT + accounts + sales`) hides the Leads nav item, but the endpoints themselves are unguarded.
- `lead_delete_view` (106), `agent_create_view` (228), `agent_commission_payment_view` (257), `agent_edit_view` (282), `agent_delete_view` (298) are `@management_or_above`.
- `views_settings.py`: `company_settings_view` (34) `@admin_or_above`; `milestones_view` (52) `@login_required` (read-only); `milestone_create/edit/delete/detail` `@management_or_above`; `receivables_aging_view` (125) and `sales_report_view` (187) `@finance_or_above`.

### 3.3 DRF (`core/api_views.py`)

| Endpoint | Permission | Write gate |
|---|---|---|
| `/api/users/` (UserViewSet, ModelViewSet) | `IsAdminOrReadOnly` | write admin only; **read = any authenticated** |
| `/api/users/me/`, `/api/users/{pk}/toggle_active/` | `IsAdminOrReadOnly` | toggle is write (admin) |
| `/api/audit-logs/` (ReadOnlyModelViewSet) | `IsAdminOrReadOnly` | **read = any authenticated** |
| `/api/profile/`, `update_profile` | `IsAuthenticated` | self only |
| `/api/leads/` (LeadViewSet) | `IsAdminOrReadOnly` | **read = any authenticated**; `set_status`/`convert` are POST (admin) |
| `/api/lead-notes/` | `IsAdminOrReadOnly` | read open |
| `/api/agents/` (AgentViewSet) | `IsAdminOrReadOnly` | read open |
| `/api/company-settings/` | `IsAdminOrReadOnly` | update admin; read open |

### 3.4 Owner/object-level gating — and its absence (IDOR)

There is **no object-level authorization anywhere in `core/`**. Every `pk`-based view resolves `get_object_or_404(Model, pk=pk)` and proceeds if the user passes the *role* check only. There is no ownership concept (no `request.user`-scoped queryset). Concretely:

- `customer_edit_view` / `customer_nominee_manage_view` / `customer_detail_view` / `customer_profile_pdf_view` are `@login_required` only — any authenticated user (including a customer-portal account) can read/edit **any** customer's CNIC, phone, email, address, nominee, financial summary, and download any customer's profile PDF.
- `booking_detail_view` / `booking_edit_view` are `@login_required` only — any authenticated user can read any booking's amounts and **edit any booking's `total_amount`/`advance_paid`** (money-mutating IDOR). The pricing guard lives in `BookingForm`, but the role guard is absent.
- `plot_edit_view` (unlike `project_edit_view`/`plot_delete_view`) has **no** `@management_or_above` — any authenticated user can edit any plot's price.
- `project_create_view` / `plot_create_view` / `reservation_create_view` / `booking_create_view` are `@login_required` only — any authenticated user (including a customer-portal account) can create projects/plots/bookings/reservations.

The systemic root cause: customer portal users are `is_staff=False` with **no `UserProfile`** (see `CustomerProfileForm.save`, `customers/forms.py:135-142` — creates a `User` with only `username`/`email`/password, no `is_staff`, no profile). Every `@login_required`-only view therefore treats them as an authorized caller.

### 3.5 Template-flag vs. actual-guard inconsistencies

- **Leads**: sidebar hides `Leads` unless `can_view_leads`, but `leads_view`/`lead_create`/`lead_detail`/`lead_edit`/`lead_status_update`/`lead_note_add`/`lead_convert` are `@login_required` only → customers and other roles can reach them directly.
- **Payments nav** is gated by `can_view_payments` (matches `@payments_access`) — consistent.
- **Users nav** gated by `can_view_users` (management) and `can_manage_users` (admin) — `users_view` matches (`@management_or_above`), write views match (`@admin_or_above`). Consistent.
- **Backup nav** gated by `can_backup` — matches `@admin_or_above`. Consistent.
- **Audit nav** gated by `can_audit` — `audit_logs_view` is `@management_or_above` (consistent role), **but** the search/filter controls in `audit_logs.html` (`search`/`action_filter`/`model_filter`) are never wired to the view — the view ignores GET params and returns only `{'logs': logs}` (`core/views.py:1994-1998`). The filter UI is decorative/non-functional.
- **AI nav**: `AI Insights` link is shown unconditionally in the sidebar (`templates/includes/sidebar.html:250-255`) but `ai_insights_page_view` is `@finance_or_above` — a `sales`/`contractor`/`staff` user sees the link but gets redirected to `/dashboard/` on click.

## 4. Business rules, state machines, invariants

`core/` is the *initiator* of most state transitions; the heavier state machines for payments/refunds/expenses live in `payments/views_workflow.py` and `expenses/` (out of scope). What `core` itself enforces:

### 4.1 Booking lifecycle (partial — managed here)

- `booking_create_view` sets `plot.status='booked'` after save (views.py:1061-1064) and, if `advance_paid > 0`, records a `verified` Payment + Receipt (views.py:1096-1116).
- `booking_confirm_view` (1327): **invariant** — refuse to confirm if `advance_paid <= 0` (1327-1343); only `pending` can be confirmed (1346-1348). Side effect: status→`confirmed` + booking-approval email/whatsapp (1359-1393).
- `booking_cancel_view` (1245): **invariant** — block while `verified` payments exist (sum > 0) (1259-1267); already-cancelled is a no-op (1255). Side effect: plot→`available`, `cancelled_at`/`cancelled_by`/`cancelled_reason`, notes append, `AuditLog(action='cancel')`.
- `booking_reopen_view` (1296): only `cancelled` can reopen (1301); plot→`reserved`, status→`pending`, `reopened_at`, clears `cancelled_reason`.
- `booking_delete_view` (1215): **invariant** — block when `payments` exist (1219-1226); else plot→`available` + delete.
- `booking_transfer_view` (1400): re-points `booking.customer`; records `BookingTransfer`. No validation that `to_customer != from_customer` beyond the queryset exclusion in the template (1439) — the server does **not** enforce it (a crafted POST can transfer a booking to its own customer).
- `payment_create_view` (1541): **invariants** — installment must belong to the booking (1563-1573); duplicate guard same booking+amount+date+method within 60s (1575-1586); `advance_paid` bumped and capped at `total_amount` (1615-1620); `status→completed` when `remaining_balance <= 0` (1621-1622); installment `paid`/`partial` transition + overpayment tracked as `unallocated_amount` (1592-1613); atomic block wraps the money writes (1589-1637).

### 4.2 Deletion guards (in `core/views.py`)

- `customer_delete_view` (789): customer with `bookings` or `ledger_entries` cannot be deleted.
- `project_delete_view` (906): project with `plots` cannot be deleted.
- `plot_delete_view` (976): plot with `bookings` or `reservations` cannot be deleted.
- `booking_delete_view` (1221): booking with `payments` cannot be deleted.

### 4.3 User management invariants

- `user_edit_view` (1884-1900): only a super_admin can edit a super_admin; a user cannot change their own role; cannot change the last active super_admin.
- `user_role_update_view` (1924-1937): self-role change blocked; super_admin role not in the allowed set.
- `user_deactivate_view` (1955-1970): no self-deactivation; only super_admin deactivates super_admin; never lock out the last active super_admin.
- `CreateUserForm.clean_role` (forms.py:74-83): a super_admin cannot create another super_admin; non-super-admins cannot create super_admin at all.

### 4.4 Revenue semantics (inconsistency inside `core` itself)

- Headline "Revenue" = `Sum(Booking.advance_paid)` (dashboard, views.py:186-188; `ai_insights_page_view` 2364-2367; `CompanySettingsViewSet.summary` 288).
- BUT the revenue **chart** endpoint `revenue_trend_view` sums **verified `Payment.amount`** (views.py:469), and `financial_reports_view` sums verified `Payment.amount` for project/overall revenue (views.py:556). So "Revenue" can differ by screen. This contradicts the stated single-source-of-truth rule and should be reconciled (either all-`advance_paid` or explicitly label the Payment-based views differently).
- `financial_reports_view` computes `profit = revenue - expenses` where `expenses` sums **all** `Expense.amount` regardless of `status` (views.py:539, 557) — pending/rejected expenses depress profit.

### 4.5 Audit-log side effects

Nearly every mutating view writes an `AuditLog` entry (create/update/delete/login/logout/verify/reject/transfer/cancel). `login`/`logout` write an entry with IP (`views.py:66-70, 84-88`). `restore` writes success/failure entries (`views.py:2111-2137`).

## 5. Edge cases (go deep)

### 5.1 Privilege / authorization

- **Privilege escalation via self-service profile (CRITICAL).** `profile_view` (`views.py:2003-2032`) instantiates `UserProfileForm` whose `Meta.fields = ['role', 'theme', 'is_active']` (`forms.py:20-29`). The `profile.html` template renders only first/last name, email, and a hidden theme field — it does **not** render `role` or `is_active` — but the view accepts and saves them. Any authenticated user can `POST /profile/` with `role=super_admin` (and `is_active=True`); for a user with no existing profile (a customer-portal user), `UserProfileForm(request.POST)` is bound without an instance and `profile_form.save(commit=False)` + `profile.user = user` **creates** a `UserProfile` with the attacker-chosen role. `get_user_role()` then returns `super_admin`, unlocking every decorator and every `IsAdminOrReadOnly` write. This is a full vertical privilege escalation from an unauthenticated-vendor (customer) account. Fix: `profile_view` must use a form that excludes `role`/`is_active` (or a dedicated `UserProfileForm` fields list) and never instantiate a role-bearing form without an instance for non-staff.
- **Customer-portal user can enumerate/read all PII.** Because customer users are authenticated non-staff with no profile, `@login_required`-only read views (`customers_view`, `customer_detail_view`, `bookings_view`, `booking_detail_view`, `properties_view`, `plot_detail_view`, `agents_view`, `leads_view`) return the entire tenant's data. Expected behavior: customers should only reach `/portal/` and their own records.
- **Customer-portal user can create/edit domain records.** `booking_create_view`, `plot_create_view`, `project_create_view`, `reservation_create_view`, `customer_edit_view`, `booking_edit_view`, `lead_create_view` are `@login_required` only.
- **`booking_transfer_view` does not reject self-transfer** (only the template dropdown excludes the current customer); a crafted POST transfers a booking onto its own customer.

### 5.2 `pk`-based IDOR details

- `customer_edit_view` (693) / `customer_nominee_manage_view` (732) / `customer_detail_view` (809): no role, no ownership. `customer_profile_pdf_view` (1811) likewise — any authenticated user downloads any customer PDF (CNIC/phone/address/balances).
- `booking_edit_view` (1193): no role; edits `total_amount`/`advance_paid` directly (guarded only by `BookingForm.clean`, which checks against `plot.total_cost`/`holding_deposit`, so the amount floor is enforced but *who* edits is not).
- `plot_edit_view` (948): no `@management_or_above` (inconsistent with `project_edit_view` and `plot_delete_view`); any authenticated user can change a plot's price, which retroactively changes the pricing floor for future bookings.

### 5.3 Input / malformed payloads

- **`booking_transfer_view` crashes on empty/garbage `transfer_fee`.** `Decimal(request.POST.get('transfer_fee', '0'))` (views.py:1409) raises `decimal.InvalidOperation` → HTTP 500 when the field is blank or non-numeric. Expected: validation error, not a 500. (Management-only, so lower severity.)
- **`financial_reports.html` renders a Python list-of-dicts with `|safe`** (line 138) instead of `json_script`/`escapejs`. It currently happens to parse as a JS object literal because the dict repr uses single-quoted keys/values and float amounts, but it is fragile — any future change that puts a `True`/`False`/`None` or a string with a quote in the data breaks the page. Not currently XSS (labels are `strftime` month strings), but a latent footgun.
- **`lead_status_update_view` open redirect.** `redirect(request.POST.get('next') or 'leads')` (views_crm.py:137) follows an attacker-supplied `next` (e.g. `//evil.com`). Expected: validate `next` against an allow-list or ignore it.
- **`lead_submit_view` accepts arbitrary fields into `Lead.notes`** (interest/message) which are rendered escaped later — no XSS, but no length limits / no spam control (the public form is CSRF-protected but has no rate limit or honeypot).
- **Password reset code brute force (no rate limit).** `password_reset_verify_view` (129-171) accepts unlimited code guesses for 15 minutes; a 6-digit code (10^6) with no lockout is feasible to brute-force. Also `new_password` minimum is only 6 chars (145). Expected: per-user/IP attempt throttling and a stronger minimum (≥8).
- **Password reset request reveals no account existence** (generic success message, 123) — good — but `password_reset_request_view` has no rate limit on email sends (mail-bombing the reset code).
- **`logout` via GET.** `base.html`/`sidebar.html` link to `{% url 'logout' %}` as a plain `<a>` (GET) and `logout_view` (82) has no `@require_POST`; a logout-CSRF (third-party site forcing logout) is possible, though low impact. The portal uses a POST form correctly.

### 5.4 Backup / restore

- **Zip-slip path traversal on restore.** `restore_from_backup` writes media entries with `dest = media_root / rel` where `rel = Path(name).relative_to('media')` with **no check** that the resolved path stays under `MEDIA_ROOT` (`backup.py:333-344`). A crafted ZIP containing `media/../../…` (or a `../` name) writes files outside the media root. Reachable only via `@admin_or_above` (`backup_restore_upload_view`), so it requires an admin account or a compromised one — still a hardening item (validate `dest.resolve().is_relative_to(media_root.resolve())`).
- **Restore wipes and re-inserts via raw `DELETE FROM`/`INSERT`** (`backup.py:304-329`). Values are parameterized (`executemany`) and column/table names come from model metadata, so no SQL injection — but there is no integrity verification of the CSV, no FK/unique failure handling (a malformed row aborts the whole atomic transaction and the restore fails with the `_perform_restore` failure path).
- **`_restore_blocked`** (`views.py:2140-2150`) is disabled under `settings.DEBUG` (returns `False` immediately) and otherwise keys on an audit-log heuristic (`description__icontains=ip`) rather than a real lock — a double-submit of the same restore within 60s on a different IP, or with a name that doesn't contain the IP, is not caught. Concurrency guard is weak.
- **Restore brings back `auth_user`** (not in `FRAMEWORK_TABLES`, backup.py:277-283), so restoring an old backup re-creates old users (documented in `backup.html`, but worth flagging: any admin who restores an old ZIP may silently resurrect deactivated accounts).

### 5.5 Money / precision / dates

- Amounts are `DecimalField(max_digits=15, decimal_places=2)`; dashboard/report chart data is cast with `float(...)` (views.py:208, 226, 265, 485, etc.) — acceptable for charts but means the JSON chart endpoints lose exact Decimal precision (assertions in tests should use `advance_paid`/`total_amount` Decimals, not the `float` chart payloads).
- `dashboard_view` monthly collection trend uses a `30 * i` day approximation (views.py:231) and `m_end` month-boundary arithmetic (232-236) — drift at month ends (e.g. 31-day months), and the `for i in range(11, -1, -1)` uses `timedelta(days=30*i)` from *today*, not calendar months, so "last 12 months" buckets are approximate.
- Fiscal-year receipt numbering (`RCP-FY25-26/…`, July–June) is generated in `payments` (out of scope) but `core` receives it verbatim; `receipt_pdf_view` filename strips `/` (views.py:1783) — fine.
- `financial_reports_view` `collection_rate` clamps at 100 (596) but `dashboard_view` clamps both `collection_rate` and the per-month trend (246-248, 333-335) — consistent behavior, but the `total_installment_amount or 1` (331, 583) fallback of `1` gives a misleading 100% rate when there are zero installments.

### 5.6 Duplicates / concurrency

- `payment_create_view` duplicate guard is a 60-second window query (1575-1586) — **not** a DB uniqueness constraint, so two truly concurrent submits that straddle the window, or a retry after 61s, create duplicate payments. There is no idempotency key.
- `Agent.save()` auto-ID uses `select_for_update().order_by('-id').first()` (models.py:183-187) — safe under concurrency, but the same "parse last suffix" pattern in Customer/Booking/etc. lives in other apps (out of scope).
- `CompanySettings.load()` `get_or_create(pk=1)` (models.py:271-274) is race-safe enough for a singleton, but two concurrent `save()` calls still last-write-wins on config (no versioning).

### 5.7 Wrong verb / expired session

- Views that require POST for mutation guard `request.method != 'POST'` manually and `redirect` (e.g. `backup_restore_*`, `lead_submit_view`) rather than `@require_POST` — behavior is correct but inconsistent; a GET to `lead_submit` redirects to home (2223-2224).
- `password_reset_verify_view` reads `reset_user_id` from the session; if the session is gone/expired it renders with `user=None` and, on POST, redirects to re-request (135-137) — correct.
- Deleted-FK handling: `Lead.assigned_to`/`interest_project`/`converted_customer` are `SET_NULL`; `AuditLog.user`/`AgentCommissionPayment.paid_by` are `SET_NULL` — deleted users do not cascade-away history. Good.

## 6. Cross-cutting risks

### 6.1 XSS

- No `mark_safe`/`format_html` in `core/` Python. Templates auto-escape by default.
- `financial_reports.html:138` `{{ monthly_chart_data|safe }}` — server-generated month labels/float amounts only, so **not currently exploitable**, but it is the one raw-`|safe` injection point and should be replaced with `json_script`.
- `templates/payment_form.html:536-538` and `templates/booking_form.html:154` build `innerHTML` from `methodFieldsConfig`/`template` fields that are **hardcoded in the template** (not user data) — safe. `payment_form.html:465,657` build `innerHTML` from numeric API fields (`total_installments`, `installment_amount`) — safe.
- `templates/ai/insights.html:257-261` writes the AI response preview into `innerHTML` via `preview = data.result.slice(0,140)` (the AI-generated text). The AI response is not user-authored, but it is model output rendered unescaped — a stored model response containing HTML would execute. Low likelihood (server-side model, not client), but the response is also stored in `data-response` and re-rendered via `textContent` on click, so the only sink is the live preview. Recommend using `textContent` for the preview too.
- `static/js/main.js` `showConfirmDialog`/`showToast` build `innerHTML` from `message`/`title` params; current callers pass static strings, but the helper is a sink if ever fed user data. `static/js/erp.js` `showToast(message)` likewise concatenates `message` into `innerHTML` (line 224) — no current user-data caller, but note it.
- `templates/payment_form.html:304-334` and `booking_form.html` correctly use `|escapejs` for customer/project/plot names embedded in JS object literals. Good pattern.

### 6.2 CSRF

- `CsrfViewMiddleware` is enabled app-wide; **no `@csrf_exempt` exists anywhere in `core/` or the whole codebase** (the only `ensure_csrf_cookie` is `api/views.py:64` for the SPA token). All `core` POST forms render `{% csrf_token %}` (verified in `base_form.html`, `login.html`, `portal/dashboard.html`, `backup.html`, `users.html` role dropdown, `confirm_delete.html`, `corporate/home.html`).
- `save_theme_view` (POST JSON) relies on the `X-CSRFToken` header set by `erp.js`/`profile.html` — correctly protected because `CsrfViewMiddleware` checks the header. The portal logout and lead form use proper tokens.
- Residual risk: **logout via GET** (no token) is a logout-CSRF vector (§5.3); `lead_status_update_view`/`user_role_update_view` are small POST forms but still token-protected.

### 6.3 IDOR / broken object-level authorization

- Covered exhaustively in §3.4/§5.1/§5.2. The two headline items are (a) `profile_view` role self-escalation and (b) the `@login_required`-only PII/money endpoints reachable by customer-portal accounts.

### 6.4 Sensitive data exposure

- **API read endpoints are open to any authenticated user.** `UserViewSet` list (via `IsAdminOrReadOnly`) returns `UserSerializer` which nests `profile` → `phone`, `cnic` (`serializers.py:17-25, 9-14`); `AuditLogViewSet` list returns IP addresses and descriptions (`serializers.py:60-66`); `AgentViewSet` list returns `cnic`/`email`/`phone` (`serializers.py:131-138`); `LeadViewSet` list returns name/email/phone/budget. All are `GET` = "read for all authenticated", which includes customer-portal users.
- **ERP templates expose CNIC/phone/email/address/balances** on `customer_detail.html` (84-103, 186-191), `customer_profile_pdf.html`, `users.html` (email), `audit_logs.html` (IP, usernames), `agents.html`/`agent_detail.html` (commission data), `leads.html`/`lead_detail.html` (lead PII) — all reachable via `@login_required`-only views.
- **`ai_insights_page_view`** displays revenue/overdue aggregates to `@finance_or_above` only (fine), but `ai_assistant_page_view` is `@login_required` and the assistant's underlying `/api/ai/assistant/` is out of scope (verify its own authz separately).
- **Backup ZIP contains the entire DB** (all CSVs incl. `auth_user` hashed passwords, customers' CNIC/phone, payments) plus all media. `backup_download_view` is `@admin_or_above`, but the downloaded ZIP is a full PII/financial dump — treat it as a credential/PII artifact in transit and at rest.

### 6.5 Accessibility

- `base.html` topbar menu toggle uses `aria-label` (good); many icon-only action buttons across templates are emoji/`<a>` links without `aria-label` (e.g. dashboard action buttons, table row links). Form fields are wrapped in `<label for>` in `base_form.html`, but `payment_form.html`/`profile.html`/`login.html` use bespoke markup with visible labels — mostly `for`-correct.
- `profile.html` theme picker is `<label onclick>` divs with no keyboard affordance/`tabindex` (mouse-only selection); the hidden `id_theme` input is not keyboard-focusable.
- `dashboard.html`/`users.html` tables rely on `erp.js` click-to-sort `<th>` without `role="columnheader"`/`aria-sort`; sortable headers have `cursor:pointer` but no keyboard handler.
- Color-only status badges (e.g. `badge-success`/`badge-danger`) carry text labels, so not color-only; contrast of `var(--text-secondary)` on cards was not measured here but is worth an a11y pass.

## 7. API surface

DRF `DefaultRouter` in `api/urls.py` registers the `core` ViewSets. Auth endpoints (`auth/csrf`, `auth/login`, `auth/logout`, `auth/me`, `portal`) live in `api/views.py` (summarized here because `login_view`/`logout_view` depend on their helpers).

| Method + path | ViewSet/action | Permission | Request (required/optional) | Response / notes |
|---|---|---|---|---|
| GET `/api/users/` | `UserViewSet.list` | `IsAdminOrReadOnly` (read = any auth) | — | all users incl. `profile.phone`/`cnic` |
| POST `/api/users/` | `UserViewSet.create` | `IsAdminOrReadOnly` (admin) | `UserCreateSerializer`: username, email, password, first_name, last_name, role; phone/cnic optional | creates User + UserProfile + AuditLog |
| GET/PATCH `/api/users/me/` | `me` | `IsAdminOrReadOnly` | PATCH partial UserSerializer | self |
| POST `/api/users/{id}/toggle_active/` | `toggle_active` | write (admin) | — | toggles `is_active`, blocks self |
| GET `/api/audit-logs/` | `AuditLogViewSet.list/retrieve` | read = any auth | `?action=&model=` | latest 100 (queryset capped) |
| GET `/api/profile/` | `ProfileViewSet.list` | `IsAuthenticated` | — | own profile or 404 |
| PATCH `/api/profile/update_profile/` | `update_profile` | `IsAuthenticated` | partial UserProfileSerializer (`role`, `phone`, `cnic`, `is_active`) | **self-service role change via API too** — same escalation as `profile_view` |
| GET/POST `/api/leads/` | `LeadViewSet` | read any / write admin | LeadSerializer | `?status=&source=` |
| POST `/api/leads/{id}/set_status/` | `set_status` | admin | `status` | validates against `LEAD_STATUS_CHOICES` |
| POST `/api/leads/{id}/convert/` | `convert` | admin | `cnic` (≥13), `phone`, optional name/email/city | CNIC uniqueness + welcome email + AuditLog |
| GET/POST `/api/lead-notes/` | `LeadNoteViewSet` | read any / write admin | LeadNoteSerializer | `created_by` set server-side |
| GET/POST `/api/agents/` | `AgentViewSet` | read any / write admin | AgentSerializer | phone uniqueness validated; `agent_id` read-only |
| GET `/api/agents/{id}/bookings/` | `bookings` | read | — | bookings via `BookingSerializer` |
| GET `/api/company-settings/` | `CompanySettingsViewSet.list` | read any | — | singleton |
| PUT/PATCH `/api/company-settings/{id}/` | `update` | admin | partial CompanySettingsSerializer | singleton (pk=1) |
| POST `/api/auth/login/` | `api_login` | `AllowAny` | username, password | 429 on lockout, 403 deactivated, 400 invalid; writes LoginAttempt + AuditLog |
| POST `/api/auth/logout/` | `api_logout` | `IsAuthenticated` | — | AuditLog + logout |
| GET `/api/auth/me/` | `current_user` | `IsAuthenticated` | — | `_user_payload` |
| GET `/api/portal/` | `portal_dashboard` | `IsAuthenticated` | — | customer-only summary or 403 |

**Key serializer notes:**

- `UserProfileSerializer` exposes `role`, `phone`, `cnic`, `is_active` (`serializers.py:9-14`) — and `ProfileViewSet.update_profile` allows PATCHing `role` (self-service role escalation via API, mirroring the HTML `profile_view` bug).
- `UserCreateSerializer` (serializers.py:28-57) accepts `role` from a fixed list `['super_admin','admin','sales','accounts','management']` and has **no restriction that the caller is a super_admin to grant `super_admin`/`admin`** — combined with `UserViewSet.perform_create` (admin-only write) this is contained, but any future loosening of the permission class would open role-granting.
- `LeadSerializer.validate` requires at least one of name/email/phone (116-119); `AgentSerializer.validate_phone` enforces phone uniqueness (145-153); `validate_commission_rate` bounds 0–100 (140-143).

## 8. Test data & fixtures needed

Preconditions and isolation rules for QA of `core`:

- **Roles**: seed one user per role — `super_admin` (or a Django `is_superuser`), `admin`, `management`, `accounts`, `sales`, `hr`, `project_manager`, `contractor`, `staff` — plus a **customer-portal user** (a `User` with `is_staff=False` and **no** `UserProfile`, linked to a `Customer` via `Customer.user`). This last one is essential to exercise the IDOR/privilege-escalation findings.
- **Seed domain data**: at least one `Project` (active) → `ProjectPhase` → `Plot` (with `price`, `development_charge`, `lease_charge`, `other_charges`, `holding_deposit` so `total_cost`/`holding_deposit` guards are testable) → `Customer` (with `cnic`, `phone`) → `Booking` (with `advance_paid`, `total_amount`) → `Payment` (`verified`/`pending`) → `Receipt`. Use `populate_dummy_data.py` then mutate.
- **Isolation rules**: auto IDs are global monotonically increasing (`CUS-00001`, `BKG-00001`, `PAY-00001`, `AGT-00001`) parsed from the last record's suffix — tests that assert exact IDs must run in a clean DB or assert only the prefix/format. Receipt numbers are fiscal-year based (July–June) — a test crossing June 30/July 1 must inject a fixed `timezone` (freezegun) or it will flake. `CompanySettings` is a forced-pk=1 singleton — tests must not create a second one.
- **CSRF/SSL**: run with `DJANGO_DEBUG=True` (else `SECURE_SSL_REDIRECT` 301s every client request); use the shared `.venv312` with `env -u PYTHONPATH`.
- **Backup tests**: craft a benign backup ZIP (via `build_backup_zip()` round-trip) plus a malicious ZIP with a `media/../../evil.txt` entry to assert the zip-slip guard (once added).
- **Money assertions**: assert `Decimal` values exactly (e.g. `Decimal('1000000.00')`), never via the `float()` chart payloads.

## 9. Key files (for traceability)

- `core/views.py` (2414) — monolith; every ERP page, auth, dashboard, booking/payment flows, backup, portal, AI. Source of the `profile_view` escalation and the `@login_required`-only IDOR endpoints.
- `core/api_views.py` (302) — `IsAdminOrReadOnly`/`IsSuperAdmin`/`IsStaffOrAbove` + User/AuditLog/Profile/Lead/LeadNote/Agent/CompanySettings ViewSets.
- `core/forms.py` (286) — `UserProfileForm` (role-bearing, used by `profile_view`), `UserForm`, `CreateUserForm`, `UserEditForm`, `RestoreBackupForm`, CRM/Agent/CompanySettings forms.
- `core/serializers.py` (161) — `UserSerializer` (nests `profile.phone/cnic`), `UserCreateSerializer`, `AgentSerializer` (cnic), `CompanySettingsSerializer`, etc.
- `core/models.py` (334) — `UserProfile`, `LoginAttempt`, `ApprovalChain/Step/Request`, `Lead`, `LeadNote`, `Agent`, `AgentCommissionPayment`, `CompanySettings`, `AuditLog`, `PasswordResetCode`.
- `core/permissions.py` (199) — role groups + decorators (`get_user_role`, `role_required`, `management_or_above`, `finance_or_above`, `payments_access`, etc.).
- `core/context_processors.py` (60) — `erp_context` role flags, `user_theme_processor`, `company_context`.
- `core/views_crm.py` (308) — leads + agents (several `@login_required`-only, `lead_status_update_view` open redirect).
- `core/views_settings.py` (218) — company settings, milestones, receivables aging, sales report.
- `core/backup.py` (350) — CSV serialization, media manifest, `restore_from_backup` (raw SQL + zip-slip sink).
- `core/admin.py` (119) — admin registration (AuditLog/LoginAttempt deletable by superuser).
- `api/views.py` (220) — `_login_locked_out`/`_record_login_attempt`, `api_login`, `portal_dashboard` (referenced by `login_view`).
- `customers/forms.py` (204) — `CustomerProfileForm.save` (creates non-staff, profile-less portal users), `CustomerForm` CNIC/phone validation.
- `bookings/forms.py` — `BookingForm.clean` pricing guards (referenced for booking invariants).
- `samana_erp/urls.py` — URL map confirming every ERP page routes to `core/views.py`.
- Templates read: `base.html`, `base_form.html`, `login.html`, `dashboard.html`, `users.html`, `profile.html`, `backup.html`, `audit_logs.html`, `customer_detail.html`, `booking_detail.html`, `payment_form.html`, `booking_form.html`, `portal/dashboard.html`, `corporate/home.html`, `corporate_base.html`, `ai/assistant.html`, `ai/insights.html`, `includes/sidebar.html`, `confirm_delete.html`.
- JS read: `static/js/erp.js`, `static/js/main.js` (theme/save-theme AJAX, `showToast`/`showConfirmDialog` innerHTML sinks).
