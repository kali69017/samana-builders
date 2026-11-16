from datetime import date
from decimal import Decimal
from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase

from finance.models import AccountHead, Voucher, VoucherLine


class SeedChartRobustnessTests(TestCase):
    def setUp(self):
        self.migration = import_module('finance.migrations.0011_seed_chart_of_accounts')

        def make(code, name, nature, parent_id=None):
            return AccountHead.objects.bulk_create([
                AccountHead(code=code, name=name, nature=nature, parent_id=parent_id,
                            is_leaf=True, is_active=True)
            ])[0]

        self.a1 = make('A00001', 'Legacy Asset', 'debit')
        self.a2 = make('A00002', 'Legacy Asset Child', 'debit', self.a1.pk)
        self.a3 = make('A00003', 'Legacy Asset Grandchild', 'debit', self.a2.pk)
        self.l1 = make('L00001', 'Legacy Liability', 'credit')
        self.c1 = make('C00001', 'Legacy Capital', 'credit')
        self.r1 = make('R00001', 'Legacy Revenue', 'credit')
        self.e1 = make('E00001', 'Legacy Expense', 'debit')
        self.x1 = make('X00001', 'Legacy Unknown', 'credit')

        user = User.objects.create_superuser('mig', 'm@example.com', 'pass123456')
        voucher = Voucher.objects.create(voucher_type='JV', date=date.today(), created_by=user)
        VoucherLine.objects.create(
            voucher=voucher, account_head=self.a1, debit=Decimal('10'), credit=0,
        )

    def test_legacy_heads_are_placed_or_held(self):
        self.migration.seed_chart(apps, None)
        for head in (self.a1, self.a2, self.a3, self.l1, self.c1, self.r1, self.e1, self.x1):
            head.refresh_from_db()

        self.assertEqual(self.a1.parent.code, '1')
        self.assertEqual(self.a2.parent_id, self.a1.pk)
        self.assertEqual(self.a3.parent_id, self.a2.pk)
        self.assertTrue(self.a2.code.startswith(self.a1.code + '.'))
        self.assertTrue(self.a3.code.startswith(self.a2.code + '.'))
        self.assertEqual(self.l1.parent.code, '2.1')
        self.assertEqual(self.l1.nature, 'credit')
        self.assertEqual(self.c1.parent.code, '3')
        self.assertEqual(self.c1.nature, 'credit')
        self.assertEqual(self.r1.parent.code, '4.1')
        self.assertEqual(self.e1.parent.code, '5.1')
        self.assertEqual(self.e1.nature, 'debit')
        self.assertEqual(self.x1.parent.code, '1.9')
        self.assertTrue(self.x1.parent.name.startswith('Holding'))
        for head in (self.a1, self.a2, self.a3, self.l1, self.c1, self.r1, self.e1, self.x1):
            self.assertLessEqual(head.level, 4)

        line = VoucherLine.objects.get(account_head=self.a1)
        self.assertEqual(line.debit, Decimal('10'))
