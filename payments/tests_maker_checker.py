from datetime import date
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from bookings.models import Booking
from core.models import AuditLog, UserProfile
from customers.models import Customer
from finance.models import AccountHead, Voucher
from notifications.models import NotificationLog
from payments.admin import PaymentAdmin
from payments.models import Payment
from properties.models import Plot, Project


class MakerCheckerBase:
    def setUp(self):
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.maker = User.objects.create_superuser(
            'maker', 'maker@example.com', 'pass123456')
        self.customer = Customer.objects.create(
            first_name='Maker', last_name='Checker', phone='03001234567',
            email='maker.checker@example.com', cnic='12345-1234567-1',
            created_by=self.maker,
        )
        self.project = Project.objects.create(
            name='Maker Checker Project', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='MC-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('0'), status='confirmed', created_by=self.maker,
        )

    def make_user(self, username, role, superuser=False):
        if superuser:
            user = User.objects.create_superuser(
                username, f'{username}@example.com', 'pass123456')
        else:
            user = User.objects.create_user(
                username, f'{username}@example.com', 'pass123456')
        UserProfile.objects.create(user=user, role=role)
        return user

    def make_payment(self, created_by=None, status_value='pending'):
        return Payment.objects.create(
            booking=self.booking, received_into=self.cash,
            amount=Decimal('100'), payment_date=date.today(),
            payment_method='cash', payment_type='advance',
            status=status_value, created_by=created_by or self.maker,
        )


