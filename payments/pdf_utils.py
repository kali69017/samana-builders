import base64
import mimetypes
from io import BytesIO

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa


def _static_data_uri(relative_path):
    """Return a self-contained data URI for a static asset."""
    absolute_path = finders.find(relative_path)
    if not absolute_path:
        source_path = settings.BASE_DIR / 'static' / relative_path
        if source_path.exists():
            absolute_path = str(source_path)
    if not absolute_path:
        return ''

    with open(absolute_path, 'rb') as asset_file:
        encoded = base64.b64encode(asset_file.read()).decode('ascii')
    media_type = mimetypes.guess_type(absolute_path)[0] or 'application/octet-stream'
    return f'data:{media_type};base64,{encoded}'


def render_to_pdf(template_src, context_dict=None):
    """Render a Django template to PDF."""
    context = dict(context_dict or {})
    context.setdefault('pdf_logo_uri', _static_data_uri('images/samana-logo.png'))
    template = get_template(template_src)
    html = template.render(context)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode('UTF-8')), result, encoding='UTF-8')
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
