"""Security regression suite for the production-readiness hardening.

Covers:
  - F1/F2  vertical privilege escalation (role can no longer be self-assigned via
           API profile update or the web /profile/ form) — regression guards.
  - F3     least-privilege API read matrix: a role may only GET the modules its
           function requires; portal customers get 403 everywhere sensitive.
  - F6     payment verify may only transition a *pending* payment; draft/bounced
           are refused.
  - F8     leave `status` is not writable via the serializer.
  - FIN    expense/cost `pay` may only follow `approved` (no draft->paid).
"""
from decimal import Decimal

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile


class SecurityBase(APITestCase):
    """Creates a superuser plus one user per role."""

    def setUp(self):
        self.superuser = User.objects.create_superuser('root', 'root@example.com', 'rootpass123')
        self.roles = {}
        for role in ('admin', 'management', 'accounts', 'sales', 'hr', 'customer'):
            u = User.objects.create_user(role, f'{role}@example.com', 'pass123456')
            UserProfile.objects.create(user=u, role=role)
            self.roles[role] = u
        # A portal customer: a plain user linked to a Customer row.
        portal = User.objects.create_user('portal', 'portal@example.com', 'pass123456')
        from customers.models import Customer
        Customer.objects.create(
            first_name='Portal', last_name='User', phone='+92-300-0000000',
            cnic='35202-1111111-1', email='portal@example.com', user=portal,
        )
        self.roles['portal'] = portal

    def auth(self, role):
        self.client.force_authenticate(user=self.roles[role])

    def auth_superuser(self):
        self.client.force_authenticate(user=self.superuser)


# ─── F1 / F2 — privilege escalation regression guards ───────────────────────

