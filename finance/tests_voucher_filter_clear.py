from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class VoucherFilterClearTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'vclear', 'vclear@example.com', 'pw12345!')
        self.client.force_login(self.user)

    def test_clear_link_is_rendered_when_filters_are_active(self):
        response = self.client.get(reverse('finance_vouchers'), {
            'type': 'CR',
            'status': 'posted',
        })

        self.assertContains(response, '>Clear</a>')
        self.assertContains(response, 'href="/finance/vouchers/"')
