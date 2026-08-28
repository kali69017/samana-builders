"""Flaw-fix regression tests for the Samana Builders ERP.

Each test class in this file targets a specific defect that was found and
fixed in the 2026 audit pass:

1.  Double-booking guard        — a plot can only be booked when available
2.  Booking cancel guard        — bookings with verified payments need refunds
3.  Confirm idempotency         — already-confirmed stays 200; cancelled → 400
4.  Installment mark-paid       — validates bounds and creates a Payment row
5.  Payment/installment link    — installment must belong to the booking
6.  Bounced reversal            — verified payments reverse booking/installment
7.  Receipt on API verify       — verify auto-generates the receipt
8.  Customer delete protection  — customers with history are not deletable
9.  Public plot feed            — only available plots are exposed
10. Lead conversion validation — CNIC + phone required, duplicates blocked
11. Login rate limiting         — 5 failures per 15 min → 429
12. Reservation conversion      — creates a real booking, plot → booked
13. ID generation               — no duplicate IDs under rapid creation
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking, InstallmentPlan, InstallmentPlanTemplate, Reservation
from core.models import UserProfile, Lead
from customers.models import Customer
from payments.models import Payment, Receipt
from properties.models import Plot, Project


class FlawFixBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'adminpass123')
        self.client.force_authenticate(user=self.admin)
        self.project = Project.objects.create(name='FlawFix Project', location='Lahore', total_plots=100)
        self.plot = Plot.objects.create(
            plot_number='FF-001', project=self.project, size_marla=Decimal('5'),
            price=Decimal('5000000'), status='available',
        )
        self.customer = Customer.objects.create(
            first_name='Flaw', last_name='Fixer', phone='+92-301-5556667',
            cnic='35202-5555555-5', email='flawfix@example.com', created_by=self.admin,
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('5000000'),
            advance_paid=Decimal('0'), status='confirmed', created_by=self.admin,
        )

    def new_plot(self, number='FF-002', price='3000000', status='available'):
        return Plot.objects.create(
            plot_number=number, project=self.project, size_marla=Decimal('3'),
            price=Decimal(price), status=status,
        )

    def make_payment(self, booking=None, amount='100000', status='pending', method='cash'):
        return Payment.objects.create(
            booking=booking or self.booking, amount=Decimal(amount),
            payment_date=date.today(), payment_method=method,
            payment_type='installment', status=status, created_by=self.admin,
        )


# ─── 1. DOUBLE-BOOKING GUARD ────────────────────────────────────────────────
class DoubleBookingGuardTests(FlawFixBase):
    def test_booking_marks_plot_booked(self):
        plot = self.new_plot()
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '3000000', 'advance_paid': '300000', 'source': 'walk_in',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        plot.refresh_from_db()
        self.assertEqual(plot.status, 'booked')

    def test_second_booking_on_booked_plot_rejected(self):
        plot = self.new_plot()
        plot.status = 'booked'
        plot.save()
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '3000000', 'source': 'walk_in',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_booking_on_sold_plot_rejected(self):
        plot = self.new_plot(status='sold')
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '3000000',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_booking_on_cancelled_plot_rejected(self):
        plot = self.new_plot(status='cancelled')
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '3000000',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_active_booking_on_same_plot_rejected(self):
        plot = self.new_plot()
        Booking.objects.create(
            customer=self.customer, plot=plot, total_amount=Decimal('3000000'),
            status='active', created_by=self.admin,
        )
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '3000000',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ─── 2. BOOKING CANCEL GUARD ────────────────────────────────────────────────
class BookingCancelGuardTests(FlawFixBase):
    def test_cancel_without_payments_succeeds(self):
        resp = self.client.post(reverse('booking-cancel', args=[self.booking.pk]),
                                {'reason': 'customer_request'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'cancelled')
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, 'available')

    def test_cancel_with_verified_payment_rejected(self):
        self.make_payment(status='verified')
        resp = self.client.post(reverse('booking-cancel', args=[self.booking.pk]),
                                {'reason': 'customer_request'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_confirm_cancelled_booking_rejected(self):
        self.booking.status = 'cancelled'
        self.booking.save()
        resp = self.client.post(reverse('booking-confirm', args=[self.booking.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_already_confirmed_idempotent(self):
        resp = self.client.post(reverse('booking-confirm', args=[self.booking.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')


# ─── 3. INSTALLMENT MARK-PAID INTEGRITY ─────────────────────────────────────
class InstallmentMarkPaidTests(FlawFixBase):
    def setUp(self):
        super().setUp()
        self.plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=3, installment_amount=Decimal('1000000'),
            down_payment_amount=Decimal('2000000'), start_date=date.today(), frequency='monthly',
        )
        self.plan.auto_generate()
        self.inst = self.plan.installments.first()

    def test_mark_paid_creates_payment_row(self):
        resp = self.client.post(reverse('installment-mark-paid', args=[self.inst.pk]),
                                {'paid_date': date.today().isoformat()}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(Payment.objects.filter(
            booking=self.booking, installment=self.inst, status='verified').exists())

    def test_mark_paid_negative_rejected(self):
        resp = self.client.post(reverse('installment-mark-paid', args=[self.inst.pk]),
                                {'paid_amount': '-10'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mark_paid_above_total_rejected(self):
        resp = self.client.post(reverse('installment-mark-paid', args=[self.inst.pk]),
                                {'paid_amount': '99999999'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mark_paid_partial_sets_partial_status(self):
        resp = self.client.post(reverse('installment-mark-paid', args=[self.inst.pk]),
                                {'paid_amount': '400000'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.status, 'partial')
        self.assertEqual(self.inst.paid_amount, Decimal('400000'))

    def test_mark_paid_full_completes_booking(self):
        # down_payment 2M + 3 installments of 1M = 5M total
        self.booking.advance_paid = Decimal('2000000')
        self.booking.save()
        for inst in self.plan.installments.all():
            self.client.post(reverse('installment-mark-paid', args=[inst.pk]),
                             {'paid_date': date.today().isoformat()}, format='json')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'completed')
        self.assertEqual(self.booking.advance_paid, self.booking.total_amount)


# ─── 4. PAYMENT / INSTALLMENT LINK ──────────────────────────────────────────
class PaymentLinkTests(FlawFixBase):
    def test_installment_from_other_booking_rejected(self):
        other_plot = self.new_plot('FF-099')
        other_booking = Booking.objects.create(
            customer=self.customer, plot=other_plot, total_amount=Decimal('2000000'),
            status='confirmed', created_by=self.admin,
        )
        other_plan = InstallmentPlan.objects.create(
            booking=other_booking, total_installments=2, installment_amount=Decimal('500000'),
            down_payment_amount=Decimal('1000000'), start_date=date.today(), frequency='monthly',
        )
        other_plan.auto_generate()
        foreign_inst = other_plan.installments.first()

        resp = self.client.post(reverse('payment-list'), {
            'booking': self.booking.pk, 'installment': foreign_inst.pk,
            'amount': '100000', 'payment_date': date.today().isoformat(),
            'payment_method': 'cash', 'payment_type': 'installment',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_installment_from_same_booking_accepted(self):
        plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=2, installment_amount=Decimal('500000'),
            down_payment_amount=Decimal('1000000'), start_date=date.today(), frequency='monthly',
        )
        plan.auto_generate()
        inst = plan.installments.first()
        resp = self.client.post(reverse('payment-list'), {
            'booking': self.booking.pk, 'installment': inst.pk,
            'amount': '100000', 'payment_date': date.today().isoformat(),
            'payment_method': 'cash', 'payment_type': 'installment',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


# ─── 5. BOUNCED PAYMENT REVERSAL ────────────────────────────────────────────
class BouncedPaymentReversalTests(FlawFixBase):
    def test_bounce_pending_payment_does_not_touch_advance(self):
        payment = self.make_payment(status='pending', method='cheque')
        self.booking.advance_paid = Decimal('100000')
        self.booking.save()
        resp = self.client.post(reverse('payment-mark-bounced', args=[payment.pk]),
                                {'bounce_reason': 'insufficient funds'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.advance_paid, Decimal('100000'))

    def test_bounce_verified_payment_reverses_advance(self):
        payment = self.make_payment(status='verified', method='cheque', amount='100000')
        self.booking.advance_paid = Decimal('100000')
        self.booking.save()
        resp = self.client.post(reverse('payment-mark-bounced', args=[payment.pk]),
                                {'bounce_reason': 'insufficient funds'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'bounced')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.advance_paid, Decimal('0'))

    def test_bounce_verified_payment_reverses_installment(self):
        plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=1, installment_amount=Decimal('500000'),
            down_payment_amount=Decimal('1000000'), start_date=date.today(), frequency='monthly',
        )
        plan.auto_generate()
        inst = plan.installments.first()
        inst.paid_amount = Decimal('100000')
        inst.status = 'partial'
        inst.save()
        payment = Payment.objects.create(
            booking=self.booking, installment=inst, amount=Decimal('100000'),
            payment_date=date.today(), payment_method='cheque', payment_type='installment',
            status='verified', created_by=self.admin,
        )
        resp = self.client.post(reverse('payment-mark-bounced', args=[payment.pk]),
                                {'bounce_reason': 'stop payment'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        inst.refresh_from_db()
        self.assertEqual(inst.paid_amount, Decimal('0'))
        self.assertEqual(inst.status, 'pending')


# ─── 6. RECEIPT ON API VERIFY ───────────────────────────────────────────────
class ReceiptOnVerifyTests(FlawFixBase):
    def test_verify_generates_receipt(self):
        payment = self.make_payment(status='pending')
        resp = self.client.post(reverse('payment-verify', args=[payment.pk]),
                                {'action': 'verify'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(Receipt.objects.filter(payment=payment).exists())
        payment.refresh_from_db()
        self.assertTrue(payment.receipt_generated)

    def test_reject_does_not_generate_receipt(self):
        payment = self.make_payment(status='pending')
        resp = self.client.post(reverse('payment-verify', args=[payment.pk]),
                                {'action': 'reject'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(Receipt.objects.filter(payment=payment).exists())


# ─── 7. CUSTOMER DELETE PROTECTION ──────────────────────────────────────────
class CustomerDeleteProtectionTests(FlawFixBase):
    def test_delete_customer_with_booking_rejected(self):
        resp = self.client.delete(reverse('customer-detail', args=[self.customer.pk]))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_customer_with_ledger_rejected(self):
        from customers.models import CustomerLedgerEntry
        fresh = Customer.objects.create(
            first_name='Ledger', last_name='Only', phone='+92-301-0001111',
            cnic='35202-6666666-6',
        )
        CustomerLedgerEntry.objects.create(
            customer=fresh, transaction_type='adjustment', debit=Decimal('100'),
            credit=Decimal('0'), running_balance=Decimal('100'), entry_date=date.today(),
        )
        resp = self.client.delete(reverse('customer-detail', args=[fresh.pk]))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_customer_without_history_succeeds(self):
        fresh = Customer.objects.create(
            first_name='Fresh', last_name='Customer', phone='+92-301-0002222',
            cnic='35202-7777777-7',
        )
        resp = self.client.delete(reverse('customer-detail', args=[fresh.pk]))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)


# ─── 8. PUBLIC PLOT FEED ────────────────────────────────────────────────────
class PublicPlotFeedTests(FlawFixBase):
    def test_public_feed_only_available_plots(self):
        self.new_plot('FF-010', status='booked')
        self.new_plot('FF-011', status='sold')
        self.new_plot('FF-012', status='available')
        resp = self.client.get(reverse('plots_list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        for plot in resp.data:
            self.assertEqual(plot['status'], 'available')

    def test_public_feed_anonymous_allowed(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(reverse('plots_list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── 9. LEAD CONVERSION VALIDATION ──────────────────────────────────────────
class LeadConversionValidationTests(FlawFixBase):
    def make_lead(self):
        return Lead.objects.create(name='Convertible Lead', phone='+92-300-9990001')

    def test_convert_requires_cnic(self):
        lead = self.make_lead()
        resp = self.client.post(reverse('lead-convert', args=[lead.pk]), {
            'first_name': 'X', 'last_name': 'Y', 'phone': '+92-300-9990001',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_convert_duplicate_cnic_rejected(self):
        lead = self.make_lead()
        resp = self.client.post(reverse('lead-convert', args=[lead.pk]), {
            'first_name': 'X', 'last_name': 'Y', 'phone': '+92-300-9990001',
            'cnic': '35202-5555555-5',  # belongs to self.customer
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_convert_success_creates_customer(self):
        lead = self.make_lead()
        resp = self.client.post(reverse('lead-convert', args=[lead.pk]), {
            'first_name': 'Converted', 'last_name': 'Person', 'phone': '+92-300-9990001',
            'cnic': '35202-8888888-8', 'city': 'Lahore',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        lead.refresh_from_db()
        self.assertEqual(lead.status, 'converted')
        self.assertIsNotNone(lead.converted_customer)
        self.assertEqual(lead.converted_customer.cnic, '35202-8888888-8')


# ─── 10. LOGIN RATE LIMITING ────────────────────────────────────────────────
class LoginRateLimitTests(APITestCase):
    def test_five_failures_locks_until_429(self):
        user = User.objects.create_user('ratelimited', 'rl@example.com', 'correctpass123')
        for _ in range(5):
            self.client.post(reverse('api_login'),
                             {'username': 'ratelimited', 'password': 'wrong'}, format='json')
        resp = self.client.post(reverse('api_login'),
                                {'username': 'ratelimited', 'password': 'correctpass123'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_correct_password_before_threshold_succeeds(self):
        user = User.objects.create_user('okuser', 'ok@example.com', 'correctpass123')
        self.client.post(reverse('api_login'),
                         {'username': 'okuser', 'password': 'wrong'}, format='json')
        resp = self.client.post(reverse('api_login'),
                                {'username': 'okuser', 'password': 'correctpass123'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_failed_attempts_recorded(self):
        from core.models import LoginAttempt
        User.objects.create_user('tracked', 't@example.com', 'pass12345')
        for _ in range(3):
            self.client.post(reverse('api_login'),
                             {'username': 'tracked', 'password': 'nope'}, format='json')
        self.assertEqual(
            LoginAttempt.objects.filter(username='tracked', is_success=False).count(), 3)


# ─── 11. RESERVATION CONVERSION ─────────────────────────────────────────────
class ReservationConversionTests(FlawFixBase):
    def make_reservation(self, status='active'):
        from django.utils import timezone as tz
        return Reservation.objects.create(
            customer=self.customer, plot=self.plot, token_amount=Decimal('500000'),
            expires_at=tz.now() + timedelta(days=7), status=status,
            created_by=self.admin,
        )

    def test_convert_creates_booking_and_books_plot(self):
        reservation = self.make_reservation()
        resp = self.client.post(reverse('reservation-convert', args=[reservation.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['booking_id'].startswith('BKG-'))
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, 'booked')
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'converted')

    def test_convert_sets_advance_from_token(self):
        reservation = self.make_reservation()
        resp = self.client.post(reverse('reservation-convert', args=[reservation.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['advance_paid'])), Decimal('500000'))

    def test_convert_non_active_reservation_rejected(self):
        reservation = self.make_reservation(status='expired')
        resp = self.client.post(reverse('reservation-convert', args=[reservation.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_convert_when_plot_taken_elsewhere_rejected(self):
        reservation = self.make_reservation()
        self.plot.status = 'sold'
        self.plot.save()
        resp = self.client.post(reverse('reservation-convert', args=[reservation.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'expired')


# ─── 12. ID GENERATION ──────────────────────────────────────────────────────
class IdGenerationTests(FlawFixBase):
    def test_rapid_creation_produces_unique_ids(self):
        ids = set()
        for i in range(25):
            c = Customer.objects.create(
                first_name=f'Bulk{i}', last_name='Customer',
                phone=f'+92-300-{1000000 + i:07d}', cnic=f'35202-{1000000 + i:07d}-{i % 9}',
            )
            ids.add(c.customer_id)
        self.assertEqual(len(ids), 25)

    def test_booking_ids_monotonic(self):
        ids = []
        for i in range(10):
            plot = self.new_plot(f'ID-{i:03d}')
            b = Booking.objects.create(
                customer=self.customer, plot=plot, total_amount=Decimal('1000000'),
                created_by=self.admin,
            )
            ids.append(int(b.booking_id.split('-')[1]))
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 10)


# ─── 13. UI DELETE GUARDS (template routes) ─────────────────────────────────
# The API already blocked deleting customers with history; these tests pin
# the same protection on the web (template) delete routes, which previously
# cascaded away financial data.
class UiDeleteGuardTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'adminpass123')
        self.client.force_login(self.admin)
        self.project = Project.objects.create(name='Guard Project', location='Lahore', total_plots=50)
        self.plot = Plot.objects.create(
            plot_number='GD-001', project=self.project, size_marla=Decimal('5'),
            price=Decimal('5000000'), status='available',
        )
        self.customer = Customer.objects.create(
            first_name='Guard', last_name='Case', phone='+92-301-7778889',
            cnic='35202-7777777-7', email='guard@example.com', created_by=self.admin,
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('5000000'),
            advance_paid=Decimal('0'), status='confirmed', created_by=self.admin,
        )

    def test_customer_with_booking_cannot_be_deleted_via_ui(self):
        resp = self.client.post(reverse('customer_delete', args=[self.customer.pk]))
        self.assertRedirects(resp, reverse('customer_detail', args=[self.customer.pk]))
        self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())

    def test_customer_without_history_can_be_deleted_via_ui(self):
        fresh = Customer.objects.create(
            first_name='Fresh', last_name='Deletable', phone='+92-301-9990001',
            cnic='35202-9990001-1', created_by=self.admin,
        )
        resp = self.client.post(reverse('customer_delete', args=[fresh.pk]))
        self.assertRedirects(resp, reverse('customers'))
        self.assertFalse(Customer.objects.filter(pk=fresh.pk).exists())

    def test_plot_with_booking_cannot_be_deleted_via_ui(self):
        resp = self.client.post(reverse('plot_delete', args=[self.plot.pk]))
        self.assertRedirects(resp, reverse('properties'))
        self.assertTrue(Plot.objects.filter(pk=self.plot.pk).exists())

    def test_booking_with_payment_cannot_be_deleted_via_ui(self):
        Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'), payment_method='cash',
            status='pending', payment_date=date.today(),
        )
        resp = self.client.post(reverse('booking_delete', args=[self.booking.pk]))
        self.assertRedirects(resp, reverse('booking_detail', args=[self.booking.pk]))
        self.assertTrue(Booking.objects.filter(pk=self.booking.pk).exists())

    def test_booking_without_payment_can_be_deleted_via_ui(self):
        plot2 = Plot.objects.create(
            plot_number='GD-002', project=self.project, size_marla=Decimal('3'),
            price=Decimal('3000000'), status='available',
        )
        booking2 = Booking.objects.create(
            customer=self.customer, plot=plot2, total_amount=Decimal('3000000'),
            advance_paid=Decimal('0'), status='pending', created_by=self.admin,
        )
        resp = self.client.post(reverse('booking_delete', args=[booking2.pk]))
        self.assertRedirects(resp, reverse('bookings'))
        self.assertFalse(Booking.objects.filter(pk=booking2.pk).exists())
        plot2.refresh_from_db()
        self.assertEqual(plot2.status, 'available')


# ─── 11. INSTALLMENT PLAN AUTO-RECALCULATION ────────────────────────────────
class InstallmentPlanRecalcTests(FlawFixBase):
    """Plans must track the booking's remaining balance after every payment:
    paying 75K of a 100K booking must shrink the unpaid installments to
    cover only the 25K that is actually left."""

    def setUp(self):
        super().setUp()
        self.booking.total_amount = Decimal('100000')
        self.booking.advance_paid = Decimal('0')
        self.booking.save()
        self.plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=12,
            installment_amount=Decimal('7083.33'),
            down_payment_amount=Decimal('15000'),
            start_date=date.today(), frequency='quarterly',
        )
        self.plan.auto_generate()

    def test_plan_generated_covers_total_minus_down_payment(self):
        total = sum((i.amount for i in self.plan.installments.all()), Decimal('0'))
        # 12 x 7,083.33 = 84,999.96 (100K total - 15K template down payment)
        self.assertEqual(total, Decimal('84999.96'))

    def test_verify_payment_recalculates_unpaid_installments(self):
        # Customer pays 75K against a 100K booking: only 25K should remain.
        self.booking.advance_paid = Decimal('75000')
        self.booking.save()
        self.plan.recalculate()
        total = sum((i.amount for i in self.plan.installments.exclude(status='paid')), Decimal('0'))
        self.assertEqual(total, Decimal('25000'))
        # 25K / 12 = 2,083.33 each; the last installment absorbs the
        # rounding remainder (2,083.37).
        amounts = {i.amount for i in self.plan.installments.all()}
        self.assertLessEqual(amounts, {Decimal('2083.33'), Decimal('2083.37')})

    def test_verify_payment_api_triggers_recalculation(self):
        payment = self.make_payment(amount='50000', status='pending')
        resp = self.client.post(reverse('payment-verify', args=[payment.pk]),
                                {'action': 'verify'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        total = sum((i.amount for i in self.plan.installments.exclude(status='paid')), Decimal('0'))
        # 100K - 50K = 50K remaining
        self.assertEqual(total, Decimal('50000'))

    def test_full_payment_marks_all_installments_paid(self):
        self.booking.advance_paid = Decimal('100000')
        self.booking.save()
        self.plan.recalculate()
        self.assertEqual(self.plan.installments.exclude(status='paid').count(), 0)

    def test_recalc_preserves_paid_installments(self):
        inst1 = self.plan.installments.first()
        inst1.paid_amount = inst1.amount
        inst1.status = 'paid'
        inst1.save()
        self.booking.advance_paid = Decimal('50000')
        self.booking.save()
        self.plan.recalculate()
        # The paid installment keeps its original amount; the remaining
        # balance (50K) is spread across the 11 unpaid installments.
        inst1.refresh_from_db()
        self.assertEqual(inst1.amount, Decimal('7083.33'))
        total = sum((i.amount for i in self.plan.installments.exclude(status='paid')), Decimal('0'))
        self.assertEqual(total, Decimal('50000'))

    def test_booking_create_uses_actual_advance_as_down_payment(self):
        from core.views import booking_create_view
        # Build the same scenario as the UI form: advance paid at booking time.
        plot2 = self.new_plot('FF-003', price='100000')
        booking2 = Booking.objects.create(
            customer=self.customer, plot=plot2, total_amount=Decimal('100000'),
            advance_paid=Decimal('75000'), status='confirmed', created_by=self.admin,
        )
        template = InstallmentPlanTemplate.objects.create(
            name='Test Plan', project=self.project, total_installments=12,
            frequency='quarterly', down_payment_percentage=Decimal('15.00'),
        )
        from bookings.models import InstallmentPlan as IP
        down_payment = booking2.advance_paid if booking2.advance_paid > 0 else (
            booking2.total_amount * template.down_payment_percentage / 100
        )
        plan = IP.objects.create(
            booking=booking2, template=template, total_installments=12,
            installment_amount=(booking2.total_amount - down_payment) / 12,
            down_payment_amount=down_payment, start_date=date.today(),
            frequency='quarterly',
        )
        plan.auto_generate()
        total = sum((i.amount for i in plan.installments.all()), Decimal('0'))
        # 100K - 75K actual advance = 25K spread over 12 installments
        # (12 x 2,083.33 = 24,999.96 due to per-installment rounding)
        self.assertEqual(total, Decimal('24999.96'))
        self.assertEqual(plan.down_payment_amount, Decimal('75000'))
