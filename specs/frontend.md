# Frontend Layer — Test Plan

> Samana Builders ERP — templates + static JS/CSS + form rendering + cross-cutting UI risks.
> Source of truth for risk analysis: `docs/qa/frontend_analysis.md` and `docs/qa/_shared-context.md`.
> Scenario ID prefix `FE`. Categories: `HP` (happy path), `EC` (edge/boundary), `SEC` (negative & security), `A11Y` (accessibility / WCAG 2.2).

## 1. Scope & roles

This plan covers the **server-rendered frontend**: the ERP shell (`templates/base.html` + `includes/sidebar.html`), the generic form renderer (`base_form.html`) and its per-entity re-implementations, the public corporate site (`corporate_base.html` + `corporate/home.html`), the two hand-written JS files (`static/js/erp.js` — loaded; `static/js/main.js` — orphaned), and the cross-cutting UI concerns: money rendering, XSS sinks, CSRF, double-submit, and accessibility.

The frontend is **100% Django templates** — there is no live SPA. The compiled React build (`frontend/dist/`) is not referenced by any template. The customer portal (`/portal/`) is the Django template `templates/portal/dashboard.html`, not React.

Roles that exercise the surface:
- **Anonymous visitor** — corporate home, lead form, login page (HP).
- **staff (`sales`)** — dashboard, lists, create/edit forms, AI pages (denied on payments/finance nav — see HP-04).
- **staff (`accounts`)** — payments / refunds / ledger / financial reports, AI pages.
- **customer login** — `/portal/` (own bookings/installments/payments).
- **`super_admin`** — user management, backup, company settings (full sidebar).

Role-denied paths (assert the nav item is absent *and* the view redirects to `/dashboard/`): a `sales` user must not see Payments/Finance/Expenses/Reports/Manage Users; a `sales` user must not see the notification bell.

## 2. Preconditions & fixtures

**Environment (from CLAUDE.md / shared-context):**
- Run with `DJANGO_DEBUG=True` (else `SECURE_SSL_REDIRECT` 301s every request).
- Dev server `http://127.0.0.1:8000`. Login `admin` / `admin123`.
- Staff land on `/dashboard/`; customers land on `/portal/`.

**Seed data (create cleanly, timestamped unique values to avoid ID collisions):**
- `CUS-XSS` — a customer whose **name** contains `<img src=x onerror=window.__xss=1>` and one agent/lead note containing the same payload (for SEC-01 / SEC-08). Use `window.__xss=1` (not `alert`) so success is observable non-interactively.
- `BKG-PAISA` — a booking with `total_amount = 1500000.50` and `advance_paid = 1500000.50` (non-zero paisa) to compare precision across pages.
- `LEAD-PAISA` / normal leads for the corporate form submit test.
- Roles: `accounts` profile, `sales` profile, and a customer login (for HP-04 / HP-08 / portal assertions).
- A payment with a file attachment (for payment_form upload-zone checks, SEC-09).

**AI pages** require `AI_ENABLED=True` + `DEEPSEEK_API_KEY`, or (preferred, deterministic) **stub the fetch response** in DevTools / Playwright route so `/api/ai/insights/` returns `{ok:true, result:"<img src=x onerror=window.__xss=1>"}` and `/api/ai/hr/assistant/` returns `{ok:true, result:"safe text"}`. Stubbing removes the LLM non-determinism from the XSS repros.

**URLs exercised** (relative to `http://127.0.0.1:8000`):
`/login/`, `/dashboard/`, `/`, `/customers/`, `/customers/new/`, `/properties/`, `/bookings/`, `/bookings/new/`, `/payments/`, `/refunds/`, `/financial-reports/`, `/ai/insights/`, `/ai/hr/`, `/ai/assistant/`, `/hr/leaves/`, `/portal/`, corporate `/` home (public).

## 3. Scenario catalog

### HP — happy path

**FE-HP-01 — Login page renders**
- **Preconditions:** Anonymous; dev server up with `DJANGO_DEBUG=True`.
- **Steps:** GET `/login/`. Inspect DOM.
- **Expected result:** Page returns 200. Form is `POST` to `/login/` with `{% csrf_token %}`; username and password inputs each have a `for`-associated `<label>` and `autocomplete` attributes; "Forgot Password?" link present; no JS console errors.
- **Evidence on failure:** Screenshot + rendered HTML showing missing labels/CSRF; browser console for JS errors.

