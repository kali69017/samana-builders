"""Populate the Samana ERP database with realistic dummy data.

Usage:
    .\\.venv312\\Scripts\\python.exe populate_dummy_data.py

Wipes existing ERP data, then reseeds users, customers, projects, plots,
bookings, installment plans, payments, receipts and related records.
"""

import os
import random
from datetime import date, timedelta
from decimal import Decimal

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'samana_erp.settings')
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone

from core.models import (
    ApprovalChain,
    ApprovalStep,
    AuditLog,
    LoginAttempt,
    UserProfile,
)
from customers.models import Customer, CustomerLedgerEntry, ReceivableAging
from properties.models import Plot, PlotFeature, PriceHistory, Project, ProjectPhase
from bookings.models import (
    Booking,
    BookingGroup,
    BookingTransfer,
    CancellationPolicy,
    CancellationTier,
    EarlySettlement,
    Installment,
    InstallmentPlan,
    InstallmentPlanTemplate,
    Reservation,
)
from payments.models import Payment, PaymentAllocation, Receipt, Refund


def clean():
    from payments.models import PaymentAttachment

    PaymentAttachment.objects.all().delete()
    PaymentAllocation.objects.all().delete()
    Refund.objects.all().delete()
    Receipt.objects.all().delete()
    Payment.objects.all().delete()
    Installment.objects.all().delete()
    InstallmentPlan.objects.all().delete()
    InstallmentPlanTemplate.objects.all().delete()
    BookingTransfer.objects.all().delete()
    EarlySettlement.objects.all().delete()
    Reservation.objects.all().delete()
    Booking.objects.all().delete()
    BookingGroup.objects.all().delete()
    CancellationTier.objects.all().delete()
    CancellationPolicy.objects.all().delete()
    CustomerLedgerEntry.objects.all().delete()
    ReceivableAging.objects.all().delete()
    Customer.objects.all().delete()
    PriceHistory.objects.all().delete()
    Plot.objects.all().delete()
    PlotFeature.objects.all().delete()
    ProjectPhase.objects.all().delete()
    Project.objects.all().delete()
    ApprovalStep.objects.all().delete()
    ApprovalChain.objects.all().delete()
    LoginAttempt.objects.all().delete()
    AuditLog.objects.all().delete()
    UserProfile.objects.all().delete()
    User.objects.filter(
        username__in=['admin', 'ahmed', 'fatima', 'umar', 'sara', 'zain']
    ).delete()


def seed_users():
    demo_users = [
        ('admin', 'super_admin', 'Admin', 'User'),
        ('ahmed', 'admin', 'Ahmed', 'Khan'),
        ('fatima', 'sales', 'Fatima', 'Ali'),
        ('umar', 'accounts', 'Umar', 'Hassan'),
        ('sara', 'sales', 'Sara', 'Ahmed'),
        ('zain', 'management', 'Zain', 'Malik'),
    ]
    created = {}
    for username, role, first, last in demo_users:
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={'first_name': first, 'last_name': last, 'email': f'{username}@samana.com'},
        )
        user.set_password('admin123')
        user.save()
        UserProfile.objects.get_or_create(
            user=user, defaults={'role': role, 'phone': '+92-300-0000000'}
        )
        created[role] = user
    return created


def seed_customers(admin_user):
    rows = [
        ('Muhammad', 'Ali', '+92-300-1112221', '42101-1111111-1', 'Lahore', '12 Gulberg III, Lahore'),
        ('Ayesha', 'Khan', '+92-321-2223332', '42201-2222222-2', 'Karachi', '45 Clifton Block 5, Karachi'),
        ('Bilal', 'Ahmed', '+92-322-3334443', '42301-3333333-3', 'Islamabad', '78 F-11 Markaz, Islamabad'),
        ('Sana', 'Malik', '+92-333-4445554', '42401-4444444-4', 'Rawalpindi', '96 Committee Chowk, Rawalpindi'),
        ('Usman', 'Butt', '+92-334-5556665', '42501-5555555-5', 'Lahore', '201 DHA Phase 5, Lahore'),
        ('Fatima', 'Zahra', '+92-335-6667776', '42601-6666666-6', 'Multan', '87 Gulgasht, Multan'),
        ('Omar', 'Sheikh', '+92-336-7778887', '42701-7777777-7', 'Faisalabad', '143 Peoples Colony No.1, Faisalabad'),
        ('Zainab', 'Hussain', '+92-337-8889998', '42801-8888888-8', 'Karachi', '321 North Nazimabad, Karachi'),
    ]
    customers = []
    for first, last, phone, cnic, city, address in rows:
        customer = Customer.objects.create(
            first_name=first,
            last_name=last,
            phone=phone,
            cnic=cnic,
            city=city,
            address=address,
            email=f'{first.lower()}.{last.lower()}@example.com',
            created_by=admin_user,
        )
        customers.append(customer)
    return customers


