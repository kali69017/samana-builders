import logging
import re
import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from .models import NotificationLog

logger = logging.getLogger(__name__)


class EmailService:
    @staticmethod
    def send(to_email, subject, message, from_email=None):
        if not to_email:
            return False, "No email address provided"
        if not getattr(settings, 'EMAIL_ENABLED', True):
            logger.info(f"[Email disabled] to {to_email}: {subject}")
            return True, "Email disabled"
        try:
            from_email = from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@samanabuilders.com')
            send_mail(subject, message, from_email, [to_email], fail_silently=False)
            return True, "Email sent successfully"
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False, str(e)


class SMSService:
    @staticmethod
    def normalize_phone(phone):
        """Convert local/international formats to SendPK's 92XXXXXXXXXX."""
        digits = re.sub(r'\D', '', phone or '')
        if not digits:
            return ''
        # +92-300-1234567 -> 923001234567
        if digits.startswith('92') and len(digits) == 12:
            return digits
        # 0300-1234567 -> 923001234567
        if digits.startswith('0') and len(digits) == 11:
            return '92' + digits[1:]
        # 3001234567 -> 923001234567
        if len(digits) == 10:
            return '92' + digits
        # Anything else is not a valid Pakistani mobile number
        return ''

    @staticmethod
    def is_valid_mobile(phone):
        """A valid mobile is exactly 92 followed by 10 digits (92XXXXXXXXXX)."""
        mobile = SMSService.normalize_phone(phone)
        return len(mobile) == 12 and mobile.startswith('92')

    @staticmethod
    def send(to_phone, message):
        if not to_phone:
            return False, "No phone number provided"

        mobile = SMSService.normalize_phone(to_phone)
        if not SMSService.is_valid_mobile(to_phone):
            return False, "Invalid phone number"

        if not getattr(settings, 'SENDPK_ENABLED', True):
            logger.info(f"[SMS disabled] to {to_phone}: {message}")
            return True, "SMS disabled"

        try:
            payload = {
                'api_key': getattr(settings, 'SENDPK_API_KEY', ''),
                'sender': getattr(settings, 'SENDPK_SENDER_ID', 'SAMANA'),
                'mobile': mobile,
                'message': message,
                'format': 'json',
            }
            resp = requests.post(
                getattr(settings, 'SENDPK_BASE_URL', 'https://sendpk.com/api/sms.php'),
                data=payload,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if str(data.get('success', '')).lower() == 'true':
                results = data.get('results', [])
                if results and results[0].get('status') == 'OK':
                    msg_id = results[0].get('messageid', '')
                    return True, f"OK ID:{msg_id}"
                return False, str(data)
            return False, str(data)
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
            return False, str(e)

    @staticmethod
    def extract_message_id(detail):
        """Parse the SendPK message ID out of a detail string like 'OK ID:6502124'."""
        m = re.search(r'ID:(\d+)', detail or '')
        return m.group(1) if m else ''

    @staticmethod
    def check_delivery(message_id):
        """Look up the delivery status of a previously sent SMS."""
        if not message_id:
            return None
        try:
            resp = requests.get(
                'https://sendpk.com/api/delivery.php',
                params={
                    'api_key': getattr(settings, 'SENDPK_API_KEY', ''),
                    'id': message_id,
                    'format': 'json',
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Delivery check failed: {e}")
            return None

    @staticmethod
    def check_balance():
        """Return the remaining SendPK credit, or None on failure."""
        if not getattr(settings, 'SENDPK_ENABLED', True):
            return None
        try:
            resp = requests.get(
                'https://sendpk.com/api/balance.php',
                params={'api_key': getattr(settings, 'SENDPK_API_KEY', ''), 'format': 'json'},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if str(data.get('success', '')).lower() == 'true':
                results = data.get('results', [])
                if results:
                    return results[0].get('balance')
            return None
        except Exception as e:
            logger.error(f"Balance check failed: {e}")
            return None


class WhatsAppService:
    @staticmethod
    def send(to_phone, message):
        if not to_phone:
            return False, "No phone number provided"
        # WhatsApp Business API integration
        # Uses the WhatsApp URL scheme for simple messaging
        try:
            # Clean phone number
            phone = to_phone.replace('+', '').replace('-', '').replace(' ', '')
            if phone.startswith('0'):
                phone = '92' + phone[1:]
            # Generate WhatsApp click-to-chat URL
            wa_url = f"https://wa.me/{phone}?text={requests.utils.quote(message)}"
            logger.info(f"WhatsApp message prepared for {phone}: {wa_url}")
            return True, wa_url
        except Exception as e:
            logger.error(f"WhatsApp prepare failed: {e}")
            return False, str(e)

    @staticmethod
    def get_click_to_chat_url(phone, message=''):
        phone = (phone or '').replace('+', '').replace('-', '').replace(' ', '')
        if phone.startswith('0'):
            phone = '92' + phone[1:]
        return f"https://wa.me/{phone}?text={requests.utils.quote(message)}" if phone else ''


class NotificationService:
    @staticmethod
    def send_notification(recipient_name, recipient_contact, channel, notification_type,
                         message, subject='', customer_id='', booking_id='', user=None,
                         sms_message=None):
        # SMS uses a shorter message when one is supplied; email/whatsapp use the full text.
        effective_message = (sms_message or message) if channel == 'sms' else message

        log = NotificationLog.objects.create(
            recipient_name=recipient_name,
            recipient_contact=recipient_contact,
            channel=channel,
            notification_type=notification_type,
            subject=subject,
            message=effective_message,
            related_customer_id=customer_id,
            related_booking_id=booking_id,
            created_by=user,
        )

        success = False
        detail = ''

        if channel == 'email':
            success, detail = EmailService.send(recipient_contact, subject, message)
        elif channel == 'sms':
            success, detail = SMSService.send(recipient_contact, effective_message)
            if success:
                log.provider_message_id = SMSService.extract_message_id(detail)
        elif channel == 'whatsapp':
            success, detail = WhatsAppService.send(recipient_contact, message)

        log.status = 'sent' if success else 'failed'
        log.error_message = '' if success else detail
        log.sent_at = timezone.now() if success else None
        log.save()

        return log

    @staticmethod
    def send_payment_confirmation(payment):
        booking = payment.booking
        customer = booking.customer

        remaining = booking.remaining_balance
        plan = getattr(booking, 'installment_plan', None)
        next_installment = None
        if plan:
            next_installment = plan.installments.filter(
                status__in=['pending', 'overdue', 'partial']
            ).order_by('installment_number').first()

        # Full message (email / whatsapp)
        message = (
            f"Dear {customer.full_name},\n\n"
            f"Your payment of Rs. {payment.amount:,.0f} has been received successfully.\n\n"
            f"Payment ID: {payment.payment_id}\n"
            f"Booking: {booking.booking_id}\n"
            f"Date: {payment.payment_date}\n"
            f"Method: {payment.get_payment_method_display()}\n\n"
            f"Remaining balance: Rs. {remaining:,.0f}\n"
        )
        if next_installment:
            message += (
                f"Next installment: #{next_installment.installment_number} "
                f"of Rs. {next_installment.amount:,.0f} due on {next_installment.due_date}.\n\n"
            )
        message += "Thank you for your payment!\nSamana Builders & Developers"

        # Concise SMS message (cost-effective, ~1 segment)
        sms_message = (
            f"Dear {customer.full_name}, payment of Rs. {payment.amount:,.0f} "
            f"received for {booking.booking_id}. Remaining: Rs. {remaining:,.0f}."
        )
        if next_installment:
            sms_message += (
                f" Next: #{next_installment.installment_number} Rs. {next_installment.amount:,.0f} "
                f"due {next_installment.due_date:%d-%b}."
            )
        sms_message += " Samana Builders"

        channels = ['email']
        if customer.phone:
            channels += ['sms', 'whatsapp']

        for ch in channels:
            contact = customer.email if ch == 'email' else customer.phone
            if contact:
                NotificationService.send_notification(
                    recipient_name=customer.full_name,
                    recipient_contact=contact,
                    channel=ch,
                    notification_type='payment_confirmation',
                    subject=f'Payment Confirmation - {payment.payment_id}',
                    message=message,
                    sms_message=sms_message,
                    customer_id=customer.customer_id,
                    booking_id=booking.booking_id,
                )

    @staticmethod
    def send_booking_notification(booking):
        customer = booking.customer
        message = (
            f"Dear {customer.full_name},\n\n"
            f"Your booking {booking.booking_id} has been created successfully.\n\n"
            f"Plot: {booking.plot.plot_number}\n"
            f"Project: {booking.plot.project.name}\n"
            f"Total Amount: Rs. {booking.total_amount:,.0f}\n"
            f"Status: {booking.get_status_display()}\n\n"
            f"Samana Builders & Developers"
        )
        channels = ['email']
        if customer.phone:
            channels.append('whatsapp')

        for ch in channels:
            contact = customer.email if ch == 'email' else customer.phone
            if contact:
                NotificationService.send_notification(
                    recipient_name=customer.full_name,
                    recipient_contact=contact,
                    channel=ch,
                    notification_type='booking_notification',
                    subject=f'Booking Confirmation - {booking.booking_id}',
                    message=message,
                    customer_id=customer.customer_id,
                    booking_id=booking.booking_id,
                )

    @staticmethod
    def send_customer_welcome(customer, user=None):
        """Send a welcome email to a freshly-created Customer.

        Failure-safe by design: the whole send is wrapped so that a broken
        email (invalid address, SMTP failure, even a NotificationLog write
        error) can NEVER propagate up and corrupt the customer transaction that
        just succeeded. Only emails to a present, non-empty address are sent.
        Returns the NotificationLog row, or None if there was nothing to send
        or the send failed (failure is logged, never raised).
        """
        try:
            email = (getattr(customer, 'email', '') or '').strip()
            if not email:
                logger.info(
                    f"[Welcome email skipped] no email address for customer "
                    f"{getattr(customer, 'customer_id', None) or getattr(customer, 'pk', None)}"
                )
                return None

            customer_id = getattr(customer, 'customer_id', '') or ''
            message = (
                f"Dear {customer.full_name},\n\n"
                f"Welcome to Samana Builders & Developers! Your customer profile "
                f"({customer_id}) has been created successfully.\n\n"
                f"We look forward to assisting you with your property needs. "
                f"Should you have any questions, please don't hesitate to "
                f"reach out to our team.\n\n"
                f"Best regards,\nSamana Builders & Developers"
            )
            return NotificationService.send_notification(
                recipient_name=customer.full_name,
                recipient_contact=email,
                channel='email',
                notification_type='customer_welcome',
                subject='Welcome to Samana Builders & Developers',
                message=message,
                customer_id=customer_id,
                user=user,
            )
        except Exception as e:
            # Log and swallow: a welcome email must never break customer creation.
            logger.error(
                f"[Welcome email failed - non-fatal] customer "
                f"{getattr(customer, 'customer_id', None) or getattr(customer, 'pk', None)}: {e}"
            )
            return None

    @staticmethod
    def send_installment_reminder(installment):
        booking = installment.plan.booking
        customer = booking.customer
        message = (
            f"Dear {customer.full_name},\n\n"
            f"This is a friendly reminder that Installment #{installment.installment_number} "
            f"of Rs. {installment.amount:,.0f} is due on {installment.due_date}.\n\n"
            f"Booking: {booking.booking_id}\n"
            f"Plot: {booking.plot.plot_number}\n"
            f"Project: {booking.plot.project.name}\n\n"
            f"Please ensure timely payment to avoid late fees.\n\n"
            f"Samana Builders & Developers"
        )
        sms_message = (
            f"Dear {customer.full_name}, installment #{installment.installment_number} "
            f"of Rs. {installment.amount:,.0f} is due on {installment.due_date:%d-%b} "
            f"for {booking.booking_id}. Samana Builders"
        )
        channels = ['email']
        if customer.phone:
            channels += ['sms', 'whatsapp']

        for ch in channels:
            contact = customer.email if ch == 'email' else customer.phone
            if contact:
                NotificationService.send_notification(
                    recipient_name=customer.full_name,
                    recipient_contact=contact,
                    channel=ch,
                    notification_type='installment_reminder',
                    subject=f'Installment Reminder - Installment #{installment.installment_number}',
                    message=message,
                    sms_message=sms_message,
                    customer_id=customer.customer_id,
                    booking_id=booking.booking_id,
                )

    @staticmethod
    def send_overdue_payment_alert(installment):
        booking = installment.plan.booking
        customer = booking.customer
        message = (
            f"Dear {customer.full_name},\n\n"
            f"Your Installment #{installment.installment_number} of Rs. {installment.amount:,.0f} "
            f"was due on {installment.due_date} and is now OVERDUE.\n\n"
            f"Late Fee Applied: Rs. {installment.late_fee:,.0f}\n"
            f"Total Outstanding: Rs. {installment.remaining_amount:,.0f}\n\n"
            f"Please arrange immediate payment to avoid additional charges.\n\n"
            f"Samana Builders & Developers"
        )
        sms_message = (
            f"Dear {customer.full_name}, installment #{installment.installment_number} "
            f"of Rs. {installment.amount:,.0f} is OVERDUE (due {installment.due_date:%d-%b}). "
            f"Outstanding: Rs. {installment.remaining_amount:,.0f}. Samana Builders"
        )
        channels = ['email']
        if customer.phone:
            channels.extend(['sms', 'whatsapp'])

        for ch in channels:
            contact = customer.email if ch == 'email' else customer.phone
            if contact:
                NotificationService.send_notification(
                    recipient_name=customer.full_name,
                    recipient_contact=contact,
                    channel=ch,
                    notification_type='overdue_payment',
                    subject=f'OVERDUE: Installment #{installment.installment_number}',
                    message=message,
                    sms_message=sms_message,
                    customer_id=customer.customer_id,
                    booking_id=booking.booking_id,
                )

    @staticmethod
    def send_receipt_notification(receipt):
        payment = receipt.payment
        booking = payment.booking
        customer = booking.customer
        message = (
            f"Dear {customer.full_name},\n\n"
            f"Your receipt {receipt.receipt_number} has been generated.\n\n"
            f"Amount: Rs. {payment.amount:,.0f}\n"
            f"Date: {receipt.receipt_date}\n"
            f"Payment ID: {payment.payment_id}\n\n"
            f"Thank you for your payment!\n\n"
            f"Samana Builders & Developers"
        )
        channels = ['email']
        if customer.phone:
            channels.append('whatsapp')

        for ch in channels:
            contact = customer.email if ch == 'email' else customer.phone
            if contact:
                NotificationService.send_notification(
                    recipient_name=customer.full_name,
                    recipient_contact=contact,
                    channel=ch,
                    notification_type='receipt_notification',
                    subject=f'Receipt Generated - {receipt.receipt_number}',
                    message=message,
                    customer_id=customer.customer_id,
                    booking_id=booking.booking_id,
                )
