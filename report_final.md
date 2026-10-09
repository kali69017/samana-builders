# Samana Builders ERP — SendPK Review Remediation & Exploratory QA Report

Date: 2026-10-09 · Branch: `main` · Base review commit: `6faf054` (SendPK fixed-sms template delivery)

## 1. Mission

1. Fix every finding from the code review of `6faf054` (SendPK SMS integration).
2. Verify each fix with fresh evidence (compile, targeted + full Django suite, and a live SendPK send).
3. Push all work to GitHub (`origin/main`) using the contributing recipe.
4. Run exploratory testing over the full ERP and produce this report.

Constraints honoured: **no late-fee wording anywhere**; headline revenue = `sum(Booking.advance_paid)` (never `Payment` rows); `docs/`/`specs/` QA artifacts updated rather than deleted.

---

## 2. Review findings → fixes

All 9 findings from the `6faf054` review were addressed in `feb2689` (notifications remediation), verified (913 Django tests green + live send), and pushed.

| # | Finding (review of `6faf054`) | Fix | Verified |
|---|---|---|---|
| 1 | `send_typed()` shipped raw `#placeholder#` slots when the message filled an expected variable with an empty value | Validates the template's expected variables; a missing required slot refuses to send and **names the variable** in `log.error_message` | `SMSServiceSendTypedTest` |
| 2 | The one conditional slot (`next_installment`) could send a raw placeholder | Falls back to `'none due'` when there is no next-installment date | `SMSServiceSendTypedTest` |
| 3 | Unconfigured template error did not say which key to set | Error now names the exact `SENDPK_TEMPLATE_*` setting | `SMSServiceSendTypedTest` |
| 4 | Transport not uniform (token-in-URL risk / reply parsing duplicated) | Unified on **POST** so `api_key` stays out of the request URL; JSON and plain-text reply handling shared via `_interpret()` | Live A/B (`OK ID:655087f4-…`, evidence file `verify_sendpk_ab.py`) |
| 5 | Free-text SMS path (no template) | **Deliberately retained** — this account is fixed-sms and the provider rejects free text. Send is refused with a clear message surfaced in the Notification Center + UI warning; classified as documented behaviour, no code change | Manual-send UI (disabled-channel warning) |
| 6 | A switched-off provider was recorded `sent`, inflating the "Delivered" stat | New `skipped` status (+ migration `notifications/0004`): disabled channels record `skipped` with `sent_at=None`; Notification Center gained a Skipped stat card + filter option; manual sends warn "Not sent: … disabled on this deployment." | Live: SMS manual send → `Skipped: 1` + warning row |
| 7 | `send()` / `check_balance()` defaults inconsistent | Defaults tightened to `False` | `SMSServiceSendTypedTest`, provider tests |
| 8 | Unconditional assertions / loose indent | Indent fixed; `NotificationMessageTest` guarded with `override_settings(**SMS_ON)` | Full suite |
| 9 | No automated coverage for the fixed paths; no guard against live sends | Added `SMSServiceSendTypedTest`, `NotificationStatusRecordingTest`, `ProviderGuardTest`, `NotificationCenterFilterTest` (+18 tests net: 895 → **913**); `settings.py` `TESTING` guard forces every provider off under `manage.py test` | Full suite 913 pass |

**Bonus fix found during exploratory sweep:** `notifications_view` filtered *after* slicing → `TypeError: Cannot filter a query once a slice has been taken.` 500'd on every Notification Center filter. Now filters first, then slices (regression test: `NotificationCenterFilterTest`).

---

## 3. Verification evidence

| Check | Result |
|---|---|
| `py_compile` on changed modules | clean |
| Targeted suite (`notifications` + `finance`) | **268 passed** |
| Full Django suite | **913 passed** (was 895; +18 new tests) |
| Live SendPK send (POST transport) | `OK ID:655087f4-…` — earlier "OTP Messages Are Not Allowed!" was test *content* (`POST Verify`), not the transport |
| Secret scan of pushed diff | clean (only `os.environ.get` refs, no keys) |

---

## 4. Shipped commits (all on `origin/main`)

- `feb2689` — notifications/SendPK remediation (findings 1–9) + settings `TESTING` guard.
- `7fcf9a2` — finance ledger remediation (independent, revertible): `ProjectCost.status` default + approve/pay, `backfill_ledger_vouchers`, `ledger_out_of_sync` surfacing, vouchers, finance E2E specs.
- `094bd7f` — docs + finance template `.docx` exports.
- `12e7c5e` — exploratory QA commit: Notification Center Skipped stat card, dead `.top-bar` button relocated to `.page-actions` (manual send reachable), `RUNBOOK.md` E2E env contract, `notifications_analysis.md` findings marked FIXED, `notifications.spec.ts` updated to the honest skipped-based contract.
- `ddbb1ba` — this report (`report_final.md`).

---

## 5. Exploratory testing — coverage & findings

