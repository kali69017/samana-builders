from io import BytesIO
from django.http import HttpResponse
from xhtml2pdf import pisa
from django.template.loader import get_template
from django.conf import settings
import os


def render_to_pdf(template_src, context_dict=None):
    """Render a Django template to PDF."""
    template = get_template(template_src)
    html = template.render(context_dict or {})
    result = BytesIO()
    # Resolve relative image paths (e.g. "images/samana-logo.png") against
    # the project's static directory so logos render in PDFs.
    pdf = pisa.pisaDocument(
        BytesIO(html.encode('UTF-8')), result, encoding='UTF-8',
        path=str(settings.BASE_DIR / 'static'),
    )
    if not pdf.err:
        return result.getvalue()
    return None


def generate_receipt_pdf(receipt):
    """Generate PDF for a payment receipt."""
    from payments.utils import amount_in_words
    payment = receipt.payment
    booking = payment.booking

    context = {
        'receipt': receipt,
        'payment': payment,
        'booking': booking,
        'amount_words': amount_in_words(payment.amount),
    }

    pdf_content = render_to_pdf('receipt_pdf.html', context)
    if pdf_content:
        from django.core.files.base import ContentFile
        filename = f"receipt_{receipt.receipt_number.replace('/', '-')}.pdf"
        receipt.pdf_file.save(filename, ContentFile(pdf_content), save=True)
        return pdf_content
    return None


def generate_invoice_pdf(booking):
    """Generate bank invoice for a booking."""
    context = {
        'booking': booking,
        'customer': booking.customer,
        'plot': booking.plot,
        'project': booking.plot.project,
        'installment_plan': getattr(booking, 'installment_plan', None),
    }

    pdf_content = render_to_pdf('invoice_pdf.html', context)
    return pdf_content


def generate_customer_profile_pdf(customer):
    """Generate customer profile PDF for office records."""
    bookings = customer.bookings.select_related('plot', 'plot__project').all()
    from payments.models import Payment
    payments = Payment.objects.filter(booking__customer=customer, status='verified')
    from django.db.models import Sum
    total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'customer': customer,
        'bookings': bookings,
        'payments': payments[:20],
        'total_paid': total_paid,
        'nominee': getattr(customer, 'nominee', None),
    }

    pdf_content = render_to_pdf('customer_profile_pdf.html', context)
    return pdf_content
