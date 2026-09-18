# Accounting Module — Design & Decisions

> Status: **Accounting module implemented end-to-end.** Phase 1 foundation; the
> Phase 2 writer migration for **all** money movements (`Payment`,
> `OfficeExpense`, `ProjectCost`, `Refund`, `Expense`, `SalaryPayment`); the API
> layer (§3.13); and the ledger report + UI screens (§3.14) are done. Models in
> `finance/models.py` (migrations `finance/0006`, `finance/0007_voucherauditlog`);
> writers in `finance/accounting.py`; report engine in `finance/reports.py`; API
> in `finance/api_views.py` + `finance/serializers.py`; UI in `finance/views.py`
> + `templates/finance/`. §5 is fully resolved **and implemented** (§3.12,
> §3.15–§3.18). This document is the source of truth for the module — decisions
> must not live only in chat history.

## 1. Source requirement

From `ERP Accounts Module.docx` (client brief):

- Complete chart of accounts with add/edit of account heads down to **level 4**.
- **Cash Receipt / Cash Payment / Bank Receipt / Bank Payment / Journal Voucher**
  for daily transactions — debit account, credit account, and narration.
- A **ledger for each account head** showing debit, credit, and balance
  **as per the nature** of the ledger.
- **Date-wise ledger report** to view transactions per ledger.
- Payment received from a customer must link to the respective ledger **by mode
  of payment**.
- Expenses paid must link to the respective ledger **by mode of payment**.
- Other costs (project cost, development cost) must link to the respective
  **expense ledger by mode of payment**.
- Every mature new customer account must link to the chart of accounts.
- Each voucher must be **authored/posted**: a user inputs it, a supervisor posts
  it after cross-check. **Once posted, data cannot be edited unless unlocked by
  the supervisor.**

## 2. Status / phasing

- **Phase 1 — Foundation (done in the working tree, uncommitted):**
  `AccountHead`, `Voucher`, `VoucherLine` models + constraints + validation +
  migration (`finance/0006`). No views, URLs, serializers, or writer integration
  yet.
- **Phase 2 — Integration (done):** auto-vouchers for
  `Payment`, `OfficeExpense`, `ProjectCost` (§3.11) and `Refund` / `Expense` /
  `SalaryPayment` (§3.15–§3.17); API (§3.13); ledger report + exports and the
  voucher/head/ledger UI (§3.14); the customer↔head "mature" trigger (§3.12,
  §3.18).
- **Confirmed:** the writer switch ships in the **same PR** as the models, and
  `AccountTransaction` is deprecated outright — no bridge, no dual-write (see
  §3.7). Headline revenue is unaffected and stays separate (see §3.8, §6).

## 3. Decisions (locked)

### 3.1 Chart of accounts

- `AccountHead` is a self-referential tree, **max 4 levels** (`level` walks
  `parent`; `clean()` rejects depth > 4).
- `nature` is `debit` normal or `credit` normal; `AccountHead.balance` returns a
  signed balance respecting that nature (and powers ledger balances).
- **Only leaf accounts are postable.** Creating a child auto-clears
  `parent.is_leaf` (a head with children is non-leaf); deleting the last child
  restores it. Posting to a non-leaf head is rejected by `VoucherLine.clean()`.
- `is_active` allows retiring an account without deleting history;
  `AccountHead` is `PROTECT`ed by voucher lines so history cannot be orphaned.

### 3.2 Voucher lifecycle & edit lock

Two states only — **`draft`** and **`posted`** — plus a separate lock flag:

| Field | Meaning |
|---|---|
| `status` | `draft` or `posted`. |
| `is_locked` | Set **True** on posting. |
| `locked_by` / `locked_at` | Set on posting (who/when holds the lock). |
| `unlocked_by` / `unlocked_at` | Set on unlock. |
| `unlock_reason` | **Mandatory** free text recorded on unlock. |

Rules:

- **Editable iff `status == 'draft'` or (`status == 'posted'` and
  `is_locked == False`)** — exposed as `Voucher.is_editable`. Enforced by
  `Voucher.clean()` and `VoucherLine.clean()`.
- **Post** (`Voucher.post(user)`): validates balanced debit/credit, at least one
  line, each line valid, and all heads are leaves; then atomically sets
  `status='posted'`, `is_locked=True`, `locked_by=user`, `locked_at=now`.
  Re-posting an **unlocked** posted voucher is allowed and **re-locks** it,
  refreshing `locked_by`/`locked_at`.
- **Unlock** (`Voucher.unlock(user, reason)`): allowed only on a posted, locked
  voucher; requires a non-empty `reason`; flips `is_locked=False` and records
  `unlocked_by`/`unlocked_at`/`unlock_reason`. **`status` stays `posted`** — it
  does not revert to draft.
