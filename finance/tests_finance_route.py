from django.contrib.auth.models import User
from django.test import TestCase

from core.models import UserProfile


class FinanceRoutePermissionTests(TestCase):
    def setUp(self):
        self.users = {}
        for role in ('super_admin', 'admin', 'management', 'accounts', 'sales'):
            user = User.objects.create_user(f'finance-{role}', f'{role}@example.com', 'pass123456')
            user.is_staff = True
            user.save()
            UserProfile.objects.create(user=user, role=role)
            self.users[role] = user

    def test_finance_routes_per_role(self):
        allowed = {'super_admin', 'admin', 'management', 'accounts'}
        urls = ['/finance/', '/finance/ledger/', '/finance/vouchers/',
                '/finance/account-heads/', '/finance/expense-categories/']
        for role, user in self.users.items():
            self.client.force_login(user)
            for url in urls:
                with self.subTest(role=role, url=url):
                    response = self.client.get(url)
                    if role in allowed:
                        if url == '/finance/':
                            self.assertEqual(response.status_code, 302, f'{role} {url}')
                            self.assertEqual(response.url, '/finance/ledger/')
                            response = self.client.get(url, follow=True)
                        self.assertEqual(response.status_code, 200, f'{role} {url}')
                    else:
                        self.assertEqual(response.status_code, 302, f'{role} {url}')
                        self.assertEqual(response.url, '/dashboard/')
                        followed = self.client.get(url, follow=True)
                        self.assertContains(followed, 'permission')
