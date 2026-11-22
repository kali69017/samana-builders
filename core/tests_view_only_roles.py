from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.forms import CreateUserForm, UserEditForm
from core.models import UserProfile
from core.permissions import (
    CONTRACTOR, PROJECT_MANAGER, VIEW_ONLY_ROLES,
)


SIDEBAR_LINKS = [
    ('Dashboard', '/dashboard/'),
    ('Customers', '/customers/'),
    ('Properties', '/properties/'),
    ('Bookings', '/bookings/'),
    ('Payments', '/payments/'),
    ('Expenses', '/expenses/'),
    ('Financial Reports', '/reports/financial/'),
    ('Leads', '/leads/'),
    ('Agents', '/agents/'),
    ('Installment Plans', '/installment-plans/'),
    ('Refunds', '/refunds/'),
    ('Receivables', '/reports/receivables/'),
    ('Sales Report', '/reports/sales/'),
    ('Milestones', '/projects/milestones/'),
    ('Ledger', '/finance/ledger/'),
    ('Vouchers', '/finance/vouchers/'),
    ('Chart of Accounts', '/finance/account-heads/'),
    ('Company Expenses', '/finance/office-expenses/'),
    ('Project Costs', '/finance/project-costs/'),
    ('Project Finance', '/finance/projects/'),
    ('Offices', '/finance/offices/'),
    ('Categories', '/finance/expense-categories/'),
    ('HR Overview', '/hr/'),
    ('Employees', '/hr/employees/'),
    ('Payroll', '/hr/payroll/'),
    ('Attendance', '/hr/attendance/'),
    ('Leave', '/hr/leaves/'),
    ('Departments', '/hr/departments/'),
    ('Designations', '/hr/designations/'),
    ('Salary Components', '/hr/salary-components/'),
    ('AI Assistant', '/ai/'),
    ('AI Insights', '/ai/insights/'),
    ('AI HR', '/ai/hr/'),
    ('Manage Users', '/users/'),
    ('Notifications', '/notifications/'),
    ('DB Backup', '/backup/'),
    ('Preferences', '/profile/'),
]


class ViewOnlyRoleTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.pm = self.make_user('view_pm', PROJECT_MANAGER)
        self.contractor = self.make_user('view_contractor', CONTRACTOR)

    def make_user(self, username, role):
        user = User.objects.create_user(
            username, f'{username}@example.com', 'pass123456')
        UserProfile.objects.create(user=user, role=role)
        return user

    def sidebar_html(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))
        html = response.content.decode()
        return html.split('<nav class="sidebar-nav">', 1)[1].split('</nav>', 1)[0]

    def test_limited_role_module_map(self):
        self.assertEqual(VIEW_ONLY_ROLES[PROJECT_MANAGER], ('properties', 'milestones'))
        self.assertEqual(VIEW_ONLY_ROLES[CONTRACTOR], ('milestones',))

    def test_project_manager_sidebar_links(self):
        html = self.sidebar_html(self.pm)
        allowed = {'/dashboard/', '/properties/', '/projects/milestones/', '/profile/'}
        for label, url in SIDEBAR_LINKS:
            if url in allowed:
                self.assertIn(f'href="{url}"', html, label)
            else:
                self.assertNotIn(f'href="{url}"', html, label)

    def test_contractor_sidebar_links(self):
        html = self.sidebar_html(self.contractor)
        allowed = {'/dashboard/', '/projects/milestones/', '/profile/'}
        for label, url in SIDEBAR_LINKS:
            if url in allowed:
                self.assertIn(f'href="{url}"', html, label)
            else:
                self.assertNotIn(f'href="{url}"', html, label)

    def test_project_manager_direct_urls(self):
        allowed = {'/dashboard/', '/properties/', '/projects/milestones/', '/profile/'}
        self.client.force_login(self.pm)
        for label, url in SIDEBAR_LINKS:
            response = self.client.get(url)
            if url in allowed:
                self.assertEqual(response.status_code, 200, label)
            else:
                self.assertEqual(response.status_code, 302, label)
                self.assertEqual(response.url, reverse('dashboard'), label)

    def test_contractor_direct_urls(self):
        allowed = {'/dashboard/', '/projects/milestones/', '/profile/'}
        self.client.force_login(self.contractor)
        for label, url in SIDEBAR_LINKS:
            response = self.client.get(url)
            if url in allowed:
                self.assertEqual(response.status_code, 200, label)
            else:
                self.assertEqual(response.status_code, 302, label)
                self.assertEqual(response.url, reverse('dashboard'), label)

    def test_limited_roles_are_hidden_from_user_forms(self):
        form = CreateUserForm()
        values = [key for key, _ in form.fields['role'].choices]
        self.assertNotIn(PROJECT_MANAGER, values)
        self.assertNotIn(CONTRACTOR, values)

        edit = UserEditForm(instance=self.pm)
        values = [key for key, _ in edit.fields['role'].choices]
        self.assertIn(PROJECT_MANAGER, values)

    @override_settings(SHOW_LIMITED_ROLES=True)
    def test_limited_roles_can_be_shown_in_user_forms(self):
        form = CreateUserForm()
        values = [key for key, _ in form.fields['role'].choices]
        self.assertIn(PROJECT_MANAGER, values)
        self.assertIn(CONTRACTOR, values)