- A voucher that is posted **and** locked cannot be posted again
  (`is_posted_locked` guard).
- The earlier draft's `posted_by`/`posted_at` were folded into
  `locked_by`/`locked_at`, since both are set at the single moment of posting;
  keeping both pairs would create two sources of truth. Re-post refreshes
  `locked_*`; `unlocked_*`/`unlock_reason` retain the most recent unlock for
  audit.

### 3.3 Voucher lines

- `VoucherLine` has exactly one non-zero side: enforced by both
  `clean()` and DB `CheckConstraint voucher_line_single_side_nonzero`
  (`(debit>0 & credit=0) | (credit>0 & debit=0)`).
- Amounts are `Decimal(15,2)`, non-negative; a line must reference a **leaf**
  `AccountHead`.
- Lines are `CASCADE`-deleted with the voucher; heads are `PROTECT`ed.

### 3.4 Voucher numbering

- `voucher_number` is `{TYPE}-{NNNNN}` per type (e.g. `CP-00001`, `JV-00042`),
  generated in `Voucher.save()` under `select_for_update` on the last row of
  the same type. Immutable/auto (`editable=False`, `unique=True`).

### 3.5 Voucher ↔ source object linkage (idempotency)

- Auto-generated vouchers reference their source via `reference_type`
  (e.g. `'Payment'`, `'OfficeExpense'`, `'ProjectCost'`, `'Refund'`,
  `'SalaryPayment'`) and `reference_id`.
- Conditional `UniqueConstraint voucher_source_unique`
  (`reference_type`, `reference_id` where `reference_id IS NOT NULL`) guarantees
  **one source object → at most one voucher**. Manual vouchers with a null
  reference are exempt. This is the idempotency mechanism replacing the old
  `AccountTransaction` (`reference_type`, `reference_id`) unique constraint.

### 3.6 Permissions (post vs unlock)

Mirror the office-expense approve/pay pattern:

- **Post** — any authorized finance user: `@finance_or_above` (HTML) /
  `IsFinanceOrAbove` + role set `(super_admin, admin, management, accounts)`
  (API).
- **Unlock** — **supervisor only**: `@management_or_above` (HTML) /
  `(super_admin, admin, management)` (API), matching the delete/approve gate.
- Model methods (`post`, `unlock`) do not check roles themselves; gating is a
  view/serializer concern, as elsewhere in the ERP. Phase 2 must wire these
  gates when the voucher endpoints are added.

### 3.7 `AccountTransaction` deprecation — no bridge (confirmed)

- `AccountTransaction` is **deprecated outright**: no compatibility bridge, no
  dual-write transition, no read-only sync.
- Rationale: the system is in development; there is no production or sensitive
  data to preserve.
- `OfficeExpense.post_to_ledger()` and `ProjectCost.post_to_ledger()` **stop
  writing to `AccountTransaction` in the same PR that adds
  `Voucher`/`VoucherLine`** — the old ledger and the new voucher ledger are not
  written in parallel.

### 3.8 Ledger/voucher income is never "revenue" (confirmed)

- Payment → Voucher posting was traced and confirmed safe: every
  `advance_paid`/`Payment`-based revenue read (dashboard, financial reports, AI
  snapshot, API summary) was checked — **none** currently sums
  `AccountTransaction`/ledger data into a revenue figure.
- Ledger/voucher income **must never** be summed into either the dashboard's
  `advance_paid`-based revenue or the financial-reports page's `Payment`-based
  revenue. Those two remain separate and pre-existing; reconciling them is **out
  of scope**.
- Voucher income is presented as **its own line**, not relabeled "revenue".

### 3.9 ProjectCost workflow & posting gate (confirmed)

- Workflow is **Draft → Approved → Paid**. Only **Paid** costs count toward
  budget/actual (`ProjectBudget.total_actual` already filters `status='paid'`).
- Only **Paid** costs auto-post to the ledger. `ProjectCost.post_to_ledger()`
  fires **exactly at the Paid transition and nowhere else** — the writer hook
  depends on this.
- Matches client brief `ERP Feedback by Mehboob.docx` #13 ("Draft → Approved →
  Paid ... only Paid Costs count ... Paid Project Costs automatically reflect in
  the Financial Ledger").

### 3.10 Voucher audit history (confirmed)

- Add an append-only **`VoucherAuditLog`** — **one row per lifecycle event**
  (`posted`, `unlocked`, `reposted`, and draft creation), each with voucher FK,
  event, actor, timestamp, and reason where applicable. `Voucher.post()` /
  `Voucher.unlock()` write a row.
