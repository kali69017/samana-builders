import { APIRequestContext, expect } from '@playwright/test';

/**
 * Ledger read helpers backed by the Voucher API.
 *
 * The old account-transactions API endpoint was removed. The ledger is now
 * exposed through `/api/vouchers/`, where one auto-generated voucher represents
 * one source event (payment, refund, expense, payroll, delivery). The adapter
 * below keeps the old row shape (amount/direction/transaction_type) so existing
 * assertions stay readable, but every value comes from the voucher and its
 * posted lines.
 *
 * There is no voucher delete endpoint. Cleanup helpers must not try to remove
 * ledger rows; auto-generated vouchers are immutable by design.
 */

export interface VoucherLine {
  id?: number;
  account_head: number;
  account_head_code?: string;
  account_head_name?: string;
  debit: string;
  credit: string;
  narration: string;
}

export interface Voucher {
  id: number;
  voucher_number: string;
  voucher_type: string;
  date: string;
  narration?: string;
  status: string;
  reference_type: string;
  reference_id: number | null;
  lines: VoucherLine[];
}

export type LedgerDirection = 'in' | 'out' | '';

export interface LedgerRow {
  id: number;
  amount: string;
  direction: LedgerDirection;
  transaction_type: string;
  category: string;
  date: string;
  narration: string;
  reference_type: string;
  reference_id: number | null;
  voucher_number: string;
  voucher_type: string;
  status: string;
  debit: string;
  credit: string;
}

/** Rough map from the voucher source to the old transaction_type values. */
const TYPE_BY_REFERENCE: Record<string, string> = {
  Expense: 'office_expense',
  OfficeExpense: 'office_expense',
  ProjectCost: 'project_cost',
  SalaryPayment: 'payroll',
  Refund: 'refund',
  Payment: 'payment',
  PaymentReversal: 'payment_reversal',
  BookingDelivery: 'booking_delivery',
};

/** Sum a list of Decimal strings without floating-point drift. */
function sumDecimal(values: string[]): string {
  const cents = values.reduce((acc, value) => acc + Math.round(Number(value) * 100), 0);
  return (cents / 100).toFixed(2);
}

export function voucherDebit(voucher: Voucher): string {
  return sumDecimal(voucher.lines.map((line) => line.debit));
}

export function voucherCredit(voucher: Voucher): string {
  return sumDecimal(voucher.lines.map((line) => line.credit));
}

export function voucherDirection(voucher: Voucher): LedgerDirection {
  if (voucher.voucher_type === 'CR' || voucher.voucher_type === 'BR') return 'in';
  if (voucher.voucher_type === 'CP' || voucher.voucher_type === 'BP') return 'out';
  // Journal vouchers (booking delivery) move between two balance heads, so they
  // have no cash-in or cash-out direction.
  return '';
}

export function toLedgerRow(voucher: Voucher): LedgerRow {
  return {
    id: voucher.id,
    amount: voucherDebit(voucher),
    direction: voucherDirection(voucher),
    transaction_type: TYPE_BY_REFERENCE[voucher.reference_type] ?? 'manual',
    category: voucher.narration ?? '',
    date: voucher.date,
    narration: voucher.narration ?? '',
    reference_type: voucher.reference_type,
    reference_id: voucher.reference_id,
    voucher_number: voucher.voucher_number,
    voucher_type: voucher.voucher_type,
    status: voucher.status,
    debit: voucherDebit(voucher),
    credit: voucherCredit(voucher),
  };
}

export async function listVouchers(request: APIRequestContext): Promise<Voucher[]> {
  const res = await request.get('/api/vouchers/');
  expect(res.status(), 'GET /api/vouchers/').toBe(200);
  const body = await res.json();
  return Array.isArray(body) ? body : (body.results ?? []);
}

export async function vouchersFor(
  request: APIRequestContext,
  referenceType: string,
  referenceId: number,
  opts: { status?: string; voucherType?: string } = {},
): Promise<Voucher[]> {
  const vouchers = await listVouchers(request);
  return vouchers.filter((voucher) => {
    if (voucher.reference_type !== referenceType) return false;
    if (voucher.reference_id !== referenceId) return false;
    if (opts.status && voucher.status !== opts.status) return false;
    if (opts.voucherType && voucher.voucher_type !== opts.voucherType) return false;
    return true;
  });
}

/** Number of vouchers for one source record. */
export async function countVouchersFor(
  request: APIRequestContext,
  referenceType: string,
  referenceId: number,
  opts: { status?: string } = {},
): Promise<number> {
  return (await vouchersFor(request, referenceType, referenceId, opts)).length;
}

/** Ledger rows (voucher adapter) for one source record. */
export async function ledgerRowsFor(
  request: APIRequestContext,
  referenceType: string,
  referenceId: number,
  opts: { status?: string } = {},
): Promise<LedgerRow[]> {
  return (await vouchersFor(request, referenceType, referenceId, opts)).map(toLedgerRow);
}

/** Every ledger row of one mapped transaction type. */
export async function ledgerRowsByTransactionType(
  request: APIRequestContext,
  transactionType: string,
): Promise<LedgerRow[]> {
  return (await listVouchers(request))
    .map(toLedgerRow)
    .filter((row) => row.transaction_type === transactionType);
}

export async function listAccountHeads(request: APIRequestContext): Promise<any[]> {
  const res = await request.get('/api/account-heads/');
  expect(res.status(), 'GET /api/account-heads/').toBe(200);
  const body = await res.json();
  return Array.isArray(body) ? body : (body.results ?? []);
}

/** Resolve a seeded account head by its stable code (for example 5.1.1). */
export async function accountHeadByCode(
  request: APIRequestContext,
  code: string,
): Promise<any> {
  const head = (await listAccountHeads(request)).find((row) => row.code === code);
  expect(head, `account head ${code}`).toBeTruthy();
  return head;
}

/**
 * Create and post a manual journal voucher through the Voucher API.
 * Used only when a test needs a ledger entry with no source record.
 */
export async function createPostedJournalVoucher(
  request: APIRequestContext,
  token: string,
  opts: {
    date: string;
    narration: string;
    debitAccountHead: number;
    creditAccountHead: number;
    amount: string;
  },
): Promise<Voucher> {
  const created = await request.post('/api/vouchers/', {
    data: {
      voucher_type: 'JV',
      date: opts.date,
      narration: opts.narration,
      lines: [
        {
          account_head: opts.debitAccountHead,
          debit: opts.amount,
          credit: '0.00',
          narration: opts.narration,
        },
        {
          account_head: opts.creditAccountHead,
          debit: '0.00',
          credit: opts.amount,
          narration: opts.narration,
        },
      ],
    },
    headers: { 'X-CSRFToken': token },
  });
  expect(created.status(), await created.text()).toBe(201);
  const voucher = (await created.json()) as Voucher;

  const posted = await request.post(`/api/vouchers/${voucher.id}/post/`, {
    headers: { 'X-CSRFToken': token },
  });
  expect(posted.status(), await posted.text()).toBe(200);
  return (await posted.json()) as Voucher;
}
