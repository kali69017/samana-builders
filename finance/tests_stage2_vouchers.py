from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking
from customers.models import Customer
from finance.models import AccountHead, Office, OfficeExpense, ProjectCost, Voucher, VoucherLine
from payments.models import Payment, Refund
from properties.models import Plot, Project


class VoucherStage2FormTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@example.com', 'pass123456')
        self.client.login(username='root', password='pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.revenue = AccountHead.objects.get(system_role='revenue')

    def post_voucher(self, voucher_type, account, amount='100', extra=None):
        data = {
            'voucher_type': voucher_type, 'date': date.today().isoformat(),
            'cash_bank_account': account.pk, 'narration': 'test',
            'lines-TOTAL_FORMS': '1', 'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '1', 'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account_head': self.revenue.pk, 'lines-0-amount': amount,
            'lines-0-narration': '',
        }
        if extra:
            data.update(extra)
        return self.client.post(reverse('finance_voucher_create'), data)

    def assert_voucher_sides(self, voucher, debit_role, credit_role):
        debits = list(voucher.lines.filter(debit__gt=0).values_list('account_head__system_role', flat=True))
        credits = list(voucher.lines.filter(credit__gt=0).values_list('account_head__system_role', flat=True))
        self.assertEqual(debits, [debit_role])
        self.assertEqual(credits, [credit_role])
        self.assertEqual(voucher.total_debit, voucher.total_credit)

    def test_cash_receipt_debits_cash_and_credits_contra(self):
        response = self.post_voucher('CR', self.cash)
        self.assertEqual(response.status_code, 302)
        voucher = Voucher.objects.get(voucher_type='CR')
        self.assertEqual(voucher.cash_bank_account, self.cash)
        self.assert_voucher_sides(voucher, 'cash_default', 'revenue')

    def test_cash_voucher_rejects_debit_credit_mismatch(self):
        response = self.post_voucher('CR', self.cash, extra={'lines-0-debit': '999'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Debit and credit fields are not valid')
        self.assertFalse(Voucher.objects.filter(voucher_type='CR').exists())

    def test_cash_payment_credits_cash_and_debits_contra(self):
        response = self.post_voucher('CP', self.cash)
        self.assertEqual(response.status_code, 302)
        voucher = Voucher.objects.get(voucher_type='CP')
        self.assert_voucher_sides(voucher, 'revenue', 'cash_default')

    def test_bank_receipt_debits_bank_and_credits_contra(self):
        response = self.post_voucher('BR', self.bank)
        self.assertEqual(response.status_code, 302)
        voucher = Voucher.objects.get(voucher_type='BR')
        self.assert_voucher_sides(voucher, 'bank_default', 'revenue')

    def test_bank_payment_credits_bank_and_debits_contra(self):
        response = self.post_voucher('BP', self.bank)
        self.assertEqual(response.status_code, 302)
        voucher = Voucher.objects.get(voucher_type='BP')
        self.assert_voucher_sides(voucher, 'revenue', 'bank_default')

    def test_cash_voucher_rejects_bank_account(self):
        response = self.post_voucher('CR', self.bank)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'flagged as cash')

    def test_contra_cannot_equal_cash_account(self):
        response = self.post_voucher('CR', self.cash, extra={
            'lines-0-account_head': self.cash.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cannot be the cash or bank account')

    def test_root_cannot_be_a_contra_account(self):
        assets = AccountHead.objects.get(code='1')
        response = self.post_voucher('CR', self.cash, extra={
            'lines-0-account_head': assets.pk,
        })
        self.assertEqual(response.status_code, 200)

    def test_unbalanced_journal_is_rejected(self):
        data = {
            'voucher_type': 'JV', 'date': date.today().isoformat(), 'narration': 'test',
            'lines-TOTAL_FORMS': '2', 'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '1', 'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account_head': self.cash.pk, 'lines-0-debit': '100', 'lines-0-credit': '0',
            'lines-1-account_head': self.revenue.pk, 'lines-1-debit': '0', 'lines-1-credit': '50',
        }
        response = self.client.post(reverse('finance_voucher_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not balanced')

    def test_balanced_journal_is_saved(self):
        data = {
            'voucher_type': 'JV', 'date': date.today().isoformat(), 'narration': 'test',
            'lines-TOTAL_FORMS': '2', 'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '1', 'lines-MAX_NUM_FORMS': '1000',
            'lines-0-account_head': self.cash.pk, 'lines-0-debit': '100', 'lines-0-credit': '0',
            'lines-1-account_head': self.revenue.pk, 'lines-1-debit': '0', 'lines-1-credit': '100',
        }
        response = self.client.post(reverse('finance_voucher_create'), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Voucher.objects.get(voucher_type='JV').lines.count(), 2)

    def test_model_and_queryset_delete_are_blocked(self):
        voucher = Voucher.objects.create(voucher_type='JV', date=date.today())
        line = VoucherLine.objects.create(
            voucher=voucher, account_head=self.cash, debit=Decimal('10'), credit=0,
        )
        with self.assertRaises(ValidationError):
            voucher.delete()
        with self.assertRaises(ValidationError):
            Voucher.objects.all().delete()
        with self.assertRaises(ValidationError):
            line.delete()
        with self.assertRaises(ValidationError):
            VoucherLine.objects.all().delete()


class VoucherStage2APITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@example.com', 'pass123456')
        self.client.force_authenticate(self.admin)
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.revenue = AccountHead.objects.get(system_role='revenue')

    def test_cash_receipt_api_generates_sides(self):
        response = self.client.post('/api/vouchers/', {
            'voucher_type': 'CR', 'date': date.today().isoformat(),
            'cash_bank_account': self.cash.pk,
            'lines': [{'account_head': self.revenue.pk, 'amount': '100', 'debit': '999'}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        voucher = Voucher.objects.get(pk=response.data['id'])
        self.assertEqual(voucher.lines.filter(debit__gt=0).get().account_head, self.cash)
        self.assertEqual(voucher.lines.filter(credit__gt=0).get().account_head, self.revenue)

    def test_cash_voucher_api_rejects_bank_account(self):
        response = self.client.post('/api/vouchers/', {
            'voucher_type': 'CR', 'date': date.today().isoformat(),
            'cash_bank_account': self.bank.pk,
            'lines': [{'account_head': self.revenue.pk, 'amount': '100'}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_journal_api_requires_balance(self):
        response = self.client.post('/api/vouchers/', {
            'voucher_type': 'JV', 'date': date.today().isoformat(),
            'lines': [
                {'account_head': self.cash.pk, 'debit': '100', 'credit': '0'},
                {'account_head': self.revenue.pk, 'debit': '0', 'credit': '50'},
            ],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_voucher_delete_is_405(self):
        voucher = Voucher.objects.create(voucher_type='JV', date=date.today())
        response = self.client.delete(f'/api/vouchers/{voucher.pk}/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_edit_rechecks_journal_balance(self):
        voucher = Voucher.objects.create(voucher_type='JV', date=date.today())
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=100)
        VoucherLine.objects.create(voucher=voucher, account_head=self.revenue, credit=100)
        response = self.client.patch(f'/api/vouchers/{voucher.pk}/', {
            'lines': [
                {'account_head': self.cash.pk, 'debit': '100', 'credit': '0'},
                {'account_head': self.revenue.pk, 'debit': '0', 'credit': '50'},
            ],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cash_voucher_line_edit_is_rejected(self):
        voucher = Voucher.objects.create(
            voucher_type='CR', date=date.today(), cash_bank_account=self.cash,
        )
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=100)
        VoucherLine.objects.create(voucher=voucher, account_head=self.revenue, credit=100)
        response = self.client.patch(f'/api/vouchers/{voucher.pk}/', {
            'lines': [{'account_head': self.revenue.pk, 'amount': '200'}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_legacy_voucher_detail_narration_edit_and_ledger(self):
        self.client.force_login(self.admin)
        voucher = Voucher.objects.create(voucher_type='CR', date=date.today())
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=100)
        VoucherLine.objects.create(voucher=voucher, account_head=self.revenue, credit=100)
        voucher.post(self.admin)
        self.assertIsNone(voucher.cash_bank_account_id)

        detail = self.client.get(f'/finance/vouchers/{voucher.pk}/')
        self.assertEqual(detail.status_code, 200)
        ledger = self.client.get('/finance/ledger/')
        self.assertEqual(ledger.status_code, 200)

        unlock = self.client.post(f'/api/vouchers/{voucher.pk}/unlock/', {'reason': 'fix narration'}, format='json')
        self.assertEqual(unlock.status_code, 200)
        edit = self.client.patch(f'/api/vouchers/{voucher.pk}/', {'narration': 'edited legacy'}, format='json')
        self.assertEqual(edit.status_code, 200, edit.data)
        voucher.refresh_from_db()
        self.assertEqual(voucher.narration, 'edited legacy')
        self.assertIsNone(voucher.cash_bank_account_id)

    def test_source_record_with_voucher_cannot_be_deleted(self):
        customer = Customer.objects.create(
            first_name='A', last_name='B', phone='03001234567', cnic='12345-1234567-1',
        )
        project = Project.objects.create(name='P', location='L', total_plots=1)
        plot = Plot.objects.create(
            plot_number='P-1', project=project, size_marla=Decimal('5'),
            price=Decimal('1000'), holding_deposit=Decimal('100'), status='available',
        )
        booking = Booking.objects.create(
            customer=customer, plot=plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed',
        )
        payment = Payment.objects.create(
            booking=booking, amount=Decimal('100'), payment_date=date.today(),
            payment_method='cash', status='verified',
        )
        with self.assertRaises(ValidationError):
            payment.delete()

        cost = ProjectCost.objects.create(
            project=project, amount=Decimal('200'), cost_date=date.today(),
            payment_method='cash', status='paid',
        )
        cost.post_to_ledger()
        with self.assertRaises(ValidationError):
            cost.delete()

        office = Office.objects.create(name='Head Office')
        expense = OfficeExpense.objects.create(
            office=office, amount=Decimal('300'), expense_date=date.today(),
            payment_method='bank_transfer', status='paid',
        )
        expense.post_to_ledger()
        with self.assertRaises(ValidationError):
            expense.delete()

        refund = Refund.objects.create(
            booking=booking, amount=Decimal('50'), reason='other',
            refund_method='cash', status='approved',
        )
        refund.post_to_ledger()
        with self.assertRaises(ValidationError):
            refund.delete()
