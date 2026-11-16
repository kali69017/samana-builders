"""
Management command to reset the database to a minimal demo set.
Run with: python manage.py reset_demo
"""
import os, django
from decimal import Decimal
from django.conf import settings
from django.db import connection
from django.core.management.base import BaseCommand


def _clear_data():
    from customers.models import Customer
    from properties.models import Project, Plot, ProjectPhase
    from bookings.models import (
        Booking, BookingGroup, Reservation, InstallmentPlan, Installment,
        InstallmentPlanTemplate, CancellationPolicy, CancellationTier,
    )
    from payments.models import Payment, PaymentAllocation, Receipt, Refund
    from core.models import AuditLog

    # Clear in dependency-safe order
    for model in [Refund, PaymentAllocation, Payment, Receipt,
                  Installment, InstallmentPlan, Booking, Reservation,
                  CustomerLedgerEntry, Customer,
                  Plot, PriceHistory, ProjectPhase, Project,
                  InstallmentPlanTemplate,
                  CancellationPolicy, CancellationTier,
                  BookingGroup, ]:
        try:
            model.objects.all().delete()
        except Exception:
            pass
    # Clear AuditLog last
    try:
        AuditLog.objects.all().delete()
    except Exception:
        pass


def _seed_demo():
    from django.contrib.auth.models import User
    from core.models import UserProfile

    # Keep existing users/profiles - skip if already present
    admin_user = UserProfile.objects.filter(role='super_admin').first().user
    accounts_user = UserProfile.objects.filter(role='accounts').first().user
    sales_user = UserProfile.objects.filter(role='sales').first().user

    # Projects & phases
    project, _ = Project.objects.get_or_create(
        name='Demo Residency', location='Karachi',
        defaults={'description': 'Demo housing scheme', 'total_plots': 10},
    )
    phase, _ = ProjectPhase.objects.get_or_create(
        project=project, name='Phase 1', phase_number=1,
        launch_date=django.utils.timezone.now().date(),
        total_plots=10, price_per_marla=Decimal('900.00'),
    )

    # Plots
    plot1, _ = Plot.objects.get_or_create(
        project=project, phase=phase, plot_number='A-001',
        defaults={'plot_type': 'residential', 'size_marla': Decimal('5'),
                  'size_sqft': Decimal('1361.25'), 'price': Decimal('1000.00'),
                  'status': 'available', 'block': 'A', 'street_number': '1',
                  'facing_direction': 'North', 'holding_deposit': Decimal('0'),
                  'description': 'Demo plot A-001, total price Rs 1000.',
        },
    )
    plot2, _ = Plot.objects.get_or_create(
        project=project, phase=phase, plot_number='A-002',
        defaults={'plot_type': 'residential', 'size_marla': Decimal('5'),
                  'size_sqft': Decimal('1361.25'), 'price': Decimal('1200.00'),
                  'status': 'available', 'block': 'A', 'street_number': '2',
                  'facing_direction': 'South', 'holding_deposit': Decimal('0'),
                  'description': 'Demo plot A-002, total price Rs 1200.',
        },
    )

    # Customers (3)
    c1, _ = Customer.objects.get_or_create(
        first_name='Ali', last_name='Raza', email='ali.raza@example.com',
        phone='+92-300-1000001', cnic='42101-1000001-1', city='Karachi',
        address='Suite 4, Clifton', occupation='salaried',
        defaults={'created_by': django.contrib.auth.models.User.objects.get(username='admin')},
    )
    c2, _ = Customer.objects.get_or_create(
        first_name='Sana', last_name='Khan', email='sana.khan@example.com',
        phone='+92-300-1000002', cnic='42201-1000002-2', city='Lahore',
        address='House 9, Model Town', occupation='business',
        defaults={'created_by': django.contrib.auth.models.User.objects.get(username='admin')},
    )
    c3, _ = Customer.objects.get_or_create(
        first_name='Bilal', last_name='Ahmed', email='bilal.ahmed@example.com',
        phone='+92-300-1000003', cnic='42301-1000003-3', city='Islamabad',
        address='Flat 12, F-7', occupation='other', occupation_other='Engineer',
        defaults={'created_by': django.contrib.auth.models.User.objects.get(username='admin')},
    )

    # Bookings (2)
    b1, _ = Booking.objects.get_or_create(
        customer=c1, plot=plot1, total_amount=Decimal('1000.00'),
        advance_paid=Decimal('0'), status='active', source='walk_in',
        defaults={'notes': 'Demo booking 1 for payment testing.', 'created_by': sales_user},
    )
    b2, _ = Booking.objects.get_or_create(
        customer=c2, plot=plot2, total_amount=Decimal('1200.00'),
        advance_paid=Decimal('0'), status='active', source='website',
        defaults={'notes': 'Demo booking 2 for payment testing.', 'created_by': sales_user},
    )
    for b in (b1, b2):
        CustomerLedgerEntry.objects.get_or_create(
            customer=b.customer, booking=b, transaction_type='booking',
            reference_id=b.booking_id, debit=b.total_amount, credit=Decimal('0'),
            running_balance=b.total_amount,
            defaults={'entry_date': django.utils.timezone.now(), 'created_by': sales_user},
        )

    # Installment plans & installments
    def make_plan(booking):
        remaining = booking.total_amount - booking.advance_paid
        total = 4
        amount = (remaining / Decimal(total)).quantize(django.db.models.Decimal('0.01'))
        plan = django.db.models.models.InstallmentPlan.objects.get_or_create(
            booking=booking, total_installments=total,
            installment_amount=amount, down_payment_amount=booking.advance_paid,
            start_date=django.utils.timezone.now().date(), frequency='monthly',
            due_day=10, late_fee_per_day=Decimal('100.00'),
            grace_period_days=7,
        )[0]
        for j in range(1, total + 1):
            due = django.utils.timezone.now().date() + django.utils.dateutil.relativedelta.relativedelta(months=j)
            django.db.models.models.Installment.objects.get_or_create(
                plan=plan, installment_number=j, due_date=due,
                amount=amount, status='pending',
            )
        return plan

    plan1 = make_plan(b1)
    plan2 = make_plan(b2)

    # Payments (3): Rs 100 / 200 / 200
    def make_payment(booking, installment, amount, method='cash'):
        p, _ = Payment.objects.get_or_create(
            booking=booking, installment=installment,
            amount=amount, payment_date=django.utils.timezone.now().date(),
            payment_method='cash', payment_type='installment',
            reference_number=f'DEMO-{booking.booking_id}-{amount}',
            status='verified', receipt_generated=True,
            defaults={'created_by': sales_user, 'verified_by': accounts_user,
                      'verified_at': django.utils.timezone.now(),
                      'notes': 'Demo payment for P&G testing.',
        }
        )
        Receipt.objects.get_or_create(payment=p, defaults={'generated_by': accounts_user})
        PaymentAllocation.objects.get_or_create(
            payment=p, installment=installment, amount=amount,
            defaults={'allocated_by': accounts_user},
        )
        CustomerLedgerEntry.objects.get_or_create(
            customer=booking.customer, booking=booking,
            transaction_type='payment', reference_id=p.payment_id,
            defaults={'debit': Decimal('0'),
                      'credit': amount,
                      'running_balance': booking.remaining_balance,
                      'description': f'Payment {p.payment_id} (Rs {amount}) for installment #{installment.installment_number}',
                      'entry_date': django.utils.timezone.now(), 'created_by': accounts_user},
        )
        return p

    p1 = make_payment(b1, plan1.installments.get(installment_number=1), Decimal('100.00'))
    p2 = make_payment(b1, plan1.installments.get(installment_number=2), Decimal('200.00'))
    p3 = make_payment(b2, plan2.installments.get(installment_number=1), Decimal('200.00'))

    # Update installment statuses and booking advance
    plan1.installments.get(installment_number=1).status = 'partial'
    plan1.installments.get(installment_number=1).paid_amount = Decimal('100.00')
    plan1.installments.get(installment_number=1).paid_date = django.utils.timezone.now()
    plan1.installments.get(installment_number=1).save()
    plan1.installments.get(installment_number=2).status = 'paid'
    plan1.installments.get(installment_number=2).paid_amount = Decimal('200.00')
    plan1.installments.get(installment_number=2).paid_date = django.utils.timezone.now()
    plan1.installments.get(installment_number=2).save()
    plan2.installments.get(installment_number=1).status = 'paid'
    plan2.installments.get(installment_number=1).paid_amount = Decimal('200.00')
    plan2.installments.get(installment_number=1).paid_date = django.utils.timezone.now()
    plan2.installments.get(installment_number=1).save()
    b1.advance_paid = Decimal('300.00')
    b1.save()
    b2.advance_paid = Decimal('200.00')
    b2.save()

    # Audit log
    admin_user = django.contrib.auth.models.User.objects.get(username='admin')
    django.db.models.models.AuditLog.objects.create(
        user=django.contrib.auth.models.User.objects.get(username='admin'),
        action='create', model_name='Database',
        description='Reset to small clean demo set via reset_demo',
    )

    # Summary
    from django.db.models import Count
    self = django.core.management.base.BaseCommand
    self.stdout.write('  ✅ Done! Small clean demo set ready.')
    self.stdout.write(f'   Customers: {Customer.objects.count()}')
    self.stdout.write(f'   Bookings: {Booking.objects.count()}')
    self.stdout.write(f'   Installment Plans: {InstallmentPlan.objects.count()}')
    self.stdout.write(f'   Installments: {Installment.objects.count()}')
    self.stdout.write(f'   Payments: {Payment.objects.count()}')
    self.stdout.write(f'   Receipts: {Receipt.objects.count()}')
    self.stdout.write('   Payments: Rs 100, Rs 200, Rs 200 (verified)')