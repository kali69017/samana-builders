# Frontend Layer — QA Analysis

> Samana Builders ERP — templates + static JS/CSS + form rendering + cross-cutting UI risks.
> Read `docs/qa/_shared-context.md` for roles/permissions/URLs (not re-derived here).

## 1. Business purpose & user journeys

The frontend is **100% server-rendered Django templates** (plus two hand-written JS files and a
hand-written CSS/theme set). There is no live SPA: the compiled React build (`frontend/dist/`) is
**not referenced by any template** (grep for `frontend/dist`, `assets/`, `root` finds no loader),
and the customer portal is `templates/portal/dashboard.html`, a Django template extending
`base.html`. The corporate marketing site (`corporate_base.html` + `corporate/home.html`) is also
Django-templated, not React.

Two surface areas:
- **ERP (authenticated staff/customer)** — `base.html` shell + `includes/sidebar.html` nav,
  `base_form.html` generic form renderer, plus ~90 per-entity templates.
- **Corporate site (public)** — `corporate_base.html` + `corporate/home.html`, with a lead form
  POSTing to `lead_submit`.

Real user journeys (role in parentheses):
- Staff login → `/dashboard/` → navigate via sidebar → list/detail/create entity (all roles).
- Finance staff: dashboard → Payments / Refunds / Ledger → verify/reject/process (accounts+).
- Sales staff: lead strip form on corporate site → `lead_submit` creates `core.Lead` → CRM leads list (sales).
- Customer login → `/portal/` → view own bookings/installments/payments (customer).
- Admin: Company Settings (logo/branding), Manage Users, DB Backup (admin+).
- Public visitor: corporate home → "Book Now" scroll to `#contact` → lead form → WhatsApp not used on the site itself (only a share link on the ERP receipt page).

## 2. Frontend architecture / "data model"

Files that matter (read in full):
- `templates/base.html` — ERP shell: topbar, toast container, messages popup, loads `erp.css`,
  `erp.js`, and Chart.js 4.4.7 from jsDelivr CDN (`base.html:81`).
- `templates/base_form.html` — generic `<form method="post" novalidate enctype="multipart/form-data">`
  renderer that loops `form` fields and branches on widget `input_type`
  (checkbox / select / file / textarea / text). **This is the single form-rendering choke point.**
- `templates/corporate_base.html` / `templates/corporate/home.html` — public site (nav, hero,
  about, vision, projects, testimonials, Google Maps iframe, contact/lead form).
- `static/js/erp.js` — the **only loaded JS** (base.html:78). Theme switcher, sidebar toggle,
  auto-hide toasts, counters, table sort, form submit spinner, tabs, `showToast`, `showConfirm`,
  `filterTable`, `formatCurrency`, floating-label fallback.
- `static/js/main.js` — a parallel, self-contained module (theme/sidebar/validation/AJAX/`ErpAPI`).
  **Orphaned: not referenced by any template** (grep `main\.js` → 0 hits). Dead code with a latent
  CSRF bug (see §6).
- CSS: `erp.css` (main + `@media print` at 794), `style.css` (legacy + `@media print` at 1279),
  `theme-*.css` ×6, `corporate.css`.

Form rendering model: `base_form.html` renders each field manually and wraps it in a
`floating-group` (label *after* the input, using `for="{{ field.id_for_label }}"`) or `form-group`.
`customer_form.html`, `booking_form.html`, `payment_form.html` re-implement the same per-field
rendering inline rather than reusing `base_form.html`, so fixes must be repeated.

Money rendering model (fragmented — see §6): a custom `money` filter
(`properties/templatetags/property_tags.py:8`) exists but is used in exactly **one** template
(`properties.html:171`); everything else uses `floatformat:0|intcomma` (humanize),
`floatformat:0`, or bare `Rs. {{ value }}`, and JS uses `Number(x).toLocaleString()`.

## 3. Roles & permissions (UI layer)

The UI gating mirrors the server flags (`core/context_processors.py` `erp_context`) — see
`_shared-context.md` for the flag list. Observations:

