# Remediation Plan — Samana Builders ERP

Merged, deduplicated defect register. Source: `docs/qa/findings-confirmed.md` (F1–F8),
`test_report.md` §3–§4, and the ~30 deterministic RED tests from the browser/API suite runs.
Read-only register — no application code changes have been applied.

Legend: each row = module, root cause (file:line), one-line fix, and the test that turns green when fixed.

---

## Group A — FIX NOW (Critical + High)

### 1. Privilege escalation — `role` is client-writable (F1 + F2)
- **Severity:** Critical
- **Module:** core (API + web)
- **Root cause:** `UserProfileSerializer.fields` includes `role`, no `read_only` (`core/serializers.py:9-14`); `ProfileViewSet.update_profile` is `IsAuthenticated` (`core/api_views.py:130-138`); `profile_view` saves `UserProfileForm(fields=['role','theme','is_active'])` with no guard (`core/forms.py:20-29`, `core/views.py:2003-2032`).
- **Fix:** make `role` read-only in the serializer AND drop `role` from the self-service form (or guard it server-side).
- **Proves fixed:** `CORE-SEC-01`, `CORE-SEC-02`, `API-SEC-01`, `API-SEC-02`, `API-API-10`.

### 2. Systemic IDOR / PII read-open (F3)
- **Severity:** Critical
- **Module:** api (every ViewSet) + core web views
- **Root cause:** every permission class returns `True` for `SAFE_METHODS` to any authenticated user (`customers/api_views.py:15-25`, `bookings/api_views.py:27-48`, `payments/api_views.py:15-35`, `hr/api_views.py:23-33`, `finance/api_views.py:15-25`, `core/api_views.py:13-24`); web views are `@login_required` only (customers/booking/plot/project/PDF).
- **Fix:** require `is_staff` (or a role whitelist) on API reads; add role decorators to the web views.
- **Proves fixed:** `CUS-SEC-01..06`, `BOOK-SEC-02/03/05/06`, `PROP-SEC-02..05/10`, `HR-SEC-01`, `PAY-SEC-01`, `API-SEC-03..08`, `API-API-01..07/09`.

### 3. CSRF via GET on expense workflow (F4)
- **Severity:** High · **Module:** expenses
- **Root cause:** `expense_approve_view`/`mark_paid`/`reject` have no `request.method == 'POST'` check (`expenses/views.py:116-178`).
- **Fix:** add `@require_POST` to all three.
- **Proves fixed:** `EXP-EC-01`, `EXP-SEC-01/02/03`.

### 4. HR API read-open + leave `status` writable (F8)
- **Severity:** High · **Module:** hr
- **Root cause:** `IsHRManagement` returns `True` for SAFE_METHODS to any user (`hr/api_views.py:23-33`); `LeaveSerializer.read_only_fields = ['id','applied_on','approved_by']` leaves `status` writable (`hr/serializers.py:146-151`).
- **Fix:** gate HR reads to HR/finance roles; make `status` read-only (drive via the `approve` action only).
- **Proves fixed:** `HR-SEC-01`, `HR-SEC-02`.

### 5. Money-flow races / missing status guards (F6)
- **Severity:** High · **Module:** payments
- **Root cause:** `payment_reverse_view` has no status guard (`payments/views_workflow.py:127-153`); `refund_approve_view` lacks `status=='pending'` (`:193-212`); verify is check-then-act with no `select_for_update` (`:69`, `api_views.py:99-167`).
- **Fix:** add status-transition guards + `select_for_update`/idempotency keys.
- **Proves fixed:** `PAY-BR-SEC-01`, `PAY-BR-SEC-03`, `PAY-EC-02`.

### 6. Booking reopen conflict (F5)
- **Severity:** High · **Module:** bookings
- **Root cause:** `booking_reopen_view` sets plot `reserved` with no re-sold check (`core/views.py:1307`).
- **Fix:** refuse reopen if the plot now has another active booking.
- **Proves fixed:** `BOOK-EC-01`.

### 7. Stored XSS — AI insights + HR chat (F7)
- **Severity:** High · **Module:** ai (frontend)
- **Root cause:** `templates/ai/insights.html:257-261` (`innerHTML` unescaped), `templates/ai/hr.html:70` (`insertAdjacentHTML` partial escape).
- **Fix:** render LLM output via `textContent`/full escaping.
- **Proves fixed:** `AI-SEC-01`, `FE-SEC-01/02`.

### 8. Stored XSS — project delete confirm
- **Severity:** High · **Module:** properties (frontend)
- **Root cause:** project name interpolated into `onclick=confirm(...)` without quote neutralization (`templates/properties.html:123`).
- **Fix:** escape/neutralize the name in the onclick (or use a data-attr + JS).
- **Proves fixed:** `PROP-SEC-01`.

### 9. File-upload XSS — SVG/HTML receipt
- **Severity:** High · **Module:** expenses
- **Root cause:** `receipt_attachment` is a `FileField` with no type/size validation (`expenses/models.py:39-43`).
- **Fix:** use `ImageField`/validated extensions; serve with `Content-Disposition: attachment`.
- **Proves fixed:** `EXP-SEC-04/05`.

### 10. Unauthenticated media serving
- **Severity:** High · **Module:** core (urls)
- **Root cause:** `urlpatterns += static(MEDIA_URL, ...)` serves vendor invoices without auth (`samana_erp/urls.py:160`).
- **Fix:** gate `/media/` behind a login view (or move private docs off the public static path).
- **Proves fixed:** `EXP-SEC-06`.

