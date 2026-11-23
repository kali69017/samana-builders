from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from bookings.models import Booking, InstallmentPlan
from core.models import UserProfile
from customers.models import Customer
from finance.models import AccountHead, Voucher
from notifications.models import NotificationLog
from payments.models import Payment, Receipt
from properties.models import Plot, Project


PAYMENT_NOTIFICATION_TYPES = ('payment_confirmation', 'receipt_notification')


class BookingMakerCheckerBase:
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            'booking_mc_super', 'booking_mc_super@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.customer = Customer.objects.create(
            first_name='Booking', last_name='Maker', phone='03007777777',
            email='booking.maker@example.com', cnic='77777-7777777-7',
            created_by=self.superuser,
        )
        self.project = Project.objects.create(
            name='Booking Maker Checker', location='Lahore', total_plots=20)
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.make_plot('BASE-1'),
            total_amount=Decimal('1000'), advance_paid=Decimal('0'),
            status='confirmed', created_by=self.superuser,
        )

    def make_user(self, role, username=None, superuser=False):
        username = username or f'booking_mc_{role}'
        if superuser:
            user = User.objects.create_superuser(
                username, f'{username}@example.com', 'pass123456')
        else:
            user = User.objects.create_user(
                username, f'{username}@example.com', 'pass123456')
        UserProfile.objects.create(user=user, role=role)
        return user

    def make_plot(self, number, price='1000'):
        return Plot.objects.create(
            plot_number=number, project=self.project,
            size_marla=Decimal('5'), price=Decimal(price), status='available',
        )

    def booking_payload(self, plot, advance='200'):
        return {
            'customer': self.customer.pk,
            'plot': plot.pk,
            'total_amount': '1000',
            'advance_paid': advance,
            'source': 'walk_in',
        }

    def make_installment(self, amount='500'):
        plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=2,
            installment_amount=Decimal(amount),
            down_payment_amount=Decimal('0'),
            start_date=date.today(), frequency='monthly',
        )
        plan.auto_generate()
        return plan.installments.first()

    def payment_notifications(self, payment):
        return NotificationLog.objects.filter(
            related_payment_id=payment.payment_id,
            notification_type__in=PAYMENT_NOTIFICATION_TYPES,
        )


