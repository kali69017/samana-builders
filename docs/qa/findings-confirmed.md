# Confirmed findings — live reproduction (2026-09-13)

Reproduced against the local dev server http://127.0.0.1:8000 (DJANGO_DEBUG=True).
"CONFIRMED (live)" = observed over real HTTP via the browser (Playwright MCP `fetch`) or
`requests`. "CODE-CONFIRMED" = unambiguous in source (file:line cited); will be re-confirmed
by the test suite as RED tests.

## Priority 1 — Critical

### F1 — Vertical privilege escalation (API): any staff user can self-elevate to super_admin
- **Status: CONFIRMED (live).**
- **Proof:** logged in as `qa_sales` (role `sales`), then
  `PATCH /api/profile/update_profile/ {"role":"super_admin"}` → HTTP 200 →
  `GET /api/auth/me/` returned `role: "super_admin"`.
- **Root cause:** `ProfileViewSet.update_profile` is `IsAuthenticated`
  (`core/api_views.py:121,130-138`); `UserProfileSerializer.fields` includes `role` and no
  `read_only_fields` (`core/serializers.py:9-14`).
- **Severity: Critical.** Any employee with a profile can become super_admin, bypassing all RBAC.

### F2 — Vertical privilege escalation (web): portal customer self-creates a super_admin profile
- **Status: CONFIRMED (live).**
- **Proof:** logged in as `qa_customer` (non-staff portal customer, no profile), then
  `POST /profile/` with `role=super_admin` → `GET /api/auth/me/` returned `role: "super_admin"`.
- **Root cause:** `profile_view` is `@login_required` only (`core/views.py:2003-2032`) and saves
  `UserProfileForm` whose `fields = ['role','theme','is_active']` has no `clean_role` guard
  (`core/forms.py:20-29`).
- **Severity: Critical.** A customer can grant themselves super_admin.

### F3 — Systemic IDOR / PII read-open (API)
- **Status: CONFIRMED (live).**
- **Proof:** as `qa_customer` (role `customer`), all of these returned HTTP 200 with full data:
  - `/api/customers/` — 70 rows incl. `cnic`, `phone`, `email`, `address`
  - `/api/users/` — 24 rows incl. `profile` (role/phone/cnic)
  - `/api/bookings/` — booking `total_amount`/`advance_paid`/`customer_name`
  - `/api/payments/` — `amount`, `cheque_number`, `method_data`, `customer_name`
  - `/api/employees/` — `cnic`, `phone`, `salaries` (Basic Salary 75000.00)
  - `/api/audit-logs/` — 100 rows incl. `ip_address`
  - `/api/leads/` — 105 rows incl. `phone`/`email`
  - `/api/agents/` — 52 rows incl. `cnic`/`phone`/`commission_rate`
  - `/api/receipts/` — 200 (empty)
  - `/api/company-settings/summary/` — `revenue`, `net_profit`
- **Root cause:** every ViewSet permission class returns `True` for `SAFE_METHODS` to *any*
  authenticated user (`IsAdminOrSuperAdmin` customers/properties, `IsStaffOrAbove` bookings,
  `IsStaffReadAdminWrite` payments, `IsHRManagement` hr, `IsFinanceOrAbove` finance,
  `IsAdminOrReadOnly` core). No `is_staff`/role check on reads.
- **Severity: Critical.** A customer can read the entire business roster (PII + financials).

## Priority 2 — High

### F4 — CSRF via GET on expense approve/reject/mark-paid
- **Status: CONFIRMED (live).**
- **Proof:** created a `pending` Expense, then a plain `GET /expenses/<id>/approve/` as a
  finance user → HTTP 200, `expense.status` became `approved`, and the ledger row was posted.
- **Root cause:** `expense_approve_view` / `expense_mark_paid_view` / `expense_reject_view`
  have no `request.method == 'POST'` check (`expenses/views.py:116-178`). GET skips CSRF.
- **Severity: High.** A crafted link/img can approve/pay/reject an expense without CSRF.

### F5 — Booking reopen conflict (two active bookings on one re-sold plot)
- **Status: CODE-CONFIRMED.** `booking_reopen_view` sets the plot to `reserved` with no check
  that it wasn't re-booked (`core/views.py:1307`). To be re-confirmed by test `BOOK-EC-01`.
- **Severity: High.**

### F6 — Money-flow races / missing status guards (payments)
- **Status: CODE-CONFIRMED.** `payment_reverse_view` has no status guard (reversing a
  draft/pending payment corrupts `advance_paid`/installment balances) (`payments/views_workflow.py:127-153`);
  `refund_approve_view` lacks a `status=='pending'` check (double-approve reduces `advance_paid`
  twice) (`payments/views_workflow.py:193-212`); verify has a check-then-act race with no
  `select_for_update` (`payments/views_workflow.py:69`, `api_views.py:99-167`). Re-confirmed by
  tests `PAY-EC-01/02/03`.
- **Severity: High.**

### F7 — Stored XSS in AI insights/history + AI HR chat
- **Status: CODE-CONFIRMED (static sink).** `templates/ai/insights.html:257-261` injects an
  unescaped LLM `result` via `innerHTML`; `templates/ai/hr.html:70` uses `insertAdjacentHTML`
  with a partial escape (only `&lt;`). Live trigger needs a crafted LLM response / stored payload.
  Re-confirmed by tests `AI-SEC-01`, `FE-SEC-01/02`.
- **Severity: High.**

### F8 — HR API read-open + leave status writable
- **Status: CONFIRMED (live read) + CODE-CONFIRMED (status).**
- **Proof (read):** `qa_customer` read `/api/employees/` → 200 with `cnic`, `phone`, `salaries`.
- **Proof (status):** `LeaveSerializer.read_only_fields = ['id','applied_on','approved_by']`
  (`hr/serializers.py:146-151`) — `status` is writable, so a client can PATCH `status='approved'`
  without the `approve` action's `approved_by` stamp.
- **Severity: High.**

## Evidence artifacts
- `tests/repro/evidence-R1-privesc-sales-to-superadmin.png` — screenshot (R1 dashboard context).
- `tests/repro/reproduce_findings.py` — standalone repro script (R6 CSRF-via-GET).
- Browser `fetch` transcripts captured in the session for R1/R2/R3.