class WebMakerCheckerTests(MakerCheckerBase, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def verify_as(self, user, payment):
        self.client.force_login(user)
        return self.client.post(
            reverse('payment_verify', args=[payment.pk]), follow=True)

    def test_allowed_roles_can_verify(self):
        for role in ('super_admin', 'admin', 'accounts'):
            user = self.make_user(f'allow_{role}', role, superuser=(role == 'super_admin'))
            payment = self.make_payment()
            response = self.verify_as(user, payment)
            self.assertEqual(response.status_code, 200)
            payment.refresh_from_db()
            self.assertEqual(payment.status, 'verified')
            self.assertEqual(payment.verified_by, user)
            self.assertIsNotNone(payment.verified_at)

    def test_denied_roles_cannot_verify(self):
        for role in ('management', 'sales', 'project_manager', 'contractor'):
            user = self.make_user(f'deny_{role}', role)
            payment = self.make_payment()
            response = self.verify_as(user, payment)
            payment.refresh_from_db()
            self.assertEqual(payment.status, 'pending')
            self.assertContains(response, 'permission')

    def test_creator_cannot_verify_own_payment(self):
        accounts = self.make_user('creator_accounts', 'accounts')
        payment = self.make_payment(created_by=accounts)
        response = self.verify_as(accounts, payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertContains(response, 'cannot verify a payment you created')

    def test_super_admin_self_verification_is_logged(self):
        superuser = self.make_user('self_super', 'super_admin', superuser=True)
        payment = self.make_payment(created_by=superuser)
        self.verify_as(superuser, payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'verified')
        log = AuditLog.objects.filter(
            action='verify', model_name='Payment', object_id=payment.payment_id,
        ).latest('id')
        self.assertIn('self-verified by super_admin', log.description)

    def test_verified_by_and_at_are_shown_on_detail(self):
        admin = self.make_user('detail_admin', 'admin')
        payment = self.make_payment()
        self.verify_as(admin, payment)
        response = self.client.get(reverse('payment_detail', args=[payment.pk]))
        self.assertContains(response, admin.username)
        self.assertContains(response, 'Verified by')

    def test_management_sees_no_verify_button(self):
        manager = self.make_user('no_button_manager', 'management')
        payment = self.make_payment()
        self.client.force_login(manager)
        response = self.client.get(reverse('payment_detail', args=[payment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Verify')
        self.assertNotContains(response, 'Reject')
        self.assertNotContains(response, 'Bounce')

    def test_accounts_sees_verify_button(self):
        accounts = self.make_user('button_accounts', 'accounts')
        payment = self.make_payment()
        self.client.force_login(accounts)
        response = self.client.get(reverse('payment_detail', args=[payment.pk]))
        self.assertContains(response, 'Verify')


class APIMakerCheckerTests(MakerCheckerBase, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def verify_as(self, user, payment):
        self.client.force_authenticate(user=user)
        return self.client.post(
            reverse('payment-verify', args=[payment.pk]),
            {'action': 'verify'}, format='json')

    def test_allowed_roles_can_verify(self):
        for role in ('super_admin', 'admin', 'accounts'):
            user = self.make_user(f'api_allow_{role}', role, superuser=(role == 'super_admin'))
            payment = self.make_payment()
            response = self.verify_as(user, payment)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            payment.refresh_from_db()
            self.assertEqual(payment.status, 'verified')
            self.assertEqual(payment.verified_by, user)

    def test_denied_roles_cannot_verify(self):
        for role in ('management', 'sales', 'project_manager', 'contractor'):
            user = self.make_user(f'api_deny_{role}', role)
            payment = self.make_payment()
            response = self.verify_as(user, payment)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            payment.refresh_from_db()
            self.assertEqual(payment.status, 'pending')

    def test_creator_cannot_verify_own_payment(self):
        accounts = self.make_user('api_creator_accounts', 'accounts')
        payment = self.make_payment(created_by=accounts)
        response = self.verify_as(accounts, payment)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')

    def test_super_admin_self_verification_is_logged(self):
        superuser = self.make_user('api_self_super', 'super_admin', superuser=True)
        payment = self.make_payment(created_by=superuser)
        response = self.verify_as(superuser, payment)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = AuditLog.objects.filter(
            action='verify', model_name='Payment', object_id=payment.payment_id,
        ).latest('id')
        self.assertIn('self-verified by super_admin', log.description)


class PaymentAdminPermissionTests(MakerCheckerBase, TestCase):
    def setUp(self):
        super().setUp()
        self.model_admin = PaymentAdmin(Payment, AdminSite())

    def request_for(self, user):
        request = RequestFactory().get('/admin/payments/payment/')
        request.user = user
        return request

    def test_accounts_can_access_payment_admin(self):
        accounts = self.make_user('admin_accounts', 'accounts')
        request = self.request_for(accounts)
        self.assertTrue(self.model_admin.has_module_permission(request))
        self.assertTrue(self.model_admin.has_view_permission(request))
        self.assertTrue(self.model_admin.has_change_permission(request))

    def test_management_cannot_access_payment_admin(self):
        manager = self.make_user('admin_manager', 'management')
        request = self.request_for(manager)
        self.assertFalse(self.model_admin.has_module_permission(request))
        self.assertFalse(self.model_admin.has_view_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request))

    def test_superuser_can_access_payment_admin(self):
        superuser = self.make_user('admin_super', 'super_admin', superuser=True)
        request = self.request_for(superuser)
        self.assertTrue(self.model_admin.has_module_permission(request))
        self.assertTrue(self.model_admin.has_view_permission(request))
        self.assertTrue(self.model_admin.has_change_permission(request))


class PaymentCreationStatusTests(MakerCheckerBase, TestCase):
    ROLES = [
        ('super_admin', True),
        ('admin', False),
        ('management', False),
        ('accounts', False),
        ('sales', False),
    ]

    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_web_create_is_pending_for_each_role(self):
        for index, (role, superuser) in enumerate(self.ROLES):
            user = self.make_user(f'create_web_{role}', role, superuser=superuser)
            self.client.force_login(user)
            amount = 100 + index
            note = f'create-web-{role}'
            response = self.client.post(reverse('payment_create'), {
                'booking': self.booking.pk,
                'received_into': self.cash.pk,
                'amount': str(amount),
                'payment_date': date.today().isoformat(),
                'payment_method': 'cash',
                'payment_type': 'advance',
                'notes': note,
            })
            self.assertEqual(response.status_code, 302, role)
            payment = Payment.objects.get(booking=self.booking, notes=note)
            self.assertEqual(payment.amount, Decimal(str(amount)), role)
            self.assertEqual(payment.status, 'pending', role)
            self.assertIsNone(payment.verified_by, role)
            self.assertIsNone(payment.verified_at, role)
            self.assertFalse(payment.receipts.exists(), role)
            self.assertFalse(Voucher.objects.filter(
                reference_type='Payment', reference_id=payment.pk).exists(), role)
            self.assertFalse(NotificationLog.objects.filter(
                related_payment_id=payment.payment_id).exists(), role)


class PaymentCreationAPICreationTests(MakerCheckerBase, TestCase):
    ROLES = PaymentCreationStatusTests.ROLES

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_api_create_is_pending_for_each_role(self):
        for index, (role, superuser) in enumerate(self.ROLES):
            user = self.make_user(f'create_api_{role}', role, superuser=superuser)
            self.client.force_authenticate(user=user)
            amount = 200 + index
            note = f'create-api-{role}'
            response = self.client.post(reverse('payment-list'), {
                'booking': self.booking.pk,
                'received_into': self.cash.pk,
                'amount': str(amount),
                'payment_date': date.today().isoformat(),
                'payment_method': 'cash',
                'payment_type': 'advance',
                'notes': note,
            }, format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, role)
            payment = Payment.objects.get(booking=self.booking, notes=note)
            self.assertEqual(payment.amount, Decimal(str(amount)), role)
            self.assertEqual(payment.status, 'pending', role)
            self.assertIsNone(payment.verified_by, role)
            self.assertIsNone(payment.verified_at, role)
            self.assertFalse(payment.receipts.exists(), role)
            self.assertFalse(Voucher.objects.filter(
                reference_type='Payment', reference_id=payment.pk).exists(), role)
            self.assertFalse(NotificationLog.objects.filter(
                related_payment_id=payment.payment_id).exists(), role)
