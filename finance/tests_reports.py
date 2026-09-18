"""Tests for the nature-aware ledger report computation (spec §3)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from .models import AccountHead, Voucher, VoucherLine
from .reports import build_ledger_report


class LedgerReportTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('rep', 'r@example.com', 'pass12345')
        self.cash = AccountHead.objects.create(code='1000', name='Cash', nature='debit')
        self.capital = AccountHead.objects.create(code='3000', name='Capital', nature='credit')

    def _voucher(self, when, lines, vtype='JV', post=True):
        v = Voucher.objects.create(voucher_type=vtype, date=when, created_by=self.user)
        for head, debit, credit in lines:
            VoucherLine.objects.create(
                voucher=v, account_head=head, debit=Decimal(debit), credit=Decimal(credit))
        if post:
            v.post(self.user)
        return v

    def test_debit_normal_running_balance(self):
        self._voucher(date(2026, 1, 1), [(self.cash, '100', '0'), (self.capital, '0', '100')])
        self._voucher(date(2026, 1, 2), [(self.cash, '50', '0'), (self.capital, '0', '50')])
        report = build_ledger_report(head=self.cash)
        self.assertEqual(report['nature'], 'debit')
        self.assertEqual([r['balance'] for r in report['rows']], [Decimal('100'), Decimal('150')])
        self.assertEqual(report['total_debit'], Decimal('150'))
        self.assertEqual(report['closing_balance'], Decimal('150'))

    def test_credit_normal_running_balance(self):
        self._voucher(date(2026, 1, 1), [(self.cash, '100', '0'), (self.capital, '0', '100')])
        self._voucher(date(2026, 1, 2), [(self.cash, '50', '0'), (self.capital, '0', '50')])
        report = build_ledger_report(head=self.capital)
        self.assertEqual(report['nature'], 'credit')
        self.assertEqual([r['balance'] for r in report['rows']], [Decimal('100'), Decimal('150')])

    def test_date_range_sets_opening_balance(self):
        self._voucher(date(2026, 1, 1), [(self.cash, '100', '0'), (self.capital, '0', '100')])
        self._voucher(date(2026, 2, 1), [(self.cash, '50', '0'), (self.capital, '0', '50')])
        report = build_ledger_report(head=self.cash, date_from=date(2026, 2, 1))
        self.assertEqual(report['opening_balance'], Decimal('100'))
        self.assertEqual(len(report['rows']), 1)
        self.assertEqual(report['closing_balance'], Decimal('150'))

    def test_parent_head_rolls_up_descendant_leaves(self):
        bank = AccountHead.objects.create(code='1010', name='Bank', parent=self.cash)
        parent = AccountHead.objects.create(code='1500', name='Assets')
        # move cash + bank under the parent to make a roll-up
        self.cash.parent = parent
        self.cash.save()
        bank.parent = parent
        bank.save()
        self._voucher(date(2026, 1, 1), [(self.cash, '100', '0'), (self.capital, '0', '100')])
        self._voucher(date(2026, 1, 2), [(bank, '200', '0'), (self.capital, '0', '200')])
        report = build_ledger_report(head=parent)
        self.assertEqual(len(report['rows']), 2)
        self.assertEqual(report['total_debit'], Decimal('300'))
        self.assertEqual(report['closing_balance'], Decimal('300'))

    def test_draft_vouchers_excluded(self):
        self._voucher(date(2026, 1, 1), [(self.cash, '100', '0'), (self.capital, '0', '100')])
        self._voucher(date(2026, 1, 2), [(self.cash, '999', '0'), (self.capital, '0', '999')], post=False)
        report = build_ledger_report(head=self.cash)
        self.assertEqual(len(report['rows']), 1)
        self.assertEqual(report['total_debit'], Decimal('100'))