def seed_projects():
    projects_data = [
        ('Gold City Housing Scheme', 'Lahore', 500, 'booking_open',
         'Premium residential housing scheme offering modern living with parks and commercial areas.'),
        ('Silver Oak Villas', 'Islamabad', 200, 'under_construction',
         'Luxury villa project featuring contemporary architecture and landscaped gardens.'),
        ('Green Valley Estate', 'Rawalpindi', 350, 'booking_open',
         'Affordable housing solution near major highways with schools and hospitals.'),
    ]
    projects = []
    for name, location, total, status, description in projects_data:
        projects.append(Project.objects.create(
            name=name, location=location, total_plots=total,
            status=status, description=description,
        ))
    return projects


def seed_phases(projects):
    rows = [
        (projects[0], 'Phase 1', date(2025, 1, 15), 150, Decimal('85000')),
        (projects[0], 'Phase 2', date(2025, 6, 1), 200, Decimal('95000')),
        (projects[1], 'Block A', date(2025, 3, 1), 80, Decimal('120000')),
        (projects[1], 'Block B', date(2025, 9, 1), 70, Decimal('135000')),
    ]
    phases = []
    for project, name, launch, total, rate in rows:
        phases.append(ProjectPhase.objects.create(
            project=project, name=name, launch_date=launch,
            total_plots=total, price_per_marla=rate,
        ))
    return phases


def seed_features():
    names = ['Park Facing', 'Corner Plot', 'Mosque Facing', 'Main Boulevard', 'Park View', 'Wide Road']
    return [PlotFeature.objects.create(name=name) for name in names]


def seed_plots(projects, phases, features):
    plot_rows = [
        (projects[0], phases[0], 'A-101', 'residential', Decimal('5'), Decimal('85000'), 'booked', 'A'),
        (projects[0], phases[0], 'A-102', 'residential', Decimal('7'), Decimal('85000'), 'sold', 'A'),
        (projects[0], phases[1], 'B-201', 'commercial', Decimal('10'), Decimal('95000'), 'available', 'B'),
        (projects[0], phases[1], 'B-202', 'residential', Decimal('5'), Decimal('95000'), 'reserved', 'B'),
        (projects[0], phases[1], 'B-203', 'residential', Decimal('3'), Decimal('95000'), 'on_hold', 'B'),
        (projects[0], phases[1], 'B-204', 'commercial', Decimal('10'), Decimal('95000'), 'available', 'B'),
        (projects[1], phases[2], 'A-001', 'residential', Decimal('8'), Decimal('120000'), 'booked', 'A'),
        (projects[1], phases[2], 'A-002', 'residential', Decimal('10'), Decimal('120000'), 'available', 'A'),
        (projects[1], phases[3], 'B-001', 'residential', Decimal('5'), Decimal('135000'), 'available', 'B'),
        (projects[1], phases[3], 'B-002', 'commercial', Decimal('15'), Decimal('135000'), 'reserved', 'B'),
        (projects[2], None, 'GC-01', 'residential', Decimal('5'), Decimal('70000'), 'available', 'GC'),
        (projects[2], None, 'GC-02', 'residential', Decimal('10'), Decimal('70000'), 'available', 'GC'),
    ]
    plots = []
    for project, phase, number, plot_type, size, rate, status, block in plot_rows:
        plot = Plot.objects.create(
            project=project,
            phase=phase,
            plot_number=number,
            plot_type=plot_type,
            size_marla=size,
            size_sqft=(size * Decimal('272.25')).quantize(Decimal('0.01')),
            price=(size * rate).quantize(Decimal('0.01')),
            status=status,
            block=block,
            facing_direction=random.choice(['North', 'South', 'East', 'West']),
            holding_deposit=Decimal('50000') if status == 'available' else Decimal('0'),
        )
        if random.random() < 0.5:
            plot.features.add(random.choice(features))
        plots.append(plot)
    return plots