| UI element | Controlled by | Enforced server-side |
|---|---|---|
| Sidebar "Payments"/"Finance" section | `can_view_payments` | `payments_access` decorator |
| Sidebar "Expenses"/"Finance & Accounts" | `can_view_expenses` | `finance_or_above` |
| "HR & Payroll" section | `can_view_payroll` / `can_manage_hr` | `hr_required` / `payroll_access` |
| "Manage Users" | `can_view_users` | `admin_or_above` |
| "DB Backup" / "Company Settings" | `can_backup` / `can_manage_settings` | `admin_or_above` |
| Notification bell (topbar) | `can_audit` | `management_or_above` |
| `is_employee` branch in sidebar | context flag | — |

- The sidebar (`includes/sidebar.html`) and topbar (base.html) hide buttons by role flag, which is
  the correct pattern **provided** the view is also decorated (it is, per shared context). No
  template-hides-but-view-unguarded mismatch was found in this audit.
- `is_employee` suppresses the Preferences/Profile link (base.html:44) and swaps the sidebar to an
  "Employee" section — consistent with `bool(getattr(user,'employee',None))`.

## 4. Business rules / state machines (UI representation)

Status actions are rendered as small inline POST forms with a `confirm()` or `data-confirm`
dialog, e.g.:

- `expenses.html:166-169`, `expense_detail.html:44-48` — Approve / Reject / Mark Paid (expense state machine).
- `finance/office_expenses.html:69-72` — Approve / Pay office expenses.
- `payment_detail.html:49-66` — Verify / Reject / Bounce / Reverse.
- `refunds.html:102-115` — Approve / Reject / Process.
- `hr/payroll_run_detail.html:26-32` — Generate / Process / Pay.
- `installment_plan_detail.html:75,82` — Mark installment paid / reschedule.
- `hr/leaves.html:48,52` — Leave approve (two forms: one posts to approve, the other to reject — see §5).

The UI does not encode state-machine guards itself (e.g. it does not hide "Approve" when a refund
is already processed); that is the server's job and is correct. But note the UI does not show a
disabled state either, so a double-click can double-submit (see §5).

## 5. Edge cases (go deep)

- **Double-submit / no idempotency UI**: `erp.js:171-185` adds a spinner to the submit button on
  `submit`, but does **not** disable the button; a rapid double-click sends two POSTs. Backend
  ledger de-dup (unique `reference_type`+`reference_id`) mitigates the money side, but
  create/approve actions could still double-fire. Expected: disable the button in the submit
  handler and re-enable on failure.
- **`novalidate` everywhere**: `base_form.html:40`, `login.html:55`, and most hand-written forms set
  `novalidate`, disabling browser validation. Django server validation still runs, so this is not a
  bypass — but it removes the last client-side safety net for free-text lengths and required fields.
- **Empty/whitespace input**: `erp.js` `syncFloatingLabels` keys off `control.value.trim() !== ''`;
  a whitespace-only value marks the field "filled" while failing a server `required` check — a minor
  label-state inconsistency.
- **`handleDrop` global dependency**: `payment_form.html:555` builds an upload zone with an inline
  `ondrop="handleDrop(event, this)"` via `innerHTML`. `handleDrop` is declared at
  `payment_form.html:582` as a global, so it resolves — but only because the script is not wrapped
  in an IIFE/module. Fragile.
- **Money precision**: storage is `DecimalField(..., decimal_places=2)` but many displays use
  `floatformat:0` (whole PKR) while the `money` filter defaults to `decimals=0` and drops paisa.
  Inconsistent precision between list, detail, receipt, and PDF views (see §6).
- **File upload**: `payment_form.html:247` and the JS-generated `:559` accept `image/*,.pdf` only;
  `customer_form.html` (`{{ form.image }}` / `{{ form.document }}`, hidden inputs at `:180`) relies
  on Django's `ImageField`/`FileField` validators (size/type enforced server-side). No client-side
  size gate; large files fail only on the server round-trip.
- **`next` open redirect**: `login.html:57` echoes `<input type="hidden" name="next" value="{{ next }}">`.
  Django HTML-escapes it (not an XSS), but an attacker can craft `?next=https://evil.com`; the
  redirect target must be validated server-side (`url_has_allowed_host_and_scheme`) — a backend
  concern surfaced by the template.
- **Concurrent/session expiry**: no JS handles a 302-to-login or 403 from a fetch (AI forms,
  payment-form summary, dashboard charts); a stale session leaves a spinner spinning or an
  uncaught promise. Expected: detect `401/403` and redirect to `/login/`.
