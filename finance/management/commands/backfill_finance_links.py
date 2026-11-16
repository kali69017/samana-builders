"""Idempotent finance link and ledger backfill for existing records.

Run with --dry-run first. The command never touches vouchers whose source
record no longer exists, and it never rewrites existing voucher lines.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from bookings.models import Booking, Installment
from expenses.models import Expense
from finance.accounting import get_system_account
from finance.models import AccountHead, OfficeExpense, ProjectCost, Voucher, VoucherLine
from payments.models import Payment, Refund


class Command(BaseCommand):
    help = 'Link existing finance records to accounts and post missing booking vouchers.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def receivable_balance(self):
        receivable = get_system_account('receivable')
        agg = VoucherLine.objects.filter(
            voucher__status='posted', account_head=receivable,
        ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
        return (agg['debit'] or Decimal('0.00')) - (agg['credit'] or Decimal('0.00'))

    def booking_balance(self, booking, receivable):
        payment_ids = list(booking.payments.values_list('pk', flat=True))
        refund_ids = list(booking.refunds.values_list('pk', flat=True))
        sources = [('Booking', booking.pk)]
        sources.extend(('Payment', pk) for pk in payment_ids)
        sources.extend(('Refund', pk) for pk in refund_ids)
        total = Decimal('0.00')
        for reference_type, reference_id in sources:
            agg = VoucherLine.objects.filter(
                voucher__status='posted',
                voucher__reference_type=reference_type,
                voucher__reference_id=reference_id,
                account_head=receivable,
            ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
            total += (agg['debit'] or Decimal('0.00')) - (agg['credit'] or Decimal('0.00'))
        return total

    def handle(self, *args, **options):
        dry = options['dry_run']
        cash = get_system_account('cash_default')
        bank = get_system_account('bank_default')
        receivable = get_system_account('receivable')
        revenue = get_system_account('revenue')
        project_cost = get_system_account('project_costs')
        office_expense = get_system_account('office_expenses')

        before = self.receivable_balance()
        stats = {}

        def bump(entity, key, note=''):
            bucket = stats.setdefault(entity, {'linked': 0, 'already': 0, 'posted': 0, 'skipped': 0, 'notes': []})
            bucket[key] += 1
            if note:
                bucket['notes'].append(note)

        with transaction.atomic():
            for payment in Payment.objects.all():
                account = cash if payment.payment_method == 'cash' else bank
                if payment.received_into_id is None:
                    bump('Payment', 'linked')
                    if not dry:
                        Payment.objects.filter(pk=payment.pk).update(received_into=account)
                        payment.received_into = account
                else:
                    bump('Payment', 'already')
                if not Voucher.objects.filter(reference_type='Payment', reference_id=payment.pk).exists():
                    bump('Payment', 'posted')
                    if not dry:
                        payment.post_to_ledger()

            for refund in Refund.objects.all():
                account = cash if refund.refund_method == 'cash' else bank
                if refund.paid_from_id is None:
                    bump('Refund', 'linked')
                    if not dry:
                        Refund.objects.filter(pk=refund.pk).update(paid_from=account)
                        refund.paid_from = account
                else:
                    bump('Refund', 'already')
                if refund.status == 'processed' and not Voucher.objects.filter(
                    reference_type='Refund', reference_id=refund.pk).exists():
                    bump('Refund', 'posted')
                    if not dry:
                        refund.post_to_ledger()

            for expense in Expense.objects.all():
                if expense.expense_account_id is None:
                    bump('Expense', 'linked')
                    if not dry:
                        Expense.objects.filter(pk=expense.pk).update(expense_account=project_cost)
                        expense.expense_account = project_cost
                else:
                    bump('Expense', 'already')
                if expense.status == 'paid' and expense.paid_from_id is None:
                    account = cash if expense.payment_method == 'cash' else bank
                    bump('Expense', 'linked')
                    if not dry:
                        Expense.objects.filter(pk=expense.pk).update(paid_from=account)
                        expense.paid_from = account
                if not Voucher.objects.filter(reference_type='Expense', reference_id=expense.pk).exists():
                    bump('Expense', 'posted')
                    if not dry:
                        expense.post_to_ledger()

            for cost in ProjectCost.objects.all():
                if cost.expense_account_id is None:
                    bump('ProjectCost', 'linked')
                    if not dry:
                        ProjectCost.objects.filter(pk=cost.pk).update(expense_account=project_cost)
                        cost.expense_account = project_cost
                else:
                    bump('ProjectCost', 'already')
                if cost.paid_from_id is None:
                    account = cash if cost.payment_method == 'cash' else bank
                    bump('ProjectCost', 'linked')
                    if not dry:
                        ProjectCost.objects.filter(pk=cost.pk).update(paid_from=account)
                        cost.paid_from = account
                if not Voucher.objects.filter(reference_type='ProjectCost', reference_id=cost.pk).exists():
                    bump('ProjectCost', 'posted')
                    if not dry:
                        cost.post_to_ledger()

            for expense in OfficeExpense.objects.all():
                if expense.expense_account_id is None:
                    bump('OfficeExpense', 'linked')
                    if not dry:
                        OfficeExpense.objects.filter(pk=expense.pk).update(expense_account=office_expense)
                        expense.expense_account = office_expense
                else:
                    bump('OfficeExpense', 'already')
                if expense.paid_from_id is None:
                    account = cash if expense.payment_method == 'cash' else bank
                    bump('OfficeExpense', 'linked')
                    if not dry:
                        OfficeExpense.objects.filter(pk=expense.pk).update(paid_from=account)
                        expense.paid_from = account
                if not Voucher.objects.filter(reference_type='OfficeExpense', reference_id=expense.pk).exists():
                    bump('OfficeExpense', 'posted')
                    if not dry:
                        expense.post_to_ledger()

            for booking in Booking.objects.select_related('customer'):
                if booking.receivable_account_id is None or booking.revenue_account_id is None:
                    bump('Booking', 'linked')
                    if not dry:
                        Booking.objects.filter(pk=booking.pk).update(
                            receivable_account=booking.receivable_account or receivable,
                            revenue_account=booking.revenue_account or revenue,
                        )
                        booking.refresh_from_db()
                else:
                    bump('Booking', 'already')
                bump('Booking', 'skipped', 'cash basis: bookings do not post vouchers')

            for installment in Installment.objects.select_related('plan__booking'):
                account = installment.plan.booking.receivable_account or receivable
                if installment.receivable_account_id is None:
                    bump('Installment', 'linked')
                    if not dry:
                        Installment.objects.filter(pk=installment.pk).update(receivable_account=account)
                else:
                    bump('Installment', 'already')

            if dry:
                transaction.set_rollback(True)

        after = self.receivable_balance()
        self.stdout.write(f'Receivable balance before: {before}')
        self.stdout.write(f'Receivable balance after: {after}')
        for entity in sorted(stats):
            data = stats[entity]
            self.stdout.write(
                f'{entity}: linked={data["linked"]} already={data["already"]} '
                f'posted={data["posted"]} skipped={data["skipped"]}'
            )
            for note in data['notes']:
                self.stdout.write(f'  skipped: {note}')

        credit_bookings = []
        for booking in Booking.objects.all():
            balance = self.booking_balance(booking, receivable)
            if balance < 0:
                credit_bookings.append((booking.booking_id, balance))
        if credit_bookings:
            self.stdout.write('Bookings with a credit receivable balance:')
            for booking_id, balance in credit_bookings:
                self.stdout.write(f'  {booking_id}: {balance}')
        else:
            self.stdout.write('No booking has a credit receivable balance.')