def seed_cancellation_policy():
    policy = CancellationPolicy.objects.create(
        name='Standard Cancellation Policy',
        description='Standard cancellation policy for residential bookings.',
    )
    CancellationTier.objects.create(policy=policy, from_days=0, to_days=30, refund_percentage=Decimal('75'), deduction_notes='25% processing fee')
    CancellationTier.objects.create(policy=policy, from_days=31, to_days=90, refund_percentage=Decimal('50'), deduction_notes='50% deduction')
    CancellationTier.objects.create(policy=policy, from_days=91, to_days=180, refund_percentage=Decimal('25'), deduction_notes='75% deduction')
    CancellationTier.objects.create(policy=policy, from_days=181, to_days=9999, refund_percentage=Decimal('0'), deduction_notes='No refund, transfer only')
    return policy


def seed_bookings(customers, plots, admin_user):
    booking_specs = [
        (customers[0], plots[0], Decimal('10'), 'active', 'website'),
        (customers[1], plots[6], Decimal('15'), 'confirmed', 'walk_in'),
        (customers[2], plots[1], Decimal('20'), 'completed', 'referral'),
        (customers[3], plots[3], Decimal('10'), 'active', 'agent'),
    ]
    bookings = []
    for customer, plot, advance_pct, status, source in booking_specs:
        advance = (plot.price * advance_pct / Decimal('100')).quantize(Decimal('0.01'))
        booking = Booking.objects.create(
            customer=customer,
            plot=plot,
            total_amount=plot.price,
            advance_paid=advance,
            status=status,
            source=source,
            notes=f'Booking for {plot.plot_number} at {plot.project.name}.',
            created_by=admin_user,
        )
        if status != 'completed':
            plot.status = 'booked'
            plot.save()
        CustomerLedgerEntry.objects.create(
            customer=customer,
            booking=booking,
            transaction_type='booking',
            reference_id=booking.booking_id,
            debit=booking.total_amount,
            credit=Decimal('0'),
            running_balance=booking.total_amount - booking.advance_paid,
            description=f'New booking - {plot.plot_number} at {plot.project.name}',
            entry_date=booking.booking_date,
            created_by=admin_user,
        )
        if booking.advance_paid > 0:
            CustomerLedgerEntry.objects.create(
                customer=customer,
                booking=booking,
                transaction_type='payment',
                reference_id=booking.booking_id,
                debit=Decimal('0'),
                credit=booking.advance_paid,
                running_balance=booking.total_amount - booking.advance_paid,
                description=f'Advance payment for {booking.booking_id}',
                entry_date=booking.booking_date,
                created_by=admin_user,
            )
        bookings.append(booking)
    return bookings


def seed_templates(projects):
    rows = [
        ('36-Month Standard', projects[0], 36, 'monthly', Decimal('10'), Decimal('100'), 7),
        ('24-Month Accelerated', projects[0], 24, 'monthly', Decimal('20'), Decimal('150'), 5),
        ('12-Quarter Plan', projects[1], 12, 'quarterly', Decimal('15'), Decimal('200'), 10),
    ]
    templates = []
    for name, project, count, freq, dp, late, grace in rows:
        templates.append(InstallmentPlanTemplate.objects.create(
            name=name, project=project, total_installments=count, frequency=freq,
            down_payment_percentage=dp, late_fee_per_day=late, grace_period_days=grace,
        ))
    return templates


def seed_plans(bookings, templates):
    plan_specs = [
        (bookings[0], templates[0]),
        (bookings[1], templates[2]),
        (bookings[3], templates[1]),
    ]
    plans = []
    for booking, template in plan_specs:
        remaining = booking.total_amount - booking.advance_paid
        install_amount = (remaining / Decimal(template.total_installments)).quantize(Decimal('0.01'))
        plan = InstallmentPlan.objects.create(
            booking=booking,
            template=template,
            total_installments=template.total_installments,
            installment_amount=install_amount,
            down_payment_amount=booking.advance_paid,
            start_date=booking.booking_date,
            frequency=template.frequency,
            due_day=10,
            late_fee_per_day=template.late_fee_per_day,
            grace_period_days=template.grace_period_days,
        )
        plan.auto_generate()
        plans.append(plan)
    return plans


def seed_reservations(customers, plots, sales_user):
    rows = [
        (customers[4], plots[5], Decimal('50000')),
        (customers[5], plots[7], Decimal('75000')),
    ]
    reservations = []
    for customer, plot, token in rows:
        reservations.append(Reservation.objects.create(
            customer=customer,
            plot=plot,
            token_amount=token,
            expires_at=timezone.now() + timedelta(days=30),
            status='active',
            created_by=sales_user,
        ))
    return reservations


