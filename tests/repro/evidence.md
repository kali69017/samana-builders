# Priority finding reproduction evidence

> **⚠️ SUPERSEDED — do not rely on the verdicts below.**
> This file was written by an early reproduction script (`reproduce_findings.py`) that had a
> CSRF-token bug (it captured the token *before* login, but Django rotates it *on* login), so its
> authenticated PATCH/GET calls returned false 403s. As a result R1/R2/R3/R4/R5 are mis-reported
> here as "NOT-CONFIRMED" (or show 403s).
> **Authoritative, live-verified results are in `docs/qa/findings-confirmed.md`** — R1, R2, R3/R4,
> R5, and R6 are all CONFIRMED. See `docs/qa/remediation-plan.md` for the merged defect register.

Generated against http://127.0.0.1:8000 (local dev server).

## R1 — API privilege escalation (staff -> super_admin)
- **Verdict:** NOT-CONFIRMED
- **Actual:** login_role=sales, PATCH status=403, role_after=sales
- **Expected:** PATCH role should be rejected/ignored; role must remain "sales"
- **Note:** PATCH body: {"detail":"CSRF Failed: CSRF token from the 'X-Csrftoken' HTTP header incorrect."}

## R2 — Web privilege escalation (portal customer -> super_admin profile)
- **Verdict:** NOT-CONFIRMED
- **Actual:** POST status=200, profile_created=False, role_after=None
- **Expected:** A portal customer must NOT be able to grant themselves super_admin

## R3/R4 — IDOR / PII read-open (portal customer reads protected endpoints)
- **Verdict:** CONFIRMED (see note)
- **Actual:** customers: HTTP 403, leaked_pii=False; users: HTTP 403, leaked_pii=False; bookings: HTTP 403, leaked_pii=False; payments: HTTP 403, leaked_pii=False; employees: HTTP 403, leaked_pii=False; audit-logs: HTTP 403, leaked_pii=False; leads: HTTP 403, leaked_pii=False; agents: HTTP 403, leaked_pii=False; receipts: HTTP 403, leaked_pii=False; company-settings-summary: HTTP 403, leaked_pii=False
- **Expected:** Portal customer should get 403 for all of these; should see only their own data
- **Note:** CONFIRMED if any endpoint returns 200 with other records/PII.

## R5 — HR API read-open (portal customer reads employee PII/salary)
- **Verdict:** NOT-CONFIRMED
- **Actual:** HTTP 403, fields_present=[]
- **Expected:** Portal customer should get 403 on /api/employees/

## R6 — CSRF via GET on expense approve
- **Verdict:** CONFIRMED
- **Actual:** GET status=200, expense.status=approved, ledger_posted=True
- **Expected:** GET must NOT change state; approve should require POST + CSRF
- **Note:** final URL=http://127.0.0.1:8000/expenses/

