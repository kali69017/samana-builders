"""Tests for the SendPK SMS integration and notification messages."""
import json
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from bookings.models import Booking, InstallmentPlan
from customers.models import Customer
from payments.models import Payment, Receipt
from properties.models import Plot, Project
from . import wa_templates
from .models import NotificationLog
from .services import SMSService, NotificationService, WhatsAppService
from .wa_templates import build_payload, build_payloads, validate_entry, validate_spec

APPROVED_ROW = {
    'id': '1', 'name': 'samana_installment_due', 'language': 'en_US',
    'category': 'UTILITY', 'sub_category': 'ORDER_DETAILS', 'status': 'APPROVED',
    'parameter_format': 'POSITIONAL', 'quality_score': {'score': 'GREEN'},
    'rejected_reason': '', 'health_status': {'can_send_message': 'YES'},
}


def graph_response(wamid='wamid.TEST', status_code=200, payload=None):
    """Build a stand-in for the Graph API `messages` response."""
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {'messages': [{'id': wamid}]}
    return resp


def _entry(**overrides):
    """A minimal valid template entry, for testing the validator in isolation."""
    entry = {
        'notification_type': 'test_type',
        'env_setting': 'WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER',
        'suggested_name': 'samana_test_notice',
        'category': 'UTILITY',
        'sub_category': 'ORDER_DETAILS',
        'language': 'en_US',
        'body': 'Dear {{1}}, your payment of Rs {{2}} is due.',
        'parameters': [
            {'param_name': 'customer_name', 'example': 'Ahmed Khan'},
            {'param_name': 'amount', 'example': '1,000,000'},
        ],
    }
    entry.update(overrides)
    return entry


class SMSNormalizationTest(TestCase):
    def test_normalize_phone(self):
        self.assertEqual(SMSService.normalize_phone('+92-300-1234567'), '923001234567')
        self.assertEqual(SMSService.normalize_phone('0300-1234567'), '923001234567')
        self.assertEqual(SMSService.normalize_phone('923001234567'), '923001234567')
        self.assertEqual(SMSService.normalize_phone('3001234567'), '923001234567')
        self.assertEqual(SMSService.normalize_phone(''), '')


class SMSServiceSendTest(TestCase):
    @override_settings(SENDPK_ENABLED=False)
    def test_send_disabled_does_not_hit_network(self):
        with patch('notifications.services.requests.post') as mock_post:
            ok, detail = SMSService.send('+92-300-1234567', 'Hello')
        self.assertTrue(ok)
        mock_post.assert_not_called()

    @override_settings(SENDPK_ENABLED=True, SENDPK_API_KEY='test-key', SENDPK_SENDER_ID='SAMANA')
    def test_send_success(self):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            'success': 'true',
            'results': [{'status': 'OK', 'messageid': '6502124', 'gsm': '923001234567'}],
        }
        with patch('notifications.services.requests.post', return_value=mock_resp) as mock_post:
            ok, detail = SMSService.send('+92-300-1234567', 'Hello')
        self.assertTrue(ok)
        self.assertIn('6502124', detail)
        payload = mock_post.call_args.kwargs['data']
        self.assertEqual(payload['mobile'], '923001234567')
        self.assertEqual(payload['sender'], 'SAMANA')

    @override_settings(SENDPK_ENABLED=True, SENDPK_API_KEY='test-key', SENDPK_SENDER_ID='SAMANA')
    def test_send_failure(self):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {'success': 'false', 'results': [{'status': '8', 'error': 'Low Credit'}]}
        with patch('notifications.services.requests.post', return_value=mock_resp):
            ok, detail = SMSService.send('+92-300-1234567', 'Hello')
        self.assertFalse(ok)

    def test_send_invalid_phone(self):
        ok, detail = SMSService.send('abc', 'Hello')
        self.assertFalse(ok)
        self.assertIn('Invalid', detail)


# Settings shared by every SendPK templated-send test: channel live and all four
# template ids stated explicitly. Same rule as WA_ON below -- a developer's .env
# holds real ids, so no test may lean on ambient state to decide what it sends.
SMS_ON = {
    'SENDPK_ENABLED': True,
    'SENDPK_API_KEY': 'test-key',
    'SENDPK_SENDER_ID': 'TEXT SMS',
    'SENDPK_TEMPLATE_CUSTOMER_WELCOME': '10904',
    'SENDPK_TEMPLATE_PAYMENT_CONFIRMATION': '10901',
    'SENDPK_TEMPLATE_INSTALLMENT_REMINDER': '10902',
    'SENDPK_TEMPLATE_OVERDUE_PAYMENT': '10903',
}

WELCOME_PARAMS = {'customer_name': 'Ahmed Khan', 'customer_id': 'CUS-00001'}
REMINDER_PARAMS = {
    'customer_name': 'Ahmed Khan', 'installment_number': '2',
    'amount': '1,000,000', 'due_date': '15-Oct-2026', 'booking_id': 'BKG-00001',
}


class ProviderGuardTest(TestCase):
    """The settings guard that keeps `manage.py test` off the network.

    A developer's .env holds live SMS/WhatsApp/SMTP credentials. If the runner
    ever read them back, every customer-creating test would bill a real send --
    so assert the guard, not just rely on it.
    """

    def test_every_provider_is_off_under_the_test_runner(self):
        from django.conf import settings
        self.assertTrue(settings.TESTING)
        for name in ('EMAIL_ENABLED', 'SENDPK_ENABLED', 'WHATSAPP_ENABLED', 'AI_ENABLED'):
            self.assertFalse(getattr(settings, name), f'{name} must be off under `manage.py test`')