**FE-HP-02 — Login submits and lands on the right home**
- **Preconditions:** A staff account (`admin`/`admin123`) and a customer account exist.
- **Steps:** Submit `admin`/`admin123` at `/login/`. Then, separately, log in as the customer.
- **Expected result:** Staff land on `/dashboard/`; customer lands on `/portal/`. Invalid credentials re-render `/login/` with the "Invalid username or password" alert and do NOT redirect.
- **Evidence on failure:** Final URL after submit; screenshot of post-login page.

**FE-HP-03 — ERP base layout + sidebar nav render for staff**
- **Preconditions:** Logged in as `admin`.
- **Steps:** Load `/dashboard/`. Verify shell (topbar + sidebar + `.main-content`), then click through sidebar links (Dashboard, Customers, Properties, Bookings, Payments, etc.).
- **Expected result:** Every sidebar link resolves to its page (no 404); active nav item highlights; `erp.js` loads (versioned `?v=2`); Chart.js 4.4.7 loads from CDN; no console errors.
- **Evidence on failure:** Screenshot of broken layout; network/console log of failed asset or 404.

**FE-HP-04 — Sidebar role gating matches server flags**
- **Preconditions:** Two profiles — `accounts` and `sales`.
- **Steps:** Log in as `sales`; note sidebar. Log in as `accounts`; note sidebar.
- **Expected result:** `sales` sees **no** Payments/Finance/Expenses/Reports/Manage Users/notification bell; `accounts` sees Payments/Refunds/Ledger/Reports but **no** Manage Users/DB Backup. Hitting a hidden URL directly (e.g. `/payments/` as `sales`) redirects to `/dashboard/` with an error message.
- **Evidence on failure:** Sidebar screenshot per role; HTTP status/location of the direct URL attempt.

**FE-HP-05 — Corporate home renders (hero, projects, lead form, contact)**
- **Preconditions:** Anonymous. GET `/`.
- **Steps:** Load the public home; scroll hero → about → projects → testimonials → location → contact.
- **Expected result:** Hero title/badge render; three project cards with images+`alt`; testimonials; Google Maps `iframe` with a `title`; the contact/lead form (id `#contact`) renders name/email/phone/interest/message + "Send Message" button. No console errors.
- **Evidence on failure:** Full-page screenshot; missing-section note; console log.

**FE-HP-06 — Corporate lead form submits → creates a Lead**
- **Preconditions:** Anonymous; a `sales`-capable CRM exists.
- **Steps:** Fill the `#contact` form with a timestamped unique name/email/phone and submit.
- **Expected result:** POST to `lead_submit` succeeds; a `core.Lead` row is created (`lead_type="strip"`); a success message is shown. No 403 (CSRF token present).
- **Evidence on failure:** Network tab (status/body of POST); DB check for the Lead; screenshot of error.

**FE-HP-07 — Money renders consistently within a single page**
- **Preconditions:** Logged in as `accounts`; `BKG-PAISA` and at least one project/expense exist.
- **Steps:** Load `/financial-reports/`. Compare the stat cards (`Rs. {{ x|floatformat:0|intcomma }}`) and the project table rows.
- **Expected result:** Within this page every `Rs.` amount uses the same pattern: thousands separators + `Rs.` prefix + whole-PKR (no paisa). No mixed `1,500,000` vs `1500000` vs `1.500.000` on the same page.
- **Evidence on failure:** Screenshot of the stats grid + table; note any cell that diverges.

**FE-HP-08 — `/portal/` is the Django template, not the orphaned React build**
- **Preconditions:** Customer login.
- **Steps:** GET `/portal/`. Inspect `<html>`/rendered markup and the scripts loaded.
- **Expected result:** Page is `templates/portal/dashboard.html` extending `base.html` (contains `.portal-wrap`, `.welcome-card`, the Django topbar/sidebar shell). **No** React mount (`frontend/dist/index.html`, `assets/index-*.js`, or `#root`) is referenced. `erp.js` is the loaded JS.
- **Evidence on failure:** Rendered `<script src=…>` list; view-source showing a React bundle reference.

### EC — edge case / boundary