### 11. Approval bypass via writable `status`
- **Severity:** High · **Module:** finance
- **Root cause:** `status` is a create/edit form/serializer field, so a non-management finance user can create an already-`paid` expense/cost and post to ledger (`finance/forms.py`, `finance/serializers.py`).
- **Fix:** make `status` read-only on create; drive transitions via approve/pay actions only.
- **Proves fixed:** `FIN-EC-05`.

### 12. Office delete guard missing in API
- **Severity:** High · **Module:** finance
- **Root cause:** `OfficeViewSet`/admin `destroy` has no dependency guard (HTML view has one) (`finance/api_views.py:50-53`).
- **Fix:** mirror the HTML guard in the ViewSet `destroy` (block if expenses/ledger rows exist).
- **Proves fixed:** `FIN-SEC-02`.

### 13. Open redirect (lead status)
- **Severity:** High · **Module:** core (CRM)
- **Root cause:** `redirect(request.POST.get('next'))` with no same-origin validation (`core/views_crm.py:137`).
- **Fix:** validate with `url_has_allowed_host_and_scheme`.
- **Proves fixed:** `LEAD-EC-04`.

### 14. Booked plot re-listed via edit
- **Severity:** High · **Module:** properties
- **Root cause:** `plot_edit_view` has no status guard — a booked/sold plot can be edited back to `available` (`core/views.py:948-967`).
- **Fix:** block status/price edit on booked/sold plots.
- **Proves fixed:** `PROP-EC-10`.

### 15. Zero/negative-net slip breaks the whole pay run
- **Severity:** High · **Module:** hr
- **Root cause:** `pay` writes `SalaryPayment(amount=0/neg)` → ledger `amount>0` constraint → `transaction.atomic` rolls back all payments 500 (`hr/views.py:397-411`, `finance/models.py:64`).
- **Fix:** skip/reject non-positive net slips before posting.
- **Proves fixed:** `HR-EC-01`.

### 16. Profile page save is broken (missing `role`/`is_active`)
- **Severity:** High · **Module:** core
- **Root cause:** `UserProfileForm` requires `role` and both forms declare `is_active`, but `profile.html` renders neither → every save fails validation.
- **Fix:** render the fields (or make them optional / auto-fill current role).
- **Proves fixed:** `AUTH-HP-04/05` (currently worked-around in tests).

---

## Group B — FIX SOON (Medium)

### 17. `CustomerLedgerEntry` never auto-created on payment
- **Module:** payments · **Root cause:** payment record/verify updates Payment/Booking/Receipt/Installment but writes no `'payment'` ledger entry.
- **Fix:** create a `CustomerLedgerEntry` (payment received) in the verify flow.
- **Proves fixed:** payments cross-table test (PAY-BR-* ledger assertion).

### 18. `UserCreateSerializer` missing `write_only`
- **Module:** core · **Root cause:** `role`/`phone`/`cnic` not `write_only=True` → `POST /api/users/` 500s in `get_success_headers` after the user persists (`core/serializers.py:28-33`).
- **Fix:** mark those three `write_only=True`.
- **Proves fixed:** `CORE-API` / auth user-create test.

### 19. Auto-ID generation race
- **Module:** core/customers/bookings/payments · **Root cause:** `save()` parses last row's suffix under `select_for_update` (no-op on SQLite) → concurrent create 500s.
- **Fix:** use a DB sequence / `transaction.atomic` with a lock, or a monotonic counter.
- **Proves fixed:** parallel-create test (currently retried in tests).

### 20. Leave over-allowance
- **Module:** hr · **Root cause:** no leave balance enforcement; `remaining` is display-clamped only.
- **Fix:** enforce balance at apply/approve.
- **Proves fixed:** `HR-EC-03`.

### 21. Paid-slip edit mutates net
- **Module:** hr · **Root cause:** slip-item edit has no `status=='draft'` guard.
- **Fix:** lock edits once processed/paid.
- **Proves fixed:** `HR-EC-04`.

### 22. Non-numeric slip amount → 500
- **Module:** hr · **Root cause:** uncaught `decimal.InvalidOperation`.
- **Fix:** validate numeric input.
- **Proves fixed:** `HR-EC-05`.

### 23. `pay` before `process`
- **Module:** hr · **Root cause:** `pay` has no `status=='processed'` check.
- **Fix:** require processed before pay.
- **Proves fixed:** `HR-EC-06`.

### 24. Reservation expiry never processed
- **Module:** properties · **Root cause:** `Reservation.expires_at` default +7d but no cron/command marks `expired`.
- **Fix:** add an expiry job (or lazy expiry on read).
- **Proves fixed:** `PROP-EC-09`.

---

## Group C — BACKLOG (Low)

### 25. Nominee "remove" broken
- **Module:** customers · **Root cause:** `CustomerNominee.nominee_name` has no `blank=True`; clearing it re-renders required-field error.
- **Fix:** `blank=True` + a real delete path.
- **Proves fixed:** `CUS-HP-07`.

### 26. Money serialization inconsistency
- **Module:** customers/bookings (serializers) · **Root cause:** `current_balance`/`remaining_balance` serialized as bare numbers, other money as Decimal strings.
- **Fix:** serialize all money as fixed-precision strings (or all numbers) consistently.
- **Proves fixed:** money assertions in customers/bookings tests.

---

## Not a bug (superseded)
- Login `next` open-redirect — **NOT present** (`login_view` ignores `next`); the open redirect is #13 above.

## Stale evidence note
`tests/repro/evidence.md` predates the corrected reproduction and reports R1/R2/R3/R4/R5 as
false 403s due to a CSRF-harness bug. It is superseded by `docs/qa/findings-confirmed.md`.