class BookingCreateMakerCheckerTests(BookingMakerCheckerBase, TestCase):
    def test_web_booking_create_with_advance_is_pending_for_each_role(self):
        for role in ('management', 'sales', 'accounts', 'admin', 'super_admin'):
            user = self.make_user(role, superuser=(role == 'super_admin'))
            plot = self.make_plot(f'WEB-{role}')
            client = Client()
            client.force_login(user)
            response = client.post(
                reverse('booking_create'), self.booking_payload(plot),
            )
            self.assertEqual(response.status_code, 302)
            booking = Booking.objects.get(plot=plot)
            self.assertEqual(booking.advance_paid, Decimal('0'))
            payment = booking.payments.get()
            self.assertEqual(payment.status, 'pending')
            self.assertIsNone(payment.verified_by)
            self.assertIsNone(payment.verified_at)
            self.assertFalse(Receipt.objects.filter(payment=payment).exists())
            self.assertFalse(Voucher.objects.filter(
                reference_type='Payment', reference_id=payment.pk).exists())
            self.assertFalse(self.payment_notifications(payment).exists())

    def test_api_booking_create_with_advance_is_pending_for_allowed_roles(self):
        for role in ('management', 'sales', 'admin', 'super_admin'):
            user = self.make_user(
                role, username=f'booking_mc_api_{role}',
                superuser=(role == 'super_admin'))
            plot = self.make_plot(f'API-{role}')
            api = APIClient()
            api.force_authenticate(user=user)
            response = api.post(
                reverse('booking-list'), self.booking_payload(plot), format='json',
            )
            self.assertEqual(
                response.status_code, status.HTTP_201_CREATED, response.data)
            booking = Booking.objects.get(plot=plot)
            self.assertEqual(booking.advance_paid, Decimal('0'))
            payment = booking.payments.get()
            self.assertEqual(payment.status, 'pending')
            self.assertIsNone(payment.verified_by)
            self.assertFalse(Receipt.objects.filter(payment=payment).exists())
            self.assertFalse(Voucher.objects.filter(
                reference_type='Payment', reference_id=payment.pk).exists())
            self.assertFalse(self.payment_notifications(payment).exists())

    def test_booking_create_does_not_count_pending_advance(self):
        plot = self.make_plot('PENDING-BALANCE')
        client = Client()
        client.force_login(self.superuser)
        client.post(reverse('booking_create'), self.booking_payload(plot))
        booking = Booking.objects.get(plot=plot)
        self.assertEqual(booking.remaining_balance, booking.total_amount)
        self.assertEqual(booking.amount_paid, Decimal('0'))

    def test_booking_update_cannot_set_advance_paid(self):
        api = APIClient()
        api.force_authenticate(user=self.superuser)
        response = api.patch(
            reverse('booking-detail', args=[self.booking.pk]),
            {'advance_paid': '999'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.advance_paid, Decimal('0'))


class BookingVerifyMakerCheckerTests(BookingMakerCheckerBase, TestCase):
    def make_pending_booking_payment(self):
        plot = self.make_plot('VERIFY-BOOKING')
        creator = self.make_user(
            'sales', username='booking_mc_sales_creator')
        client = Client()
        client.force_login(creator)
        client.post(reverse('booking_create'), self.booking_payload(plot))
        booking = Booking.objects.get(plot=plot)
        return booking, booking.payments.get()

    def test_verify_advance_posts_one_voucher_receipt_and_notification_set(self):
        booking, payment = self.make_pending_booking_payment()
        verifier = self.make_user(
            'accounts', username='booking_mc_accounts_verifier')
        client = Client()
        client.force_login(verifier)
        response = client.post(reverse('payment_verify', args=[payment.pk]))
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(payment.status, 'verified')
        self.assertEqual(payment.verified_by, verifier)
        self.assertEqual(payment.receipts.count(), 1)
        self.assertEqual(Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk,
            status='posted').count(), 1)
        self.assertEqual(booking.advance_paid, Decimal('200'))
        self.assertEqual(payment.unallocated_amount, Decimal('0'))
        self.assertEqual(self.payment_notifications(payment).count(), 5)
        response = client.post(reverse('payment_verify', args=[payment.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk).count(), 1)

    def test_reject_pending_advance_leaves_balance_unchanged(self):
        booking, payment = self.make_pending_booking_payment()
        verifier = self.make_user(
            'accounts', username='booking_mc_accounts_reject')
        api = APIClient()
        api.force_authenticate(user=verifier)
        response = api.post(
            reverse('payment-verify', args=[payment.pk]),
            {'action': 'reject'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(payment.status, 'rejected')
        self.assertEqual(booking.advance_paid, Decimal('0'))
        self.assertFalse(Receipt.objects.filter(payment=payment).exists())
        self.assertFalse(Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk).exists())

    def test_bounce_pending_advance_leaves_balance_unchanged(self):
        booking, payment = self.make_pending_booking_payment()
        admin = self.make_user('admin', username='booking_mc_admin_bounce')
        api = APIClient()
        api.force_authenticate(user=admin)
        response = api.post(
            reverse('payment-mark-bounced', args=[payment.pk]),
            {'bounce_reason': 'test bounce'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(payment.status, 'bounced')
        self.assertEqual(booking.advance_paid, Decimal('0'))
        self.assertFalse(Receipt.objects.filter(payment=payment).exists())
        self.assertFalse(Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk).exists())


class ModelBalanceRecomputeTests(BookingMakerCheckerBase, TestCase):
    def test_model_verification_recomputes_advance_from_verified_payments_only(self):
        self.booking.advance_paid = Decimal('100')
        self.booking.save(update_fields=['advance_paid', 'updated_at'])
        payment = Payment.objects.create(
            booking=self.booking, received_into=self.cash,
            amount=Decimal('50'), payment_date=date.today(),
            payment_method='cash', payment_type='advance',
            status='pending', created_by=self.superuser,
        )
        payment.status = 'verified'
        payment.verified_by = self.superuser
        payment.save()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.advance_paid, Decimal('50'))

    def test_model_verification_updates_linked_installment(self):
        installment = self.make_installment()
        payment = Payment.objects.create(
            booking=self.booking, installment=installment,
            received_into=self.cash, amount=Decimal('250'),
            payment_date=date.today(), payment_method='cash',
            payment_type='installment', status='pending',
            created_by=self.superuser,
        )
        payment.status = 'verified'
        payment.verified_by = self.superuser
        payment.save()
        installment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(installment.paid_amount, Decimal('250'))
        self.assertEqual(installment.status, 'partial')
        self.assertEqual(self.booking.advance_paid, Decimal('250'))

    def test_model_reversal_recomputes_advance_and_installment(self):
        installment = self.make_installment()
        first = Payment.objects.create(
            booking=self.booking, installment=installment,
            received_into=self.cash, amount=Decimal('250'),
            payment_date=date.today(), payment_method='cash',
            payment_type='installment', status='verified',
            verified_by=self.superuser, created_by=self.superuser,
        )
        second = Payment.objects.create(
            booking=self.booking, installment=installment,
            received_into=self.cash, amount=Decimal('250'),
            payment_date=date.today(), payment_method='cash',
            payment_type='installment', status='verified',
            verified_by=self.superuser, created_by=self.superuser,
        )
        installment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(installment.paid_amount, Decimal('500'))
        self.assertEqual(self.booking.advance_paid, Decimal('500'))
        second.status = 'reversed'
        second.save()
        installment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(installment.paid_amount, Decimal('250'))
        self.assertEqual(installment.status, 'partial')
        self.assertEqual(self.booking.advance_paid, Decimal('250'))


class InstallmentMakerCheckerTests(BookingMakerCheckerBase, TestCase):
    def test_api_mark_paid_creates_pending_payment_and_verify_updates_installment(self):
        installment = self.make_installment()
        manager = self.make_user(
            'management', username='booking_mc_management_mark')
        api = APIClient()
        api.force_authenticate(user=manager)
        response = api.post(
            reverse('installment-mark-paid', args=[installment.pk]),
            {'paid_amount': '500'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        installment.refresh_from_db()
        payment = installment.payments.get()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.amount, Decimal('500'))
        self.assertIsNone(payment.verified_by)
        self.assertEqual(installment.paid_amount, Decimal('0'))
        self.assertEqual(installment.status, 'pending')
        self.assertEqual(installment.pending_payment_amount, Decimal('500'))
        self.assertTrue(installment.payment_pending_verification)
        self.assertFalse(Receipt.objects.filter(payment=payment).exists())
        self.assertFalse(Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk).exists())

        verifier = self.make_user(
            'accounts', username='booking_mc_accounts_mark_verify')
        client = Client()
        client.force_login(verifier)
        response = client.post(reverse('payment_verify', args=[payment.pk]))
        self.assertEqual(response.status_code, 302)
        installment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(installment.paid_amount, Decimal('500'))
        self.assertEqual(installment.status, 'paid')
        self.assertEqual(installment.pending_payment_amount, Decimal('0'))
        self.assertEqual(self.booking.advance_paid, Decimal('500'))
        self.assertEqual(payment.receipts.count(), 1)

    def test_api_mark_paid_is_pending_for_allowed_roles(self):
        for role in ('management', 'sales', 'admin', 'super_admin'):
            user = self.make_user(
                role, username=f'booking_mc_mark_{role}',
                superuser=(role == 'super_admin'))
            plot = self.make_plot(f'MARK-{role}')
            booking = Booking.objects.create(
                customer=self.customer, plot=plot, total_amount=Decimal('1000'),
                advance_paid=Decimal('0'), status='confirmed',
                created_by=self.superuser,
            )
            plan = InstallmentPlan.objects.create(
                booking=booking, total_installments=1,
                installment_amount=Decimal('500'), down_payment_amount=Decimal('0'),
                start_date=date.today(), frequency='monthly',
            )
            plan.auto_generate()
            installment = plan.installments.first()
            api = APIClient()
            api.force_authenticate(user=user)
            response = api.post(
                reverse('installment-mark-paid', args=[installment.pk]), {},
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            payment = installment.payments.get()
            self.assertEqual(payment.status, 'pending')
            self.assertEqual(payment.created_by, user)

    def test_web_mark_paid_creates_pending_payment(self):
        installment = self.make_installment()
        accounts = self.make_user(
            'accounts', username='booking_mc_accounts_web_mark')
        client = Client()
        client.force_login(accounts)
        response = client.post(
            reverse('installment_mark_paid', args=[installment.pk]))
        self.assertEqual(response.status_code, 302)
        installment.refresh_from_db()
        payment = installment.payments.get()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.created_by, accounts)
        self.assertEqual(installment.paid_amount, Decimal('0'))
        self.assertEqual(installment.status, 'pending')
        self.assertEqual(installment.pending_payment_amount, Decimal('500'))

    def test_reject_and_bounce_pending_installment_leave_it_unchanged(self):
        for action in ('reject', 'bounce'):
            plot = self.make_plot(f'ACTION-{action}')
            booking = Booking.objects.create(
                customer=self.customer, plot=plot, total_amount=Decimal('1000'),
                advance_paid=Decimal('0'), status='confirmed',
                created_by=self.superuser,
            )
            plan = InstallmentPlan.objects.create(
                booking=booking, total_installments=1,
                installment_amount=Decimal('500'), down_payment_amount=Decimal('0'),
                start_date=date.today(), frequency='monthly',
            )
            plan.auto_generate()
            installment = plan.installments.first()
            manager = self.make_user(
                'management', username=f'booking_mc_manager_{action}')
            api = APIClient()
            api.force_authenticate(user=manager)
            api.post(
                reverse('installment-mark-paid', args=[installment.pk]),
                {'paid_amount': '500'}, format='json',
            )
            payment = installment.payments.get()
            verifier = self.make_user(
                'accounts', username=f'booking_mc_accounts_{action}')
            verifier_api = APIClient()
            verifier_api.force_authenticate(user=verifier)
            if action == 'reject':
                response = verifier_api.post(
                    reverse('payment-verify', args=[payment.pk]),
                    {'action': 'reject'}, format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                payment.refresh_from_db()
                self.assertEqual(payment.status, 'rejected')
            else:
                admin = self.make_user(
                    'admin', username='booking_mc_admin_installment_bounce')
                admin_api = APIClient()
                admin_api.force_authenticate(user=admin)
                response = admin_api.post(
                    reverse('payment-mark-bounced', args=[payment.pk]),
                    {'bounce_reason': 'test bounce'}, format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                payment.refresh_from_db()
                self.assertEqual(payment.status, 'bounced')
            installment.refresh_from_db()
            self.assertEqual(installment.paid_amount, Decimal('0'))
            self.assertEqual(installment.status, 'pending')
            self.assertEqual(installment.pending_payment_amount, Decimal('0'))
            self.assertFalse(Receipt.objects.filter(payment=payment).exists())
            self.assertFalse(Voucher.objects.filter(
                reference_type='Payment', reference_id=payment.pk).exists())

    def test_booking_detail_and_installment_list_show_pending_amount(self):
        installment = self.make_installment()
        manager = self.make_user(
            'management', username='booking_mc_management_display')
        api = APIClient()
        api.force_authenticate(user=manager)
        api.post(
            reverse('installment-mark-paid', args=[installment.pk]),
            {'paid_amount': '500'}, format='json',
        )
        client = Client()
        client.force_login(self.superuser)
        response = client.get(reverse('booking_detail', args=[self.booking.pk]))
        self.assertContains(response, 'Pending Verification')
        self.assertContains(response, '500')
        response = client.get(
            reverse('installment_plan_detail', args=[installment.plan_id]))
        self.assertContains(response, 'Payment pending verification')
        self.assertContains(response, '500')