**FE-EC-01 — Money formatting fragmentation across pages (floatformat:0 vs intcomma vs toLocaleString)**
- **Preconditions:** `BKG-PAISA` exists; logged in as `accounts`.
- **Steps:** Render the same booking's amount on: (a) `properties.html` (uses the custom `money` filter, `property_tags.py`), (b) `financial_reports.html` (`floatformat:0|intcomma`), (c) `receipt_detail.html` (`floatformat:0`), (d) a list table using bare `Rs. {{ value }}`, (e) a JS counter (`toLocaleString`).
- **Expected result:** Documented inconsistency. The **same amount** appears differently — with/without separators, with/without `Rs.` — depending on page. Test asserts each page's actual format is recorded and compared; this scenario is the baseline that EC-02/EC-03 quantify.
- **Evidence on failure:** A side-by-side table of the same amount's rendered string per page.

**FE-EC-02 — Paisa precision dropped silently**
- **Preconditions:** `BKG-PAISA` = `1,500,000.50`.
- **Steps:** View the booking in list, detail, receipt, and PDF.
- **Expected result:** Every `floatformat:0` / `money` (default `decimals=0`) display rounds to `1,500,000`, dropping `.50`. The DB stores 2 decimals. Test records exactly where paisa is lost and flags it as a silent-rounding defect (no half-up policy stated).
- **Evidence on failure:** Screenshots of list/detail/receipt/PDF showing the rounded value vs the DB value.

**FE-EC-03 — JS `toLocaleString()` grouping follows browser locale (de-DE test)**
- **Preconditions:** `BKG-PAISA`; a browser forced to `de-DE` locale (DevTools → Sensors/Locale, or `--lang=de-DE`).
- **Steps:** Load `/dashboard/` (counter) and `/payments/`/`payment_form` summary which use `Number(x).toLocaleString()` with **no** locale.
- **Expected result:** Amounts render with German grouping (e.g. `1.500.000,5`) while `erp.js formatCurrency` uses `'en-IN'` (`15,00,000`) — grouping is inconsistent *inside the same product*. Test records both and flags the mismatch.
- **Evidence on failure:** Screenshot under `de-DE` showing the divergent grouping.

**FE-EC-04 — `hr/leaves.html` approve/reject action forms are correctly wired**
- **Preconditions:** Logged in as `admin` (`can_manage_hr`); at least one `pending` leave request.
- **Steps:** On `/hr/leaves/`, inspect the two inline POST forms per pending row (lines 48–55). Click **Approve** on one, **Reject** on another.
- **Expected result:** The two forms are **distinct**: form 1 posts `action=approve`, form 2 posts `action=reject`, both to `hr_leave_approve`. Approve sets status `approved`; Reject sets `rejected`. They must NOT both submit `approve` (copy-paste regression) and must not cross-wire buttons to the opposite action.
- **Evidence on failure:** DOM of the two forms (hidden `action` value + button label); final leave statuses in DB.

**FE-EC-05 — No client-side double-submit disable (spinner but button stays enabled)**
- **Preconditions:** Logged in as `admin`; an entity create page (e.g. `/customers/new/`).
- **Steps:** In `erp.js:171-185`, confirm the submit handler only adds `.loading` + spinner and never sets `disabled`. Then rapidly double-click the submit button.
- **Expected result:** Current behavior: **two POSTs fire** (button not disabled). Expected-fix behavior: button is disabled in the handler and re-enabled on failure. Test asserts the actual behavior and records the defect; for money actions the backend ledger de-dup (`reference_type`+`reference_id`) is the only mitigation.
- **Evidence on failure:** Network tab showing two POST requests; DB showing a duplicate row (create path).

**FE-EC-06 — `novalidate` disables browser validation (whitespace-only required field passes client, fails server)**
- **Preconditions:** Logged in; a form rendered with `novalidate` (e.g. `base_form.html`, `login.html`).
- **Steps:** Submit a required text field containing only spaces (e.g. customer name = `"   "`).
- **Expected result:** No browser "Please fill out this field" (because `novalidate`). Server-side Django validation rejects with a field error. Test asserts the error renders and no DB row is created.
- **Evidence on failure:** Screenshot of the server error vs no client prompt; DB row count.

**FE-EC-07 — Floating-label state on whitespace-only value**
- **Preconditions:** Logged in; a `floating-group` input.
- **Steps:** Type three spaces into the field; blur.
- **Expected result:** `erp.js syncFloatingLabels` keys off `value.trim() !== ''`, so the label stays **down** ("filled") while a server `required` check would reject it — a label-state inconsistency. Test records the mismatch.
- **Evidence on failure:** Screenshot of the label position after whitespace input.

