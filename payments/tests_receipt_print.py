from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from properties.models import Plot, Project

from .models import Payment, Receipt
from .utils import amount_in_words


class ReceiptPrintPathTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'receiptprint', 'receiptprint@example.com', 'pw12345!')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            created_by=self.user,
        )
        self.project = Project.objects.create(name='Test', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), created_by=self.user,
        )
        self.payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal('100000'),
            payment_date=date.today(),
            payment_method='bank_transfer',
            reference_number='REF-1',
            method_data={},
            status='verified',
            created_by=self.user,
        )
        self.receipt = Receipt.objects.create(
            payment=self.payment, generated_by=self.user)

    def test_receipt_detail_has_no_browser_print_button(self):
        response = self.client.get(f'/receipts/{self.receipt.pk}/')

        self.assertNotContains(response, 'window.print()')
        self.assertNotContains(response, 'Print Receipt')

    def test_receipt_detail_has_download_pdf_link(self):
        response = self.client.get(f'/receipts/{self.receipt.pk}/')

        self.assertContains(response, 'Download PDF')
        self.assertContains(response, f'/receipts/{self.receipt.pk}/pdf/')

    def test_receipt_pdf_uses_only_the_fixed_footer(self):
        html = render_to_string('receipt_pdf.html', {
            'receipt': self.receipt,
            'payment': self.payment,
            'booking': self.booking,
            'amount_words': amount_in_words(self.payment.amount),
            'pdf_logo_uri': '',
        })

        self.assertIn('id="footerContent"', html)
        self.assertNotIn('class="notice"', html)
        self.assertEqual(html.count('Shayan Iconic Tower'), 1)