def seed_payments(plans, accounts_user, sales_user):
    paid_installments = []
    plan_paid_counts = {0: 2, 1: 1, 2: 1}
    for idx, plan in enumerate(plans):
        count = plan_paid_counts.get(idx, 0)
        for inst in list(plan.installments.order_by('installment_number'))[:count]:
            inst.status = 'paid'
            inst.paid_amount = inst.amount
            inst.paid_date = inst.due_date - timedelta(days=3)
            inst.save()
            paid_installments.append(inst)

    balances = {}
    methods = ['cash', 'bank_transfer', 'online']
    for inst in paid_installments:
        booking = inst.plan.booking
        key = booking.pk
        if key not in balances:
            balances[key] = booking.total_amount - booking.advance_paid
        payment = Payment.objects.create(
            booking=booking,
            installment=inst,
            amount=inst.amount,
            payment_date=inst.paid_date,
            payment_method=random.choice(methods),
            payment_type='installment',
            reference_number=f'TXN-{random.randint(100000, 999999)}',
            status='verified',
            receipt_generated=True,
            created_by=sales_user,
            verified_by=accounts_user,
            verified_at=timezone.now(),
            notes=f'Payment for installment #{inst.installment_number}',
        )
        Receipt.objects.create(payment=payment, generated_by=accounts_user)
        PaymentAllocation.objects.create(
            payment=payment, installment=inst, amount=inst.amount, allocated_by=accounts_user
        )
        balances[key] -= payment.amount
        CustomerLedgerEntry.objects.create(
            customer=booking.customer,
            booking=booking,
            transaction_type='payment',
            reference_id=payment.payment_id,
            debit=Decimal('0'),
            credit=payment.amount,
            running_balance=balances[key],
            description=f'Payment {payment.payment_id} for installment #{inst.installment_number}',
            entry_date=payment.payment_date,
            created_by=accounts_user,
        )

    pending_inst = plans[0].installments.filter(status='pending').order_by('installment_number').first()
    if pending_inst:
        Payment.objects.create(
            booking=plans[0].booking,
            installment=pending_inst,
            amount=pending_inst.amount,
            payment_date=date.today(),
            payment_method='cheque',
            payment_type='installment',
            status='pending',
            bank_name='Habib Bank Limited',
            cheque_number='CHQ-902345',
            cheque_date=date.today(),
            reference_number='TXN-PENDING-001',
            created_by=sales_user,
            notes='Cheque submitted, awaiting clearance.',
        )

    rejected_inst = plans[1].installments.filter(status='pending').order_by('installment_number').first()
    if rejected_inst:
        Payment.objects.create(
            booking=plans[1].booking,
            installment=rejected_inst,
            amount=rejected_inst.amount,
            payment_date=date.today(),
            payment_method='online',
            payment_type='installment',
            status='rejected',
            reference_number='TXN-REJECTED-002',
            created_by=sales_user,
            verified_by=accounts_user,
            verified_at=timezone.now(),
            notes='Transaction reference mismatch.',
        )


def seed_refunds(bookings, admin_user):
    Refund.objects.create(
        booking=bookings[0],
        amount=Decimal('20000'),
        reason='overpayment',
        status='approved',
        approved_by=admin_user,
        processed_date=timezone.now(),
        notes='Excess amount returned to customer.',
    )
    Refund.objects.create(
        booking=bookings[1],
        amount=Decimal('68000'),
        reason='cancellation',
        status='pending',
        notes='Waiting for management approval.',
    )


def seed_transfers(bookings, customers, admin_user):
    BookingTransfer.objects.create(
        booking=bookings[3],
        from_customer=customers[3],
        to_customer=customers[6],
        transfer_fee=Decimal('25000'),
        previous_payments_handling='transfer',
        approved_by=admin_user,
        notes='Plot transferred to a buyer in the same family.',
    )


def seed_early_settlement(plans):
    plan = plans[1]
    pending = list(plan.installments.exclude(status='paid'))
    total_remaining = sum(i.amount + i.late_fee for i in pending)
    discount = (total_remaining * Decimal('0.05')).quantize(Decimal('0.01'))
    EarlySettlement.objects.create(
        plan=plan,
        remaining_installments=len(pending),
        total_remaining_amount=total_remaining.quantize(Decimal('0.01')),
        discount_percentage=Decimal('5'),
        discount_amount=discount,
        settlement_amount=total_remaining - discount,
        approved=True,
        settled_at=timezone.now(),
    )