**FE-EC-08 — Stale session: fetch/XHR leaves a hung spinner (no 401/403 handling)**
- **Preconditions:** Logged in on an AI page or payment form; session expired server-side (or delete the session cookie).
- **Steps:** Trigger an AI generate / payment-summary fetch after expiry.
- **Expected result:** Current behavior: the 302/401/403 is not handled — spinner keeps spinning or an uncaught promise logs an error. Expected-fix: detect 401/403 and redirect to `/login/`. Test asserts current behavior and flags it.
- **Evidence on failure:** Screenshot of stuck spinner; console error / network 302.

**FE-EC-09 — Print CSS hides entry/confirm forms**
- **Preconditions:** Logged in; a page with a form (or `/login/`).
- **Steps:** Trigger print preview (`window.print()` or Ctrl+P) on `/login/` and on a list page with inline action forms.
- **Expected result:** `erp.css`/`style.css` `@media print { form { display:none } }` hides the login/entry forms and action buttons. List tables print fine. Test records that `#toastContainer`/messages are **not** hidden (minor noise).
- **Evidence on failure:** Print-preview screenshot showing a missing form or stray toasts.

### SEC — negative & security (XSS sinks prioritized)

**FE-SEC-01 — [HIGH] Stored XSS via AI insights preview (`ai/insights.html`)**
- **Preconditions:** Logged in as staff; `CUS-XSS` exists (name/note contains `<img src=x onerror=window.__xss=1>`); stub `/api/ai/insights/` to return `{ok:true, result:"<img src=x onerror=window.__xss=1>"}` (or run against a live LLM that echoes the planted field).
- **Steps:** Open `/ai/insights/`, click "⚡ Generate Insights". Inspect the prepended history item (`.history-item`) that `erp.js`/inline script built at `insights.html:256-261`.
- **Expected result:** `item.innerHTML` interpolates `preview` (the raw AI result) **unescaped**. The `<img onerror>` becomes a **live DOM element** and `window.__xss` is set to `1` — arbitrary script in the staff session. (Note: the full result goes into `box` via `textContent` — safe — but the `preview` path is the sink. `data-response` only escapes `"`, line 254.)
- **Evidence on failure:** `window.__xss === 1`; an `<img>` element present in `#historyList` (not text); screenshot of the injected node.

**FE-SEC-02 — Partial-escape XSS in AI HR chat echo (`ai/hr.html`)**
- **Preconditions:** Logged in as staff; `/ai/hr/` reachable.
- **Steps:** In the HR chat, submit the entity-encoded payload `&lt;img src=x onerror=window.__xss=1&gt;` (literally those characters).
- **Expected result:** `hr.html:70` does `q.replace(/</g,'&lt;')` — only `<` is escaped; `&`, `>`, `"` are not. Because the user typed `&lt;`, the `&` passes through and the browser **decodes it back to `<`**, injecting a live `<img>` into `#hrChat .msg.user`. `window.__xss` is set to `1`. (Typing a literal `<img…>` is *blocked*, but the entity-encoded form bypasses.)
- **Evidence on failure:** `window.__xss === 1`; an `<img>`/`<svg>` element inside `#hrChat .msg.user`.

**FE-SEC-03 — `financial_reports.html` `|safe` Python-repr chart data**
- **Preconditions:** Logged in as `accounts`; `/financial-reports/` reachable.
- **Steps:** Load the page; inspect `const chartData = {{ monthly_chart_data|safe }};` (line 138) in view-source and the browser console.
- **Expected result:** `monthly_chart_data` is a **Python `repr`** (single-quoted), not JSON: `[{'label': 'Sep 2026', 'amount': 123.0}, …]`. It renders the chart only *by accident*; any label with a `'`/`None`/`True` would be a JS SyntaxError. Test asserts the chart renders today, records the repr form, and flags it as the only `|safe` in the codebase (should be `json_script`).
- **Evidence on failure:** View-source of line 138; console SyntaxError if data ever diverges.

**FE-SEC-04 — `base.html` `window.SAMANA_THEME` unescaped interpolation**
- **Preconditions:** Logged in; page loads `base.html`.
- **Steps:** Inspect `window.SAMANA_THEME = '{{ user_theme|default:"professional-blue" }}';` (line 75) and confirm the theme applies.
- **Expected result:** Safe today because `user_theme` is a `ChoiceField` (no free text). Test asserts: (a) the theme string is a valid choice and `data-theme` is applied with no console error; (b) **source-level**: the interpolation lacks `|escapejs` — any future free-text theme value containing `'` would break out of the JS string. Flag as latent.
- **Evidence on failure:** Console error on theme apply; view-source showing raw interpolation.

