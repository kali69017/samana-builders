# QA Analysis — Master Index & Risk Register

Consolidated from the 12 per-module analyses in this directory. Every finding below
carries file:line citations in its source doc. Severity: Critical / High / Medium / Low.

## Modules analyzed

| # | Module | Doc |
|---|--------|-----|
| 1 | core (users/auth/permissions + monolith views) | `core_analysis.md` |
| 2 | customers | `customers_analysis.md` |
| 3 | properties | `properties_analysis.md` |
| 4 | bookings | `bookings_analysis.md` |
| 5 | payments | `payments_analysis.md` |
| 6 | finance | `finance_analysis.md` |
| 7 | expenses | `expenses_analysis.md` |
| 8 | hr | `hr_analysis.md` |
| 9 | notifications | `notifications_analysis.md` |
| 10 | ai | `ai_analysis.md` |
| 11 | api (DRF auth/portal) | `api_analysis.md` |
| 12 | frontend (templates/JS/forms) | `frontend_analysis.md` |

Shared context: `_shared-context.md`. Required output shape: `_analysis-template.md`.

## Cross-cutting risk register (deduplicated, severity-ranked)

### CRITICAL
1. **Vertical privilege escalation via `profile_view` / `ProfileViewSet.update_profile`.**
   `UserProfileForm` and `UserProfileSerializer` leave `role` (and `is_active`) writable with no
   guard. Any authenticated user — including a customer-portal user with no profile — can
   `POST role=super_admin`. Confirmed independently by core, api, and the shared permission
   reading. (`core/views.py:2003-2032`, `core/forms.py:20-29`, `core/api_views.py:118-138`,
   `core/serializers.py:9-15`.)
2. **Systemic PII exposure / broken object-level auth (IDOR).**
   Two root causes: (a) server views are `@login_required` only (customers, bookings, plot/project
   edit, profile PDF) with no role/ownership check; (b) every DRF ViewSet's local permission class
   returns `True` for `SAFE_METHODS` for **any** authenticated user (`IsAdminOrReadOnly`,
   `IsHRManagement`, `IsStaffOrAbove`, …). A customer-portal user can read full CNIC/phone/address,
   bookings, payments, receipts, employees + salary, and audit logs with IPs.

### HIGH
3. **CSRF via GET on expense approve/reject/mark-paid.** No `request.method` check, so the
   CSRF middleware skips them. (`expenses/views.py:116-178`.)
4. **Booking reopen conflict.** Reopen re-reserves the plot with no check it wasn't re-sold →
   two active bookings on one plot. (`core/views.py:1307`.)
5. **Money-flow correctness bugs (payments/bookings):** reverse of a draft/pending payment corrupts
   balances (no status guard); double-approve refund reduces `advance_paid` twice; concurrent
   double-verify race (no `select_for_update`); web create marks payments `verified` immediately
   while API create defaults to `pending` (divergent semantics); `BookingSerializer.update` drops the
   `total_cost`/`holding_deposit` price guards.
6. **Stored XSS** in `ai/insights.html` (`innerHTML` with unescaped LLM result) and
   `ai/hr.html` (`insertAdjacentHTML` partial escape).
7. **HR API read-open** exposes salary/CNIC/phone; `LeaveSerializer.status` writable (self-approve).
8. **Receipt/media exposure:** `ReceiptViewSet` is `IsAuthenticated`; expense `receipt_attachment`
   is an unvalidated `FileField` (SVG/HTML stored XSS); `static(MEDIA_URL)` serves vendor invoices
   unauthenticated.

### MEDIUM
9. **Open redirects:** `lead_status_update_view` (`redirect(request.POST.get('next'))`) and
   `login.html` `next` field.
10. **Backup zip-slip** path traversal in restore; restore blocked only by a weak heuristic,
    disabled under DEBUG.
11. **Ledger-integrity gaps:** orphaned `AccountTransaction` rows on expense/cost demote/delete;
    `approved→rejected` leaves an orphaned debit; approval bypass via editable `status` form field.
12. **Revenue chart** (`revenue_trend_view`, `financial_reports_view`) sums `Payment.amount`,
    contradicting the `advance_paid` headline invariant.
13. **AI prompt injection / data egress** — user input and full business snapshot sent raw to
    DeepSeek; no rate limiting.
14. **Notifications:** `notifications_view` 500s (filter on sliced queryset); disabled providers
    logged as `sent`; customer-controlled name raw-interpolated into SMS/email (smishing).
15. **Password reset** 6-digit code with no rate limit; 6-char minimum password.
16. **Booking double-create race** (web form lacks `select_for_update` on the plot).
17. **UI dead-ends:** transfer form template undefined (`booking_transfer.html`); audit-log filter
    controls non-functional; properties search input dead; `on_hold` status unreachable; money
    formatting fragmented.

### LOW
18. Accessibility: corporate lead form has no `<label>`; `base_form.html` select/file lack `for`;
    confirm dialogs lack ARIA/focus-trap; sortable `<th>` not keyboard-focusable.
19. `base.html` `window.SAMANA_THEME` unescaped (latent); `financial_reports.html` `|safe` on a
    Python repr (non-user data).
20. Orphaned React build (`frontend/dist/`) referenced by no template; portal is Django, not React.

## Analysis note

These are static-analysis findings — they have NOT yet been reproduced against the running app.
Phase D is where the highest-severity items get reproduced with the Playwright MCP browser and
evidence captured. Do not treat the list above as verified bugs until then; it is the target list
that drives test-planning and execution.
