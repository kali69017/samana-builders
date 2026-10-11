# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Real Estate Management ERP + corporate website for Samana Builders & Developers. Django 6.0 + Django REST Framework backend serving two frontends: a server-rendered ERP (Django templates) and a corporate marketing site (also Django templates, with a compiled React build artifact in `frontend/dist/`). SQLite for dev, PostgreSQL for production.

## Work status (last updated 2026-10-11)

### Shipped — production-ready finalization (cron scheduler + Docker deploy, 2026-10-11)

- **Notification scheduler**: `send_installment_reminders` now fires both installment
  reminders (due within N days) and overdue alerts, with a per-booking cooldown dedupe via
  `NotificationLog`. Docker ships a `scheduler` service running `deploy/crontab` daily at
  08:00 (no host cron needed) — see `RUNBOOK.md` §3b. Tests: 100 OK.
- **Deploy (Docker/Caddy)**: `DEPLOY.md` step-by-step guide; Caddy now serves `/media/*` from
  the shared volume; `docker-compose` wires WhatsApp + SMS template env through `x-app-env`;
  `settings.py` adds HSTS/nosniff/X-Frame-Options in prod; `.env.example` is a complete prod
  template. `manage.py check --deploy` clean except optional HSTS subdomain/preload.
- Pushed as `77fcf0a`, `88b485a` (this sits on top of the 2026-10-10 hardening batch).

### Shipped — production-readiness security hardening (2026-10-10)

All documented Critical/High confirmed findings closed; full Django suite 935+ green; pushed.

- **F1/F2 privesc** (already fixed in code): role not self-assignable via API profile update
  or the web `/profile/` form (serializer `read_only_fields`, form `fields=['theme']`).
  Regression-guarded in `api/tests_permissions.py`.
- **F3 least-privilege API reads**: every ViewSet now gates SAFE_METHODS by function role
  (`core/permissions.user_role_allows`): customers/users → admin+; agents → admin+management;
  leads → CRM roles; bookings → admin+management+sales+accounts; payments/office-expenses/
  account-transactions/project-costs → finance roles; hr/employees → hr roles; audit-logs →
  management+. Sales/hr no longer read other modules' PII. Flips FIN-SEC-01, CUS-SEC-06 green.
- **Portal isolation**: `dashboard_view` redirects portal customers to `/portal/` (was: portal
  could open the full business dashboard). Portal also blocked from customers/others via the
  existing read gates. Fixes CUS-SEC-05.
- **F6 payment workflow**: verify (API + web) now accepts *pending* only and runs inside
  `transaction.atomic` with `select_for_update` on the payment + booking; payment reverse and
  refund approve take row locks. No double-count races.
- **FIN-SEC-03**: expense/`ProjectCost` `pay` (API + web views) requires `approved` source —
  a draft/pending can no longer post money to the ledger.
- **F7 XSS / F4 CSRF / F8 leave-writable / N-SEC-04**: verified already fixed in current code
  (templates use `textContent`+escaping; `@require_POST` on expense mutations; Leave
  `status` read_only) and regression-guarded.
- **Notifications (N-SEC-01/03/05)**: manual send is rate-limited per recipient (429,
  `NOTIFICATION_MANUAL_RATE_LIMIT`); Notification Center masks PII contacts for non-admin via
  `mask_contact`; the log is scoped to `created_by` for management. Flips NOTIF-SEC-01/03/05,
  and EC-03/04/09/HP-09/HP-10 now assert the honest skipped/disabled contract.
- **EmailService.send** disabled-default inverted (`getattr(..., False)`).

E2E notes: notifications 22 passed / 3 pre-existing confirmed-bug RED (HP-03 welcome-SMS,
EC-08 dropdown, EC-05 name overflow). Payments/customers share sec-flips above (PAY-HP-05,
CUS-SEC-02/03/04/06, CUS-HP-07). Finance suite's residual 20ish failures are the documented
stale assertions against the deprecated single-entry `AccountTransaction` (the double-entry
Voucher ledger is verified healthy; see `report_final.md` §5.4).

### Shipped — WhatsApp transactional notifications on approved templates (`6e0a505`, pushed)