**FE-SEC-05 — `erp.js` `showToast` / `showConfirm` build `innerHTML` from the message arg**
- **Preconditions:** Logged in; browser console available.
- **Steps:** From console call `showToast('<img src=x onerror=window.__xss=1>')` and `showConfirm('<img src=x onerror=window.__xss=1>', ()=>{})`.
- **Expected result:** Current behavior: `showToast` (line 224) and `showConfirm` (lines 238-245) interpolate `message` into `innerHTML` unescaped → `window.__xss` set to `1`. Current callers pass fixed/rendered strings, so risk is **latent**, but the helper is generic and unsafe (should use `textContent`/escaping).
- **Evidence on failure:** `window.__xss === 1`; injected `<img>` in the toast/modal.

**FE-SEC-06 — Login `next` open-redirect vector**
- **Preconditions:** Anonymous.
- **Steps:** GET `/login/?next=https://evil.com`, confirm the hidden field `value="{{ next }}"` (line 57) is HTML-escaped; submit valid credentials; observe the redirect target.
- **Expected result:** The `next` value is HTML-escaped (no XSS). After login, the server must redirect only to a safe host via `url_has_allowed_host_and_scheme` — i.e. to `/dashboard/` or the originally requested *internal* path, **never** to `https://evil.com`.
- **Evidence on failure:** Final browser URL after login (assert it is not `https://evil.com`).

**FE-SEC-07 — `main.js` reads a nonexistent `csrf-token` meta (orphaned, harmless)**
- **Preconditions:** Any authenticated page.
- **Steps:** Grep every template for `main.js` (expect 0 references). Inspect `static/js/main.js:466-469` (`document.querySelector('meta[name="csrf-token"]')`).
- **Expected result:** No template loads `main.js`, so the bug is **dead code** today. Assert: (a) no `<script src=…main.js>` in any rendered page; (b) `base.html` defines **no** `<meta name="csrf-token">`; (c) if `main.js` were ever wired in, `ErpAPI.post()` would send no `X-CSRFToken` and 403. Flag as a trap for future wiring.
- **Evidence on failure:** grep output; a manual `ErpAPI.post()` 403 response.

**FE-SEC-08 — List/detail pages render the same XSS payload escaped (positive control)**
- **Preconditions:** `CUS-XSS` (payload in name/note) exists; logged in.
- **Steps:** View `/customers/` list and `/customers/<id>/` detail; view the lead/note where the payload was planted.
- **Expected result:** The payload renders as **escaped text** (`&lt;img src=x onerror=…&gt;`), no `<img>` element, `window.__xss` stays undefined. This is the correct-behavior contrast to FE-SEC-01/02.
- **Evidence on failure:** `window.__xss` set, or an injected DOM node in the list/detail page.

