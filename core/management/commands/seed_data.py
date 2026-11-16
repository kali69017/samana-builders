"""
Management command to seed the database with comprehensive dummy data for Samana Builders ERP.
Run with: python manage.py seed_data
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
import random

from core.models import UserProfile, AuditLog, ApprovalChain, ApprovalStep
from customers.models import Customer, CustomerLedgerEntry
from properties.models import Project, ProjectPhase, Plot, PlotFeature, PriceHistory
from bookings.models import (
    Booking, BookingGroup, Reservation, BookingTransfer, BookingAmendment,
    InstallmentPlan, Installment, InstallmentPlanTemplate,
    CancellationPolicy, CancellationTier, EarlySettlement,
    LateFeeConfiguration, PaymentReminder
)
from payments.models import Payment, PaymentAllocation, Receipt, Refund


class Command(BaseCommand):
    help = 'Seeds the database with comprehensive dummy data'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🌱 Seeding database...'))

        # ─── 1. USERS ──────────────────────────────────────────────────────
        self.stdout.write('  Creating users...')
        
        users_data = [
            {'username': 'admin', 'email': 'admin@samana.com', 'password': 'admin123',
             'first_name': 'Admin', 'last_name': 'User', 'role': 'super_admin', 'phone': '+92-300-1111111'},
            {'username': 'ahmed', 'email': 'ahmed@samana.com', 'password': 'admin123',
             'first_name': 'Ahmed', 'last_name': 'Khan', 'role': 'admin', 'phone': '+92-300-2222222'},
            {'username': 'fatima', 'email': 'fatima@samana.com', 'password': 'admin123',
             'first_name': 'Fatima', 'last_name': 'Ali', 'role': 'sales', 'phone': '+92-300-3333333'},
            {'username': 'umar', 'email': 'umar@samana.com', 'password': 'admin123',
             'first_name': 'Umar', 'last_name': 'Hassan', 'role': 'accounts', 'phone': '+92-300-4444444'},
            {'username': 'sara', 'email': 'sara@samana.com', 'password': 'admin123',
             'first_name': 'Sara', 'last_name': 'Ahmed', 'role': 'sales', 'phone': '+92-300-5555555'},
            {'username': 'zain', 'email': 'zain@samana.com', 'password': 'admin123',
             'first_name': 'Zain', 'last_name': 'Malik', 'role': 'management', 'phone': '+92-300-6666666'},
        ]

        created_users = {}
        for u_data in users_data:
            user, created = User.objects.get_or_create(
                username=u_data['username'],
                defaults={
                    'email': u_data['email'],
                    'first_name': u_data['first_name'],
                    'last_name': u_data['last_name'],
                }
            )
            if created:
                user.set_password(u_data['password'])
                user.save()
                UserProfile.objects.create(
                    user=user,
                    role=u_data['role'],
                    phone=u_data['phone'],
                    cnic=f'{random.randint(10000,99999)}-{random.randint(1000000,9999999)}-{random.randint(1,9)}'
                )
                self.stdout.write(f'    ✓ Created user: {user.username} ({u_data["role"]})')
            else:
                # Ensure profile exists
                UserProfile.objects.get_or_create(
                    user=user,
                    defaults={'role': u_data['role'], 'phone': u_data['phone']}
                )
            created_users[u_data['role']] = user

        admin_user = created_users['super_admin']
        accounts_user = created_users['accounts']
        sales_user = created_users['sales']

        # ─── 2. CUSTOMERS ──────────────────────────────────────────────────
        self.stdout.write('  Creating customers...')
        
        customers_data = [
            {'first_name': 'Muhammad', 'last_name': 'Ali', 'phone': '+92-321-1000001', 'cnic': '42101-1234567-1', 'city': 'Lahore', 'address': '123 Gulberg, Lahore'},
            {'first_name': 'Ayesha', 'last_name': 'Khan', 'phone': '+92-322-1000002', 'cnic': '42201-2345678-2', 'city': 'Karachi', 'address': '456 Clifton, Karachi'},
            {'first_name': 'Bilal', 'last_name': 'Ahmed', 'phone': '+92-333-1000003', 'cnic': '42301-3456789-3', 'city': 'Islamabad', 'address': '789 F-7, Islamabad'},
            {'first_name': 'Sana', 'last_name': 'Malik', 'phone': '+92-334-1000004', 'cnic': '42401-4567890-4', 'city': 'Rawalpindi', 'address': '321 Saddar, Rawalpindi'},
            {'first_name': 'Usman', 'last_name': 'Butt', 'phone': '+92-335-1000005', 'cnic': '42501-5678901-5', 'city': 'Lahore', 'address': '654 DHA, Lahore'},
            {'first_name': 'Fatima', 'last_name': 'Zahra', 'phone': '+92-336-1000006', 'cnic': '42601-6789012-6', 'city': 'Multan', 'address': '987 Shah Rukn-e-Alam, Multan'},
            {'first_name': 'Omar', 'last_name': 'Sheikh', 'phone': '+92-337-1000007', 'cnic': '42701-7890123-7', 'city': 'Faisalabad', 'address': '147 Peoples Colony, Faisalabad'},
            {'first_name': 'Zainab', 'last_name': 'Hussain', 'phone': '+92-338-1000008', 'cnic': '42801-8901234-8', 'city': 'Karachi', 'address': '258 Gulshan-e-Iqbal, Karachi'},
            {'first_name': 'Hassan', 'last_name': 'Raza', 'phone': '+92-339-1000009', 'cnic': '42901-9012345-9', 'city': 'Lahore', 'address': '369 Model Town, Lahore'},
            {'first_name': 'Noor', 'last_name': 'Fatima', 'phone': '+92-340-1000010', 'cnic': '43101-0123456-1', 'city': 'Peshawar', 'address': '159 University Town, Peshawar'},
            {'first_name': 'Ali', 'last_name': 'Rizvi', 'phone': '+92-341-1000011', 'cnic': '43201-1122334-4', 'city': 'Quetta', 'address': '753 Civil Lines, Quetta'},
            {'first_name': 'Hira', 'last_name': 'Manzoor', 'phone': '+92-342-1000012', 'cnic': '43301-2233445-5', 'city': 'Sialkot', 'address': '951 Wazirabad Road, Sialkot'},
        ]

        for c_data in customers_data:
            customer, created = Customer.objects.get_or_create(
                cnic=c_data['cnic'],
                defaults={
                    'first_name': c_data['first_name'],
                    'last_name': c_data['last_name'],
                    'phone': c_data['phone'],
                    'email': f"{c_data['first_name'].lower()}.{c_data['last_name'].lower()}@email.com",
                    'city': c_data['city'],
                    'address': c_data['address'],
                    'created_by': admin_user,
                }
            )
            if created:
                self.stdout.write(f'    ✓ Created customer: {customer.customer_id} - {customer.full_name}')

        customers = Customer.objects.all()

        # ─── 3. PROJECTS ───────────────────────────────────────────────────
        self.stdout.write('  Creating projects...')
        
        projects_data = [
            {'name': 'Gold City Housing Scheme', 'description': 'A premium residential housing scheme located in the heart of Lahore, offering modern living spaces with world-class amenities including parks, mosques, and commercial areas.', 'location': 'Lahore', 'total_plots': 500},
            {'name': 'Silver Oak Villas', 'description': 'Luxury villa project in Islamabad featuring contemporary architecture, smart home features, and landscaped gardens. Perfect for families seeking exclusivity.', 'location': 'Islamabad', 'total_plots': 200},
            {'name': 'Green Valley Estate', 'description': 'Affordable housing solution in Rawalpindi with easy access to major highways. Features include schools, hospitals, and recreational areas within the community.', 'location': 'Rawalpindi', 'total_plots': 350},
        ]

        for p_data in projects_data:
            project, created = Project.objects.get_or_create(
                name=p_data['name'],
                defaults={
                    'description': p_data['description'],
                    'location': p_data['location'],
                    'total_plots': p_data['total_plots'],
                }
            )
            if created:
                self.stdout.write(f'    ✓ Created project: {project.name}')

        projects = Project.objects.all()
        gold_city = projects[0]
        silver_oak = projects[1]

        # ─── 4. PROJECT PHASES ─────────────────────────────────────────────
        self.stdout.write('  Creating project phases...')
        
        phases_data = [
            {'project': gold_city, 'phase_number': 1, 'name': 'Phase 1', 'launch_date': date(2025, 1, 15), 'total_plots': 150, 'price_per_marla': Decimal('85000')},
            {'project': gold_city, 'phase_number': 2, 'name': 'Phase 2', 'launch_date': date(2025, 6, 1), 'total_plots': 200, 'price_per_marla': Decimal('95000')},
            {'project': silver_oak, 'phase_number': 1, 'name': 'Block A', 'launch_date': date(2025, 3, 1), 'total_plots': 80, 'price_per_marla': Decimal('120000')},
            {'project': silver_oak, 'phase_number': 2, 'name': 'Block B', 'launch_date': date(2025, 9, 1), 'total_plots': 70, 'price_per_marla': Decimal('135000')},
        ]

        for ph_data in phases_data:
            phase, created = ProjectPhase.objects.get_or_create(
                project=ph_data['project'],
                name=ph_data['name'],
                defaults={
                    'phase_number': ph_data['phase_number'],
                    'launch_date': ph_data['launch_date'],
                    'total_plots': ph_data['total_plots'],
                    'price_per_marla': ph_data['price_per_marla'],
                }
            )
            if created:
                self.stdout.write(f'    ✓ Created phase: {phase.project.name} - {phase.name}')

        # ─── 5. PLOT FEATURES ──────────────────────────────────────────────
        self.stdout.write('  Creating plot features...')
        
        features_list = ['Park Facing', 'Corner Plot', 'Wider Road', 'Street Corner', 'Main Boulevard', 'Mosque Facing', 'Park View', 'Community Center']
        features = {}
        for f_name in features_list:
            f, _ = PlotFeature.objects.get_or_create(name=f_name)
            features[f_name] = f

        self.stdout.write(f'    ✓ Created {len(features)} plot features')

        # ─── 6. PLOTS ──────────────────────────────────────────────────────
        self.stdout.write('  Creating plots...')
        
        plot_types = ['residential', 'commercial']
        statuses_available = ['available', 'available', 'available', 'reserved', 'booked', 'booked', 'sold']
        
        # Gold City plots (20)
        for i in range(1, 21):
            block = random.choice(['A', 'B', 'C'])
            phase = ProjectPhase.objects.filter(project=gold_city).order_by('?').first()
            size_marla = random.choice([3, 5, 7, 10, 12])
            status = random.choice(statuses_available)
            price_per_marla = phase.price_per_marla if phase else Decimal('85000')
            price = size_marla * price_per_marla * Decimal(str(random.uniform(0.9, 1.1))).quantize(Decimal('0.01'))
            
            plot, created = Plot.objects.get_or_create(
                project=gold_city,
                plot_number=f'{block}-{str(i).zfill(3)}',
                defaults={
                    'phase': phase,
                    'plot_type': random.choice(plot_types),
                    'size_marla': size_marla,
                    'size_sqft': size_marla * Decimal('272.25'),
                    'price': price.quantize(Decimal('0.01')),
                    'status': status,
                    'block': block,
                    'street_number': str(random.randint(1, 30)),
                    'is_corner': random.choice([True, False, False]),
                    'is_park_facing': random.choice([True, False, False, False]),
                    'facing_direction': random.choice(['North', 'South', 'East', 'West']),
                    'holding_deposit': Decimal('50000') if status == 'available' else Decimal('0'),
                    'description': f'Beautiful {size_marla} marla plot in {gold_city.name} {phase.name if phase else ""}. Ideal for residential construction.',
                }
            )
            if created:
                # Add random features
                random_features = random.sample(list(features.values()), random.randint(1, 3))
                plot.features.add(*random_features)

        # Silver Oak plots (15)
        for i in range(1, 16):
            block = random.choice(['A', 'B'])
            phase = ProjectPhase.objects.filter(project=silver_oak).order_by('?').first()
            size_marla = random.choice([5, 8, 10, 15, 20])
            status = random.choice(statuses_available)
            price_per_marla = phase.price_per_marla if phase else Decimal('120000')
            price = size_marla * price_per_marla * Decimal(str(random.uniform(0.9, 1.1))).quantize(Decimal('0.01'))
            
            plot, created = Plot.objects.get_or_create(
                project=silver_oak,
                plot_number=f'{block}-{str(i).zfill(3)}',
                defaults={
                    'phase': phase,
                    'plot_type': random.choice(plot_types),
                    'size_marla': size_marla,
                    'size_sqft': size_marla * Decimal('272.25'),
                    'price': price.quantize(Decimal('0.01')),
                    'status': status,
                    'block': block,
                    'is_corner': random.choice([True, False, False]),
                    'is_park_facing': random.choice([True, False, False]),
                    'facing_direction': random.choice(['North', 'South', 'East', 'West']),
                    'holding_deposit': Decimal('75000') if status == 'available' else Decimal('0'),
                }
            )
            if created:
                random_features = random.sample(list(features.values()), random.randint(1, 2))
                plot.features.add(*random_features)

        self.stdout.write(f'    ✓ Created plots for Gold City and Silver Oak')

        # ─── 7. INSTALLMENT PLAN TEMPLATES ─────────────────────────────────
        self.stdout.write('  Creating installment plan templates...')
        
        templates_data = [
            {'name': '36-Month Standard', 'project': gold_city, 'total_installments': 36, 'frequency': 'monthly',
             'down_payment_percentage': Decimal('10'), 'late_fee_per_day': Decimal('100'), 'grace_period_days': 7},
            {'name': '24-Month Accelerated', 'project': gold_city, 'total_installments': 24, 'frequency': 'monthly',
             'down_payment_percentage': Decimal('20'), 'late_fee_per_day': Decimal('150'), 'grace_period_days': 5},
            {'name': '12-Quarter Plan', 'project': silver_oak, 'total_installments': 12, 'frequency': 'quarterly',
             'down_payment_percentage': Decimal('15'), 'late_fee_per_day': Decimal('200'), 'grace_period_days': 10},
            {'name': 'Full Payment', 'project': gold_city, 'total_installments': 1, 'frequency': 'monthly',
             'down_payment_percentage': Decimal('100'), 'late_fee_per_day': Decimal('0'), 'grace_period_days': 0},
        ]

        for t_data in templates_data:
            template, created = InstallmentPlanTemplate.objects.get_or_create(
                name=t_data['name'],
                project=t_data['project'],
                defaults={
                    'total_installments': t_data['total_installments'],
                    'frequency': t_data['frequency'],
                    'down_payment_percentage': t_data['down_payment_percentage'],
                    'late_fee_per_day': t_data['late_fee_per_day'],
                    'grace_period_days': t_data['grace_period_days'],
                }
            )
            if created:
                self.stdout.write(f'    ✓ Created template: {template.name}')

        # ─── 8. CANCELLATION POLICIES ──────────────────────────────────────
        self.stdout.write('  Creating cancellation policies...')
        
        policy, created = CancellationPolicy.objects.get_or_create(
            name='Standard Cancellation Policy',
            defaults={'description': 'Standard cancellation policy for residential bookings in Pakistan.'}
        )
        if created:
            CancellationTier.objects.create(policy=policy, from_days=0, to_days=30, refund_percentage=Decimal('75'), deduction_notes='25% processing fee')
            CancellationTier.objects.create(policy=policy, from_days=31, to_days=90, refund_percentage=Decimal('50'), deduction_notes='50% deduction')
            CancellationTier.objects.create(policy=policy, from_days=91, to_days=180, refund_percentage=Decimal('25'), deduction_notes='75% deduction')
            CancellationTier.objects.create(policy=policy, from_days=181, to_days=9999, refund_percentage=Decimal('0'), deduction_notes='No refund, transfer only')
            self.stdout.write(f'    ✓ Created cancellation policy with 4 tiers')

        # ─── 9. BOOKINGS ───────────────────────────────────────────────────
        self.stdout.write('  Creating bookings...')
        
        # Get available and booked plots
        booked_plots = list(Plot.objects.filter(status__in=['booked', 'sold', 'reserved'])[:8])
        
        booking_records = []
        for i, plot in enumerate(booked_plots[:5]):
            customer = customers[i % len(customers)]
            
            advance_pct = random.choice([Decimal('10'), Decimal('15'), Decimal('20'), Decimal('25')])
            advance = (plot.price * advance_pct / Decimal('100')).quantize(Decimal('0.01'))
            
            booking, created = Booking.objects.get_or_create(
                customer=customer,
                plot=plot,
                defaults={
                    'total_amount': plot.price,
                    'advance_paid': advance,
                    'status': random.choice(['confirmed', 'active', 'active', 'completed']) if plot.status == 'sold' else 'active',
                    'source': random.choice(['website', 'walk_in', 'referral', 'agent']),
                    'notes': f'Booking for {plot} at {plot.project.name}. Customer contacted via {"website" if random.random() > 0.5 else "referral"}.',
                    'created_by': random.choice([admin_user, sales_user]),
                }
            )
            
            if created:
                booking_records.append(booking)
                # Create ledger entry for booking
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
                
                # Create ledger entry for advance payment
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
                
                self.stdout.write(f'    ✓ Created booking: {booking.booking_id} - {customer.full_name}')

        # ─── 10. INSTALLMENT PLANS + INSTALLMENTS ──────────────────────────
        self.stdout.write('  Creating installment plans...')
        
        for booking in booking_records:
            template = random.choice(list(InstallmentPlanTemplate.objects.all()))
            if template.total_installments == 1:
                continue  # Skip full payment plans
            
            remaining = booking.total_amount - booking.advance_paid
            installment_amt = (remaining / Decimal(template.total_installments)).quantize(Decimal('0.01'))
            
            plan, created = InstallmentPlan.objects.get_or_create(
                booking=booking,
                defaults={
                    'template': template,
                    'total_installments': template.total_installments,
                    'installment_amount': installment_amt,
                    'down_payment_amount': booking.advance_paid,
                    'start_date': booking.booking_date,
                    'frequency': template.frequency,
                    'due_day': 10,
                    'late_fee_per_day': template.late_fee_per_day,
                    'grace_period_days': template.grace_period_days,
                }
            )
            
            if created:
                # Generate installments
                from dateutil.relativedelta import relativedelta
                
                for j in range(1, template.total_installments + 1):
                    if template.frequency == 'monthly':
                        due = booking.booking_date + relativedelta(months=j)
                    elif template.frequency == 'quarterly':
                        due = booking.booking_date + relativedelta(months=j * 3)
                    elif template.frequency == 'half_yearly':
                        due = booking.booking_date + relativedelta(months=j * 6)
                    else:
                        due = booking.booking_date + relativedelta(years=j)
                    
                    try:
                        due = due.replace(day=10)
                    except ValueError:
                        due = due.replace(day=28)
                    
                    # Mark some installments as paid
                    is_paid = j <= 3 and booking.status != 'confirmed'
                    
                    Installment.objects.create(
                        plan=plan,
                        installment_number=j,
                        due_date=due,
                        amount=installment_amt,
                        status='paid' if is_paid else 'pending',
                        paid_amount=installment_amt if is_paid else Decimal('0'),
                        paid_date=booking.booking_date + timedelta(days=j * 28) if is_paid else None,
                    )
                
                self.stdout.write(f'    ✓ Created installment plan: {plan}, {template.total_installments} installments')

        # ─── 11. PAYMENTS + RECEIPTS ───────────────────────────────────────
        self.stdout.write('  Creating payments...')
        
        installments = Installment.objects.filter(status='paid')[:15]
        for inst in installments:
            payment, created = Payment.objects.get_or_create(
                booking=inst.plan.booking,
                installment=inst,
                payment_date=inst.paid_date or date.today(),
                amount=inst.amount,
                defaults={
                    'payment_method': random.choice(['cash', 'bank_transfer', 'cheque', 'online', 'jazzcash', 'raast']),
                    'reference_number': f'TXN-{random.randint(100000, 999999)}',
                    'status': 'verified',
                    'verified_by': accounts_user,
                    'verified_at': timezone.now(),
                    'receipt_generated': True,
                    'created_by': sales_user,
                    'notes': f'Payment for {inst}',
                }
            )
            
            if created:
                # Create receipt
                Receipt.objects.create(
                    payment=payment,
                    generated_by=accounts_user,
                )
                
                # Create ledger entry
                CustomerLedgerEntry.objects.create(
                    customer=payment.booking.customer,
                    booking=payment.booking,
                    transaction_type='payment',
                    reference_id=payment.payment_id,
                    debit=Decimal('0'),
                    credit=payment.amount,
                    running_balance=payment.booking.remaining_balance,
                    description=f'Payment {payment.payment_id} for installment #{inst.installment_number}',
                    entry_date=payment.payment_date,
                    created_by=accounts_user,
                )

        # Also create some pending payments
        pending_installments = Installment.objects.filter(status='pending')[:5]
        for inst in pending_installments:
            Payment.objects.get_or_create(
                booking=inst.plan.booking,
                installment=inst,
                payment_date=date.today(),
                amount=inst.amount,
                defaults={
                    'payment_method': random.choice(['cheque', 'online', 'bank_transfer']),
                    'reference_number': f'TXN-{random.randint(100000, 999999)}',
                    'status': 'pending',
                    'created_by': sales_user,
                    'notes': 'Payment pending verification',
                }
            )

        self.stdout.write(f'    ✓ Created payments with receipts')

        # ─── 12. APPROVAL CHAINS ───────────────────────────────────────────
        self.stdout.write('  Creating approval chains...')
        
        chain, created = ApprovalChain.objects.get_or_create(
            name='Payment Verification',
            defaults={
                'model_name': 'Payment',
                'trigger_field': 'status',
                'trigger_value': 'pending',
                'is_active': True,
            }
        )
        if created:
            ApprovalStep.objects.create(chain=chain, step_order=1, role='accounts', min_amount=Decimal('0'), max_amount=Decimal('500000'))
            ApprovalStep.objects.create(chain=chain, step_order=2, role='management', min_amount=Decimal('500000'))
            self.stdout.write(f'    ✓ Created approval chain: Payment Verification')

        chain2, created = ApprovalChain.objects.get_or_create(
            name='Booking Cancellation',
            defaults={
                'model_name': 'Booking',
                'trigger_field': 'status',
                'trigger_value': 'cancelled',
                'is_active': True,
            }
        )
        if created:
            ApprovalStep.objects.create(chain=chain2, step_order=1, role='sales')
            ApprovalStep.objects.create(chain=chain2, step_order=2, role='accounts')
            self.stdout.write(f'    ✓ Created approval chain: Booking Cancellation')

        # ─── 13. AUDIT LOGS ─────────────────────────────────────────────────
        self.stdout.write('  Creating audit logs...')
        
        actions = ['create', 'update', 'login']
        models = ['Customer', 'Project', 'Plot', 'Booking', 'Payment', 'User']
        
        for _ in range(20):
            AuditLog.objects.create(
                user=random.choice([admin_user, sales_user, accounts_user]),
                action=random.choice(actions),
                model_name=random.choice(models),
                object_id=str(random.randint(1, 100)),
                description=f'Sample audit log entry',
                ip_address=f'192.168.1.{random.randint(2, 254)}',
            )

        self.stdout.write(f'    ✓ Created audit logs')

        # ─── 14. PRICE HISTORY ─────────────────────────────────────────────
        self.stdout.write('  Creating price history...')
        
        for plot in Plot.objects.all()[:5]:
            PriceHistory.objects.create(
                plot=plot,
                old_price=plot.price * Decimal('0.85'),
                new_price=plot.price,
                change_reason='Phase launch price adjustment',
                changed_by=admin_user,
            )

        self.stdout.write(f'    ✓ Created price history records')

        # ─── SUMMARY ───────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\n✅ Database seeded successfully!'))
        self.stdout.write(f'   Users: {User.objects.count()}')
        self.stdout.write(f'   Customers: {Customer.objects.count()}')
        self.stdout.write(f'   Projects: {Project.objects.count()}')
        self.stdout.write(f'   Project Phases: {ProjectPhase.objects.count()}')
        self.stdout.write(f'   Plots: {Plot.objects.count()}')
        self.stdout.write(f'   Plot Features: {PlotFeature.objects.count()}')
        self.stdout.write(f'   Bookings: {Booking.objects.count()}')
        self.stdout.write(f'   Installment Plans: {InstallmentPlan.objects.count()}')
        self.stdout.write(f'   Installments: {Installment.objects.count()}')
        self.stdout.write(f'   Payments: {Payment.objects.count()}')
        self.stdout.write(f'   Receipts: {Receipt.objects.count()}')
        self.stdout.write(f'   Customer Ledger Entries: {CustomerLedgerEntry.objects.count()}')
        self.stdout.write(f'   Installment Plan Templates: {InstallmentPlanTemplate.objects.count()}')
        self.stdout.write(f'   Cancellation Policy: {CancellationPolicy.objects.count()}')
        self.stdout.write(f'   Audit Logs: {AuditLog.objects.count()}')
        self.stdout.write(f'   Approval Chains: {ApprovalChain.objects.count()}')
        self.stdout.write(f'   Price History: {PriceHistory.objects.count()}')
        self.stdout.write(f'\n   📋 Login with: admin / admin123')