- Rationale: the fields on `Voucher` (`locked_*`, `unlocked_*`, `unlock_reason`)
  retain only the **latest** unlock; a financial system needs the **full**
  history of every supervisor unlock (who/when/why). Retrofitting after the
  writer migration would require backfilling every auto-posted voucher, so it is
  added now.
- `Voucher`'s lock fields remain the fast current-state cache; the log is the
  history.

### 3.11 Auto-writer heads & posting points (implemented)

- Canonical heads resolved/created by code (`finance/accounting.py`):
  `1000 Cash`, `1010 Bank`, `1100 Accounts Receivable`, `5000 Office Expenses`,
  `5100 Project Costs`, `5200 Salaries`.
- Voucher type by direction: **CR/BR** for receipts, **CP/BP** for payments
  (`voucher_type_for`); `cash` → cash head/CR/CP, any other method → bank
  head/BR/BP.
- **`Payment`** posts a Cash/Bank **Receipt** voucher on `save()` (idempotent by
  `reference_type='Payment'`); it does **not** touch `advance_paid`/`amount_paid`.
- **`OfficeExpense.post_to_ledger()`** posts a Cash/Bank **Payment** voucher and
  no longer writes `AccountTransaction` (`reference_type='OfficeExpense'`).
- **`ProjectCost.post_to_ledger()`** posts the same only when `status == 'paid'`
  (spec §3.9); otherwise a no-op (`reference_type='ProjectCost'`). It assumes the
  cash head until `ProjectCost` gains a `payment_method` field.
- All hooks go through `post_source_voucher(...)`, which returns the existing
  voucher untouched if one already exists — re-saving a source never duplicates.

### 3.12 Customer → AccountHead linkage (implemented)

- **Shape:** a nullable **ForeignKey** on `Customer`:
  `account_head = ForeignKey('finance.AccountHead', null=True, blank=True,
  on_delete=SET_NULL, related_name='customers')`. It is a FK (not a one-to-one)
  because the head is the **shared** `1100` control account — many customers
  link to the same head.
- **Trigger (implemented):** `Booking.save()` calls
  `Customer.link_account_head()` on the **confirmed** transition (§3.18);
  pending/cancelled bookings do not link. Migration
  `customers/0006_customer_account_head` (nullable `AddField`, no backfill).

### 3.13 API surface (implemented)

Registered on the DRF router (`api/urls.py`); all under `/api/`.

- `vouchers/` — `GET`/`POST` list+create (nested `lines`); `GET`/`PATCH`/`DELETE`
  `vouchers/{id}/`. Edits/deletes are **draft-only**; auto-generated vouchers
  (`reference_id` set) are read-only here. Gated by a **strict** `IsFinanceRole`
  (finance roles for every method — unlike `IsFinanceOrAbove`, no read leak to
  other staff).
- `POST vouchers/{id}/post/` — finance gate; validates balance and locks.
- `POST vouchers/{id}/unlock/` — `IsManagementOrAbove` (supervisor only);
  requires `reason` in the body; writes a `VoucherAuditLog` row.
- `GET vouchers/{id}/audit/` — full `VoucherAuditLog` history for the voucher.
- `account-heads/` — CRUD; levels 1–4, parent restricted to a valid level below
  (and not self/descendant); delete blocked when the head has children or any
  posted voucher line. Gated by `IsFinanceRole`.

### 3.14 Ledger report & UI (implemented)

- **Report engine** — `finance/reports.py::build_ledger_report(head, date_from,
  date_to)`: nature-aware running balance (debit-normal = debit − credit;
  credit-normal = credit − debit), opening balance from pre-range entries,
  leaf-or-roll-up head selection, posted vouchers only.
- **Ledger screen** (`ledger_view`, rewritten from the old `AccountTransaction`
  list): head + date-range filters, opening/debit/credit/closing stats, a
  running-balance column, labeled **"Ledger balance"** (never "Revenue" — §3.8).
- **Exports**: `ledger/export/excel/` (openpyxl `.xlsx`) and
  `ledger/export/pdf/` (xhtml2pdf). `openpyxl==3.1.5` added to requirements.
- **Voucher screens**: list (type/status filters), detail (lines + audit history
  + post/unlock), create (line formset). Gated by `finance_or_above`; unlock by
  `management_or_above` and requires a reason.
- **Chart of accounts screen**: levels 1–4 tree with add/edit/delete.
- **FIN-EC-03 warning**: editing an already-paid office expense shows a banner
  that the edit **will not rewrite** the posted voucher, linking to the voucher
  for supervisor unlock.

### 3.15 Refund writer (confirmed)