**FE-SEC-09 — `booking_form.html` / `payment_form.html` latent `innerHTML` sinks**
- **Preconditions:** Logged in; booking create and payment create pages open.
- **Steps:** Inspect `booking_form.html` `templateInfo.innerHTML` (fed by `data-info` = `total_installments|frequency|down_payment_percentage`) and `payment_form.html` `planInfo.innerHTML` / method-field builder / upload zone `ondrop="handleDrop(event, this)"` + global `handleDrop`.
- **Expected result:** Currently fed only by server-defined enum/numbers or a **hardcoded** `methodFieldsConfig` → not exploitable today. Test asserts: (a) the rendered markup is correct; (b) the customer/project/plot strings use `|escapejs` (good pattern, `payment_form.html:309-329`); (c) `handleDrop` resolves as a global (only because the inline script isn't wrapped in an IIFE — fragile). Flag both as latent.
- **Evidence on failure:** Console `ReferenceError` for `handleDrop`; malformed `templateInfo`/`planInfo` markup.

**FE-SEC-10 — Every POST form carries `{% csrf_token %}` (regression assertion)**
- **Preconditions:** Whole codebase.
- **Steps:** For each rendered page with a `<form method="post">` (login, base_form, entity forms, inline action forms), assert the CSRF input is present.
- **Expected result:** Every POST form renders `<input type="hidden" name="csrfmiddlewaretoken" …>`. No POST form is missing it (57 occurrences cross-checked against 40 files).
- **Evidence on failure:** The specific page/form missing the token; the resulting 403.

**FE-SEC-11 — Receipt WhatsApp share exfiltrates amount into a third-party link (informational)**
- **Preconditions:** Logged in; a receipt exists.
- **Steps:** Open `receipt_detail.html` and inspect the `wa.me` share URL.
- **Expected result:** The link is Django-escaped (no XSS), but clicking it sends the receipt number + amount to WhatsApp (`https://wa.me/?text=Receipt … Rs. …`). Low risk; document the data-exfiltration surface and confirm it is user-initiated only.
- **Evidence on failure:** The generated `wa.me` URL containing amount text.

### A11Y — accessibility (WCAG 2.2)

**FE-A11Y-01 — Corporate lead form inputs have no `<label>` (placeholder only)**
- **Preconditions:** Anonymous; corporate `/` home.
- **Steps:** Inspect `#contact` form fields (name/email/phone/interest/message, `corporate/home.html:222-243`).
- **Expected result:** Current: each input has `placeholder` and **no `<label>`/`for`** — WCAG 1.3.1 / 3.3.2 violation on the public site (placeholder is not an accessible name and disappears on focus). Test asserts the accessible-name computation returns empty/placeholder-only for each field.
- **Evidence on failure:** Accessibility-tree snapshot (or axe/lighthouse run) listing each unlabeled input.

**FE-A11Y-02 — `base_form.html` select and file labels have no `for`**
- **Preconditions:** Logged in; open a form using `base_form.html` (or `customer_form.html`) that has a `<select>` and/or a file field.
- **Steps:** Inspect the select branch (`:54-58`) and file branch (`:67-76`).
- **Expected result:** Current: those branches render a bare `<label>` with **no `for`** and `{{ field }}` separately, so screen readers do not associate them (text/textarea/checkbox branches do use `for`). Test asserts the `<label>` lacks `for` and the input lacks an accessible name.
- **Evidence on failure:** DOM snippet of the select/file block; axe "label" / "select-name" violation.

**FE-A11Y-03 — Confirm dialogs lack `role="dialog"` / `aria-modal` / focus trap / Escape**
- **Preconditions:** Logged in; trigger any `showConfirm` (e.g. a delete/approve action) or call it from console.
- **Steps:** Open the modal; Tab repeatedly; press Escape; observe focus and screen-reader exposure.
- **Expected result:** Current (`erp.js:235-257`): the modal has **no** `role="dialog"`, no `aria-modal`, focus is not moved into it nor trapped, no `Escape` handler, and the "Confirm Action" heading has no `aria-labelledby` link. Test asserts these attributes are absent and tabbing escapes to the page behind.
- **Evidence on failure:** DOM attributes of `.modal-overlay`/`.modal`; focus order (activeElement) during Tab.

**FE-A11Y-04 — Sortable `<th>` not keyboard-focusable, no `aria-sort`**
- **Preconditions:** Logged in; a `table.sortable` page (e.g. `/financial-reports/`).
- **Steps:** Inspect the sortable headers (`erp.js:123-135`); try to reach and activate them with the keyboard only.
- **Expected result:** Current: `<th>` gets `cursor:pointer` + a click listener and a `↕` icon injected via `innerHTML`, but has **no `tabindex`**, no `role="button"`, no `aria-sort`, and no key handler — keyboard users cannot sort, and sort state isn't announced. Test asserts headers are unreachable via Tab and `aria-sort` is absent.
- **Evidence on failure:** Tab-order trace skipping headers; absence of `aria-sort` after a sort click.

**FE-A11Y-05 — User-menu trigger and theme buttons lack state ARIA**
- **Preconditions:** Logged in; profile page with `.theme-btn` list.
- **Steps:** Inspect the topbar user-menu trigger (`base.html:37`) and theme buttons (`erp.js:10`).
- **Expected result:** Current: the user-menu `<button>` toggles `open` but has no `aria-expanded`; theme buttons toggle `active` but have no `aria-pressed`. Test asserts these states are not conveyed to assistive tech. (The hamburger *does* have `aria-label` — positive.)
- **Evidence on failure:** DOM snapshot of the trigger/theme buttons before/after toggle.

**FE-A11Y-06 — Corporate mobile menu: no Escape-to-close / focus management**
- **Preconditions:** Anonymous; corporate home at mobile width.
- **Steps:** Open the mobile nav (`corporate_base.html:145-156`); press Escape; Tab.
- **Expected result:** Current: `aria-hidden`/`aria-expanded` are toggled correctly (positive), but there is no `Escape` handler and focus is not moved into/trapped within the open menu. Test asserts Escape does nothing and focus is not managed.
- **Evidence on failure:** Behavior recording of Escape; focus order while menu is open.

**FE-A11Y-07 — Inline `onclick` icon buttons expose accessible names (spot-check)**
- **Preconditions:** Logged in; load the shell and a list page.
- **Steps:** Run an automated a11y scan (axe/lighthouse) on `/dashboard/` and a list page.
- **Expected result:** The hamburger (has `aria-label`) and notification/social icon buttons expose names; flag any `<button>`/icon with a click handler but no accessible name (e.g. the user-menu trigger relies on initials+name text, which is borderline). Test captures the violations list.
- **Evidence on failure:** axe/lighthouse JSON listing `button-name` / `aria-label` issues.

## 4. Data isolation rules

- **Unique/timestamped values** for anything that persists: customer names/emails, lead emails, booking references. Auto-generated IDs (`CUS-00001`, `BKG-00001`, `PAY-00001`, `RCP-00001`) are parsed from the last numeric suffix — never assume a fixed ID in assertions.
- **XSS payloads** use `window.__xss=1` (observable, non-blocking) instead of `alert()`. Reset `window.__xss = undefined` before each SEC scenario.
- **AI scenarios** stub the fetch response (or use a real key); do not let LLM output be the assertion — control the injected string.
- **Cleanup:** delete seeded `CUS-XSS`, `BKG-PAISA`, test leads, and any rows created by double-submit tests after the run. Reset the `sales`/`accounts` profiles to their canonical roles.
- **Determinism:** run with `DJANGO_DEBUG=True`; clear `sessionStorage`/`localStorage` (theme + sidebar-scroll) between runs to avoid cross-test leakage.

## 5. Coverage checklist (for the master map)

```
FE-HP-01   Login page renders
FE-HP-02   Login submits and lands on the right home
FE-HP-03   ERP base layout + sidebar nav render for staff
FE-HP-04   Sidebar role gating matches server flags
FE-HP-05   Corporate home renders (hero, projects, lead form, contact)
FE-HP-06   Corporate lead form submits → creates a Lead
FE-HP-07   Money renders consistently within a single page
FE-HP-08   /portal/ is the Django template, not the orphaned React build
FE-EC-01   Money formatting fragmentation across pages
FE-EC-02   Paisa precision dropped silently
FE-EC-03   JS toLocaleString grouping follows browser locale
FE-EC-04   hr/leaves.html approve/reject action forms correctly wired
FE-EC-05   No client-side double-submit disable
FE-EC-06   novalidate disables browser validation (whitespace-only required)
FE-EC-07   Floating-label state on whitespace-only value
FE-EC-08   Stale session: fetch leaves a hung spinner
FE-EC-09   Print CSS hides entry/confirm forms
FE-SEC-01  [HIGH] Stored XSS via AI insights preview (ai/insights.html)
FE-SEC-02  Partial-escape XSS in AI HR chat echo (ai/hr.html)
FE-SEC-03  financial_reports.html |safe Python-repr chart data
FE-SEC-04  base.html window.SAMANA_THEME unescaped interpolation
FE-SEC-05  erp.js showToast/showConfirm innerHTML from message arg
FE-SEC-06  Login next open-redirect vector
FE-SEC-07  main.js reads nonexistent csrf-token meta (orphaned)
FE-SEC-08  List/detail pages render XSS payload escaped (positive control)
FE-SEC-09  booking_form/payment_form latent innerHTML sinks
FE-SEC-10  Every POST form carries csrf_token (regression)
FE-SEC-11  Receipt WhatsApp share exfiltrates amount (informational)
FE-A11Y-01 Corporate lead form inputs have no <label>
FE-A11Y-02 base_form.html select/file labels have no for
FE-A11Y-03 Confirm dialogs lack role=dialog/aria-modal/focus-trap/Escape
FE-A11Y-04 Sortable <th> not keyboard-focusable, no aria-sort
FE-A11Y-05 User-menu trigger and theme buttons lack state ARIA
FE-A11Y-06 Corporate mobile menu: no Escape-to-close/focus management
FE-A11Y-07 Inline onclick icon buttons expose accessible names (spot-check)
```
