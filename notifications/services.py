import json
import logging
import re
import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from . import wa_templates
from .models import NotificationLog

logger = logging.getLogger(__name__)

# channel -> the settings flag that says whether that provider is switched on.
CHANNEL_ENABLED_SETTING = {
    'email': 'EMAIL_ENABLED',
    'sms': 'SENDPK_ENABLED',
    'whatsapp': 'WHATSAPP_ENABLED',
}


class EmailService:
    @staticmethod
    def send(to_email, subject, message, from_email=None):
        if not to_email:
            return False, "No email address provided"
        if not getattr(settings, 'EMAIL_ENABLED', False):
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
    # notification_type -> (template setting suffix, SMS template variable map).
    # Values are the SendPK-approved template variable names (e.g. #name#).
    # This account is fixed-sms: it requires template_id + a JSON message string.
    TEMPLATES = {
        'customer_welcome': ('CUSTOMER_WELCOME', {'name': 'customer_name', 'customer_id': 'customer_id'}),
        'payment_confirmation': (
            'PAYMENT_CONFIRMATION',
            {'name': 'customer_name', 'amount': 'amount', 'booking_id': 'booking_id',
             'remaining': 'remaining_balance', 'next_installment': 'next_installment'}),
        'installment_reminder': (
            'INSTALLMENT_REMINDER',
            {'name': 'customer_name', 'installment_number': 'installment_number',
             'amount': 'amount', 'due_date': 'due_date', 'booking_id': 'booking_id'}),
        'overdue_payment': (
            'OVERDUE_PAYMENT',
            {'name': 'customer_name', 'installment_number': 'installment_number',
             'amount': 'amount', 'due_date': 'due_date', 'outstanding': 'outstanding'}),
    }

    # Template slots the caller only fills conditionally: {caller-side param:
    # value to send when it is absent}. Every slot in an approved template must
    # receive *something* -- SendPK renders the raw #placeholder# otherwise --
    # so an optional slot falls back to this instead of being dropped. Anything
    # outside this map is required and send_typed() refuses to send without it.
    OPTIONAL_VARS = {
        'payment_confirmation': {'next_installment': 'none due'},
    }

    @staticmethod
    def template_for(notification_type):
        """Return (setting name, template id, required caller-side params).

        The setting name is returned alongside the value so a missing template
        can name the exact `.env` key the operator has to fill in.
        """
        entry = SMSService.TEMPLATES.get(notification_type)
        if not entry:
            return None, None, set()
        setting_name = f'SENDPK_TEMPLATE_{entry[0]}'
        # var_map: SMS template name -> the key in the caller's params dict
        return setting_name, getattr(settings, setting_name, '') or None, set(entry[1].values())

    @staticmethod
    def send_typed(to_phone, notification_type, params):
        """Send via the approved fixed-sms template configured for this type.

        SendPK fixed-sms accounts reject free text; they require template_id
        plus a JSON object mapping the template's variables to their values.
        """
        mobile = SMSService.normalize_phone(to_phone)
        if not mobile:
            return False, "Invalid phone number"
        if not getattr(settings, 'SENDPK_ENABLED', False):
            return True, "SMS disabled"

        setting_name, template_id, expected = SMSService.template_for(notification_type)
        if not template_id:
            if setting_name is None:
                return False, (
                    f"No SMS template configured for '{notification_type}'. "
                    "Set SENDPK_TEMPLATE_* in .env."
                )
            return False, (
                f"{setting_name} is not set for '{notification_type}', so there is no "
                "approved template id to send. Set it in .env."
            )

        var_map = SMSService.TEMPLATES[notification_type][1]
        provided = {k: v for k, v in (params or {}).items() if v not in (None, '')}
        optional = SMSService.OPTIONAL_VARS.get(notification_type, {})

        # `expected` is the set of caller-side params this template needs. Fail
        # loudly rather than dropping the slot: a half-filled approved template
        # would either be rejected by SendPK or reach the customer with a raw
        # #placeholder# in it.
        missing = sorted(expected - set(provided) - set(optional))
        if missing:
            return False, (
                f"SMS template '{template_id}' missing required variable(s): "
                f"{', '.join(missing)}. Refusing to send an incomplete template."
            )

        # Build the JSON message from the caller's params using the template var names.
        message_vars = {}
        for sms_var, src_key in var_map.items():
            value = provided.get(src_key, optional.get(src_key))
            if value in (None, ''):
                continue
            message_vars[sms_var] = str(value)

        try:
            payload = {
                'api_key': getattr(settings, 'SENDPK_API_KEY', ''),
                'sender': getattr(settings, 'SENDPK_SENDER_ID', 'SMS Alert'),
                'mobile': mobile,
                'template_id': template_id,
                'message': json.dumps(message_vars),
                'format': 'json',
            }
            # POST, not GET: keeps api_key and the customer's details out of the
            # request URL, and matches SMSService.send() so one provider means
            # one transport.
            resp = requests.post(
                getattr(settings, 'SENDPK_BASE_URL', 'https://sendpk.com/api/sms.php'),
                data=payload,
                timeout=15,
            )
            resp.raise_for_status()
            return SMSService._interpret(resp)
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
            return False, str(e)

    @staticmethod
    def _interpret(resp):
        """Map a SendPK reply to (ok, detail) for both json and plain-text modes."""
        text = (resp.text or '').strip()
        try:
            data = resp.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            results = data.get('results') or []
            first = results[0] if results and isinstance(results[0], dict) else {}
            if (str(data.get('success', '')).lower() == 'true'
                    and str(first.get('status', '')).upper() == 'OK'):
                return True, f"OK ID:{first.get('messageid', '')}"
            return False, text or json.dumps(data)
        # format=json was not honoured (or absent): SendPK answers "OK ID:<uuid>".
        if text.upper().startswith('OK'):
            return True, text
        return False, text

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

        if not getattr(settings, 'SENDPK_ENABLED', False):
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
        """Parse the SendPK message ID out of a detail string like 'OK ID:6502124'
        or 'OK ID:ebd6dc1e-...' (fixed-sms returns a UUID)."""
        m = re.search(r'ID:\s*(\w[\w-]*)', detail or '')
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
        if not getattr(settings, 'SENDPK_ENABLED', False):
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
    # Which setting names the Meta-approved template for each notification type.
    # Empty value = not configured; that notification fails with a message
    # naming the setting rather than silently sending the wrong thing.
    TEMPLATE_SETTING_BY_TYPE = {
        'payment_confirmation': 'WHATSAPP_TEMPLATE_PAYMENT_CONFIRMATION',
        'booking_notification': 'WHATSAPP_TEMPLATE_BOOKING_NOTIFICATION',
        'booking_approval': 'WHATSAPP_TEMPLATE_BOOKING_APPROVAL',
        'installment_reminder': 'WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER',
        'overdue_payment': 'WHATSAPP_TEMPLATE_OVERDUE_PAYMENT',
        'receipt_notification': 'WHATSAPP_TEMPLATE_RECEIPT_NOTIFICATION',
    }

    # Graph error codes worth translating. Anything else passes through raw.
    ERROR_HINTS = {
        131047: 'More than 24h since the customer last replied - send an approved template, not free-form text.',
        130429: 'Throughput exceeded - slow down and retry with backoff.',
        131056: 'Too many messages to this recipient - limit is 1 message per 6 seconds.',
        132000: 'Template parameter count does not match the approved template.',
        132001: 'Template is unknown, not yet approved, or the language code is wrong.',
        131049: 'Blocked to protect ecosystem quality - wait 24h and review template content.',
        131050: 'Recipient is not subscribed to this category - do not retry.',
    }

    @staticmethod
    def normalize_phone(to_phone):
        """E.164 without '+': 923001234567 (same shape SendPK uses)."""
        digits = re.sub(r'\D', '', to_phone or '')
        if digits.startswith('92') and len(digits) == 12:
            return digits
        if digits.startswith('0') and len(digits) == 11:
            return '92' + digits[1:]
        if len(digits) == 10:
            return '92' + digits
        return ''

    @staticmethod
    def template_name_for(notification_type):
        """Configured template name for a notification type, '' when unset."""
        setting = WhatsAppService.TEMPLATE_SETTING_BY_TYPE.get(notification_type)
        return getattr(settings, setting, '') if setting else ''

    @staticmethod
    def extract_message_id(detail):
        """Parse the wamid out of a detail string like 'OK ID:wamid.HBg...'."""
        m = re.search(r'ID:(\S+)', detail or '')
        return m.group(1) if m else ''

    @staticmethod
    def _describe_error(status_code, data, exc=None):
        """Turn a Graph failure into a detail string a human can act on.

        The Graph API returns the actionable part (code, subcode, details) in the
        JSON body, so this must never collapse to a bare HTTP status.
        """
        if exc is not None:
            # Keep the status: a 502 gateway page and a 200-serving-HTML both surface
            # here as a JSON parse failure, and without it they look identical.
            where = f"HTTP {status_code}" if status_code else "request"
            return f"WhatsApp {where} failed: {exc}"

        error = (data or {}).get('error') or {}
        code = error.get('code')
        subcode = error.get('error_subcode')
        message = error.get('message') or f'HTTP {status_code}'
        details = (error.get('error_data') or {}).get('details') or ''

        label = f"Graph error {code}" if code else f"HTTP {status_code}"
        if subcode:
            label += f"/{subcode}"
        out = f"{label}: {message}"
        if details:
            out += f" | {details}"
        hint = WhatsAppService.ERROR_HINTS.get(code)
        if hint:
            out += f" | {hint}"
        return out

    @staticmethod
    def _graph(url, json_body=None, params=None, get=False):
        """One Graph round trip. Returns (ok, data, detail); never raises.

        Shared by the send path and template management so a network blip or a
        non-JSON body is described identically wherever it happens.
        """
        token = getattr(settings, 'WHATSAPP_API_TOKEN', '')
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        try:
            if get:
                resp = requests.get(url, headers=headers, params=params, timeout=15)
            else:
                resp = requests.post(url, headers=headers, params=params, json=json_body, timeout=15)
        except Exception as e:
            logger.error(f"WhatsApp request failed: {e}")
            return False, None, WhatsAppService._describe_error(0, None, exc=e)

        try:
            data = resp.json()
        except ValueError as e:
            logger.error(f"WhatsApp response was not JSON: {e}")
            return False, None, WhatsAppService._describe_error(resp.status_code, None, exc=e)

        if resp.status_code >= 400 or (isinstance(data, dict) and data.get('error')):
            return False, None, WhatsAppService._describe_error(resp.status_code, data)

        return True, data, ''

    @staticmethod
    def _post(payload):
        """POST a message payload to the Graph API. Returns (ok, detail); never raises."""
        version = getattr(settings, 'WHATSAPP_API_VERSION', 'v25.0')
        number_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
        url = f"https://graph.facebook.com/{version}/{number_id}/messages"

        ok, data, detail = WhatsAppService._graph(url, json_body=payload)
        if not ok:
            return False, detail

        messages = data.get('messages') if isinstance(data, dict) else None
        msg_id = messages[0].get('id', '') if messages else ''
        return True, f"OK ID:{msg_id}"

    @staticmethod
    def _templates_url():
        """The WABA-level message_templates edge, or '' when the WABA is unset.

        Deliberately ignores WHATSAPP_ENABLED: provisioning has to be possible
        while the live send path is switched off.
        """
        version = getattr(settings, 'WHATSAPP_API_VERSION', 'v25.0')
        waba_id = getattr(settings, 'WHATSAPP_WABA_ID', '')
        if not waba_id:
            return ''
        if not getattr(settings, 'WHATSAPP_API_TOKEN', ''):
            return ''
        return f"https://graph.facebook.com/{version}/{waba_id}/message_templates"

    # Fields the audit report needs. rejected_reason is why a template died;
    # quality_score is the early warning that it is about to.
    TEMPLATE_AUDIT_FIELDS = (
        'id,name,language,category,sub_category,status,parameter_format,'
        'quality_score,rejected_reason,health_status,last_updated_time'
    )

    @staticmethod
    def create_template(payload):
        """Create one message template on the WABA. Returns (ok, data, detail).

        'data' on success is Meta's {id, status, category}. 'status' will be
        PENDING until review completes - use list_templates() to follow it.
        """
        if not getattr(settings, 'WHATSAPP_WABA_ID', ''):
            return False, None, (
                "WhatsApp template provisioning not configured. Set WHATSAPP_WABA_ID in .env "
                "(App Dashboard > WhatsApp > API Setup)."
            )
        url = WhatsAppService._templates_url()
        ok, data, detail = WhatsAppService._graph(url, json_body=payload)
        return ok, data, detail

    @staticmethod
    def list_templates():
        """Audit every template on the WABA. Returns (ok, rows, detail)."""
        if not getattr(settings, 'WHATSAPP_WABA_ID', ''):
            return False, [], (
                "WhatsApp template audit not configured. Set WHATSAPP_WABA_ID in .env "
                "(App Dashboard > WhatsApp > API Setup)."
            )
        url = WhatsAppService._templates_url()
        ok, data, detail = WhatsAppService._graph(
            url, params={'fields': WhatsAppService.TEMPLATE_AUDIT_FIELDS}, get=True)
        if not ok:
            return False, [], detail
        rows = data.get('data') if isinstance(data, dict) else None
        return True, (rows or []), ''

    @staticmethod
    def send(to_phone, message):
        """Free-form text send. Only valid inside the 24h customer service window;
        used by the manual-send view, where staff compose arbitrary text."""
        if not to_phone:
            return False, "No phone number provided"

        phone = WhatsAppService.normalize_phone(to_phone)
        if not phone:
            return False, "Invalid phone number"

        if not getattr(settings, 'WHATSAPP_ENABLED', False):
            wa_url = WhatsAppService.get_click_to_chat_url(phone, message)
            logger.info(f"[WhatsApp disabled] fallback link for {phone}")
            return True, wa_url

        if not getattr(settings, 'WHATSAPP_API_TOKEN', '') or not getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', ''):
            return False, "WhatsApp not configured. Set WHATSAPP_API_TOKEN and WHATSAPP_PHONE_NUMBER_ID."

        return WhatsAppService._post({
            'messaging_product': 'whatsapp',
            'to': phone,
            'type': 'text',
            'text': {'body': message},
        })

    @staticmethod
    def send_typed(to_phone, notification_type, params):
        """Send via the Meta-approved template configured for this notification type.

        Transactional notifications fire outside the 24h customer service window,
        where free-form text is rejected with 131047 - only a template works.
        """
        if not to_phone:
            return False, "No phone number provided"

        phone = WhatsAppService.normalize_phone(to_phone)
        if not phone:
            return False, "Invalid phone number"

        if not getattr(settings, 'WHATSAPP_ENABLED', False):
            wa_url = WhatsAppService.get_click_to_chat_url(phone)
            logger.info(f"[WhatsApp disabled] fallback link for {phone}")
            return True, wa_url

        if not getattr(settings, 'WHATSAPP_API_TOKEN', '') or not getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', ''):
            return False, "WhatsApp not configured. Set WHATSAPP_API_TOKEN and WHATSAPP_PHONE_NUMBER_ID."

        template_name = WhatsAppService.template_name_for(notification_type)
        if not template_name:
            setting = WhatsAppService.TEMPLATE_SETTING_BY_TYPE.get(notification_type)
            return False, (
                f"No WhatsApp template configured for '{notification_type}'. "
                f"Set {setting or 'the matching WHATSAPP_TEMPLATE_* setting'} in .env."
            )

        # Templates are POSITIONAL (NAMED-with-variables is not creatable via the
        # Graph API), so the order of the parameters list decides which value lands
        # in which {{n}}. That order comes from wa_templates.json, never from the
        # order this dict happens to be in — otherwise a reordered dict literal
        # would silently post a customer's name into their balance field.
        supplied = {k: v for k, v in (params or {}).items() if v not in (None, '')}
        order = wa_templates.parameter_order(notification_type)
        if order:
            unexpected = set(supplied) - set(order)
            if unexpected:
                return False, (
                    f"Unknown WhatsApp template parameter(s) for '{notification_type}': "
                    f"{', '.join(sorted(unexpected))}. Expected {', '.join(order)}."
                )
            ordered = [supplied[k] for k in order if k in supplied]
        else:
            # No spec entry (custom template) — fall back to the caller's order.
            logger.warning(
                f"No wa_templates.json entry for '{notification_type}'; "
                "sending parameters in the order supplied")
            ordered = list(supplied.values())

        parameters = [{'type': 'text', 'text': str(value)} for value in ordered]
        template = {
            'name': template_name,
            'language': {'code': getattr(settings, 'WHATSAPP_TEMPLATE_LANGUAGE', 'en_US')},
        }
        if parameters:
            template['components'] = [{'type': 'body', 'parameters': parameters}]

        return WhatsAppService._post({
            'messaging_product': 'whatsapp',
            'to': phone,
            'type': 'template',
            'template': template,
        })

    @staticmethod
    def get_click_to_chat_url(phone, message=''):
        phone = WhatsAppService.normalize_phone(phone)
        return f"https://wa.me/{phone}?text={requests.utils.quote(message)}" if phone else ''