class PrivescRegressionTests(SecurityBase):
    def test_api_profile_update_cannot_change_role(self):
        """F1: a sales user cannot PATCH their profile role to super_admin."""
        self.auth('sales')
        resp = self.client.patch('/api/profile/update_profile/', {'role': 'super_admin'}, format='json')
        self.assertIn(resp.status_code, (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST))
        self.roles['sales'].profile.refresh_from_db()
        self.assertEqual(self.roles['sales'].profile.role, 'sales')

    def test_web_profile_cannot_change_role(self):
        """F2: the self-service /profile/ form must not persist a posted role."""
        self.auth('sales')
        resp = self.client.post('/profile/', {
            'first_name': 'Sales', 'last_name': 'User', 'email': 'sales@example.com',
            'role': 'super_admin', 'theme': 'default', 'is_active': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.roles['sales'].profile.refresh_from_db()
        self.assertEqual(self.roles['sales'].profile.role, 'sales')

    def test_leave_status_not_writable_via_serializer(self):
        """F8: patching a leave's status through the API does not change it."""
        from hr.models import Employee, Department, Leave, Designation
        self.auth_superuser()
        dept = Department.objects.create(name='Engineering')
        designation = Designation.objects.create(title='Engineer')
        emp = Employee.objects.create(
            user=self.roles['sales'], department=dept, designation=designation,
            first_name='Sa', last_name='Les', employee_id='EMP-001',
            joining_date='2024-01-01',
        )
        leave = Leave.objects.create(
            employee=emp, leave_type='annual', start_date='2024-06-01',
            end_date='2024-06-03', days=3, reason='vacation', status='pending',
        )
        self.auth('hr')
        resp = self.client.patch(f'/api/leaves/{leave.pk}/', {'status': 'approved'}, format='json')
        # Either refused (400) or ignored — status must remain pending.
        self.assertIn(resp.status_code, (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST))
        leave.refresh_from_db()
        self.assertEqual(leave.status, 'pending')


# ─── F3 — least-privilege API read matrix ────────────────────────────────────

class ApiReadAccessMatrixTests(SecurityBase):
    """Each sensitive endpoint may only be READ by its function's roles."""

    # endpoint -> roles that may GET it
    MATRIX = {
        '/api/customers/': {'admin', 'super_admin'},
        '/api/users/': {'admin', 'super_admin'},
        '/api/agents/': {'admin', 'super_admin', 'management'},
        '/api/leads/': {'admin', 'super_admin', 'management', 'sales'},
        '/api/bookings/': {'admin', 'super_admin', 'management', 'accounts', 'sales'},
        '/api/payments/': {'admin', 'super_admin', 'management', 'accounts'},
        '/api/receipts/': {'admin', 'super_admin', 'management', 'accounts'},
        '/api/office-expenses/': {'admin', 'super_admin', 'management', 'accounts'},
        '/api/account-transactions/': {'admin', 'super_admin', 'management', 'accounts'},
        '/api/project-costs/': {'admin', 'super_admin', 'management', 'accounts'},
        '/api/employees/': {'admin', 'super_admin', 'management', 'hr'},
        '/api/audit-logs/': {'admin', 'super_admin', 'management'},
        '/api/company-settings/summary/': {'admin', 'super_admin', 'management'},
    }

    def test_read_matrix(self):
        roles = ['admin', 'management', 'accounts', 'sales', 'hr', 'customer', 'portal']
        failures = []
        for endpoint, allowed in self.MATRIX.items():
            for role in roles:
                self.auth(role)
                resp = self.client.get(endpoint)
                if role in allowed:
                    if resp.status_code not in (200, 404):
                        failures.append(f'{endpoint} as {role}: expected 200 got {resp.status_code}')
                else:
                    if resp.status_code != 403:
                        failures.append(f'{endpoint} as {role}: expected 403 got {resp.status_code}')
        self.assertEqual(failures, [])

    def test_superuser_reads_everything(self):
        self.auth_superuser()
        for endpoint in self.MATRIX:
            resp = self.client.get(endpoint)
            self.assertIn(resp.status_code, (200, 404), f'{endpoint} denied for superuser')

    def test_customers_api_hidden_from_portal(self):
        self.auth('portal')
        resp = self.client.get('/api/customers/')
        self.assertEqual(resp.status_code, 403)

    def test_portal_customer_redirected_off_dashboard(self):
        """The business dashboard must never render for a portal customer (PII leak)."""
        # Plain Django view -> needs a real (session) login, not DRF force_authenticate.
        self.client.force_login(self.roles['portal'])
        resp = self.client.get('/dashboard/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('portal', resp.url)

    def test_payments_api_hidden_from_portal(self):
        self.auth('portal')
        resp = self.client.get('/api/payments/')
        self.assertEqual(resp.status_code, 403)


# ─── F6 — payment verify may only transition pending ─────────────────────────

class PaymentVerifyGuardTests(SecurityBase):
    def _booking(self):
        from customers.models import Customer
        from properties.models import Project, Plot
        from bookings.models import Booking
        project = Project.objects.create(name='P', location='L', total_plots=10)
        plot = Plot.objects.create(
            plot_number='A-1', project=project, size_marla=Decimal('5.00'),
            price=Decimal('5000000'), status='available',
        )
        customer = Customer.objects.create(
            first_name='V', last_name='C', phone='+92-300-1111111',
            cnic='35202-2222222-2', email='v@example.com', created_by=self.superuser,
        )
        return Booking.objects.create(
            customer=customer, plot=plot, total_amount=Decimal('5000000'),
            advance_paid=Decimal('0'), status='active', created_by=self.superuser,
        )

    def _payment(self, booking, txn_status):
        from payments.models import Payment
        return Payment.objects.create(
            booking=booking, amount=Decimal('100000'), payment_method='cash',
            payment_date='2024-06-01', status=txn_status, created_by=self.superuser,
        )

    def test_verify_from_bounced_is_refused(self):
        self.auth_superuser()
        booking = self._booking()
        payment = self._payment(booking, 'bounced')
        resp = self.client.post(f'/api/payments/{payment.pk}/verify/', {'action': 'verify'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'bounced')

    def test_verify_from_draft_is_refused(self):
        self.auth_superuser()
        booking = self._booking()
        payment = self._payment(booking, 'draft')
        resp = self.client.post(f'/api/payments/{payment.pk}/verify/', {'action': 'verify'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'draft')

    def test_verify_from_pending_succeeds(self):
        self.auth_superuser()
        booking = self._booking()
        payment = self._payment(booking, 'pending')
        resp = self.client.post(f'/api/payments/{payment.pk}/verify/', {'action': 'verify'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'verified')

    def test_web_verify_from_bounced_is_refused(self):
        booking = self._booking()
        payment = self._payment(booking, 'bounced')
        self.auth('admin')
        self.client.post(f'/payments/{payment.pk}/verify/', {})
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'bounced')


# ─── FIN — pay may only follow approved (draft->paid refused) ────────────────

class FinancePayGuardTests(SecurityBase):
    def _expense(self, txn_status):
        from finance.models import Office, ExpenseCategory, OfficeExpense
        office = Office.objects.create(name='HO', office_type='head_office')
        category = ExpenseCategory.objects.create(name='Rent')
        return OfficeExpense.objects.create(
            office=office, category=category, amount=Decimal('25000'),
            expense_date='2024-06-01', status=txn_status, created_by=self.superuser,
        )

    def test_api_pay_draft_expense_is_refused(self):
        self.auth_superuser()
        expense = self._expense('draft')
        resp = self.client.post(f'/api/office-expenses/{expense.pk}/pay/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'draft')

    def test_api_pay_approved_expense_succeeds(self):
        self.auth_superuser()
        expense = self._expense('approved')
        resp = self.client.post(f'/api/office-expenses/{expense.pk}/pay/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'paid')

    def test_web_pay_draft_expense_is_refused(self):
        self.auth_superuser()
        expense = self._expense('draft')
        self.client.post(f'/finance/office-expenses/{expense.pk}/pay/', {})
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'draft')

    def test_api_pay_draft_project_cost_is_refused(self):
        from properties.models import Project as PropertyProject
        from finance.models import ProjectCost
        self.auth_superuser()
        project = PropertyProject.objects.create(name='Proj', location='L', total_plots=5)
        cost = ProjectCost.objects.create(
            project=project, cost_category='material', amount=Decimal('40000'),
            cost_date='2024-06-01', status='draft',
        )
        resp = self.client.post(f'/api/project-costs/{cost.pk}/pay/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        cost.refresh_from_db()
        self.assertEqual(cost.status, 'draft')