- A refund posts an **independent payment voucher** (CP/BP) — it does **not**
  reverse or mutate the original receipt voucher. Rationale: vouchers are
  immutable and one-source→one-voucher; the receipt must remain intact history.
- Lines economically reverse the receipt: **debit `1100 Accounts Receivable`,
  credit Cash/Bank** (resolved from `refund_method`). Reference
  `('Refund', pk)`; fires from `Refund.process()`; idempotent.

### 3.16 Expense writer (confirmed)

- `expenses.Expense` is a **distinct model** from `OfficeExpense` (project-scoped,
  in the `expenses` app). It has **no `payment_method`** field, so the head
  defaults to **Cash** (same ruling as ProjectCost, §3.18).
- Posts a Cash/Bank Payment voucher against **`5100 Project Costs`** (matching
  its legacy `transaction_type='project_cost'` mapping). Reference
  `('Expense', pk)`; idempotent.

### 3.17 SalaryPayment writer (confirmed)

- `SalaryPayment` has a `method` field → Cash/Bank resolved from it.
- Posts against a new **`5200 Salaries`** head, which is a **top-level
  debit-normal leaf** — deliberately **not** a child of `5000 Office Expenses`.
  Making 5000 a parent would flip it to non-leaf and break the leaf-only posting
  rule used by the already-wired `OfficeExpense` writer.
- Reference `('SalaryPayment', pk)`; idempotent.

### 3.18 §5 closeout (confirmed)

- **Customer "mature" trigger:** a customer becomes mature when they have **at
  least one confirmed booking** (`booking.status` confirmed or beyond — not
  pending/cancelled). At that point `Customer.account_head` links to the shared
  **`1100 Accounts Receivable`** control head (get-or-create). **No per-customer
  head is created**: a child under 1100 would make 1100 non-leaf and break the
  leaf-only posting rule for the Payment/Refund writers; customer-level detail is
  already served by `CustomerLedgerEntry`. *(Trigger implementation is a
  follow-up; the decision is fixed.)*
- **ProjectCost default method:** falls back to the **Cash** head (`1000`) until
  `ProjectCost` gains a `payment_method` field; once it does, a method should be
  required at the Paid transition.
- **Hard line guard:** refers to the brief's *"once posted, data cannot be edited
  unless unlocked by the supervisor."* Enforcement rule: **model-level hard
  guards** — `Voucher.save()` refuses a non-`update_fields` save of a posted and
  locked voucher, and `VoucherLine.save()` / `delete()` refuse when the parent
  voucher is not editable. `post()` / `unlock()` are exempt (they save with
  explicit `update_fields`). This complements `clean()`, which `save()` does not
  call.

## 4. Phase 2 integration plan (to be detailed)

1. **Auto-generation** — on the qualifying transition of each source object
   (Payment verified, OfficeExpense paid, ProjectCost paid, Refund processed,
   SalaryPayment paid), create exactly one `Voucher` + `VoucherLine`s via the
   `reference_type`/`reference_id` idempotency key, and post it. This removes
   the current `post_to_ledger()` / `AccountTransaction` writers.
2. **Mode of payment → head** — map cash vs bank (and receipt vs payment) to the
   appropriate Cash/Bank `AccountHead` so customer payments, expenses, and
   project/development costs hit the correct ledger by mode.
3. **Customer ↔ chart of accounts** — a nullable one-to-one on `Customer`
   (§3.12); the linking trigger waits on the "mature" definition (§5).
4. **UI** — voucher entry/edit, post, supervisor unlock (with reason), per-head
   ledger with running balance by nature, and a date-wise ledger report.
5. **Removal of `AccountTransaction`** — writers stop in the same PR as the
   models (§3.7); the old ledger is dropped once no readers depend on it
   (explicitly **no** sync bridge).

## 5. Gaps / open questions

_All prior items are resolved **and implemented in code** — see §3.12 (customer
linkage + trigger), §3.15 (Refund), §3.16 (Expense), §3.17 (SalaryPayment), and
§3.18 (mature trigger, ProjectCost default method, hard line guard). No open
questions remain; new items are added here as they arise._

## 6. Related, unchanged design facts

- **Revenue = sum of `Booking.advance_paid`** across all bookings — the single
  source of truth for headline revenue; deliberately **not** `Payment` rows. The
  financial-reports page separately uses `Payment`-based revenue. Neither may
  ever include ledger/voucher income (§3.8).
- Existing money-movement workflows (Refund `pending → approved → processed |
  rejected`; Expense `pending → approved → paid | rejected`) keep their state
  machines; Phase 2 only changes *how they record* to the books.
- `AuditLog` continues to record create/update/delete on finance actions.