- **Leave approve/reject forms**: `hr/leaves.html:48` and `:52` are two separate forms — the
  first posts to `hr_leave_approve`, the second to `hr_leave_reject`. (Correction: the initial
  analysis misreported these as duplicates; they are correctly wired.)

## 6. Cross-cutting risks (the core)

### 6.1 XSS sinks (ranked)

1. **`templates/ai/insights.html:257-261` — HIGH (stored XSS).**
   ```js
   const preview = data.result.slice(0, 140);
   item.innerHTML = '...' + preview + '</div>';
   ```
   `data.result` is the AI assistant's response (DeepSeek) and is injected into `innerHTML` **with no
   escaping**. The AI summarizes business data that can contain user-controlled text (customer
   names/addresses, booking notes, lead notes, expense descriptions, agent notes). An attacker who
   plants `<img src=x onerror=…>` in any such field and then triggers an AI insight has it
   re-emitted verbatim into the DOM → arbitrary script in the staff's session. The full result is
   also stashed in `data-response` with only `"` escaped (`:254`), but the click handler reads it
   back via `textContent` (`:265`), so the `innerHTML` preview is the sink. **Fix: render `preview`
   via `textContent` (or escape HTML) and never interpolate AI output into `innerHTML`.**

2. **`templates/ai/hr.html:70` — LOW-MEDIUM (partial escaping, fragile).**
   ```js
   hrChat.insertAdjacentHTML('beforeend', '<div class="msg user">' + q.replace(/</g, '&lt;') + '</div>');
   ```
   Only `<` is escaped (`>`, `&`, `"` are not). In the current position this happens to block tag
   injection, but the pattern is exactly the kind that breaks when someone later moves the value into
   an attribute. The bot reply uses `textContent` (`:82`) — safe. **Fix: use `textContent` for the
   user echo too.**

3. **`templates/financial_reports.html:138` — the only `|safe` in the codebase (LOW exploit, real smell).**
   ```js
   const chartData = {{ monthly_chart_data|safe }};
   ```
   `monthly_chart_data` (`core/views.py:570`) is a Python list of dicts of `{label: strftime('%b %Y'),
   amount: float}` — month names and numeric totals, not user-controlled, so exploitability is low.
   But it is rendered as a **Python `repr`** (single-quoted), not JSON: valid only by accident, and it
   breaks if any label ever carries a quote/`None`. **Fix: `{{ monthly_chart_data|json_script:"monthly" }}`**
   and read `JSON.parse(document.getElementById('monthly').textContent)`.

4. **`templates/booking_form.html:154` — LOW.** `templateInfo.innerHTML` is fed by `data-info`
   (`:104`) = `total_installments|frequency|down_payment_percentage` — server-defined enum/numbers,
   not free text. Pattern is unsafe but not currently exploitable.

5. **`templates/payment_form.html:465, 536-538, 555` — LOW.** `planInfo.innerHTML` uses numeric API
   fields; the method-field builder uses `f.key`/`f.label` from a **hardcoded** `methodFieldsConfig`
   (`:336-389`). The same file correctly uses `|escapejs` for customer/project/plot strings
   (`:309-329`), so the developer is aware of the escaping problem but applies it unevenly.

6. **`templates/base.html:75` — latent.** `window.SAMANA_THEME = '{{ user_theme|default:"professional-blue" }}';`
   interpolates into a JS string literal without `|escapejs`. Safe today because `user_theme` is a
   `ChoiceField`, but any future move to free-text breaks it. Add `|escapejs`.

7. **`static/js/erp.js:224` (`showToast`) and `:238-245` (`showConfirm`) — LOW/latent.**
   Both build `innerHTML` from a `message` argument. Current callers pass fixed or already-rendered
   strings, but the helpers are generic; any future caller passing user content is an XSS. Use
   `textContent` or document escaping.
   (`static/js/main.js:300-309` and `:411-418` have the same pattern but main.js is **not loaded**.)

### 6.2 CSRF

- **Every** `<form method="post">` carries `{% csrf_token %}` (cross-checked the 57 `csrf_token`
  occurrences against the 40 files containing them; no POST form is missing one).
- AI pages submit via `fetch` with `X-CSRFToken` from `getCookie('csrftoken')`
  (`assistant.html:90`, `hr.html:79`, `insights.html:241`) — correct. `erp.js:34` (theme save) and
  `profile.html:123` (XHR) do the same.
