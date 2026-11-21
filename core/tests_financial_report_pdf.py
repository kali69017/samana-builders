from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class FinancialReportPdfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'finpdf', 'finpdf@example.com', 'pw12345!')
        self.client.force_login(self.user)

    def test_financial_report_pdf_endpoint_returns_pdf_document(self):
        response = self.client.get('/reports/financial/pdf/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_financial_report_page_links_to_pdf_download(self):
        response = self.client.get(reverse('financial_reports'))

        self.assertContains(response, 'href="/reports/financial/pdf/"')
