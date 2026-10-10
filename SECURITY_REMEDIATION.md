# Security remediation — final status (2026-10-10)

Production-readiness hardening. Full Django suite green; all documented Critical/High confirmed
findings closed and verified (regression-guarded in `api/tests_permissions.py`,
`notifications/tests_security.py`).

## Blocker status

| ID | Finding | Status |
|---|---|---|
| F1 | API privesc: staff PATCH role → super_admin | CLOSED (pre-existing fix verified) — serializer `read_only_fields` |
| F2 | Web privesc: portal POST /profile/ role | CLOSED (pre-existing fix verified) — form `fields=['theme']` |
| F3 | Systemic IDOR/PII read-open (all ViewSets) | CLOSED — least-privilege read matrix (`user_role_allows`) + portal dashboard redirect |
| F4 | CSRF-via-GET expense mutations | CLOSED (pre-existing `@require_POST` verified) |
| F5 | Booking reopen conflict (re-sold plot) | CLOSED (pre-existing conflict guard verified) — tested |
| F6 | Payment money-flow races / missing guards | CLOSED — pending-only verify + `select_for_update` (API+web), reverse/refund row locks |
| F7 | Stored XSS (AI insights/hr) | CLOSED (pre-existing escape/textContent verified) |
| F8 | HR read-open + leave status writable | CLOSED (pre-existing read_only verified) + reads tightened to HR roles |
| N-SEC-01 | Manual send rate limiting | CLOSED — per-recipient 429 throttle |
| N-SEC-03 | NotificationLog PII listable | CLOSED — `mask_contact` + full view admin-only |
| N-SEC-05 | No object-level scoping on log | CLOSED — scoped to `created_by` |
| FIN-SEC-03 | draft→paid transition guard | CLOSED — pay requires `approved` (API+web) |

## Verification

- Django suite: **935+ tests green** (`manage.py test` exit 0).
- Security tests: `api.tests_permissions` (16) + `notifications.tests_security` (11) pass.
- E2E flips (verified green): NOTIF-SEC-01/03/05, EC-03/04/09, HP-09/10; FIN-SEC-01/03;
  PAY-HP-05; CUS-SEC-02/03/04/05/06, CUS-HP-07.
- Portal dashboard redirect verified live (`/portal/` landing).

## Out of code scope (business/external)
- WhatsApp token rotation + Phase-2 webhooks (Meta app).
- PTA branded "SAMANA" SMS mask.
- `report_final.md` §5.4 finance E2E spec drift (test-only; product Verified healthy).