@override_settings(**SMS_ON)
class SMSServiceSendTypedTest(TestCase):
    """The fixed-sms path: variable validation, transport, response parsing."""

    @staticmethod
    def _resp(json_value=None, text='', json_raises=False):
        resp = Mock()
        resp.text = text
        if json_raises:
            resp.json.side_effect = ValueError('not json')
        else:
            resp.json.return_value = json_value
        return resp

    @staticmethod
    def _ok_json(messageid='4241a169-0000-0000'):
        return {'success': 'true', 'results': [{'status': 'OK', 'messageid': messageid}]}

    def test_posts_template_id_and_maps_param_names_to_template_variables(self):
        with patch('notifications.services.requests.post',
                   return_value=self._resp(self._ok_json())) as mock_post:
            ok, detail = SMSService.send_typed('03001234567', 'installment_reminder',
                                               dict(REMINDER_PARAMS))
        self.assertTrue(ok, detail)
        data = mock_post.call_args.kwargs['data']
        self.assertEqual('10902', data['template_id'])
        self.assertEqual('923001234567', data['mobile'])
        self.assertEqual('TEXT SMS', data['sender'])
        sent = json.loads(data['message'])
        # SendPK's slot names, not the caller's parameter names.
        self.assertEqual('Ahmed Khan', sent['name'])
        self.assertEqual('2', sent['installment_number'])
        self.assertNotIn('customer_name', sent)

    def test_transport_is_post_so_the_api_key_stays_out_of_the_url(self):
        with patch('notifications.services.requests.post',
                   return_value=self._resp(self._ok_json())) as mock_post:
            SMSService.send_typed('03001234567', 'customer_welcome',
                                  dict(WELCOME_PARAMS))
        call = mock_post.call_args
        self.assertNotIn('test-key', call.args[0])
        self.assertNotIn('params', call.kwargs)

    def test_missing_required_variable_refuses_to_send(self):
        with patch('notifications.services.requests.post') as mock_post:
            ok, detail = SMSService.send_typed(
                '03001234567', 'installment_reminder',
                {'customer_name': 'Ahmed Khan', 'amount': '1,000,000'})
        self.assertFalse(ok)
        mock_post.assert_not_called()
        self.assertIn('due_date', detail)
        self.assertIn('booking_id', detail)

    def test_every_template_slot_is_filled_even_when_the_caller_omits_one(self):
        with patch('notifications.services.requests.post',
                   return_value=self._resp(self._ok_json())) as mock_post:
            ok, detail = SMSService.send_typed(
                '03001234567', 'payment_confirmation',
                {'customer_name': 'Ahmed Khan', 'amount': '120,000',
                 'booking_id': 'BKG-00001', 'remaining_balance': '4,000,000',
                 'next_installment': ''})
        self.assertTrue(ok, detail)
        sent = json.loads(mock_post.call_args.kwargs['data']['message'])
        self.assertEqual(
            {'name', 'amount', 'booking_id', 'remaining', 'next_installment'},
            set(sent))
        self.assertEqual('none due', sent['next_installment'])

    def test_disabled_provider_never_touches_the_network(self):
        with override_settings(SENDPK_ENABLED=False), \
                patch('notifications.services.requests.post') as mock_post:
            ok, detail = SMSService.send_typed('03001234567', 'customer_welcome',
                                               dict(WELCOME_PARAMS))
        self.assertTrue(ok)
        self.assertEqual('SMS disabled', detail)
        mock_post.assert_not_called()

    def test_unconfigured_template_names_the_missing_setting(self):
        with override_settings(SENDPK_TEMPLATE_CUSTOMER_WELCOME=''):
            ok, detail = SMSService.send_typed('03001234567', 'customer_welcome',
                                               dict(WELCOME_PARAMS))
        self.assertFalse(ok)
        self.assertIn('SENDPK_TEMPLATE_CUSTOMER_WELCOME', detail)

    def test_type_without_an_sms_template_is_refused(self):
        ok, detail = SMSService.send_typed('03001234567', 'receipt_notification', {})
        self.assertFalse(ok)
        self.assertIn('No SMS template configured', detail)

    def test_invalid_phone_is_refused_before_any_lookup(self):
        ok, detail = SMSService.send_typed('abc', 'customer_welcome',
                                           dict(WELCOME_PARAMS))
        self.assertFalse(ok)
        self.assertIn('Invalid', detail)

    def test_plain_text_ok_response_is_accepted_and_parsed(self):
        resp = self._resp(text='OK ID:4241a169-1111', json_raises=True)
        with patch('notifications.services.requests.post', return_value=resp):
            ok, detail = SMSService.send_typed('03001234567', 'customer_welcome',
                                               dict(WELCOME_PARAMS))
        self.assertTrue(ok, detail)
        self.assertEqual('4241a169-1111', SMSService.extract_message_id(detail))

    def test_json_error_response_is_a_failure_not_a_success(self):
        resp = self._resp({'success': 'false',
                           'results': [{'status': '8', 'error': 'Low Credit'}]})
        with patch('notifications.services.requests.post', return_value=resp):
            ok, detail = SMSService.send_typed('03001234567', 'customer_welcome',
                                               dict(WELCOME_PARAMS))
        self.assertFalse(ok)
        self.assertIn('Low Credit', detail)

    def test_network_exception_becomes_a_failure_not_a_crash(self):
        with patch('notifications.services.requests.post',
                   side_effect=Exception('connection refused')):
            ok, detail = SMSService.send_typed('03001234567', 'customer_welcome',
                                               dict(WELCOME_PARAMS))
        self.assertFalse(ok)
        self.assertIn('connection refused', detail)

    def test_extract_message_id_reads_a_fixed_sms_uuid(self):
        self.assertEqual('ebd6dc1e-aaaa-bbbb',
                         SMSService.extract_message_id('OK ID:ebd6dc1e-aaaa-bbbb'))
        self.assertEqual('6502124', SMSService.extract_message_id('OK ID:6502124'))
        self.assertEqual('', SMSService.extract_message_id(''))


