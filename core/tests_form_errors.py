from django.contrib.auth.models import User
from django.test import TestCase


CREATE_URLS = [
    '/customers/create/',
    '/properties/project/create/',
    '/properties/plot/create/',
    '/bookings/create/',
    '/payments/create/',
    '/refunds/create/',
    '/expenses/create/',
    '/finance/project-costs/create/',
    '/finance/office-expenses/create/',
    '/finance/vouchers/create/?type=JV',
    '/finance/vouchers/create/?type=CR',
    '/finance/account-heads/create/',
    '/finance/offices/create/',
    '/finance/expense-categories/create/',
    '/leads/create/',
    '/agents/create/',
    '/hr/employees/create/',
    '/hr/departments/create/',
    '/hr/designations/create/',
    '/hr/salary-components/create/',
    '/users/create/',
]


class CreateFormErrorVisibilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('formaudit', 'audit@example.com', 'pass123456')
        self.client.login(username='formaudit', password='pass123456')

    def _assert_errors_visible(self, response, form):
        html = response.content.decode()
        for field_name, errors in form.errors.items():
            for error in errors:
                text = str(error)
                with self.subTest(field=field_name, error=text):
                    self.assertIn(text, html)
                    if field_name != '__all__':
                        self.assertIn(f'id_{field_name}', html)

    def test_empty_post_errors_are_visible_on_every_create_form(self):
        failures = []
        for url in CREATE_URLS:
            with self.subTest(url=url):
                response = self.client.post(url, {})
                self.assertEqual(response.status_code, 200, url)
                form = response.context.get('form') if response.context else None
                if form is None:
                    failures.append(f'{url}: no form in context')
                    continue
                self.assertTrue(form.errors, f'{url}: empty POST produced no form errors')
                try:
                    self._assert_errors_visible(response, form)
                except AssertionError as exc:
                    failures.append(f'{url}: {exc}')
                formset = response.context.get('formset') if response.context else None
                if formset is not None and formset.errors:
                    for index, errors in enumerate(formset.errors):
                        if not errors:
                            continue
                        for field_name, field_errors in errors.items():
                            for error in field_errors:
                                if str(error) not in response.content.decode():
                                    failures.append(
                                        f'{url}: formset {index} {field_name} error not visible')
        if failures:
            self.fail('Visible error audit failures:\n' + '\n'.join(failures))