The WhatsApp channel could not actually deliver a transactional notification. All five
`services.py` triggers plus `booking_confirm_view` called `WhatsAppService.send()`, which
posts `type: 'text'`. Meta only permits free-form text inside the 24-hour customer service
window, and every one of those triggers fires outside it, so each send failed with 131047.
Three further defects made the failure invisible: `raise_for_status()` discarded the Graph
error body (the actionable code and `error_data.details` never reached
`NotificationLog.error_message`), no `provider_message_id` was extracted for WhatsApp (so
delivery could not be tracked), and an unconfigured channel still reported `sent`.

1. **Templates** — `WhatsAppService.send_typed()` sends a Meta-approved utility template with
   named body parameters, resolved per notification type through
   `TEMPLATE_SETTING_BY_TYPE`. `NotificationService.send_notification()` gained an optional
   `template_params` kwarg; when present on the `whatsapp` channel it routes to the template
   path, when absent it keeps the existing free-form behaviour, so all existing callers are
   unaffected. Empty-string params are dropped so a customer with no next installment does not
   get a blank phrase.
2. **Six templates, one per type** — `payment_confirmation`, `booking_notification`,
   `booking_approval`, `installment_reminder`, `overdue_payment`, `receipt_notification`,
   specified in the new `notifications/wa_templates.json` (create them in WhatsApp Manager,
   category UTILITY, named parameters). Each is enabled by its own `WHATSAPP_TEMPLATE_*`
   setting; **blank means that notification fails with a message naming the setting** rather
   than failing opaquely against Meta.
3. **Errors are now readable** — Graph error bodies are parsed into
   `code/subcode + message + details + hint`, with actionable hints for 131047, 130429,
   131056, 132000, 132001, 131049 and 131050. Network failures and non-JSON responses return
   `(False, detail)` instead of raising, so a broken WhatsApp send still cannot fail a
   payment. The send logic is shared by both paths via `WhatsAppService._post()`.
4. **Delivery tracking** — the `wamid` is parsed out and stored in `provider_message_id`,
   giving Phase 2's webhook a row to update.
5. **Late-fee wording removed** from both the WhatsApp templates and the email bodies
   (`send_installment_reminder`, `send_overdue_payment_alert`) per business decision that no
   late fees are charged; the overdue template no longer sends a `late_fee` parameter.
6. **UI** — the manual-send modal warns that free-form WhatsApp only works within 24h of the
   customer's last message.

New file: `notifications/wa_templates.json`. Settings: 7 new `WHATSAPP_TEMPLATE_*` entries.
No migration — `NotificationLog` already carried `provider_message_id` and `error_message`.

#### Provisioned live; parameter format is POSITIONAL by Meta's constraint, not preference

All six templates now exist on WABA `1384537200534046` and are wired into `.env`. Creating
them surfaced three platform constraints that the published docs do not describe — all found
empirically against the live WABA, all now enforced in `wa_templates.py`:

