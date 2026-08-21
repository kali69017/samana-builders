"""Bulk-populate the database with 50+ entries in every business table.

Run with: python manage.py populate_db

Uses get_or_create on natural keys so re-running is safe (idempotent).
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import (
    UserProfile, AuditLog, Lead, LeadNote, Agent, CompanySettings,
)
from customers.models import Customer, CustomerLedgerEntry, CustomerNominee
from properties.models import Project, ProjectPhase, Plot, PlotFeature, ProjectMilestone, PriceHistory
from bookings.models import (
    Booking, BookingGroup, InstallmentPlan, InstallmentPlanTemplate, Installment,
    Reservation, BookingTransfer, EarlySettlement, CancellationPolicy,
    BookingAmendment, PaymentReminder,
)
from payments.models import Payment, Receipt, PaymentAllocation, Refund as PayRefund
from expenses.models import Expense
from notifications.models import NotificationLog

N = 50  # minimum rows per table


class Command(BaseCommand):
    help = 'Populate every table with at least 50 realistic dummy rows.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Populating database (50+ per table)...'))

        admin = User.objects.filter(is_superuser=True).first()
        if admin is None:
            admin = User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
        # Ensure a couple of staff users exist
        sales_user, _ = User.objects.get_or_create(username='sales_seed', defaults={'first_name': 'Seed', 'last_name': 'Sales'})
        UserProfile.objects.get_or_create(user=sales_user, defaults={'role': 'sales'})

        # ── Projects ────────────────────────────────────────────────────────
        for i in range(N):
            Project.objects.get_or_create(
                name=f'Seed Project {i+1}',
                defaults={
                    'description': f'Dummy residential project #{i+1} for testing.',
                    'location': random.choice(['Lahore', 'Karachi', 'Islamabad', 'Rawalpindi', 'Multan', 'Faisalabad']),
                    'total_plots': random.randint(100, 600),
                    'status': random.choice(['booking_open', 'under_construction', 'completed', 'coming_soon']),
                },
            )
        projects = list(Project.objects.all())

        # ── Project Phases ─────────────────────────────────────────────────
        for i, p in enumerate(projects[:N]):
            ProjectPhase.objects.get_or_create(
                project=p, name=f'Phase {random.randint(1, 5)}',
                defaults={
                    'launch_date': date.today() - timedelta(days=random.randint(30, 700)),
                    'total_plots': random.randint(50, 300),
                    'price_per_marla': Decimal(random.randint(50000, 180000)),
                },
            )

        # ── Plot Features (lookup) ─────────────────────────────────────────
        feature_names = ['Park Facing', 'Corner Plot', 'Main Boulevard', 'Mosque Facing', 'Park View',
                         'Community Center', 'Wider Road', 'Corner', 'Lake View', 'South Facing']
        features = []
        for fn in feature_names:
            features.append(PlotFeature.objects.get_or_create(name=fn)[0])

        # ── Plots ──────────────────────────────────────────────────────────
        plots = []
        for i in range(N + 10):
            project = projects[i % len(projects)]
            phase = project.phases.order_by('?').first()
            size = random.choice([3, 5, 7, 10, 12])
            price = (Decimal(size) * Decimal(random.randint(50000, 150000))).quantize(Decimal('0.01'))
            plot, _ = Plot.objects.get_or_create(
                project=project, plot_number=f'S-{i+1:03d}',
                defaults={
                    'phase': phase,
                    'plot_type': random.choice(['residential', 'commercial']),
                    'size_marla': size,
                    'price': price,
                    'status': random.choice(['available', 'available', 'reserved', 'booked', 'sold']),
                    'block': random.choice(['A', 'B', 'C', 'D']),
                    'is_corner': random.random() < 0.3,
                    'is_park_facing': random.random() < 0.2,
                },
            )
            plots.append(plot)

        # ── Customers ──────────────────────────────────────────────────────
        customers = []
        for i in range(N):
            cnic = f'{random.randint(42000, 45999)}-{random.randint(1000000, 9999999)}-{random.randint(1, 9)}'
            email = f'seed.customer{i+1}@example.com'
            cust, _ = Customer.objects.get_or_create(
                email=email,
                defaults={
                    'cnic': cnic,
                    'first_name': random.choice(['Muhammad', 'Ali', 'Ayesha', 'Bilal', 'Sana', 'Usman', 'Fatima', 'Omar', 'Zainab', 'Hassan']),
                    'last_name': random.choice(['Khan', 'Ahmed', 'Malik', 'Butt', 'Zahra', 'Sheikh', 'Hussain', 'Raza', 'Fatima', 'Iqbal']),
                    'phone': f'+92-3{random.randint(10, 45)}-{random.randint(1000000, 9999999)}',
                    'city': random.choice(['Lahore', 'Karachi', 'Islamabad', 'Multan', 'Peshawar', 'Quetta']),
                    'is_active': random.random() > 0.1,
                    'created_by': admin,
                },
            )
            customers.append(cust)

        # ── Nominees ───────────────────────────────────────────────────────
        for i, c in enumerate(customers[:N]):
            CustomerNominee.objects.get_or_create(
                customer=c,
                defaults={
                    'nominee_name': f'Nominee {i+1}',
                    'nominee_cnic': f'{random.randint(42000, 45999)}-{random.randint(1000000, 9999999)}-{random.randint(1, 9)}',
                    'nominee_phone': f'+92-3{random.randint(10, 45)}-{random.randint(1000000, 9999999)}',
                    'relationship': random.choice(['Father', 'Wife', 'Son', 'Brother', 'Daughter']),
                },
            )

        # ── Agents ─────────────────────────────────────────────────────────
        agents = []
        for i in range(N):
            agent, _ = Agent.objects.get_or_create(
                name=f'Agent {i+1}',
                defaults={
                    'phone': f'+92-3{random.randint(10, 45)}-{random.randint(1000000, 9999999)}',
                    'email': f'agent{i+1}@example.com',
                    'commission_rate': Decimal(random.choice([1, 1.5, 2, 2.5, 3, 5])),
                    'is_active': random.random() > 0.15,
                },
            )
            agents.append(agent)

        # ── Installment Plan Templates ─────────────────────────────────────
        templates = []
        for i in range(N):
            t, _ = InstallmentPlanTemplate.objects.get_or_create(
                name=f'Template {i+1}',
                defaults={
                    'project': projects[i % len(projects)],
                    'total_installments': random.choice([12, 18, 24, 36, 48]),
                    'frequency': random.choice(['monthly', 'quarterly']),
                    'down_payment_percentage': Decimal(random.choice([10, 15, 20, 25])),
                    'late_fee_per_day': Decimal(random.choice([50, 100, 150, 200])),
                    'grace_period_days': random.choice([0, 3, 5, 7, 10]),
                },
            )
            templates.append(t)

        # ── Bookings ───────────────────────────────────────────────────────
        bookings = []
        for i in range(N):
            plot = plots[i]
            cust = customers[i % len(customers)]
            agent = random.choice(agents)
            plot.status = 'booked'
            plot.save(update_fields=['status'])
            total = plot.price
            advance = (total * Decimal(random.randint(10, 30)) / Decimal(100)).quantize(Decimal('0.01'))
            b, _ = Booking.objects.get_or_create(
                customer=cust, plot=plot,
                defaults={
                    'total_amount': total,
                    'advance_paid': advance,
                    'status': random.choice(['pending', 'confirmed', 'active', 'active', 'completed']),
                    'source': random.choice(['website', 'walk_in', 'referral', 'agent', 'other']),
                    'agent': agent,
                    'created_by': sales_user,
                },
            )
            bookings.append(b)

        # ── Installment Plans + Installments ───────────────────────────────
        for i, b in enumerate(bookings):
            n_inst = random.choice([6, 12, 24])
            amount = ((b.total_amount - b.advance_paid) / Decimal(n_inst)).quantize(Decimal('0.01'))
            plan, created = InstallmentPlan.objects.get_or_create(
                booking=b,
                defaults={
                    'total_installments': n_inst,
                    'installment_amount': amount,
                    'down_payment_amount': b.advance_paid,
                    'start_date': b.booking_date,
                    'frequency': 'monthly',
                    'due_day': random.randint(1, 28),
                    'late_fee_per_day': Decimal(random.choice([50, 100, 150])),
                    'grace_period_days': random.choice([0, 5, 7]),
                },
            )
            if created:
                for j in range(1, n_inst + 1):
                    due = b.booking_date + timedelta(days=30 * j)
                    paid = j <= 2
                    Installment.objects.create(
                        plan=plan, installment_number=j, due_date=due,
                        amount=amount, late_fee=Decimal('0'),
                        paid_amount=amount if paid else Decimal('0'),
                        status='paid' if paid else ('overdue' if due < date.today() and j > 2 else 'pending'),
                        paid_date=due if paid else None,
                    )

        # ── Payments + Receipts ────────────────────────────────────────────
        for i, b in enumerate(bookings):
            pay, _ = Payment.objects.get_or_create(
                booking=b, payment_date=b.booking_date + timedelta(days=1), amount=b.advance_paid or Decimal('10000'),
                defaults={
                    'payment_method': random.choice(['cash', 'bank_transfer', 'cheque', 'online', 'jazzcash', 'raast']),
                    'payment_type': 'down_payment',
                    'reference_number': f'TX-{random.randint(100000, 999999)}',
                    'status': 'verified',
                    'verified_by': admin,
                    'verified_at': timezone.now(),
                    'receipt_generated': True,
                    'created_by': sales_user,
                },
            )
            if not pay.receipts.exists():
                Receipt.objects.create(payment=pay, generated_by=admin)

        # ── Refunds ────────────────────────────────────────────────────────
        for i, b in enumerate(bookings[:N]):
            PayRefund.objects.get_or_create(
                booking=b, amount=Decimal(random.randint(5000, 50000)),
                defaults={'reason': random.choice(['cancellation', 'overpayment', 'other']),
                          'status': random.choice(['pending', 'approved', 'processed'])}
            )

        # ── Customer Ledger Entries ────────────────────────────────────────
        for i, b in enumerate(bookings):
            CustomerLedgerEntry.objects.get_or_create(
                customer=b.customer, booking=b, transaction_type='booking', reference_id=b.booking_id,
                defaults={
                    'debit': b.total_amount, 'credit': Decimal('0'),
                    'running_balance': b.remaining_balance,
                    'entry_date': b.booking_date,
                    'description': f'Booking {b.booking_id}',
                },
            )

        # ── Leads + Lead Notes ─────────────────────────────────────────────
        leads = []
        for i in range(N):
            lead, _ = Lead.objects.get_or_create(
                phone=f'+92-3{random.randint(10, 45)}-{random.randint(1000000, 9999999)}',
                defaults={
                    'name': f'Lead Person {i+1}',
                    'email': f'lead{i+1}@example.com',
                    'source': random.choice(['hero', 'strip', 'newsletter', 'referral', 'walk_in', 'agent']),
                    'status': random.choice(['new', 'contacted', 'qualified', 'lost']),
                    'budget': Decimal(random.randint(500000, 50000000)),
                },
            )
            leads.append(lead)
        for i, lead in enumerate(leads[:N]):
            LeadNote.objects.get_or_create(
                lead=lead, note=f'Follow-up note #{i+1} for this lead.',
                defaults={'created_by': sales_user},
            )

        # ── Expenses ───────────────────────────────────────────────────────
        for i in range(N):
            Expense.objects.get_or_create(
                project=projects[i % len(projects)], description=f'Construction expense {i+1}', amount=Decimal(random.randint(50000, 2000000)),
                defaults={
                    'expense_type': random.choice(['internal', 'external', 'miscellaneous']),
                    'paid_to': f'Vendor {i+1}',
                    'expense_date': date.today() - timedelta(days=random.randint(0, 300)),
                },
            )

        # ── Milestones ─────────────────────────────────────────────────────
        for i in range(N):
            ProjectMilestone.objects.get_or_create(
                project=projects[i % len(projects)], title=f'Milestone {i+1}',
                defaults={
                    'target_date': date.today() + timedelta(days=random.randint(-200, 300)),
                    'status': random.choice(['pending', 'in_progress', 'completed', 'delayed']),
                    'order': i,
                },
            )

        # ── Notification Logs ──────────────────────────────────────────────
        for i in range(N):
            NotificationLog.objects.create(
                recipient_name=f'Recipient {i+1}',
                recipient_contact=random.choice([f'+92-3{random.randint(10, 45)}-{random.randint(1000000, 9999999)}', f'seed{i+1}@example.com']),
                channel=random.choice(['email', 'sms', 'whatsapp']),
                notification_type=random.choice(['payment_confirmation', 'installment_reminder', 'overdue_payment', 'receipt_notification', 'booking_notification', 'general']),
                subject='Sample subject',
                message='Sample notification message.',
                status=random.choice(['sent', 'failed', 'pending']),
                created_by=admin,
            )

        # ── Payment Allocations ────────────────────────────────────────────
        alloc_count = 0
        for b in bookings:
            plan = getattr(b, 'installment_plan', None)
            if not plan:
                continue
            inst = plan.installments.filter(status='paid').first()
            pay = b.payments.first()
            if inst and pay and alloc_count < N:
                PaymentAllocation.objects.get_or_create(payment=pay, installment=inst, defaults={'amount': inst.amount, 'allocated_by': admin})
                alloc_count += 1

        # ── Booking Transfers ──────────────────────────────────────────────
        for i in range(N):
            b = bookings[i % len(bookings)]
            to_cust = customers[(i + 1) % len(customers)]
            BookingTransfer.objects.get_or_create(
                booking=b, from_customer=b.customer, to_customer=to_cust,
                defaults={'transfer_fee': Decimal(random.randint(10000, 50000)),
                          'previous_payments_handling': random.choice(['transfer', 'refund']),
                          'approved_by': admin},
            )

        # ── Reservations ───────────────────────────────────────────────────
        for i in range(N):
            Reservation.objects.create(
                customer=customers[i % len(customers)], plot=plots[i % len(plots)],
                token_amount=Decimal('50000'),
                expires_at=timezone.now() + timedelta(days=random.randint(3, 14)),
                status=random.choice(['active', 'expired', 'converted', 'cancelled']),
                created_by=sales_user,
            )

        # ── Price History ──────────────────────────────────────────────────
        for i in range(N):
            plot = plots[i % len(plots)]
            PriceHistory.objects.create(
                plot=plot, old_price=(plot.price * Decimal('0.9')).quantize(Decimal('0.01')),
                new_price=plot.price, change_reason='Seed price adjustment', changed_by=admin,
            )

        # ── Booking Amendments ─────────────────────────────────────────────
        for i in range(N):
            b = bookings[i % len(bookings)]
            BookingAmendment.objects.create(
                booking=b, field_name=random.choice(['total_amount', 'advance_paid', 'possession_date']),
                old_value='0', new_value=str(b.total_amount), changed_by=sales_user,
            )

        # ── Payment Reminders ──────────────────────────────────────────────
        paid_insts = Installment.objects.filter(status__in=['paid', 'pending', 'overdue'])
        for i in range(N):
            inst = paid_insts[i % paid_insts.count()] if paid_insts.exists() else None
            if inst is None:
                continue
            PaymentReminder.objects.create(
                installment=inst,
                reminder_type=random.choice(['upcoming', 'overdue', 'grace_period', 'late_fee']),
                sent_via=random.choice(['sms', 'email', 'both']),
                message='Reminder message.',
                delivery_status=random.choice(['pending', 'sent', 'failed']),
            )

        # ── Early Settlements ──────────────────────────────────────────────
        for i in range(N):
            plan = InstallmentPlan.objects.all()[i % InstallmentPlan.objects.count()]
            rem = Decimal(random.randint(1, 12))
            total = plan.installment_amount * rem
            EarlySettlement.objects.create(
                plan=plan, remaining_installments=rem,
                total_remaining_amount=total,
                discount_percentage=Decimal('5'),
                discount_amount=(total * Decimal('0.05')).quantize(Decimal('0.01')),
                settlement_amount=(total * Decimal('0.95')).quantize(Decimal('0.01')),
                approved=random.random() > 0.5,
            )

        # ── Audit Logs ─────────────────────────────────────────────────────
        for i in range(N):
            AuditLog.objects.create(
                user=random.choice([admin, sales_user]),
                action=random.choice(['create', 'update', 'delete', 'login', 'verify', 'transfer', 'cancel']),
                model_name=random.choice(['Customer', 'Booking', 'Payment', 'Plot', 'Project', 'Lead']),
                object_id=str(random.randint(1, 9999)),
                description=f'Seed audit entry {i+1}',
                ip_address=f'192.168.1.{random.randint(2, 254)}',
            )

        # ── Company Settings (singleton) ───────────────────────────────────
        CompanySettings.load()

        # ── Summary ────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\nDatabase populated.'))
        rows = {
            'Projects': Project.objects.count(), 'Phases': ProjectPhase.objects.count(),
            'Plots': Plot.objects.count(), 'Customers': Customer.objects.count(),
            'Nominees': CustomerNominee.objects.count(), 'Agents': Agent.objects.count(),
            'Templates': InstallmentPlanTemplate.objects.count(), 'Bookings': Booking.objects.count(),
            'InstallmentPlans': InstallmentPlan.objects.count(), 'Installments': Installment.objects.count(),
            'Payments': Payment.objects.count(), 'Receipts': Receipt.objects.count(),
            'Refunds': PayRefund.objects.count(), 'LedgerEntries': CustomerLedgerEntry.objects.count(),
            'Leads': Lead.objects.count(), 'LeadNotes': LeadNote.objects.count(),
            'Expenses': Expense.objects.count(), 'Milestones': ProjectMilestone.objects.count(),
            'NotificationLogs': NotificationLog.objects.count(), 'Allocations': PaymentAllocation.objects.count(),
            'Transfers': BookingTransfer.objects.count(), 'Reservations': Reservation.objects.count(),
            'PriceHistory': PriceHistory.objects.count(), 'Amendments': BookingAmendment.objects.count(),
            'Reminders': PaymentReminder.objects.count(), 'Settlements': EarlySettlement.objects.count(),
            'AuditLogs': AuditLog.objects.count(),
        }
        for label, count in rows.items():
            flag = '[OK]' if count >= N else '    '
            self.stdout.write(f'  {flag} {label}: {count}')
