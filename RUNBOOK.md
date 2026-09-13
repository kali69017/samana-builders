# Samana ERP — Playwright E2E Runbook

How to run the browser test suite from a clean shell. Everything is project-local
(`D:\ERP\samana`); the target is the local Django dev server only (no prod/staging).

> **Key docs:** confirmed bugs → `docs/qa/findings-confirmed.md`; merged prioritized fix list →
> `docs/qa/remediation-plan.md`; test-harness fix patterns → `tests/HEALING.md`.
> (`tests/repro/evidence.md` is superseded by `findings-confirmed.md`.)

## 1. Prerequisites (one-time)

- Python 3.12 venv with deps: `D:\samana\.venv312` (the shared venv; the in-repo `.venv312`
  is incomplete). Node + Playwright already installed via `package.json` (`@playwright/test`,
  `@playwright/mcp`). Tests use the system Google Chrome (`channel: 'chrome'`) — no browser
  download needed.

## 2. Start the dev server

```powershell
# From repo root, in PowerShell
$env:DJANGO_DEBUG='True'
D:\samana\.venv312\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

`DJANGO_DEBUG=True` is required: otherwise `SECURE_SSL_REDIRECT` 301-redirects plain-HTTP
requests. The server must be reachable at `http://127.0.0.1:8000/login/`.

## 3. Seed the role users + portal customer (idempotent)

```powershell
$env:DJANGO_DEBUG='True'
D:\samana\.venv312\Scripts\python.exe tests\fixtures\seed_roles.py
```

Creates (password `admin123` for all): `admin` (existing superuser), `qa_management`,
`qa_accounts`, `qa_sales`, `qa_hr`, and `qa_customer` (a non-staff portal customer linked to a
`Customer`, with no `UserProfile`). Re-running is safe.

## 4. Run the tests

```powershell
npx playwright test                 # full suite (auto-runs the auth setup project first)
npx playwright test tests/core      # one module
npx playwright test tests/api       # one module
npx playwright test --project=setup # regenerate auth storageState only
```

Storage state is generated into `tests/.auth/*.json` (gitignored) by the `setup` project and
reused by authenticated suites, so no manual login is required.

## 5. View the report

```powershell
npm run report        # opens the HTML report (playwright-report/)
```

`playwright.config.ts` also enables `trace: 'on-first-retry'` and `screenshot: 'only-on-failure'`.

## 6. Notes

- **Real bugs stay RED.** Several suites intentionally contain failing tests that assert correct
  behavior for confirmed defects (see `docs/qa/findings-confirmed.md`). Those red tests are the
  bug documentation, not flake — do not "fix" them by weakening assertions.
- **AI / notifications** assert shape and the disabled-provider contract only (AI_ENABLED and
  SENDPK/EMAIL are off locally), never exact LLM prose or live sends.
- Test data is unique/timestamped and cleaned up; no table is wiped.