class NotificationService:
    @staticmethod
    def send_notification(recipient_name, recipient_contact, channel, notification_type,
                         message, subject='', customer_id='', booking_id='', user=None,
                         sms_message=None, template_params=None):
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
            # Automated transactional sends go via an approved fixed-sms template
            # (this account rejects free text). template_params present = templated;
            # absent = free text (e.g. a one-off staff message).
            if template_params is not None:
                success, detail = SMSService.send_typed(
                    recipient_contact, notification_type, template_params)
            else:
                success, detail = SMSService.send(recipient_contact, effective_message)
            if success:
                log.provider_message_id = SMSService.extract_message_id(detail)
        elif channel == 'whatsapp':
            # template_params present = an automated transactional notification, which
            # must go out as an approved template. Absent = staff free-form text from
            # the manual-send view, which only works inside the 24h window.
            if template_params is not None:
                success, detail = WhatsAppService.send_typed(
                    recipient_contact, notification_type, template_params)
            else:
                success, detail = WhatsAppService.send(recipient_contact, message)
            if success:
                log.provider_message_id = WhatsAppService.extract_message_id(detail)

        # Every provider returns (True, "... disabled") when it is switched off so
        # that no caller ever breaks. But nothing was transmitted, so recording it
        # as `sent` inflates the Notification Center's Delivered figure with
        # messages that never left the building (docs/qa finding #2).
        provider_setting = CHANNEL_ENABLED_SETTING.get(channel)
        provider_off = (provider_setting is not None
                        and not getattr(settings, provider_setting, False))

        if success and provider_off:
            log.status = 'skipped'
            log.error_message = detail or f'{channel} is disabled'
            log.sent_at = None
        else:
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

        # WhatsApp template params (approved templates only; see wa_templates.json)
        template_params = {
            'customer_name': customer.full_name,
            'amount': f'{payment.amount:,.0f}',
            'booking_id': booking.booking_id,
            'remaining_balance': f'{remaining:,.0f}',
        }
        if next_installment:
            template_params['next_installment'] = (
                f"#{next_installment.installment_number} of Rs. {next_installment.amount:,.0f} "
                f"due on {next_installment.due_date:%d-%b-%Y}"
            )

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
                    template_params=template_params,
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
        template_params = {
            'customer_name': customer.full_name,
            'booking_id': booking.booking_id,
            'plot_number': booking.plot.plot_number,
            'project_name': booking.plot.project.name,
            'total_amount': f'{booking.total_amount:,.0f}',
        }
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
                    template_params=template_params,
                    customer_id=customer.customer_id,
                    booking_id=booking.booking_id,
                )

    @staticmethod
    def send_customer_welcome(customer, user=None):
        """Send a welcome to a freshly-created Customer (email + SMS via template).

        Failure-safe by design: the whole send is wrapped so that a broken send
        (invalid address, SMTP failure, even a NotificationLog write error) can
        NEVER propagate up and corrupt the customer transaction that just
        succeeded. Run channels: SMS (approved fixed-sms template) when a phone
        is present, plus email when an address is present. Returns the last
        NotificationLog row, or None if there was nothing to send or the send
        failed (failure is logged, never raised).
        """
        try:
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
            template_params = {
                'customer_name': customer.full_name,
                'customer_id': customer_id,
            }
            email = (getattr(customer, 'email', '') or '').strip()
            phone = SMSService.normalize_phone(getattr(customer, 'phone', '') or '')

            channels = []
            if phone:
                channels.append('sms')
            if email:
                channels.append('email')

            last = None
            for ch in channels:
                contact = phone if ch == 'sms' else email
                last = NotificationService.send_notification(
                    recipient_name=customer.full_name,
                    recipient_contact=contact,
                    channel=ch,
                    notification_type='customer_welcome',
                    subject='Welcome to Samana Builders & Developers',
                    message=message,
                    template_params=template_params,
                    customer_id=customer_id,
                    user=user,
                )
            return last
        except Exception as e:
            # Log and swallow: a welcome send must never break customer creation.
            logger.error(
                f"[Welcome failed - non-fatal] customer "
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
            f"Please arrange payment at your earliest convenience.\n\n"
            f"Samana Builders & Developers"
        )
        template_params = {
            'customer_name': customer.full_name,
            'installment_number': installment.installment_number,
            'amount': f'{installment.amount:,.0f}',
            'due_date': f'{installment.due_date:%d-%b-%Y}',
            'booking_id': booking.booking_id,
        }
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
                    template_params=template_params,
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
            f"Total Outstanding: Rs. {installment.remaining_amount:,.0f}\n\n"
            f"Please arrange payment at your earliest convenience.\n\n"
            f"Samana Builders & Developers"
        )
        template_params = {
            'customer_name': customer.full_name,
            'installment_number': installment.installment_number,
            'amount': f'{installment.amount:,.0f}',
            'due_date': f'{installment.due_date:%d-%b-%Y}',
            'outstanding': f'{installment.remaining_amount:,.0f}',
            'booking_id': booking.booking_id,
        }
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
                    template_params=template_params,
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
        template_params = {
            'customer_name': customer.full_name,
            'receipt_number': receipt.receipt_number,
            'amount': f'{payment.amount:,.0f}',
            'receipt_date': f'{receipt.receipt_date:%d-%b-%Y}',
            'payment_id': payment.payment_id,
        }
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
                    template_params=template_params,
                    customer_id=customer.customer_id,
                    booking_id=booking.booking_id,
                )
