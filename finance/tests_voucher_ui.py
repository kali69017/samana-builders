from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from finance.models import AccountHead, Voucher
from finance.forms import CASH_BANK_VOUCHER_KINDS


class VoucherTypeUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('vtype', 'vtype@example.com', 'pass123456')
        self.client.login(username='vtype', password='pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.revenue = AccountHead.objects.get(system_role='revenue')
        self.expense = AccountHead.objects.get(system_role='project_costs')

    def test_default_page_is_a_type_chooser(self):
        response = self.client.get(reverse('finance_voucher_create'))
        self.assertEqual(response.status_code, 200)
        for value in ('CR', 'CP', 'BR', 'BP', 'JV'):
            self.assertContains(response, f'?type={value}')
        self.assertNotContains(response, 'lines-0-debit')

    def test_each_cash_bank_type_renders_cash_bank_form(self):
        for voucher_type in CASH_BANK_VOUCHER_KINDS:
            with self.subTest(voucher_type=voucher_type):
                response = self.client.get(
                    reverse('finance_voucher_create') + f'?type={voucher_type}')
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id_cash_bank_account')
                self.assertNotContains(response, 'lines-0-debit')
                self.assertNotContains(response, 'lines-0-credit')

    def test_journal_renders_debit_and_credit_form(self):
        response = self.client.get(reverse('finance_voucher_create') + '?type=JV')
        self.assertContains(response, 'value="JV" selected')
        self.assertContains(response, 'lines-0-debit')
        self.assertContains(response, 'lines-0-credit')
        self.assertNotContains(response, 'id_cash_bank_account')

    def post_cash_voucher(self, voucher_type, cash_account, contra_account, amount='100.00'):
        return self.client.post(reverse('finance_voucher_create'), {
            'voucher_type': voucher_type,
            'date': date.today().isoformat(),
            'narration': 'E2E test voucher',
            'cash_bank_account': cash_account.pk,
            'lines-TOTAL_FORMS': '2',
            'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '1',
            'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account_head': contra_account.pk,
            'lines-0-amount': amount,
            'lines-0-narration': 'contra one',
            'lines-1-account_head': contra_account.pk,
            'lines-1-amount': amount,
            'lines-1-narration': 'contra two',
        })

    def test_cash_and_bank_posts_have_correct_sides(self):
        cases = [
            ('CR', self.cash, 'cash_default', 'debit'),
            ('CP', self.cash, 'cash_default', 'credit'),
            ('BR', self.bank, 'bank_default', 'debit'),
            ('BP', self.bank, 'bank_default', 'credit'),
        ]
        for voucher_type, account, role, side in cases:
            with self.subTest(voucher_type=voucher_type):
                response = self.post_cash_voucher(voucher_type, account, self.revenue)
                self.assertEqual(response.status_code, 302)
                voucher = Voucher.objects.get(voucher_type=voucher_type)
                cash_line = voucher.lines.get(account_head__system_role=role)
                if side == 'debit':
                    self.assertEqual(cash_line.debit, Decimal('200.00'))
                    self.assertEqual(cash_line.credit, Decimal('0.00'))
                else:
                    self.assertEqual(cash_line.credit, Decimal('200.00'))
                    self.assertEqual(cash_line.debit, Decimal('0.00'))
                self.assertEqual(voucher.total_debit, Decimal('200.00'))
                self.assertEqual(voucher.total_credit, Decimal('200.00'))

    def test_cash_form_rejects_debit_credit_payload(self):
        response = self.client.post(reverse('finance_voucher_create'), {
            'voucher_type': 'CR',
            'date': date.today().isoformat(),
            'cash_bank_account': self.cash.pk,
            'lines-TOTAL_FORMS': '1',
            'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '1',
            'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account_head': self.revenue.pk,
            'lines-0-debit': '100.00',
            'lines-0-credit': '0.00',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Voucher.objects.exists())

    def test_journal_rejects_cash_bank_payload(self):
        response = self.client.post(reverse('finance_voucher_create'), {
            'voucher_type': 'JV',
            'date': date.today().isoformat(),
            'cash_bank_account': self.cash.pk,
            'lines-TOTAL_FORMS': '2',
            'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '1',
            'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account_head': self.cash.pk,
            'lines-0-debit': '100.00', 'lines-0-credit': '0.00',
            'lines-1-account_head': self.revenue.pk,
            'lines-1-debit': '0.00', 'lines-1-credit': '100.00',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Voucher.objects.exists())


class JournalErrorVisibilityTests(VoucherTypeUiTests):
    def post_journal(self, lines):
        data = {
            'voucher_type': 'JV', 'date': date.today().isoformat(), 'narration': 'test',
            'lines-TOTAL_FORMS': str(len(lines)), 'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '1', 'lines-MAX_NUM_FORMS': '1000',
        }
        for index, (head, debit, credit) in enumerate(lines):
            data[f'lines-{index}-account_head'] = head.pk
            data[f'lines-{index}-debit'] = str(debit)
            data[f'lines-{index}-credit'] = str(credit)
        return self.client.post(reverse('finance_voucher_create') + '?type=JV', data)

    def test_unbalanced_error_is_visible_near_lines(self):
        response = self.post_journal([
            (self.cash, '100.00', '0.00'),
            (self.revenue, '0.00', '50.00'),
        ])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Journal is not balanced')
        self.assertContains(response, 'id="journal-errors"')
        self.assertContains(response, 'id="journal-debit-total"')
        self.assertContains(response, 'id="journal-credit-total"')
        self.assertContains(response, 'id="journal-difference"')

    def test_one_sided_error_is_visible(self):
        response = self.post_journal([(self.cash, '100.00', '0.00')])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Journal is not balanced')

    def test_empty_lines_error_is_visible(self):
        response = self.post_journal([])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please submit at least 1 form')

    def test_zero_amount_lines_error_is_visible(self):
        response = self.post_journal([
            (self.cash, '0.00', '0.00'),
            (self.revenue, '0.00', '0.00'),
        ])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a debit or a credit')
        self.assertContains(response, 'A line must have a debit or a credit')