- **Latent bug (no live impact):** `static/js/main.js:466-469` `ErpAPI` reads
  `document.querySelector('meta[name="csrf-token"]')` — **no such meta tag exists** in `base.html`,
  so every `ErpAPI.post()` would 403. It is harmless only because `main.js` is not loaded anywhere.
  If main.js is ever wired in, fix it to use the cookie like `erp.js` does.
- CSRF relies on `document.cookie` being readable — Django's `csrftoken` cookie is not `HttpOnly`
  (default), so this holds.

### 6.3 Accessibility

1. **Corporate lead form has no labels** — `templates/corporate/home.html:222-243`: name/email/phone/
   interest/message use `placeholder` only, no `<label>`, no `for`. WCAG 1.3.1 / 3.3.2 violation on
   the public site.
2. **`base_form.html` select and file fields have unassociated labels** — the select branch
   (`:54-58`) and file branch (`:67-76`) render a bare `<label>` with **no `for`**, then `{{ field }}`
   separately; screen readers won't associate them (text/textarea/checkbox branches do use `for`).
3. **Confirm dialogs (`erp.js:235-257`) lack `role="dialog"` / `aria-modal` / focus trap / Escape**
   — focus is not moved into the dialog, not trapped, and there's no `Escape` handler.
4. **Corporate mobile menu** (`corporate_base.html:145-156`) sets `aria-hidden`/`aria-expanded`
   correctly but has no Escape-to-close and no focus management.
5. **Sortable table headers** (`erp.js:123-135`) are clickable `<th>` with a cursor change but no
   `tabindex`, no `aria-sort`, and are keyboard-inaccessible.
6. **Inline `onclick` handlers** on icon buttons (base.html:23,37; sidebar; base_form) — the hamburger
   has `aria-label`, but the user-menu trigger (`base.html:37`) is a `<button>` with no accessible
   name (its text is initials + name, which is likely enough, but the state change `open` isn't
   conveyed via `aria-expanded`).
7. **Theme buttons** (`erp.js:10`) use `data-theme` active toggling but no `aria-pressed`.

Positives: corporate images carry `alt`; the map iframe has a `title`; social icons carry
`aria-label`; login inputs have `for`-associated labels and `autocomplete` attributes.

### 6.4 Money rendering precision / consistency

- **One custom filter, one call site**: `money` (`property_tags.py:8`) is used only at
  `properties.html:171`. It adds thousands separators via `f'{num:,.0f}'` (round-half-even) and no
  currency symbol. Elsewhere: `floatformat:0|intcomma` (financial_reports, portal, dashboard),
  `floatformat:0` (receipt_detail), and bare `Rs. {{ value }}` in numerous list tables — so a given
  amount renders differently (with/without separators, with/without decimals) across pages.
- **JS vs server formatting**: `erp.js:277` `formatCurrency` uses `'en-IN'` grouping;
  `payment_form.html` and `dashboard.html` use `Number(x).toLocaleString()` with **no locale**,
  which follows the user's browser locale (e.g. `1.500.000` in de-DE) — inconsistent grouping inside
  the same product.
- **Precision dropped**: `floatformat:0` and `money` (default `decimals=0`) round to whole PKR while
  the DB stores 2 decimals. Reports round silently; no explicit half-up policy is stated anywhere.

### 6.5 Sensitive data exposure (frontend)

- PDF templates (`receipt_pdf.html`, `invoice_pdf.html`, `customer_profile_pdf.html`) render CNIC,
  phone, address, amounts — no `|safe`, so no XSS in the xhtml2pdf context, but these are full PII
  documents; access is (per shared context) decorator-gated. Verify the PDF views are `login_required`
  + role-gated, not just linked.
- `receipt_detail.html:24` WhatsApp share builds `https://wa.me/?text=Receipt … Rs. …` from the
  auto-generated receipt number and amount — Django-escaped, low risk, but it does exfiltrate a
  receipt amount into a third-party link if clicked.
- `customer_form.html:193` shows the uploaded document's raw filename via
  `{{ customer.document.name|cut:"customers/documents/" }}` (escaped — safe, but leaks the original
  upload filename).

### 6.6 Print / PDF

- Print CSS hides chrome (`erp.css:794-803`, `style.css:1279`): topbar, sidebar, buttons, forms,
  `.no-print`. `sales_report.html:17` and `financial_reports.html:21` expose Print buttons. This is
  intended, but note the print rule `form { display:none }` also hides the login/entry forms if a
  user prints those pages, and `#toastContainer`/messages are not hidden (minor).
