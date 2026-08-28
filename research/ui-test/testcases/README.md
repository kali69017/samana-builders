# Samana ERP — Playwright MCP UI Test Suite

Runnable UI test cases executed in a **headed Chromium** browser through
Microsoft's Playwright MCP server (`@playwright/mcp`). Every case drives the
real Django ERP at `http://127.0.0.1:8000` via `browser_run_code_unsafe` and
asserts on live DOM state.

## Test cases

| ID | File | Covers |
|----|------|--------|
| TC-01 | `tc01_corporate_site.py` | Public corporate home: hero, nav, lead form |
| TC-02 | `tc02_login_logout.py` | Login form, valid login → dashboard, invalid creds error, logout |
| TC-03 | `tc03_dashboard.py` | Dashboard KPIs, charts, sidebar |
| TC-04 | `tc04_customer_form_validation.py` | Customer create form validation (empty + invalid data) |
| TC-05 | `tc05_booking_create_form.py` | Booking form: customers/plots/templates dropdowns |
| TC-06 | `tc06_ai_pages.py` | AI Assistant chat UI, AI Insights, AI HR controls |
| TC-07 | `tc07_module_pages_audit.py` | Full 35-page module audit (title, content, no redirects/errors) |
| TC-08 | `tc08_evidence_screenshots.py` | Captures page screenshots to `../screenshots/` |

## How to run

```bash
# 1. Start the ERP
cd /d/ERP/samana
source .venv312/Scripts/activate && unset PYTHONPATH
python manage.py runserver 127.0.0.1:8000 --noreload

# 2. Start Playwright MCP (headed browser; block external CDNs for speed)
npx @playwright/mcp --port 8931 --snapshot-mode none --allowed-hosts "*" \
  --allowed-origins "*" \
  --blocked-origins "https://fonts.googleapis.com,https://fonts.gstatic.com,https://cdn.jsdelivr.net,https://www.googletagmanager.com,https://images.unsplash.com,https://www.openstreetmap.org"

# 3. Run the suite (or a single case)
python research/ui-test/testcases/run_all.py
python research/ui-test/testcases/tc01_corporate_site.py
```

## Transport notes (learned the hard way)

- The MCP server is **streamable HTTP** at `http://localhost:8931/mcp` (not `/sse`).
  Initialize once per process, keep the `Mcp-Session-Id` header.
- **Sessions die after ~4 tool calls** — each test case opens one fresh session.
- **`browser_run_code_unsafe` has a ~5 s server-side cap** — keep each code block
  short; long waits (e.g. DeepSeek replies > 5 s) must be asserted elsewhere.
- **`--snapshot-mode none` is required** — full snapshots hang on pages with
  external iframes (OpenStreetMap embed on the corporate home).
- **`--isolated` destabilizes the browser** between sessions — do not use it
  for this suite. Do kill leftover `chrome.exe` between full suite runs.
- Never call `form.submit()` via `page.evaluate` — navigation inside an
  evaluate kills the MCP session. Use `page.click` on the submit button.

## Artifacts

- `../screenshots/*.png` — visual evidence from TC-08
- `../ui_audit_results.json` — machine-readable 35-page audit (TC-07 output)
- `../report.md` — human-readable QA report
