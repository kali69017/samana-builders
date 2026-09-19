# Samana Builders - Real Estate Management ERP

Django 6.0.7 ERP + corporate website (SQLite dev / PostgreSQL prod). **`CLAUDE.md` at the repo root is the canonical, latest context — read it first.** This file only lists what an agent is likely to miss.

## Environment (Windows)

- Working venv: **`D:\samana\.venv312\Scripts\python.exe`** (Python 3.12, shared). The in-repo `.venv312` is an INCOMPLETE copy (no pydantic/langchain — AI-backed tests fail under it). The README's `venv` path is stale.
- Always run Python with `PYTHONPATH` unset (`env -u PYTHONPATH` in bash; clear it in PowerShell). A stray `PYTHONPATH` from surrounding tooling shadows venv packages and breaks imports.
- `.env` (gitignored) configures everything — `settings.py` loads it via python-dotenv. Dev = SQLite `db.sqlite3`; prod = Postgres via `DB_ENGINE=postgres`.

## Commands

```powershell
# Dev server — MUST set DJANGO_DEBUG=True or SECURE_SSL_REDIRECT 301s every request
$env:DJANGO_DEBUG='True'
D:\samana\.venv312\Scripts\python.exe manage.py runserver

# Django tests — ALWAYS prefix DJANGO_DEBUG=True, else the whole suite mass-fails
# with 301 redirects. Full suite: 663 tests, ~9 min.
$env:DJANGO_DEBUG='True'
D:\samana\.venv312\Scripts\python.exe manage.py test
D:\samana\.venv312\Scripts\python.exe manage.py test payments.tests.PaymentModelTest.test_payment_id_generation

# Migrations / shell / superuser
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

Default login: `admin` / `admin123`. Login `/login/`; staff land on `/dashboard/`, customers on `/portal/`.

## Playwright E2E

- Config: `playwright.config.ts`; **full runbook: `RUNBOOK.md`**; conventions: `tests/CONVENTIONS.md`; healing patterns: `tests/HEALING.md`.
- Needs the dev server up at `http://127.0.0.1:8000` with `DJANGO_DEBUG=True`, plus idempotent role seeding: `python tests/fixtures/seed_roles.py` (shared venv).
- Uses system Chrome (`channel: 'chrome'`); the Playwright CDN is blocked so `npx playwright install` times out — never run it.
- `npx playwright test` (full suite), `npx playwright test tests/core` (one module), `npm run report` (HTML report), `npx playwright test --project=setup` (regenerate `tests/.auth/*.json` only).
- Some suites intentionally keep failing tests for confirmed bugs (`// CONFIRMED BUG` → `docs/qa/findings-confirmed.md`). Do NOT weaken those assertions to make them green.
- Page specs should log in fresh via `loginViaApi(page.request, role)` in `beforeEach` — `storageState` cookies go stale (`tests/HEALING.md` Pattern 6).

## Architecture (full detail in CLAUDE.md)

- **`core/views.py` is the hub**: `samana_erp/urls.py` routes nearly every ERP page (customers, bookings, payments, receipts, PDFs, portal, backup) to functions there, not in each app's `views.py`. Check `core/` first when an ERP page misbehaves.
- Domain apps (`customers/`, `properties/`, `bookings/`, `payments/`) hold models/forms/serializers and DRF ViewSets in `api_views.py`; `api/urls.py` registers everything on one `DefaultRouter`.
- **Revenue = sum of `Booking.advance_paid`** (NOT `Payment` rows) — deliberate design. Don't reintroduce Payment-based headline revenue.
- Auto-generated IDs (`CUS-00001`, `BKG-…`, `PAY-…`, `GRP-…`, `RCP-…`) created in `Model.save()` by parsing the last record's suffix; receipts also get fiscal-year numbers like `RCP-FY25-26/00001`.
- Roles via `core/permissions.py` decorators + `core/context_processors.py` `erp_context`; a superuser always counts as `super_admin`.
- PDFs via xhtml2pdf (`payments/pdf_utils.py`); amounts-in-words use Pakistani Crore/Lakh (`payments/utils.py`).
- Payment workflow `draft → pending → verified/rejected/bounced/reversed`; ledger rows are de-duped by a unique (`reference_type`, `reference_id`) pair.
- `frontend/dist/` is a compiled Vite build with **no React source in-repo** — treat as generated artifact; the corporate site is Django templates.

## Gotchas

- `requirements.txt` is **UTF-16 encoded** — ordinary UTF-8 tooling garbles it.
- SMS (SendPK), Email (Brevo), WhatsApp, and AI (DeepSeek) are all disabled in local `.env` (`*_ENABLED=False`). Tests assert shape / disabled-provider contract only, never live sends or LLM prose.
- SMS sender "SAMANA" needs PTA-approved branded mask; `SENDPK_SENDER_ID` is currently "SMS Alert" (`settings.py`).
- `docs/` and `specs/` hold planning/QA artifacts; `CLAUDE.md` "Work status" is the source of truth for what shipped.