Environment: dev server at `127.0.0.1:8000`, `DJANGO_DEBUG=True`, launched with `*_ENABLED=False` so create/payment actions can never fire live messages (also exercises the new `skipped` path in the real UI). Rich dev DB (200 customers, 10 bookings, 18 payments, 29 vouchers, ~1700 notification logs).

### 5.1 Passed (no issues)

- **URL probe:** 43 core ERP pages → all HTTP 200, no tracebacks. (`/api/finance/vouchers/` and `/receipts/` 404s were my *guessed* paths — real routes are `/api/vouchers/` and `receipts/<pk>/`.)
- **Dashboard:** KPIs render; `/dashboard/revenue-trend/` returns 200 JSON.
- **Customers:** list, detail (CUS-id), profile PDF (200, `application/pdf`, ~466 KB).
- **Bookings:** detail (BKG-id), invoice PDF at `/bookings/<pk>/invoice/` (200, ~470 KB).
- **Payments:** detail (PAY-id); receipt detail + receipt PDF at `/receipts/<pk>/pdf/` (200, ~466 KB).
- **Notification Center:** stats render; channel/type/status filters all 200 with data (`?status=skipped` surface the skipped rows); manual SMS send with providers off → **Skipped** row + honest warning.
- **Finance:** ledger trial balance shows **Balanced**; per-account running balance arithmetic correct (−330,000 + 9,296.88 → −320,703.12); exercised **office expense 53 → Approve → Pay → voucher lands in Cash ledger (Rs. 4,321)** end-to-end; project-cost status badges render correctly.
- **API smoke (admin):** `/api/customers/`, `/api/bookings/`, `/api/payments/`, `/api/leads/`, `/api/vouchers/`, `/api/company-settings/summary/` → all 200 JSON.
- **Console:** zero console errors on clean page loads (the 404 console entries were my own wrong test URLs).

### 5.2 Found & fixed during exploratory

1. **Missing "Skipped" stat card** — `skipped_count` was in context but no template card. Added `⏭ Skipped` card (indigo) to `notifications/notifications.html`.
2. **Manual-send button unreachable** — `erp.css:756` sets `.top-bar { display:none }` ("superseded by the global topbar"), so the only "Send Notification" trigger was dead UI and the manual-send modal had **no visible entry point**. Relocated the button into `.page-actions` beside the header and removed the dead hidden `.top-bar` block. Verified: visible button opens the modal at any viewport.
3. **Test/doc drift from the honest `skipped` contract** — `notifications.spec.ts` HP-09/HP-10 asserted the old inflated "sent successfully" flashes; EC-01's selector became ambiguous now that filters don't 500. Updated to the fixed behaviour; EC-01 now asserts the fixed filter (was RED). `notifications_analysis.md` §4/§6 findings marked FIXED. `RUNBOOK.md` §2 now codifies the providers-off E2E server.

### 5.3 Live E2E suite state (Playwright, notifications module)

**19 passed · 8 skipped · 6 failed.** The 6 failures are all **pre-existing, intentionally-RED** tests for confirmed bugs (AGENTS.md policy: don't weaken them):

| Test | Confirmed bug (still open) |
|---|---|
| NOTIF-HP-03 | Customer welcome also fires an **SMS** channel when a phone exists but no email — the test asserts no row; channel-selection behaviour predates this session (untouched by the remediation; flag for product decision) |
| NOTIF-EC-08 | Type dropdown lists 7 of 8 types, omits `customer_welcome` |
| NOTIF-EC-05 | `recipient_name` `CharField(200)` stores 201-char full names un-truncated on SQLite |
| NOTIF-SEC-01 | Manual send `/notifications/send/` has no rate limiting (arbitrary `recipient_contact` + message from any management user) |
| NOTIF-SEC-03 | `NotificationLog` stores PII (emails/phones/amounts) in plaintext, visible to all management |
| NOTIF-SEC-05 | No object-level scoping on the log |

The remediation **flipped four previously-RED tests green**: NOTIF-EC-01 (filter 500 → fixed), NOTIF-EC-02 (disabled email recorded `sent` → now `skipped`), NOTIF-EC-03 (disabled SMS recorded `sent` → now `skipped`), NOTIF-EC-04 (WhatsApp no-op recorded `sent` → now `skipped`).

### 5.4 Observations (no change made)

- `EmailService.send` still defaults `EMAIL_ENABLED` via `getattr(..., True)` — neutralized by the `TESTING` guard + providers-off dev server, but the default is the wrong way round (latent inconsistency, flagged for cleanup).
- The dead `.top-bar` pattern exists in 40+ templates but is mostly harmless: other pages keep their real actions in `.page-actions`; only notifications trapped its action there.
- WhatsApp is a `wa.me` click-to-chat link, not a delivery channel; SMS branding mask still `TEXT SMS` (shared route) pending PTA approval.

---

## 6. Outstanding (outside this task's scope, tracked)

- WhatsApp token rotation (user-side) and Phase-2 webhooks (app publication).
- SEC findings in §5.3 (rate limiting, PII-at-rest, object scoping) — real security gaps, documented RED.
- Type-dropdown omission + `recipient_name` overflow + welcome-channel premise (§5.3).