def seed_approval_chains():
    chain = ApprovalChain.objects.create(
        name='Payment Verification', model_name='Payment',
        trigger_field='status', trigger_value='pending', is_active=True,
    )
    ApprovalStep.objects.create(
        chain=chain, step_order=1, role='accounts',
        min_amount=Decimal('0'), max_amount=Decimal('500000'),
    )
    ApprovalStep.objects.create(
        chain=chain, step_order=2, role='management', min_amount=Decimal('500000'),
    )
    chain2 = ApprovalChain.objects.create(
        name='Booking Cancellation', model_name='Booking',
        trigger_field='status', trigger_value='cancelled', is_active=True,
    )
    ApprovalStep.objects.create(chain=chain2, step_order=1, role='sales')
    ApprovalStep.objects.create(chain=chain2, step_order=2, role='accounts')
    return chain, chain2


def seed_audit_logs(users):
    actions = ['create', 'update', 'login', 'verify', 'reject']
    models = ['Customer', 'Project', 'Plot', 'Booking', 'Payment', 'User']
    for _ in range(10):
        AuditLog.objects.create(
            user=random.choice(list(users.values())),
            action=random.choice(actions),
            model_name=random.choice(models),
            object_id=str(random.randint(1, 100)),
            description='Dummy audit log entry.',
            ip_address=f'192.168.1.{random.randint(2, 254)}',
        )


def seed_price_history(plots, admin_user):
    for plot in plots[:4]:
        PriceHistory.objects.create(
            plot=plot,
            old_price=(plot.price * Decimal('0.85')).quantize(Decimal('0.01')),
            new_price=plot.price,
            change_reason='Phase launch price adjustment',
            changed_by=admin_user,
        )


def seed_aging(bookings):
    for booking in bookings[:2]:
        ReceivableAging.objects.create(
            customer=booking.customer,
            booking=booking,
            current_balance=booking.remaining_balance,
            days_overdue=0,
            aging_bucket='current',
        )


def seed_login_attempts():
    LoginAttempt.objects.create(username='admin', ip_address='127.0.0.1', is_success=True)
    LoginAttempt.objects.create(username='ahmed', ip_address='127.0.0.1', is_success=True)
    LoginAttempt.objects.create(username='test', ip_address='127.0.0.1', is_success=False)


def print_summary():
    print('Database populated successfully:')
    print(f'  Users: {User.objects.count()}')
    print(f'  Customers: {Customer.objects.count()}')
    print(f'  Projects: {Project.objects.count()}')
    print(f'  Project Phases: {ProjectPhase.objects.count()}')
    print(f'  Plots: {Plot.objects.count()}')
    print(f'  Bookings: {Booking.objects.count()}')
    print(f'  Installment Plans: {InstallmentPlan.objects.count()}')
    print(f'  Installments: {Installment.objects.count()}')
    print(f'  Payments: {Payment.objects.count()}')
    print(f'  Receipts: {Receipt.objects.count()}')
    print(f'  Refunds: {Refund.objects.count()}')
    print(f'  Reservations: {Reservation.objects.count()}')
    print(f'  Ledger Entries: {CustomerLedgerEntry.objects.count()}')
    print(f'  Audit Logs: {AuditLog.objects.count()}')
    print('')
    print('  Login with: admin / admin123')


def main():
    print('Wiping existing data...')
    clean()
    users = seed_users()
    admin_user = users['super_admin']
    customers = seed_customers(admin_user)
    projects = seed_projects()
    phases = seed_phases(projects)
    features = seed_features()
    plots = seed_plots(projects, phases, features)
    seed_cancellation_policy()
    bookings = seed_bookings(customers, plots, admin_user)
    templates = seed_templates(projects)
    plans = seed_plans(bookings, templates)
    seed_reservations(customers, plots, users['sales'])
    seed_payments(plans, users['accounts'], users['sales'])
    seed_refunds(bookings, admin_user)
    seed_transfers(bookings, customers, admin_user)
    seed_early_settlement(plans)
    seed_approval_chains()
    seed_audit_logs(users)
    seed_price_history(plots, admin_user)
    seed_aging(bookings)
    seed_login_attempts()

    group = BookingGroup.objects.create(
        customer=customers[0],
        total_amount=bookings[0].total_amount,
        discount_amount=Decimal('0'),
        payment_plan='36-Month Standard',
    )
    bookings[0].group = group
    bookings[0].save()
    print_summary()


if __name__ == '__main__':
    main()