- The Google Maps iframe (`corporate/home.html:190`) is a third-party embed on the public page
  (privacy/cookie consideration, no API key needed).

## 7. API surface (frontend-facing fetch/XHR)

| Caller | Endpoint | Method | CSRF | Notes |
|---|---|---|---|---|
| `erp.js:32` | `/api/save-theme/` | POST | cookie | theme persist |
| `ai/assistant.html:86` | `/api/ai/assistant/` | POST | cookie | body `{question}` |
| `ai/hr.html:77` | `/api/ai/hr/assistant/` | POST | cookie | body `{question}` |
| `ai/insights.html:237` | `/api/ai/insights/?focus=` | GET | cookie (unneeded) | returns `{ok,result}` |
| `payment_form.html:453` | `/api/bookings/<id>/payment-summary/` | GET | — | numeric summary |
| `profile.html:123` | theme save (XHR) | POST | cookie | |
| `dashboard.html` | revenue chart data | GET | — | see §6.1 note (uses fetch, not `|safe`) |
| `main.js` `ErpAPI` | generic | any | **broken** | orphaned file |

AI responses are rendered with `textContent` in assistant/hr (safe) but `innerHTML` in insights (see §6.1.1).

## 8. Test data & fixtures needed

To exercise the frontend risks deterministically:

- A customer whose **name** and a **lead/agent note** contain `<img src=x onerror=alert(1)>` (and a
  benign `<b>bold</b>`), to prove §6.1.1 (AI insights must NOT execute it) and that list/detail
  pages render it escaped.
- A booking with `total_amount`, `advance_paid` values ending in non-zero paisa (e.g. `1,500,000.50`)
  to compare `floatformat:0` vs `money` vs `toLocaleString` rendering across list/detail/receipt/PDF.
- Two roles (`accounts`, `sales`) to assert sidebar sections and action buttons hide consistently
  with the server flags; and a customer login to assert `/portal/` shows only own data.
- A payment with a file attachment to exercise the upload zone (`payment_form.html`) and its
  `handleDrop`/`updateUploadLabel` globals.
- Set `DJANGO_DEBUG=True` for the test client (else `SECURE_SSL_REDIRECT` 301s — see CLAUDE.md).
- Isolation: customer/booking/agent IDs are auto-generated (`CUS-00001` etc.), so use unique
  timestamped names/emails to avoid cross-test collision.

## 9. Key files (for traceability)

- `templates/base.html` — ERP shell; theme JS literal (:75), CDN Chart.js (:81), messages popup (:63).
- `templates/base_form.html` — generic form renderer; CSRF (:41), unassociated select/file labels (:54-76).
- `templates/corporate_base.html` / `templates/corporate/home.html` — public site; no-label lead form (:222), map iframe (:190).
- `templates/login.html` — `next` open-redirect field (:57).
- `templates/ai/insights.html` — **top XSS sink** (:257-261), history `data-response` (:254).
- `templates/ai/hr.html` — partial-escape `insertAdjacentHTML` (:70).
- `templates/ai/assistant.html` — safe `textContent` pattern (:73) — reference for the fix.
- `templates/financial_reports.html` — only `|safe` (:138).
- `templates/booking_form.html` — `data-info` → `innerHTML` (:104, :154).
- `templates/payment_form.html` — `|escapejs` (good, :309-329) + `innerHTML` builders (:465, :536-538, :555), upload zone (:559), `handleDrop` (:582).
- `templates/customer_form.html` — image/document upload hidden inputs (:180), filename leak (:193).
- `templates/portal/dashboard.html` — Django portal (not React).
- `templates/includes/sidebar.html` — role-gated nav.
- `templates/dashboard.html`, `templates/expenses.html`, `templates/financial_reports.html` — Chart.js canvases.
- `static/js/erp.js` — loaded JS; `showToast`/`showConfirm` innerHTML (:224, :238), sort headers (:129), submit spinner (:171).
- `static/js/main.js` — **orphaned**; `ErpAPI` broken CSRF (:466-469).
- `static/css/erp.css` / `style.css` — `@media print` (:794 / :1279).
- `properties/templatetags/property_tags.py` — `money` filter (used once).
- `core/views.py:570-594` — source of `monthly_chart_data` (non-user data).