class NotificationCenterFilterTest(TestCase):
    """Regression: the log list sliced before filtering, so every filter 500'd."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            'notifadmin', 'notif@example.com', 'pw12345!')
        self.client.force_login(self.user)

    def test_every_filter_combination_renders(self):
        NotificationLog.objects.create(
            recipient_name='Test', recipient_contact='+923001234567',
            channel='sms', notification_type='general', message='hi',
            status='skipped')
        for query in ('', '?status=skipped', '?status=sent', '?channel=sms',
                      '?type=general', '?channel=sms&status=skipped&type=general'):
            with self.subTest(query=query):
                resp = self.client.get(reverse('notifications') + query)
                self.assertEqual(resp.status_code, 200)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NotificationStatusRecordingTest(TestCase):
    """`sent` must mean transmitted: a switched-off provider is `skipped`."""

    @staticmethod
    def _send(template_params=None):
        return NotificationService.send_notification(
            recipient_name='Ahmed Khan', recipient_contact='+92-300-1234567',
            channel='sms', notification_type='customer_welcome',
            message='hello', template_params=template_params,
        )

    @override_settings(SENDPK_ENABLED=False)
    def test_disabled_provider_is_recorded_as_skipped_not_sent(self):
        log = self._send(dict(WELCOME_PARAMS))
        self.assertEqual('skipped', log.status)
        self.assertIsNone(log.sent_at)
        self.assertNotEqual('', log.error_message)

    @override_settings(**SMS_ON)
    def test_successful_send_is_recorded_as_sent(self):
        resp = Mock()
        resp.text = ''
        resp.json.return_value = {'success': 'true',
                                  'results': [{'status': 'OK', 'messageid': '4241'}]}
        with patch('notifications.services.requests.post', return_value=resp):
            log = self._send(dict(WELCOME_PARAMS))
        self.assertEqual('sent', log.status)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual('4241', log.provider_message_id)

    @override_settings(**SMS_ON)
    def test_failed_send_is_recorded_as_failed_with_the_reason(self):
        with patch('notifications.services.SMSService.send_typed',
                   return_value=(False, 'Low Credit')):
            log = self._send(dict(WELCOME_PARAMS))
        self.assertEqual('failed', log.status)
        self.assertEqual('Low Credit', log.error_message)
        self.assertIsNone(log.sent_at)

    @override_settings(**SMS_ON)
    def test_missing_template_variable_marks_the_log_as_failed(self):
        log = self._send({'customer_name': 'Ahmed Khan'})
        self.assertEqual('failed', log.status)
        self.assertIn('missing required variable', log.error_message)


# Settings shared by every WhatsApp Cloud API test: channel live, one template
# configured, so each test only has to state what it actually varies.
WA_ON = {
    'WHATSAPP_ENABLED': True,
    'WHATSAPP_API_TOKEN': 'test-token',
    'WHATSAPP_PHONE_NUMBER_ID': '1276551565544996',
    'WHATSAPP_API_VERSION': 'v25.0',
    'WHATSAPP_TEMPLATE_LANGUAGE': 'en_US',
}

WA_WABA = '109876543210'

# Explicitly "no template configured". Tests that exercise the unconfigured
# path must say so: a developer's .env legitimately holds real approved
# template names, and relying on those being blank makes the suite depend on
# ambient environment state.
WA_NO_TEMPLATES = {setting: '' for setting in WhatsAppService.TEMPLATE_SETTING_BY_TYPE.values()}


def create_payload(**overrides):
    """The compiled create body for one real template, so tests need no hand-built JSON."""
    entry = wa_templates.templates()[0]
    return wa_templates.build_payload(entry, **overrides)


def waba_response(payload, status_code=200):
    """Build a stand-in for a WABA-level Graph response (template create / list)."""
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


@override_settings(**WA_ON)
class WhatsAppDisabledTest(TestCase):
    """The disabled-channel contract predates this work and must not regress."""

    @override_settings(WHATSAPP_ENABLED=False)
    def test_send_returns_click_to_chat_link(self):
        with patch('notifications.services.requests.post') as mock_post:
            ok, detail = WhatsAppService.send('+92-300-1234567', 'Hello')
        self.assertTrue(ok)
        self.assertTrue(detail.startswith('https://wa.me/923001234567?text='))
        mock_post.assert_not_called()

    @override_settings(WHATSAPP_ENABLED=False)
    def test_send_typed_returns_click_to_chat_link(self):
        with patch('notifications.services.requests.post') as mock_post:
            ok, detail = WhatsAppService.send_typed(
                '0300-1234567', 'installment_reminder', {'customer_name': 'Ahmed'})
        self.assertTrue(ok)
        self.assertTrue(detail.startswith('https://wa.me/923001234567?text='))
        mock_post.assert_not_called()


@override_settings(**{**WA_ON, **WA_NO_TEMPLATES})
class WhatsAppTemplateConfigTest(TestCase):
    """A notification type with no configured template must fail loudly."""

    def test_send_typed_without_configured_template_reports_the_setting(self):
        with patch('notifications.services.requests.post') as mock_post:
            ok, detail = WhatsAppService.send_typed(
                '+92-300-1234567', 'installment_reminder', {'customer_name': 'Ahmed'})
        self.assertFalse(ok)
        self.assertIn('WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER', detail)
        mock_post.assert_not_called()

    def test_template_name_for_returns_configured_name(self):
        with override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due'):
            self.assertEqual('samana_installment_due', WhatsAppService.template_name_for('installment_reminder'))

    def test_template_name_for_returns_blank_for_unknown_type(self):
        self.assertEqual('', WhatsAppService.template_name_for('general'))

    def test_extract_message_id_parses_wamid(self):
        self.assertEqual('wamid.HBgTEST', WhatsAppService.extract_message_id('OK ID:wamid.HBgTEST'))

    def test_extract_message_id_returns_blank_for_click_to_chat_link(self):
        self.assertEqual('', WhatsAppService.extract_message_id('https://wa.me/923001234567?text=Hi'))


@override_settings(**WA_ON)
class WhatsAppSendTypedTest(TestCase):
    @override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
    def test_send_typed_posts_approved_template_with_positional_params(self):
        resp = graph_response('wamid.HBgTEST')
        with patch('notifications.services.requests.post', return_value=resp) as mock_post:
            ok, detail = WhatsAppService.send_typed('+92-300-1234567', 'installment_reminder', {
                'customer_name': 'Ahmed Khan',
                'installment_number': '2',
                'amount': '350,000',
                'due_date': '15-Oct-2026',
                'booking_id': 'BKG-00007',
            })

        self.assertTrue(ok)
        self.assertIn('wamid.HBgTEST', detail)
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual('whatsapp', payload['messaging_product'])
        self.assertEqual('923001234567', payload['to'])
        self.assertEqual('template', payload['type'])
        self.assertEqual('samana_installment_due', payload['template']['name'])
        self.assertEqual({'code': 'en_US'}, payload['template']['language'])
        # Positional: values only, no parameter_name, in the spec's order.
        self.assertEqual(
            ['Ahmed Khan', '2', '350,000', '15-Oct-2026', 'BKG-00007'],
            [p['text'] for p in payload['template']['components'][0]['parameters']],
        )
        self.assertNotIn(
            'parameter_name',
            payload['template']['components'][0]['parameters'][0],
            'Positional templates must not carry parameter_name',
        )

    @override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
    def test_send_typed_orders_by_spec_not_by_dict_order(self):
        """The whole point of positional: a reordered dict must not misalign values."""
        resp = graph_response('wamid.ORDER')
        with patch('notifications.services.requests.post', return_value=resp) as mock_post:
            WhatsAppService.send_typed('+92-300-1234567', 'installment_reminder', {
                'booking_id': 'BKG-00007',
                'due_date': '15-Oct-2026',
                'amount': '350,000',
                'installment_number': '2',
                'customer_name': 'Ahmed Khan',
            })

        self.assertEqual(
            ['Ahmed Khan', '2', '350,000', '15-Oct-2026', 'BKG-00007'],
            [p['text'] for p in mock_post.call_args.kwargs['json']['template']['components'][0]['parameters']],
        )

    @override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
    def test_send_typed_rejects_a_parameter_the_template_does_not_have(self):
        """Silently dropping it would shift every later value by one place."""
        with patch('notifications.services.requests.post') as mock_post:
            ok, detail = WhatsAppService.send_typed('+92-300-1234567', 'installment_reminder', {
                'customer_name': 'Ahmed Khan',
                'late_fee': '500',
            })

        self.assertFalse(ok)
        self.assertIn('late_fee', detail)
        mock_post.assert_not_called()

    @override_settings(WHATSAPP_TEMPLATE_PAYMENT_CONFIRMATION='samana_payment_received')
    def test_send_typed_omits_components_when_no_params(self):
        resp = graph_response('wamid.NOPARAMS')
        with patch('notifications.services.requests.post', return_value=resp) as mock_post:
            ok, _ = WhatsAppService.send_typed('+92-300-1234567', 'payment_confirmation', {})

        self.assertTrue(ok)
        payload = mock_post.call_args.kwargs['json']
        self.assertNotIn('components', payload['template'])

    @override_settings(WHATSAPP_TEMPLATE_PAYMENT_CONFIRMATION='samana_payment_received')
    def test_send_typed_drops_empty_params(self):
        """A customer with no next installment must not get a blank phrase."""
        resp = graph_response('wamid.OMIT')
        with patch('notifications.services.requests.post', return_value=resp) as mock_post:
            WhatsAppService.send_typed('+92-300-1234567', 'payment_confirmation', {
                'customer_name': 'Ahmed Khan',
                'next_installment': '',
            })

        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(
            ['Ahmed Khan'],
            [p['text'] for p in payload['template']['components'][0]['parameters']],
        )

    @override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
    def test_send_typed_rejects_invalid_phone(self):
        with patch('notifications.services.requests.post') as mock_post:
            ok, detail = WhatsAppService.send_typed('abc', 'installment_reminder', {'a': 'b'})
        self.assertFalse(ok)
        self.assertIn('Invalid', detail)
        mock_post.assert_not_called()

    @override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
    def test_send_typed_surfaces_graph_error_code_and_hint(self):
        resp = graph_response(status_code=400, payload={'error': {
            'message': '(#131047) Re-engagement message',
            'type': 'OAuthException',
            'code': 131047,
            'error_data': {'details': 'Message failed to send because more than 24 hours have passed.'},
        }})
        with patch('notifications.services.requests.post', return_value=resp):
            ok, detail = WhatsAppService.send_typed(
                '+92-300-1234567', 'installment_reminder', {'customer_name': 'Ahmed'})

        self.assertFalse(ok)
        self.assertIn('131047', detail)
        self.assertIn('24 hours', detail)
        self.assertIn('template', detail.lower())

    @override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
    def test_send_typed_reports_unapproved_template(self):
        resp = graph_response(status_code=400, payload={'error': {
            'message': 'Invalid parameter', 'code': 132001,
        }})
        with patch('notifications.services.requests.post', return_value=resp):
            ok, detail = WhatsAppService.send_typed(
                '+92-300-1234567', 'installment_reminder', {'customer_name': 'Ahmed'})

        self.assertFalse(ok)
        self.assertIn('132001', detail)

    @override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
    def test_send_typed_survives_network_exception(self):
        with patch('notifications.services.requests.post', side_effect=OSError('boom')):
            ok, detail = WhatsAppService.send_typed(
                '+92-300-1234567', 'installment_reminder', {'customer_name': 'Ahmed'})
        self.assertFalse(ok)
        self.assertIn('boom', detail)

    @override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
    def test_send_typed_survives_non_json_response(self):
        resp = Mock()
        resp.status_code = 200
        resp.json.side_effect = ValueError('not json')
        with patch('notifications.services.requests.post', return_value=resp):
            ok, detail = WhatsAppService.send_typed(
                '+92-300-1234567', 'installment_reminder', {'customer_name': 'Ahmed'})
        self.assertFalse(ok)
        self.assertIn('not json', detail)


@override_settings(**WA_ON, WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER='samana_installment_due')
class WhatsAppGraphErrorHintTest(TestCase):
    """Every code we special-case must carry an actionable hint."""

    def test_known_codes_explain_themselves(self):
        for code in (131047, 130429, 131056, 132000, 132001, 131049, 131050):
            with self.subTest(code=code):
                resp = graph_response(status_code=400, payload={'error': {
                    'message': 'boom', 'code': code,
                }})
                with patch('notifications.services.requests.post', return_value=resp):
                    ok, detail = WhatsAppService.send_typed(
                        '+92-300-1234567', 'installment_reminder',
                        {'customer_name': 'Ahmed Khan'})
                self.assertFalse(ok)
                self.assertIn(str(code), detail)

    def test_unknown_code_still_reports_raw(self):
        resp = graph_response(status_code=500, payload={'error': {
            'message': 'Something upstream broke', 'code': 999999,
        }})
        with patch('notifications.services.requests.post', return_value=resp):
            ok, detail = WhatsAppService.send_typed(
                '+92-300-1234567', 'installment_reminder', {'customer_name': 'Ahmed Khan'})
        self.assertFalse(ok)
        self.assertIn('999999', detail)
        self.assertIn('Something upstream broke', detail)


# SENDPK_ENABLED is stated explicitly: these tests reach the SMS channel through
# send_notification(), and .env legitimately holds SENDPK_ENABLED=True with a real
# key. Relying on ambient state would turn `manage.py test` into a live SMS sender.
@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SENDPK_ENABLED=False,
)
class NotificationMessageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            email='ahmed@example.com', created_by=self.user,
        )
        self.project = Project.objects.create(name='Test', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), advance_paid=Decimal('1000000'),
            status='active', created_by=self.user,
        )
        self.plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=4,
            installment_amount=Decimal('1000000'), down_payment_amount=Decimal('1000000'),
            start_date=date.today(), frequency='monthly',
        )
        self.plan.auto_generate()

    def test_payment_confirmation_sms_contains_remaining_and_next_installment(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('120000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='verified', created_by=self.user,
        )
        # send_notification routes through send_typed(), not send(), whenever
        # template_params is present -- patch the one that actually runs.
        with patch('notifications.services.SMSService.send_typed', return_value=(True, 'OK ID:123')):
            NotificationService.send_payment_confirmation(payment)

        sms_log = NotificationLog.objects.filter(
            channel='sms', notification_type='payment_confirmation'
        ).first()
        self.assertIsNotNone(sms_log)
        # remaining balance = 5,000,000 - 1,000,000
        self.assertIn('Remaining', sms_log.message)
        self.assertIn('4,000,000', sms_log.message)
        # next unpaid installment is #1
        self.assertIn('#1', sms_log.message)

    def test_installment_reminder_sends_sms(self):
        installment = self.plan.installments.filter(installment_number=1).first()
        with patch('notifications.services.SMSService.send_typed', return_value=(True, 'OK ID:456')):
            NotificationService.send_installment_reminder(installment)

        sms_log = NotificationLog.objects.filter(
            channel='sms', notification_type='installment_reminder'
        ).first()
        self.assertIsNotNone(sms_log)
        self.assertIn('installment #1', sms_log.message)

    def test_sms_log_stores_concise_message_not_full_email(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('120000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='verified', created_by=self.user,
        )
        with patch('notifications.services.SMSService.send_typed', return_value=(True, 'OK ID:123')):
            NotificationService.send_payment_confirmation(payment)

        sms_log = NotificationLog.objects.get(channel='sms', notification_type='payment_confirmation')
        email_log = NotificationLog.objects.get(channel='email', notification_type='payment_confirmation')
        # SMS is concise; email is verbose
        self.assertLess(len(sms_log.message), len(email_log.message))
        self.assertNotIn('Payment ID', sms_log.message)


@override_settings(
    SENDPK_ENABLED=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    WHATSAPP_ENABLED=True,
    WHATSAPP_API_TOKEN='test-token',
    WHATSAPP_PHONE_NUMBER_ID='1276551565544996',
    WHATSAPP_API_VERSION='v25.0',
    WHATSAPP_TEMPLATE_LANGUAGE='en_US',
    # Wire every template straight from the spec. These used to be string
    # literals, so the _v2 rename broke these tests with a bare KeyError on
    # customer_name instead of pointing at the name that had moved.
    **{e['env_setting']: e['suggested_name'] for e in wa_templates.templates()},
)
class WhatsAppTemplateDeliveryTest(TestCase):
    """End-to-end: trigger -> NotificationService -> WhatsAppService -> Graph payload."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            email='ahmed@example.com', created_by=self.user,
        )
        self.project = Project.objects.create(name='Bahria Town', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), advance_paid=Decimal('1000000'),
            status='active', created_by=self.user,
        )
        self.plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=4,
            installment_amount=Decimal('1000000'), down_payment_amount=Decimal('1000000'),
            start_date=date.today(), frequency='monthly',
        )
        self.plan.auto_generate()

    def _payload_for(self, mock_post, template_name):
        """Pull the outbound template payload with the given template name."""
        matches = [c.kwargs['json'] for c in mock_post.call_args_list
                   if c.kwargs['json'].get('template', {}).get('name') == template_name]
        self.assertEqual(1, len(matches), f'expected one {template_name} send')
        return matches[0]

    def _params_for(self, payload):
        """Map the positional texts back onto param names via the spec's order."""
        template = payload.get('template') or {}
        notification_type = next(
            (e['notification_type'] for e in wa_templates.templates()
             if e['suggested_name'] == template.get('name')), '')
        if not notification_type:
            self.fail(f"no wa_templates.json entry names {template.get('name')!r}")
        order = wa_templates.parameter_order(notification_type)
        texts = [p['text'] for c in (template.get('components') or []) for p in c['parameters']]
        return dict(zip(order, texts))

    def _deliver(self, action, wamid='wamid.OK1'):
        resp = graph_response(wamid)
        with patch('notifications.services.requests.post', return_value=resp) as mock_post:
            action()
        return mock_post

    def _verified_payment(self):
        return Payment.objects.create(
            booking=self.booking, amount=Decimal('120000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='verified', created_by=self.user,
        )

    def test_payment_confirmation_sends_approved_template(self):
        payment = self._verified_payment()
        mock_post = self._deliver(lambda: NotificationService.send_payment_confirmation(payment))

        payload = self._payload_for(mock_post, wa_templates.template_name('payment_confirmation'))
        self.assertEqual('923001234567', payload['to'])
        params = self._params_for(payload)
        self.assertEqual('Ahmed Khan', params['customer_name'])
        self.assertEqual('120,000', params['amount'])
        self.assertEqual('BKG-00001', params['booking_id'])
        self.assertEqual('4,000,000', params['remaining_balance'])
        self.assertIn('#1', params['next_installment'])

    def test_payment_confirmation_records_wamid_for_delivery_tracking(self):
        payment = self._verified_payment()
        self._deliver(lambda: NotificationService.send_payment_confirmation(payment), wamid='wamid.PC42')

        log = NotificationLog.objects.get(channel='whatsapp', notification_type='payment_confirmation')
        self.assertEqual('sent', log.status)
        self.assertEqual('wamid.PC42', log.provider_message_id)

    def test_payment_confirmation_omits_next_installment_when_none_due(self):
        payment = self._verified_payment()
        self.plan.installments.update(status='paid')
        mock_post = self._deliver(lambda: NotificationService.send_payment_confirmation(payment))

        params = self._params_for(self._payload_for(
            mock_post, wa_templates.template_name('payment_confirmation')))
        self.assertNotIn('next_installment', params)

    def test_booking_notification_sends_approved_template(self):
        mock_post = self._deliver(lambda: NotificationService.send_booking_notification(self.booking))

        params = self._params_for(self._payload_for(
            mock_post, wa_templates.template_name('booking_notification')))
        self.assertEqual('Ahmed Khan', params['customer_name'])
        self.assertEqual('BKG-00001', params['booking_id'])
        self.assertEqual('A-101', params['plot_number'])
        self.assertEqual('Bahria Town', params['project_name'])
        self.assertEqual('5,000,000', params['total_amount'])

    def test_installment_reminder_sends_approved_template(self):
        installment = self.plan.installments.get(installment_number=1)
        mock_post = self._deliver(lambda: NotificationService.send_installment_reminder(installment))

        params = self._params_for(self._payload_for(
            mock_post, wa_templates.template_name('installment_reminder')))
        self.assertEqual('Ahmed Khan', params['customer_name'])
        self.assertEqual('1', params['installment_number'])
        self.assertEqual('1,000,000', params['amount'])
        self.assertEqual('BKG-00001', params['booking_id'])
        self.assertRegex(params['due_date'], r'^\d{2}-[A-Za-z]{3}-\d{4}$')

    def test_overdue_alert_omits_late_fee_parameter(self):
        installment = self.plan.installments.get(installment_number=1)
        mock_post = self._deliver(lambda: NotificationService.send_overdue_payment_alert(installment))

        params = self._params_for(self._payload_for(
            mock_post, wa_templates.template_name('overdue_payment')))
        self.assertNotIn('late_fee', params)
        self.assertEqual('1,000,000', params['amount'])
        self.assertIn('outstanding', params)

    def test_receipt_notification_sends_approved_template(self):
        payment = self._verified_payment()
        receipt = Receipt.objects.create(payment=payment, receipt_date=date.today(), generated_by=self.user)
        mock_post = self._deliver(lambda: NotificationService.send_receipt_notification(receipt))

        params = self._params_for(self._payload_for(
            mock_post, wa_templates.template_name('receipt_notification')))
        self.assertEqual('Ahmed Khan', params['customer_name'])
        self.assertEqual(receipt.receipt_number, params['receipt_number'])
        self.assertEqual('120,000', params['amount'])
        self.assertEqual('PAY-00001', params['payment_id'])

    def test_unconfigured_template_marks_log_failed_naming_the_setting(self):
        with override_settings(WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER=''):
            installment = self.plan.installments.get(installment_number=1)
            resp = graph_response()
            with patch('notifications.services.requests.post', return_value=resp) as mock_post:
                NotificationService.send_installment_reminder(installment)

        mock_post.assert_not_called()
        log = NotificationLog.objects.get(channel='whatsapp', notification_type='installment_reminder')
        self.assertEqual('failed', log.status)
        self.assertIn('WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER', log.error_message)

    def test_graph_failure_is_recorded_on_the_log(self):
        installment = self.plan.installments.get(installment_number=1)
        resp = graph_response(status_code=400, payload={'error': {
            'message': 'Re-engagement message', 'code': 131047,
            'error_data': {'details': 'More than 24 hours have passed.'},
        }})
        with patch('notifications.services.requests.post', return_value=resp):
            NotificationService.send_installment_reminder(installment)

        log = NotificationLog.objects.get(channel='whatsapp', notification_type='installment_reminder')
        self.assertEqual('failed', log.status)
        self.assertIn('131047', log.error_message)
        self.assertIsNone(log.sent_at)

    def test_manual_send_still_uses_freeform_text(self):
        resp = graph_response('wamid.MANUAL')
        with patch('notifications.services.requests.post', return_value=resp) as mock_post:
            NotificationService.send_notification(
                recipient_name='Ahmed Khan', recipient_contact='+92-300-1234567',
                channel='whatsapp', notification_type='general',
                subject='Quick question', message='Please call me back.',
            )

        payload = mock_post.call_args.kwargs['json']
        self.assertEqual('text', payload['type'])
        self.assertEqual('Please call me back.', payload['text']['body'])

    def test_email_copy_does_not_mention_late_fees(self):
        installment = self.plan.installments.get(installment_number=1)
        with patch('notifications.services.requests.post', return_value=graph_response()):
            NotificationService.send_installment_reminder(installment)
        body = NotificationLog.objects.get(channel='email', notification_type='installment_reminder').message
        self.assertNotIn('late fee', body.lower())

    def test_overdue_email_copy_drops_the_late_fee_line(self):
        installment = self.plan.installments.get(installment_number=1)
        with patch('notifications.services.requests.post', return_value=graph_response()):
            NotificationService.send_overdue_payment_alert(installment)
        body = NotificationLog.objects.get(channel='email', notification_type='overdue_payment').message
        self.assertNotIn('Late Fee Applied', body)
        self.assertIn('Total Outstanding', body)


class WaSpecValidationTest(TestCase):
    """wa_templates.json must stay valid â€” Meta rejects malformed creates."""

    def test_the_shipped_spec_file_has_no_validation_errors(self):
        self.assertEqual([], validate_spec())

    def test_spec_declares_six_templates(self):
        self.assertEqual(6, len(wa_templates.templates()))

    def test_every_env_setting_is_one_send_typed_actually_reads(self):
        """A typo'd env_setting means that notification can never resolve a template."""
        for entry in wa_templates.templates():
            self.assertEqual(
                entry['env_setting'],
                WhatsAppService.TEMPLATE_SETTING_BY_TYPE.get(entry['notification_type']),
                f"{entry['notification_type']} has an env_setting send_typed() never reads",
            )

    def test_every_notification_type_is_unique(self):
        types = [e['notification_type'] for e in wa_templates.templates()]
        self.assertEqual(len(types), len(set(types)))

    def test_every_name_is_lowercase_alphanumeric_underscore(self):
        for entry in wa_templates.templates():
            self.assertRegex(entry['suggested_name'], r'^[a-z0-9_]+$')

    def test_every_category_and_sub_category_is_in_the_graph_enum(self):
        for entry in wa_templates.templates():
            self.assertIn(entry['category'], wa_templates.CATEGORIES)
            self.assertIn(entry.get('sub_category', ''), wa_templates.UTILITY_SUB_CATEGORIES)

    def test_every_sub_category_is_one_this_waba_actually_accepts(self):
        """BOOKING_STATUS is in Meta's docs but refused by this account."""
        for entry in wa_templates.templates():
            self.assertIn(
                entry.get('sub_category', ''), wa_templates.ACCEPTED_SUB_CATEGORIES,
                f"{entry['suggested_name']}: {entry.get('sub_category')} will be rejected by this WABA")

    def test_all_six_are_utility(self):
        """These are transactional. A MARKETING category would imply opt-in we never collected."""
        self.assertEqual(
            ['UTILITY'] * 6, [e['category'] for e in wa_templates.templates()])

    def test_body_placeholders_run_1_to_n_in_order(self):
        """Positional: {{1}}..{{N}} must line up with the declared parameter count."""
        for entry in wa_templates.templates():
            self.assertEqual(
                list(range(1, len(entry['parameters']) + 1)),
                wa_templates.body_indices(entry['body']),
                f"{entry['suggested_name']}: body indices do not match declared parameters",
            )

    def test_no_body_uses_named_placeholders(self):
        """A leftover {{customer_name}} would come back INVALID_FORMAT from Meta."""
        for entry in wa_templates.templates():
            # NAMED_RE, not \{\{(\w+)\}\}: \w matches digits, so it would flag
            # every legitimate {{1}} positional placeholder.
            self.assertEqual(
                [], wa_templates.NAMED_RE.findall(entry['body']),
                f"{entry['suggested_name']} still has named placeholders",
            )

    def test_parameter_order_is_the_declared_order(self):
        entry = next(e for e in wa_templates.templates()
                     if e['notification_type'] == 'overdue_payment')
        self.assertEqual(
            ['customer_name', 'installment_number', 'amount', 'due_date',
             'booking_id', 'outstanding'],
            wa_templates.parameter_order('overdue_payment'),
        )

    def test_parameter_order_is_empty_for_an_unknown_type(self):
        self.assertEqual([], wa_templates.parameter_order('not_a_real_type'))

    def test_template_name_comes_from_the_spec(self):
        """Hardcoding a name in a test broke when templates were renamed."""
        for entry in wa_templates.templates():
            self.assertEqual(
                entry['suggested_name'],
                wa_templates.template_name(entry['notification_type']),
            )

    def test_template_name_is_blank_for_an_unknown_type(self):
        self.assertEqual('', wa_templates.template_name('not_a_real_type'))

    def test_every_send_template_setting_resolves_to_a_real_template(self):
        """A setting pointing at a name the spec does not have sends nothing."""
        for notification_type, setting in WhatsAppService.TEMPLATE_SETTING_BY_TYPE.items():
            self.assertTrue(
                wa_templates.template_name(notification_type),
                f'{setting} has no template in the spec for {notification_type}',
            )

    def test_validation_flags_a_bad_name(self):
        entry = _entry(suggested_name='Samana Payment Received')
        self.assertIn('lowercase', ' '.join(validate_entry(entry)))

    def test_validation_flags_an_unknown_sub_category(self):
        entry = _entry(sub_category='ORDER_ISH')
        self.assertIn('ORDER_ISH', ' '.join(validate_entry(entry)))

    def test_validation_flags_a_documented_but_unaccepted_sub_category(self):
        """BOOKING_STATUS is valid per the docs and still fatal on this account."""
        errors = validate_entry(_entry(sub_category='BOOKING_STATUS'))
        self.assertTrue(any('not accepted by this WABA' in e for e in errors), errors)

    def test_validation_flags_named_placeholders_in_a_positional_template(self):
        entry = _entry(body='Dear {{customer_name}}, Rs {{amount}} is due.')
        errors = validate_entry(entry)
        self.assertTrue(any('named placeholders' in e for e in errors), errors)

    def test_validation_flags_a_gap_in_the_positional_indices(self):
        entry = _entry(body='Dear {{1}}, Rs {{3}} is due.')
        errors = validate_entry(entry)
        self.assertTrue(any('must be [1, 2]' in e for e in errors), errors)

    def test_validation_rejects_named_format_outright(self):
        entry = _entry(parameter_format='NAMED', body='Dear {{1}}, Rs {{2}} is due.')
        self.assertIn('only POSITIONAL', ' '.join(validate_entry(entry)))

    def test_validation_flags_a_sub_category_used_outside_utility(self):
        entry = _entry(category='MARKETING')
        self.assertTrue(any('sub_category' in e for e in validate_entry(entry)), validate_entry(entry))


class WaSpecPayloadTest(TestCase):
    """The POST body for POST /{waba}/message_templates."""

    def setUp(self):
        self.entry = next(e for e in wa_templates.templates()
                          if e['notification_type'] == 'installment_reminder')

    def test_payload_carries_the_graph_required_and_optional_fields(self):
        payload = wa_templates.build_payload(self.entry)
        self.assertEqual('samana_installment_due', payload['name'])
        self.assertEqual('en_US', payload['language'])
        self.assertEqual('UTILITY', payload['category'])
        self.assertEqual('ORDER_DETAILS', payload['sub_category'])
        self.assertEqual('POSITIONAL', payload['parameter_format'])
        self.assertIs(False, payload['allow_category_change'])

    def test_language_is_a_plain_string_on_create(self):
        """The send payload uses {code: ...}; the create payload uses a bare string."""
        self.assertIsInstance(wa_templates.build_payload(self.entry)['language'], str)

    def test_body_component_carries_the_text_and_examples(self):
        component = wa_templates.build_payload(self.entry)['components'][0]
        self.assertEqual('BODY', component['type'])
        self.assertEqual(self.entry['body'], component['text'])
        self.assertEqual(
            [[p['example'] for p in self.entry['parameters']]],
            component['example']['body_text'],
        )

    def test_examples_follow_declared_parameter_order(self):
        """Meta matches examples positionally to the {{placeholders}} in the body."""
        payload = wa_templates.build_payload(self.entry)
        self.assertEqual('Ahmed Khan', payload['components'][0]['example']['body_text'][0][0])

    def test_no_example_key_when_a_template_has_no_parameters(self):
        payload = wa_templates.build_payload(_entry(body='Hello', parameters=[]))
        self.assertNotIn('example', payload['components'][0])

    def test_build_payloads_returns_one_payload_per_template(self):
        self.assertEqual(6, len(wa_templates.build_payloads()))

    def test_defaults_can_be_overridden_per_call(self):
        payload = wa_templates.build_payload(self.entry, defaults={'allow_category_change': True})
        self.assertIs(True, payload['allow_category_change'])

    def test_build_payloads_can_narrow_to_one_name(self):
        payloads = wa_templates.build_payloads(only=['samana_receipt_ready'])
        self.assertEqual(['samana_receipt_ready'], [p['name'] for p in payloads])


@override_settings(**WA_ON, WHATSAPP_WABA_ID=WA_WABA)
class WhatsAppTemplateCreateTest(TestCase):
    """POST /{Version}/{WABA-ID}/message_templates"""

    def test_create_posts_to_the_waba_message_templates_edge(self):
        resp = waba_response({'id': '998877', 'status': 'PENDING', 'category': 'UTILITY'})
        with patch('notifications.services.requests.post', return_value=resp) as mock_post:
            ok, data, detail = WhatsAppService.create_template(create_payload())

        self.assertTrue(ok, detail)
        self.assertEqual('', detail)
        self.assertEqual('998877', data['id'])
        self.assertEqual('PENDING', data['status'])
        self.assertIn(f'/{WA_WABA}/message_templates', mock_post.call_args.args[0])
        self.assertIn('v25.0', mock_post.call_args.args[0])

    def test_create_sends_the_compiled_body_unchanged(self):
        payload = create_payload()
        with patch('notifications.services.requests.post',
                   return_value=waba_response({'id': '1', 'status': 'PENDING'})) as mock_post:
            WhatsAppService.create_template(payload)
        self.assertEqual(payload, mock_post.call_args.kwargs['json'])

    def test_create_without_waba_id_reports_the_setting_and_sends_nothing(self):
        with override_settings(WHATSAPP_WABA_ID=''), \
                patch('notifications.services.requests.post') as mock_post:
            ok, data, detail = WhatsAppService.create_template(create_payload())
        self.assertFalse(ok)
        self.assertIn('WHATSAPP_WABA_ID', detail)
        mock_post.assert_not_called()

    def test_create_surfaces_the_graph_rejection_body(self):
        """A 100 with an actionable message must not collapse to 'HTTP 400'."""
        resp = waba_response(
            {'error': {'message': 'Invalid parameter: name must contain only lowercase alphanumeric',
                       'type': 'OAuthException', 'code': 100}},
            status_code=400)
        with patch('notifications.services.requests.post', return_value=resp):
            ok, data, detail = WhatsAppService.create_template(create_payload())

        self.assertFalse(ok)
        self.assertIsNone(data)
        self.assertIn('100', detail)
        self.assertIn('lowercase', detail)

    def test_create_network_failure_returns_a_detail_instead_of_raising(self):
        with patch('notifications.services.requests.post', side_effect=Exception('connection reset')):
            ok, data, detail = WhatsAppService.create_template(create_payload())
        self.assertFalse(ok)
        self.assertIn('connection reset', detail)

    def test_create_non_json_response_is_reported_not_raised(self):
        resp = Mock()
        resp.status_code = 502
        resp.json.side_effect = ValueError('Expecting value')
        with patch('notifications.services.requests.post', return_value=resp):
            ok, data, detail = WhatsAppService.create_template(create_payload())
        self.assertFalse(ok)
        self.assertIn('502', detail)

    def test_create_does_not_require_the_channel_to_be_enabled(self):
        """Provisioning must work while WHATSAPP_ENABLED=False, so the live path stays inert."""
        with override_settings(WHATSAPP_ENABLED=False), \
                patch('notifications.services.requests.post',
                      return_value=waba_response({'id': '1', 'status': 'PENDING'})) as mock_post:
            ok, data, detail = WhatsAppService.create_template(create_payload())
        self.assertTrue(ok, detail)
        mock_post.assert_called_once()


@override_settings(**WA_ON, WHATSAPP_WABA_ID=WA_WABA)
class WhatsAppTemplateListTest(TestCase):
    """GET /{Version}/{WABA-ID}/message_templates"""

    def test_list_returns_the_template_rows(self):
        resp = waba_response({'data': [
            {'id': '1', 'name': 'samana_installment_due', 'status': 'APPROVED',
             'category': 'UTILITY', 'quality_score': {'score': 'GREEN'}},
        ]})
        with patch('notifications.services.requests.get', return_value=resp):
            ok, rows, detail = WhatsAppService.list_templates()

        self.assertTrue(ok, detail)
        self.assertEqual('samana_installment_due', rows[0]['name'])
        self.assertEqual('APPROVED', rows[0]['status'])

    def test_list_requests_the_fields_the_audit_needs(self):
        with patch('notifications.services.requests.get',
                   return_value=waba_response({'data': []})) as mock_get:
            WhatsAppService.list_templates()

        self.assertIn(f'/{WA_WABA}/message_templates', mock_get.call_args.args[0])
        fields = mock_get.call_args.kwargs['params']['fields'].split(',')
        for field in ('status', 'rejected_reason', 'quality_score', 'category', 'sub_category', 'language'):
            self.assertIn(field, fields)

    def test_list_returns_empty_rows_when_the_waba_has_no_templates(self):
        with patch('notifications.services.requests.get', return_value=waba_response({'data': []})):
            ok, rows, detail = WhatsAppService.list_templates()
        self.assertTrue(ok, detail)
        self.assertEqual([], rows)

    def test_list_error_reports_rather_than_returning_rows(self):
        resp = waba_response(
            {'error': {'message': 'Insufficient permissions to access templates',
                       'type': 'OAuthException', 'code': 200}}, status_code=403)
        with patch('notifications.services.requests.get', return_value=resp):
            ok, rows, detail = WhatsAppService.list_templates()
        self.assertFalse(ok)
        self.assertEqual([], rows)
        self.assertIn('200', detail)
        self.assertIn('Insufficient permissions', detail)

