# QA Project Context - Samana Builders ERP + Landing Page

## Product

- **Name:** Samana Builders & Developers ERP + corporate landing page
- **What it does (one line):** A Django/Django REST Framework real-estate ERP for a Pakistani builder (customers, properties/plots, bookings, payments, installments, refunds, expenses, finance, HR/payroll, AI assistant/insights), plus a public marketing landing page.
- **Type:** Internal SaaS-style ERP tool + public marketing site.
- **URLs (dev):**
  - ERP: `http://127.0.0.1:8000` (login `/login/`, dashboard `/dashboard/`)
  - Landing page: `http://127.0.0.1:8000/` (corporate home, public, no auth)
  - Customer portal: `/portal/` (React, non-staff customers)
- **Critical user journeys (if this breaks, business stops):**
  1. User logs in and sees the dashboard (correct revenue/defaulter metrics).
  2. Create a customer; view customer detail (CNIC, bookings).
  3. Create a booking for a plot; confirm it; the plot becomes booked.
  4. Record and verify a payment -> receipt generated, advance_paid/balance updated, installment plan recalculated.
  5. Approve/reject a refund -> booking balance adjusts.
  6. Run payroll: generate slips from salary components, process, mark paid (posts to ledger).
  7. Mark bulk attendance for all employees (Present/Absent/Leave).
  8. Use the AI assistant + generate AI insights (revenue/collections/inventory/HR).
  9. Mark attendance, apply for leave (employee self-service portal).
  10. Landing page loads with hero, projects, our office map, and contact footer.

## Tech Stack

- **Frontend framework/language:** Django templates (server-rendered) + custom JS (`static/js/erp.js`), Chart.js; React customer portal (`/portal/`).
- **Backend framework/language:** Python 3.12, Django 6.0.7, Django REST Framework 3.17.1.
- **API style:** REST (DRF) at `/api/...` (customers, bookings, payments, plans, AI assistant/insights/language).
- **Database/ORM:** SQLite (`db.sqlite3`) via Django ORM; migrations per app.
- **Hosting/Docker:** `Dockerfile`, `docker-compose.yml` (web + Caddy reverse proxy), `Caddyfile`.
- **Email:** Brevo SMTP relay (`smtp-relay.brevo.com:587`) via `django.core.mail` / `notifications/services.py` `EmailService`.
- **AI:** LangChain + DeepSeek (`deepseek-chat`), DEEPSEEK_API_KEY in `.env`.

## Test Stack

### E2E / Integration
- **Framework:** None selected yet. Django test suite used for unit/integration (654 passing).
  - Default recommendation: Playwright (see playwright-automation). Agentic browser testing via Playwright MCP on port 8931 used for exploratory/smoke.
- **Config Location:** n/a (no Playwright config committed).
- **Test Directory:** Django tests live under `api/tests*.py`, plus per-app `*/tests.py`.

### Unit / Component
- **Framework:** Django TestCase / django.test.Client + DRF APIClient.
- **Directory:** `api/tests.py`, `api/tests_flaw_fixes.py`, `api/tests_audit_*.py`, `api/tests_password_reset.py`, `*/tests.py`.

### API
- **Framework:** DRF APIClient in Django tests. OpenAPI/schema not exported.

## CI/CD

- **Platform:** None active (git push to GitHub remote `kali69017/samana-builders`; `docker-compose` for deploy).
- **When tests run:** Manually via `python manage.py test` (654 tests, ~6 min).
- **What gates deploy:** Not wired; suite run manually before pushing.

## Environments

- Dev: local `runserver` on `127.0.0.1:8000`, SQLite `db.sqlite3`, DEBUG variably on.
- Prod intent: docker-compose (web + Caddy). No separate staging.
- Email: Brevo configured live; SMS SendPK; DeepSeek AI live.
- Seed/reset: `core/management/commands/seed_data.py`, `reset_demo.py`; live dev DB has real + demo data (64 customers etc.).

## Quality Goals

- Django unit/integration suite: no failing tests on `main` (currently 654 green). Target: keep 100% green.
- No E2E suite yet. Target: agentic browser smoke of top-10 critical journeys passes; graduate stable paths to Playwright scripts.
- Email flows (password reset) verified live end-to-end.
- Flake tolerance: agentic runs must be deterministic via explicit success oracle + negative check (no "looks good").

## Risk Areas

| Area | Risk Level | Business Impact | Notes |
|------|-----------|-----------------|-------|
| Payment verify/receipt/refund money flow | Critical | Financial correctness; balance/ledger | Payments, installments, refunds adjust advance_paid; highest test coverage needed |
| Installment plan recalculation | Critical | Money owed; auto-recalc on payment | `InstallmentPlan.recalculate()` wired into 6 paths |
| AI assistant/insights (DeepSeek) | Important | Revenue/collections/inventory answers | Nondeterministic; needs oracle on shape not exact text |
| Auth + password reset (Brevo email) | Important | Account security | Brute-force guard; email code flow verified live |
| HR self-service (employee leave/attendance) | Monitor | Staff productivity | Employee login redirects to My Leave; hiding admin nav |
| Landing page (public) | Backlog | Marketing presence | Map embed (Google), footer contact verified |

## Team

- **Headcount / dev:QA ratio:** Solo developer + AI agent effectively (infinite dev:QA). No dedicated QA engineer; strategy + critical-path testing owned by the agent.
- **Methodology:** No formal sprint; autonomous fixes + manual verification by the user in the browser.

## Conventions

- **Test framework:** Django `manage.py test`; ad-hoc `hermes-verify-*.py` scripts in `%TEMP%` (deleted after), run with real-path venv python `D:\samana\.venv312\Scripts\python.exe`, `env -u PYTHONPATH`.
- **Selector strategy:** Server-rendered templates use role/accessible-name based interaction via Playwright MCP `browser_snapshot` (accessibility tree). No `data-testid` convention; templates use form-control, floating-group classes.
- **Test data:** Live dev SQLite with seeded/demo data; backups `db.sqlite3.bak-*` gitignored.
- **Branching/PR:** All work committed directly to `main`; `.env` gitignored (secrets never committed).
- **Verification pattern:** idempotent probe users (create/use/delete), self-cleaning; backup DB before live mutations.