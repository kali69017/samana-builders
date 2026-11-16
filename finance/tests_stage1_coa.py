from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking
from customers.models import Customer
from finance.forms import AccountHeadForm
from finance.models import AccountHead, Office, OfficeExpense, ProjectCost, Voucher
from payments.models import Payment, Refund
from properties.models import Plot, Project


ROOT_SPECS = {
    '1': ('Assets', 'debit'),
    '2': ('Liabilities', 'credit'),
    '3': ('Capital', 'credit'),
    '4': ('Revenue', 'credit'),
    '5': ('Expenses', 'debit'),
}


class ChartOfAccountsStage1Tests(APITestCase):
    def setUp(self):
        self.assets = AccountHead.objects.get(code='1')
        self.liabilities = AccountHead.objects.get(code='2')
        self.expenses = AccountHead.objects.get(code='5')
        self.cash_banks = AccountHead.objects.get(code='1.1.1')
        self.fixed_assets = AccountHead.objects.get(code='1.2')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')

    def test_five_roots_are_seeded(self):
        roots = AccountHead.objects.filter(parent__isnull=True).order_by('code')
        self.assertEqual(
            [(h.code, h.name, h.nature) for h in roots],
            [(code, name, nature) for code, (name, nature) in ROOT_SPECS.items()],
        )

    def test_nature_is_inherited_from_root(self):
        head = AccountHead.objects.create(name='Accrued Liabilities', parent=self.liabilities)
        self.assertEqual(head.nature, 'credit')
        child = AccountHead.objects.create(name='Accrued Rent', parent=head)
        self.assertEqual(child.nature, 'credit')

    def test_code_generation_uses_next_sibling_sequence(self):
        head = AccountHead.objects.create(name='Petty Cash', parent=self.cash_banks)
        self.assertEqual(head.code, '1.1.1.3')
        level_three = AccountHead.objects.get(code='1.2.1')
        child = AccountHead.objects.create(name='Desk', parent=level_three)
        self.assertEqual(child.code, '1.2.1.1')

    def test_gap_is_reused_after_highest_sibling_is_deleted(self):
        one = AccountHead.objects.create(name='One', parent=self.fixed_assets)
        two = AccountHead.objects.create(name='Two', parent=self.fixed_assets)
        self.assertEqual((one.code, two.code), ('1.2.5', '1.2.6'))
        two.delete()
        three = AccountHead.objects.create(name='Three', parent=self.fixed_assets)
        self.assertEqual(three.code, '1.2.6')

    def test_non_root_requires_parent(self):
        with self.assertRaises(ValidationError):
            AccountHead.objects.create(name='Orphan', parent=None)

    def test_roots_cannot_be_edited_deactivated_or_deleted(self):
        for head in AccountHead.objects.filter(parent__isnull=True):
            with self.assertRaises(ValidationError):
                head.name = f'{head.name} changed'
                head.save()
            with self.assertRaises(ValidationError):
                head.is_active = False
                head.save()
            with self.assertRaises(ValidationError):
                head.delete()

    def test_reparent_regenerates_code_and_descendants(self):
        head = AccountHead.objects.create(name='Office Furniture', parent=self.fixed_assets)
        child = AccountHead.objects.create(name='Desks', parent=head)
        head.parent = self.assets
        head.save()
        head.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(head.code, '1.3')
        self.assertEqual(child.code, '1.3.1')

    def test_reparent_blocked_when_account_has_ledger_entries(self):
        voucher = Voucher.objects.create(voucher_type='JV', date='2026-01-01')
        from finance.models import VoucherLine
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=10, credit=0)
        with self.assertRaises(ValidationError):
            self.cash.parent = self.fixed_assets
            self.cash.save()

    def test_delete_blocked_for_children_and_ledger_entries(self):
        with self.assertRaises(ValidationError):
            self.cash_banks.delete()
        voucher = Voucher.objects.create(voucher_type='JV', date='2026-01-01')
        from finance.models import VoucherLine
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=10, credit=0)
        with self.assertRaises(ValidationError):
            self.cash.delete()

    def test_cash_and_bank_kind_only_allowed_under_assets(self):
        head = AccountHead.objects.create(name='Cash Drawer', parent=self.cash_banks,
                                          account_kind='cash')
        self.assertEqual(head.account_kind, 'cash')
        with self.assertRaises(ValidationError):
            AccountHead.objects.create(name='Illegal Bank', parent=self.liabilities,
                                       account_kind='bank')

    def test_form_ignores_nature_and_code_and_requires_parent(self):
        form = AccountHeadForm(data={
            'name': 'Cash Drawer', 'parent': self.cash_banks.pk, 'nature': 'credit',
            'code': 'HACKED', 'account_kind': 'cash', 'is_active': 'on',
        })
        self.assertTrue(form.is_valid(), form.errors)
        head = form.save()
        self.assertEqual(head.nature, 'debit')
        self.assertEqual(head.code, '1.1.1.3')
        self.assertNotIn('nature', form.fields)
        self.assertNotIn('code', form.fields)

        bad = AccountHeadForm(data={'name': 'No Parent', 'account_kind': 'normal'})
        self.assertFalse(bad.is_valid())

    def test_api_ignores_client_nature_and_code(self):
        user = User.objects.create_superuser('root', 'r@example.com', 'pass123456')
        self.client.force_authenticate(user)
        response = self.client.post('/api/account-heads/', {
            'name': 'Cash Drawer', 'parent': self.cash_banks.pk, 'nature': 'credit',
            'code': 'HACKED', 'account_kind': 'cash', 'is_active': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['nature'], 'debit')
        self.assertEqual(response.data['code'], '1.1.1.3')

    def test_postings_still_work_after_recode(self):
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
            booking=booking, amount=Decimal('100'), payment_date='2026-01-01',
            payment_method='cash', status='verified',
        )
        payment_voucher = Voucher.objects.get(reference_type='Payment', reference_id=payment.pk)
        self.assertSetEqual(
            set(payment_voucher.lines.values_list('account_head__system_role', flat=True)),
            {'cash_default', 'customer_advances'},
        )

        refund = Refund.objects.create(
            booking=booking, amount=Decimal('50'), reason='other',
            refund_method='bank_transfer', status='approved',
        )
        refund.post_to_ledger()
        refund_voucher = Voucher.objects.get(reference_type='Refund', reference_id=refund.pk)
        self.assertSetEqual(
            set(refund_voucher.lines.values_list('account_head__system_role', flat=True)),
            {'bank_default', 'customer_advances'},
        )

        cost = ProjectCost.objects.create(
            project=project, amount=Decimal('200'), cost_date='2026-01-02',
            payment_method='cash', status='paid',
        )
        cost.post_to_ledger()
        cost_voucher = Voucher.objects.get(reference_type='ProjectCost', reference_id=cost.pk)
        self.assertSetEqual(
            set(cost_voucher.lines.values_list('account_head__system_role', flat=True)),
            {'cash_default', 'project_costs'},
        )

        office = Office.objects.create(name='Head Office')
        expense = OfficeExpense.objects.create(
            office=office, amount=Decimal('300'), expense_date='2026-01-03',
            payment_method='bank_transfer', status='paid',
        )
        expense.post_to_ledger()
        expense_voucher = Voucher.objects.get(reference_type='OfficeExpense', reference_id=expense.pk)
        self.assertSetEqual(
            set(expense_voucher.lines.values_list('account_head__system_role', flat=True)),
            {'bank_default', 'office_expenses'},
        )