1. **NAMED templates with variables cannot be created via the Graph API.** Supplying
   `example` fails with subcode `2388043` ("component of type BODY is missing expected
   field(s) (example)") in *every* shape tried — nested, flat, and keyed-by-name. Omitting
   `example` creates the template only for Meta to reject it as `INVALID_FORMAT`.
   POSITIONAL works. So bodies use `{{1}}..{{N}}`, and `parameters` in the spec is the
   ordered contract mapping index → `param_name`.
   **This changes the send path:** `send_typed()` now emits positional parameters (no
   `parameter_name`) ordered by `wa_templates.parameter_order()`, never by Python dict
   order — otherwise a reordered dict literal would silently post a customer's name into
   their balance field. Unknown parameter names are rejected outright rather than dropped.
2. **`sub_category` is narrower than documented, and `ORDER_STATUS` is unusable.**
   This account accepts only `{ORDER_DETAILS, ORDER_STATUS, RICH_ORDER_STATUS}`;
   `BOOKING_STATUS` is refused outright. But `ORDER_STATUS` itself fails with `2388210`
   ("There should not be title or button(s) in an order status template"). All six
   therefore use `ORDER_DETAILS`.
3. **Variables cannot lead or trail a template** — `2388299`. Every body needs literal text
   before its first and after its last placeholder.

Also worth knowing: subcode `2388023` means *"content for this name+language is still being
deleted"* — recreating a template within ~a minute of deleting it fails even though the name
is absent from the list API. Three templates carry a `_v2` suffix purely because my own
cleanup tombstoned the originals; the names are otherwise arbitrary.

#### Provisioning: templates are created from code, not clicked through the UI

The six templates cannot be created by Django — they need `POST /{waba}/message_templates`.
`notifications/wa_templates.py` reads `wa_templates.json`, validates it against the Graph
enums, and compiles it into create-payloads; two commands do the rest:

```powershell
python manage.py create_wa_templates --dry-run   # print the exact bodies, call nothing
python manage.py create_wa_templates             # create all six (PENDING until review)
python manage.py check_wa_templates              # status + quality + why it failed
```

`WhatsAppService.create_template()` / `list_templates()` are the WABA-level API calls, sharing
the HTTP + error-describing layer with the send path via `WhatsAppService._graph()`. Both
deliberately ignore `WHATSAPP_ENABLED` — provisioning while the live channel is off is the
intended workflow. They need `WHATSAPP_WABA_ID` (**not** the phone number ID; it is not
discoverable through the API — every edge is refused, so read it off App Dashboard >
WhatsApp > API Setup).

`check_wa_templates` exists because a template that never approves is otherwise invisible:
it maps `rejected_reason` (`INCORRECT_CATEGORY`, `TAG_CONTENT_MISMATCH`, `PROMOTIONAL`, …) to
specific copy advice, and cross-checks the WABA against `.env` so a created-but-unwired
template is flagged. `allow_category_change` is **false** throughout — a template Meta thinks
is promotional should come back REJECTED so we can see and fix it, not get silently
reclassified to MARKETING with different pricing and an opt-in we never collected.
Each entry carries a `sub_category` (`ORDER_STATUS` / `BOOKING_STATUS` / `ORDER_DETAILS`),
which materially improves approval odds and classification accuracy.

### Shipped — finance ledger remediation (`7fcf9a2`, committed + pushed this session)

Found by a full manual pass over the double-entry ledger (headed Playwright against
a seeded DB), then fixed and regression-tested. 786 tests green at time of writing.

1. **`ProjectCost` could never reach the ledger** (HIGH) — `status` defaulted to
   `'pending'`, which was not a member of `STATUS_CHOICES` (draft/approved/paid), so
   the UI rendered the raw string; the list had no actions column, edit/delete URLs
   were unreachable, `status` was read-only in the API, and `post_to_ledger()` is
   gated on `status == 'paid'` — so no user-facing path could ever post one. Fixed:
   `('pending', 'Pending Approval')` added to the choices (migration
   `finance/0009`), `project_cost_approve_view` / `project_cost_pay_view` +
   routes, an actions column mirroring `office_expenses.html`, and `approve` / `pay`
   actions on `ProjectCostViewSet`.
2. **Rs. 35,000 paid-but-unposted** (MEDIUM) — `post_to_ledger()` only fires on the
   write path, so rows that were `paid` before the writers shipped had no voucher and
   the ledger silently under-reported. Added
   `manage.py backfill_ledger_vouchers` (`--dry-run`, idempotent, prints a trial-balance
   check). It recovered 25,000 (office expense) + 10,000 (project cost).
3. **Edit-after-post desync was invisible** (MEDIUM) — FIN-EC-03 means editing a paid
   source never rewrites its immutable voucher, so the two can disagree forever.
   Added `Voucher.total_debit/total_credit/is_balanced`, plus
   `posted_voucher` / `ledger_out_of_sync` on `OfficeExpense` and `ProjectCost`.
   Surfaced as a `⚠ Ledger mismatch` badge in both lists and an escalation banner in
   the edit forms (the mismatch banner supersedes the generic immutability note).
4. **Meaningless balance column in the all-accounts ledger** (LOW) — one running
   balance across mixed-nature accounts; the closing `0.00` was just the dr==cr
   identity. The balance column, the opening-balance card and the closing-balance card
   are now shown only when a single account (or roll-up) is selected; the all-accounts
   view shows posting-line count and a debits-vs-credits `Balanced` check instead.
   Applied to `ledger.html`, `ledger_pdf.html` and the Excel export.
5. **`test_ledger_full.py` deleted** (LOW) — lived at the repo root and ran
   `asyncio.run(test_ledger())` at import time, so `manage.py test` discovery spawned
   a server and a headed browser and blocked for 5 minutes. It also had 4 wrong URLs
   and a broken `'OfficeExpense' in content` assertion. Its coverage was replaced by
   `finance/tests_project_cost_flow.py` and `finance/tests_backfill_ledger.py`.
6. **A paid source could be silently reopened** (MEDIUM, found while fixing #1) — both
   `office_expense_approve_view` and `OfficeExpenseViewSet.approve` accepted a direct
   POST on a `paid` expense and reverted it to `approved` while its locked voucher
   stayed posted. The UI hid the button, but the URL was reachable. Both now refuse
   (web: error toast; API: `409 Conflict`), matching the guard already added to
   `project_cost_approve_view`.

New files: `finance/management/commands/backfill_ledger_vouchers.py`,
`finance/tests_backfill_ledger.py`, `finance/tests_project_cost_flow.py`,
`finance/migrations/0009_alter_projectcost_status.py`.

### Shipped — SendPK review remediation (this session)

Review findings on the fixed-sms integration shipped in `6faf054`, all fixed and
verified (913 tests green, transport re-verified live against SendPK):

- `SMSService.send_typed()` now enforces the template's expected variables:
  a missing required slot refuses to send and names the variable; the one slot
  the caller builds conditionally (`next_installment`) falls back to `none due`
  instead of shipping a raw `#placeholder#`; an unconfigured template names the
  exact `SENDPK_TEMPLATE_*` key to fill in.
- Transport unified on POST (api_key kept out of the request URL) and the
  JSON/plain-text reply parsing is shared with `send()`; confirmed live with
  `OK ID:655087f4-...`.
- A switched-off provider is recorded `skipped`, not `sent` (docs/qa finding #2):
  new `skipped` status (`notifications/0004` migration), Notification Center
  stat + filter option, and a disabled manual send now warns instead of claiming
  "sent successfully".
- Notification Center filters no longer 500 — Django raises
  `TypeError: Cannot filter a query once a slice has been taken`; the log list
  filters before slicing.
- `settings.py`: every provider is forced off under `manage.py test` (the
  `TESTING` guard), so a key-carrying `.env` can never make the suite a real
  sender. Tests that need a channel live declare it with `override_settings`.

### Shipped (committed + pushed to origin/main)

Two commits landed since 2026-09-08, both on `main` and pushed. Working tree is clean.

- **`aeead4d` — "Client feedback round"** — the client-feedback batch below (booking pricing guards, cancel/reopen, refund + expense workflows, ledger dedup, nominee, welcome email, milestones, UI polish), plus the CLAUDE.md refresh and the SendPK API 3.0 doc. 663 tests green at commit time.
- **`d2e6d34` — "QA remediation"** — permission tightening, read-only expense status, office-delete guard, self-service profile, XSS/ledger fixes (details below). 663 tests green at commit time.

What shipped (client-feedback round):

1. **Booking pricing guardrails** — `Plot` gained `development_charge`, `lease_charge`, `other_charges`; `Plot.total_charges` and `Plot.total_cost` (price + charges) are the single source of truth. Booking create/edit forms and the API serializer reject a `total_amount` below `plot.total_cost` and an `advance_paid` below `plot.holding_deposit`. `Booking` also gained `payment_plan` / `amount_paid` / `total_charges` display helpers.
2. **Confirm requires an advance** — `booking_confirm_view` and the API `confirm` action refuse to confirm when `advance_paid <= 0`.
3. **Cancel / reopen bookings** — new `booking_cancel_view` / `booking_reopen_view` (+ `booking_cancel.html`, `booking_reopen.html`, URL routes). Cancel is blocked while verified payments exist (refund first); it releases the plot to `available` and records `cancelled_at` / `cancelled_by` / `cancelled_reason`. Reopen returns the booking to `pending`, stamps `reopened_at`, and re-reserves the plot. Both write AuditLog entries.
4. **Refund workflow upgrade** — `Refund` gained `refund_method`, `refund_date`, `supporting_document`, `processed_by`, `updated_at`, an `amount > 0` constraint, and `-created_at` ordering. Computed helpers: `total_paid`, `total_refunded`, `refundable_amount` (verified payments − non-rejected refunds), `refund_percentage`. Lifecycle: `pending → approved → processed | rejected`; `process()` marks it processed and posts exactly one ledger row (idempotent, skips if already posted). Validation enforced on model + form + serializer. UI: process button on `refunds.html`; API: `approve` / `reject` / `process` actions with audit logging.
5. **Expense approval workflow** — `Expense` gained `status` (`pending → approved → paid | rejected`), `approved_by` / `approved_at`, `payment_reference`, `receipt_attachment`. New approve / reject / mark-paid views + URLs; approve and mark-paid post the expense to the ledger exactly once; approved/paid expenses are locked from editing.
6. **Ledger de-duplication** — unique constraint on `AccountTransaction` (`reference_type`, `reference_id`); refunds, expenses, and salary payments post via idempotent `update_or_create` keyed on that pair.
7. **Deletion guards** — a project with plots cannot be deleted; an office with expenses or ledger transactions cannot be deleted (enforced in both the web view and `OfficeViewSet.destroy`).
8. **Nominee management** — `customer_nominee_manage_view` + `customer_nominee_form.html` lets staff add/edit/remove a customer's nominee (also shown on customer detail + the portal).
9. **Customer welcome email** — `NotificationService.send_customer_welcome()` fires on customer create (UI + API) and lead conversion; failure-safe and skipped when no email. New `customer_welcome` notification type.
10. **Milestones** — `ProjectMilestone` gained `start_date`, `milestone_type`, `completion_percent`, `progress_date`; form, list (progress bar), and detail updated.
11. **UI polish** — `money` template filter; print stylesheet (hides chrome) + Print button on the sales report; refreshed properties / expenses / refunds / offices / milestones tables.

New files from both commits: `api/tests_booking_pricing.py`; migrations `bookings/0005`, `expenses/0003` + `expenses/0004`, `finance/0004` + `finance/0005`, `notifications/0003`, `payments/0007`, `properties/0006` + `properties/0007`, `customers/0005`; templates `booking_cancel.html`, `booking_reopen.html`, `customer_nominee_form.html`; `Business_SMS_API_3.0.pdf`.

### QA remediation (commit `d2e6d34`)

Permissions and API-contract tightening applied as part of the QA pass:

- **`project_create_view` / `plot_create_view` / plot_edit now require `management_or_above`** (were `login_required` only). Tests updated to give the view-test user an admin profile.
- **Portal customers blocked from staff/financial API reads** — new `core.permissions.is_portal_customer()`; finance `IsFinanceOrAbove` returns `not is_portal_customer(...)`.
- **Office/project-cost `status` is now read-only on the API** (removed from the form; serializer `read_only_fields`). Create always lands `pending` and never auto-posts to the ledger. `OfficeExpense` is moved to `paid` via the `pay` action (posts ledger); `ProjectCost` has no pay action. `ProjectCost.status` default changed from `paid` → `pending` (migration `finance/0005`).
- **`OfficeViewSet.destroy`** refuses deletion while the office has expenses/ledger transactions (was view-only guard).
- **Self-service profile form is `theme`-only** — `role` / `is_active` are no longer user-editable; `UserCreateSerializer` write_only. `CustomerNominee.nominee_name` `blank=True`; expense receipt attachment wired.

**Verification:** full Django suite green — 663/663, `OK` — with `DJANGO_DEBUG=True` + shared venv, run before both commits.

### SMS (SendPK) status

The SMS channel is wired to the SendPK HTTP API (`SMSService`) and **enabled in the local `.env`** (`SENDPK_ENABLED=True`, real `SENDPK_API_KEY`, sender `TEXT SMS`). This account is **fixed-sms**: it rejects free text, so automated sends go through four approved templates via `SMSService.send_typed()` — `SENDPK_TEMPLATE_CUSTOMER_WELCOME=10904`, `_PAYMENT_CONFIRMATION=10901`, `_INSTALLMENT_REMINDER=10902`, `_OVERDUE_PAYMENT=10903` (ids are account-specific; override in `.env`). The free-text `SMSService.send()` remains only for one-off staff messages and will be rejected by the provider. Reference docs: `sendpk_documentation.md` (gitignored) and `Business_SMS_API_3.0.pdf`. Live account findings (2026-09):

- Sends work and are billed (~3.9 PKR/SMS). "Accepted for delivery" only means queued; the delivery report is where real per-number status shows.
- On the shared sender route the message arrived on Telenor showing a generic "TEXT SMS" sender — shared sender names are not carried reliably, and the brand only appears in the auto-appended footer.
- Showing **SAMANA** as the sender requires a branded sender mask approval (one-time; account verification documents needed). After approval set `SENDPK_SENDER_ID=SAMANA` (see the comment in `settings.py`).
- A ported number (Ufone → Jazz) did not receive the shared-route message (routing follows the original operator). For ported numbers pass the `network` parameter (Jazz/Zong/Ufone/Telenor), or verify the branded route resolves MNP automatically.

### Production deploy notes

Recent commits on `main` (through `d2e6d34`, Sep 14) cover prod safety: `DEBUG` defaults to False in production, CSRF trusted origins + secure proxy/cookie settings, and AI/OpenRouter env mappings in compose. Prod is docker-compose on the VPS; env vars (`DJANGO_SECRET_KEY`, `DB_*`, `EMAIL_*`, `SENDPK_*`, `OPENROUTER_API_KEY`) must be supplied there. The two shipped commits above are not yet deployed to the VPS — `git pull` + `docker compose up -d --build` there will deploy them (and the new migrations needed).

## Commands

The working virtualenv is **`D:\samana\.venv312`** (Python 3.12) — activate it as below, or call its `Scripts\python.exe` directly. Always run with `PYTHONPATH` unset (`env -u PYTHONPATH` in bash): a stray `PYTHONPATH` from the surrounding tooling can shadow the venv packages and break imports. Note: the `.venv312` inside this checkout is an incomplete copy (no pydantic / langchain, so the AI-backed tests fail under it) — use the shared venv for the full run. The README's `venv` is stale.

```powershell
# Activate (PowerShell)
D:\samana\.venv312\Scripts\Activate.ps1
# or Bash
source /d/samana/.venv312/Scripts/activate

# Run dev server
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Tests — full suite, one app, or a single test.
# IMPORTANT: prefix DJANGO_DEBUG=True (bash) or set $env:DJANGO_DEBUG='True'
# (PowerShell) — see the note below the commands. Without it the suite
# mass-fails with 301 redirects (SECURE_SSL_REDIRECT is `not DEBUG`).
DJANGO_DEBUG=True python manage.py test
DJANGO_DEBUG=True python manage.py test payments
DJANGO_DEBUG=True python manage.py test payments.tests.PaymentModelTest.test_payment_id_generation

# Django shell / superuser / migrations check
python manage.py shell
python manage.py createsuperuser
python manage.py showmigrations
```

**Set `DJANGO_DEBUG=True` when running tests.** With the `.env` default (`DJANGO_DEBUG=False`), `SECURE_SSL_REDIRECT` redirects every test-client request (301), so the suite mass-fails with hundreds of bogus failures. Full suite: 663 tests, ~9 minutes.

Default login: `admin` / `admin123`. Login URL `/login/`, post-login staff land on `/dashboard/`, customers on `/portal/`.

Useful scripts: `populate_dummy_data.py` (seed data), `debug_revenue.py` (ad-hoc revenue debugging).

## Architecture

### `core/` is the hub — most HTML views live there

Despite each module having its own `views.py`, **`samana_erp/urls.py` routes nearly every ERP page to functions in `core/views.py`** (~2000 lines): customers, properties, bookings, payments, receipts, PDFs, users, audit logs, backup, the corporate home page, and the customer portal. When working on an ERP page, the view logic is almost always in `core/views.py`, not the app's `views.py`.

The domain apps split responsibilities like this:

- **`core/`** — the monolith view layer, plus `UserProfile` (role + theme), `AuditLog`, `Lead`, approval-chain models, permission decorators (`permissions.py`), template context processors, and backup.
- **`customers/`, `properties/`, `bookings/`, `payments/`** — models, forms, serializers, and DRF `api_views.py` (ViewSets). Their own `views.py` are largely unused for the ERP.
- **`expenses/`, `notifications/`** — the only apps with their own `urls.py` and active template views.
- **`api/`** — a single DRF `DefaultRouter` (`api/urls.py`) that registers every app's ViewSet; auth/session endpoints live in `api/views.py`.

### Data model (core business relationships)

```
Project ──< ProjectPhase ──< Plot ──< Booking ──< Payment
                                  │
                                  ├──< InstallmentPlan (1:1) ──< Installment
                                  └──< BookingTransfer / Refund / EarlySettlement
Customer ──< Booking / CustomerLedgerEntry / CustomerNominee / ReceivableAging
```

- **Booking.installment_plan** is a `OneToOneField`; `InstallmentPlan.auto_generate()` creates `Installment` rows on demand.
- **Payments** have a status workflow (`draft → pending → verified / rejected / bounced / reversed`) and `PaymentAllocation` joins payments to installments.
- **Expenses** are project-scoped and standalone (no customer/booking linkage).
- **Booking lifecycle**: `pending → confirmed → ...`, plus `cancelled` (cancel releases the plot to `available`; reopen returns it to `pending` and re-reserves it). Confirming requires `advance_paid > 0`; cancelling is blocked while verified payments exist (refund first). Booking amounts are validated against `Plot.total_cost` (price + development/lease/other charges) and `plot.holding_deposit`.
- **Refunds**: `pending → approved → processed | rejected`; `refundable_amount` = verified payments − non-rejected refunds. Processing posts exactly one ledger row (idempotent).
- **Account ledger**: `AccountTransaction` is uniquely constrained on (`reference_type`, `reference_id`); refunds, expenses, and salary payments post via idempotent `update_or_create` keyed on that pair.

### Auto-generated IDs

IDs are generated in `Model.save()` by parsing the last record's numeric suffix (not DB sequences). Prefixed formats: `CUS-00001` (Customer), `BKG-00001` (Booking), `PAY-00001` (Payment), `GRP-00001` (BookingGroup), `RCP-00001` (Receipt). Receipts also get a fiscal-year `receipt_number` like `RCP-FY25-26/00001` (July–June fiscal year).

### Role-based access control

Roles: `super_admin`, `admin`, `management`, `accounts`, `sales` (defined in `core/models.py` `UserProfile.ROLE_CHOICES`).

- Decorators in `core/permissions.py`: `role_required`, `super_admin_required`, `admin_or_above`, `management_or_above`, `finance_or_above`, `payments_access`. They redirect to `/dashboard/` with a message on denial.
- `core/context_processors.py` (`erp_context`) injects per-role flags (`can_view_payments`, `can_manage_users`, `can_delete`, etc.) into every template for role-aware UI.
- DRF equivalents (`IsAdminOrReadOnly`, `IsSuperAdmin`, `IsStaffOrAbove`) live in `core/api_views.py`.
- A superuser is always treated as `super_admin` regardless of profile.

### Revenue semantics

**Revenue = the sum of `Booking.advance_paid` across all bookings** — the single source of truth. `advance_paid` is what makes a booking "revenue", not the `Payment` rows. This is a deliberate design decision (see `dashboard_view` in `core/views.py`); don't reintroduce `Payment`-based totals for headline revenue.

### PDFs

Generated from Django templates via **xhtml2pdf** (`pisa`) in `payments/pdf_utils.py` (`render_to_pdf`, `generate_receipt_pdf`, `generate_invoice_pdf`, `generate_customer_profile_pdf`). `payments/utils.py` has `amount_in_words()` using Pakistani numbering (Crore/Lakh). Receipts/invoices/customer profiles each have dedicated `*.pdf.html` templates.

### Notifications

`notifications/services.py` provides `EmailService`, `SMSService`, `WhatsAppService`, and a `NotificationService` facade that logs every send to `NotificationLog` (with `provider_message_id` for SMS).

`notifications/wa_templates.py` + `notifications/wa_templates.json` are the spec and compiler
for the six WhatsApp templates; `manage.py create_wa_templates` / `check_wa_templates` provision
and audit them. See Work status above.

- **Email** — uses SMTP (Brevo relay) when `EMAIL_HOST` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` are set, otherwise Django's console backend. Gated by `EMAIL_ENABLED`.
- **SMS** - real SendPK HTTP API integration (not a stub): `send()` posts the legacy free-text form, while `send_typed()` posts an approved fixed-sms template (`template_id` + a JSON message mapping `#slots#` to caller params) with strict variable validation. Both normalize Pakistani numbers to `92XXXXXXXXXX`, store the returned message id, and expose `check_delivery()` / `check_balance()`. Env: `SENDPK_ENABLED`, `SENDPK_API_KEY`, `SENDPK_SENDER_ID`, `SENDPK_BASE_URL`, `SENDPK_TEMPLATE_*` (10901-10904). Enabled in the local `.env`; forced off under `manage.py test` by the `TESTING` guard in `settings.py`.
- **WhatsApp** — real WhatsApp Business Cloud API integration (not a stub): posts to `graph.facebook.com/v25.0/{phone_id}/messages`, gated by `WHATSAPP_ENABLED`. Env: `WHATSAPP_API_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_API_VERSION`. Falls back to a `wa.me` click-to-chat URL when disabled. Verified live 2026-10: HTTP 200 `accepted`, template delivered from `+92 320 6229330`.
  Transactional notifications go out as **Meta-approved templates** via `WhatsAppService.send_typed()` — free-form text is rejected outside the 24h customer service window (error 131047), so all five `services.py` triggers plus `booking_confirm_view` pass `template_params` to `NotificationService.send_notification()`. The six template bodies are specified in `notifications/wa_templates.json`; each is enabled by its own `WHATSAPP_TEMPLATE_*` setting, and a blank value fails that notification with a log message naming the setting. Staff free-form sends (the notifications view) stay on `WhatsAppService.send()` and are warned about the 24h rule in the UI. Graph error bodies are parsed and translated (`WhatsAppService.ERROR_HINTS`) instead of collapsing into a bare HTTP status, and the returned `wamid` is stored in `provider_message_id` for delivery tracking.
- Triggers: payment confirmation, booking notification, installment reminder, overdue alert, receipt notification, and customer welcome (fires on customer create via UI + API and on lead conversion; failure-safe so a broken email can never break the customer transaction).

### Backup / restore

`core/backup.py` serializes each DB table to CSV and bundles media into a zip. Restore is exposed via `core/views.py` (`backup_restore_latest_view`, `backup_restore_upload_view`) and gated by `admin_or_above`.

### Corporate website & React

The public site is a Django template (`templates/corporate/home.html` extending `corporate_base.html`); its forms POST to `lead_submit` which creates `core.Lead` rows. `frontend/dist/` is a compiled Vite React build (`index.html` + hashed assets) with **no `src/` or `package.json` in the repo** — the React source lives outside this checkout, so treat `frontend/dist/` as a generated artifact. `docs/superpowers/specs/2026-07-24-react-frontend-design.md` documents the intended SPA design.

## Notes & gotchas

- `requirements.txt` is **UTF-16 encoded** (a BOM + wide chars); open it carefully — normal UTF-8 tooling may garble it. Key deps: `Django==6.0.7`, `djangorestframework`, `psycopg2-binary`, `django-cors-headers`, `xhtml2pdf`, `requests`.
- `AGENTS.md` and `docs/superpowers/` hold planning/spec artifacts (spec-driven development); `README.md` has module and API-endpoint tables. `opencode.json` enables the `superpowers` plugin.
- Templates live in `templates/` with the ERP base as `base.html` / `base_form.html` and the corporate base as `corporate_base.html`. Theme CSS files (`theme-*.css`) correspond to `UserProfile.THEME_CHOICES`.
- Static files (hand-written) live in `static/` (`css/`, `js/`); the React build outputs to `static/assets/`.
