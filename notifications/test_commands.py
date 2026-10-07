"""Tests for the two WhatsApp template provisioning commands.

These call the commands directly with a StringIO, so they assert on real
command output rather than a mocked one.
"""
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from . import wa_templates
from .services import WhatsAppService

WA_ON = {
    'WHATSAPP_ENABLED': True,
    'WHATSAPP_API_TOKEN': 'test-token',
    'WHATSAPP_PHONE_NUMBER_ID': '1276551565544996',
    'WHATSAPP_API_VERSION': 'v25.0',
    'WHATSAPP_WABA_ID': '109876543210',
    # Nothing wired by default. check_wa_templates exists to answer "is this
    # template wired into .env?", so leaving the answer to ambient .env state
    # made the tests pass or fail depending on the developer's machine. The one
    # test that wants them wired passes its own values.
    **{e['env_setting']: '' for e in wa_templates.templates()},
}

APPROVED_ROW = {
    'id': '1', 'name': 'samana_installment_due', 'language': 'en_US',
    'category': 'UTILITY', 'sub_category': 'ORDER_DETAILS', 'status': 'APPROVED',
    'parameter_format': 'POSITIONAL', 'quality_score': {'score': 'GREEN'},
    'rejected_reason': '', 'health_status': {'can_send_message': 'YES'},
}


class FakeGraph:
    """Stands in for `requests`, recording POSTs and serving canned GETs."""

    def __init__(self, create_payload=None, create_status=200, list_payload=None, list_status=200):
        self.create_payload = create_payload or {'id': '1', 'status': 'PENDING', 'category': 'UTILITY'}
        self.create_status = create_status
        self.list_payload = list_payload if list_payload is not None else {'data': []}
        self.list_status = list_status
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _resp(self.create_payload, self.create_status)

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return _resp(self.list_payload, self.list_status)

    def sent_names(self):
        return [kwargs.get('json', {}).get('name') for _, kwargs in self.posts]


def _resp(payload, status_code=200):
    from unittest.mock import Mock
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def run(command, *argv, graph=None, **env):
    """Call a management command, capturing output and any CommandError."""
    graph = graph or FakeGraph()
    out = StringIO()
    err = StringIO()
    error = None
    try:
        with override_settings(**env), \
                patch('notifications.services.requests.post', graph.post), \
                patch('notifications.services.requests.get', graph.get):
            call_command(command, *argv, stdout=out, stderr=err)
    except CommandError as e:
        error = e
    return error, out.getvalue() + err.getvalue(), graph


class CreateWaTemplatesTest(TestCase):
    def test_creates_all_six_by_default(self):
        error, output, graph = run('create_wa_templates', **WA_ON)
        self.assertIsNone(error)
        self.assertEqual(6, len(graph.posts))
        self.assertIn('Created 6, failed 0 of 6', output)

    def test_creation_is_possible_while_the_channel_is_disabled(self):
        """Provisioning must not require turning the live send path on."""
        env = {**WA_ON, 'WHATSAPP_ENABLED': False}
        error, output, graph = run('create_wa_templates', **env)
        self.assertIsNone(error)
        self.assertEqual(6, len(graph.posts))

    def test_dry_run_makes_no_calls_and_prints_the_real_bodies(self):
        error, output, graph = run('create_wa_templates', '--dry-run', **WA_ON)
        self.assertIsNone(error)
        self.assertEqual([], graph.posts)
        self.assertIn('samana_installment_due', output)
        self.assertIn('ORDER_DETAILS', output)
        self.assertIn('No calls made', output)

    def test_dry_run_prints_one_parseable_json_line_per_template(self):
        error, output, graph = run('create_wa_templates', '--dry-run', **WA_ON)
        bodies = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
        self.assertEqual(6, len(bodies))
        self.assertEqual(
            {e['suggested_name'] for e in wa_templates.templates()},
            {b['name'] for b in bodies},
        )

    def test_dry_run_shows_each_positional_parameter_example(self):
        error, output, graph = run('create_wa_templates', '--dry-run', '--only',
                                   'samana_installment_due', **WA_ON)
        self.assertIsNone(error)
        self.assertIn('{{1}} customer_name = Ahmed Khan', output)
        self.assertIn('{{5}} booking_id = BKG-00001', output)

    def test_payloads_are_positional_with_doubly_nested_examples(self):
        """The flat and single-nested example shapes are both refused by Meta."""
        for payload in wa_templates.build_payloads():
            self.assertEqual('POSITIONAL', payload['parameter_format'])
            body_text = payload['components'][0]['example']['body_text']
            self.assertIsInstance(body_text, list)
            self.assertIsInstance(body_text[0], list)
            self.assertEqual(
                len(payload['components'][0]['example']['body_text'][0]),
                len([i for i in wa_templates.body_indices(payload['components'][0]['text'])]),
            )

    def test_only_narrows_the_run(self):
        error, output, graph = run(
            'create_wa_templates', '--only', 'samana_receipt_ready', **WA_ON)
        self.assertIsNone(error)
        self.assertEqual(['samana_receipt_ready'], graph.sent_names())

    def test_unknown_only_name_fails_and_lists_the_valid_ones(self):
        error, output, graph = run('create_wa_templates', '--only', 'nope', **WA_ON)
        self.assertIsInstance(error, CommandError)
        self.assertIn('No templates matched', str(error))
        self.assertIn('samana_installment_due', str(error))
        self.assertEqual([], graph.posts)

    def test_missing_waba_id_fails_before_any_call(self):
        env = {**WA_ON, 'WHATSAPP_WABA_ID': ''}
        error, output, graph = run('create_wa_templates', **env)
        self.assertIsInstance(error, CommandError)
        self.assertIn('WHATSAPP_WABA_ID', str(error))
        self.assertEqual([], graph.posts)

    def test_partial_failure_reports_each_and_exits_nonzero(self):
        graph = FakeGraph(
            create_payload={'error': {'message': 'Invalid parameter', 'code': 100}},
            create_status=400)
        error, output, graph = run('create_wa_templates', **WA_ON, graph=graph)
        self.assertIsInstance(error, CommandError)
        self.assertEqual(6, len(graph.posts))
        self.assertIn('Created 0, failed 6 of 6', output)
        self.assertIn('Invalid parameter', output)

    def test_output_names_the_status_and_id_of_each_created_template(self):
        error, output, graph = run('create_wa_templates', '--only', 'samana_receipt_ready', **WA_ON)
        self.assertIn('samana_receipt_ready', output)
        self.assertIn('PENDING', output)

    def test_points_the_operator_at_the_check_command(self):
        error, output, graph = run('create_wa_templates', '--only', 'samana_receipt_ready', **WA_ON)
        self.assertIn('check_wa_templates', output)


class CheckWaTemplatesTest(TestCase):
    def rows(self, *statuses, **extra):
        rows = []
        for i, status in enumerate(statuses):
            row = {**APPROVED_ROW, 'status': status, 'id': str(i)}
            row.update(extra)
            rows.append(row)
        return {'data': rows}

    def test_reports_status_language_and_quality_per_template(self):
        graph = FakeGraph(list_payload=self.rows('APPROVED'))
        error, output, graph = run('check_wa_templates', graph=graph, **WA_ON)
        self.assertIsNone(error)
        self.assertIn('samana_payment_received', output)
        self.assertIn('APPROVED', output)
        self.assertIn('en_US', output)
        self.assertIn('GREEN', output)

    def test_missing_waba_id_fails_clearly(self):
        error, output, graph = run('check_wa_templates', **{**WA_ON, 'WHATSAPP_WABA_ID': ''})
        self.assertIsInstance(error, CommandError)
        self.assertIn('WHATSAPP_WABA_ID', str(error))
        self.assertEqual([], graph.gets)

    def test_permission_error_is_surfaced(self):
        graph = FakeGraph(
            list_payload={'error': {'message': 'Insufficient permissions to access templates', 'code': 200}},
            list_status=403)
        error, output, graph = run('check_wa_templates', graph=graph, **WA_ON)
        self.assertIsInstance(error, CommandError)
        self.assertIn('Insufficient permissions', str(error))

    def test_empty_waba_tells_the_operator_to_create_templates(self):
        error, output, graph = run('check_wa_templates', **WA_ON)
        self.assertIsNone(error)
        self.assertIn('No templates on this WABA', output)
        self.assertIn('create_wa_templates', output)

    def test_rejection_reason_is_printed_with_advice(self):
        graph = FakeGraph(list_payload=self.rows(
            'REJECTED', rejected_reason='TAG_CONTENT_MISMATCH'))
        error, output, graph = run('check_wa_templates', graph=graph, **WA_ON)
        self.assertIsNone(error)
        self.assertIn('REJECTED', output)
        self.assertIn('TAG_CONTENT_MISMATCH', output)
        self.assertIn('Drop sub_category', output)

    def test_promotional_rejection_gets_copy_advice(self):
        graph = FakeGraph(list_payload=self.rows('REJECTED', rejected_reason='PROMOTIONAL'))
        error, output, graph = run('check_wa_templates', graph=graph, **WA_ON)
        self.assertIsNone(error)
        self.assertIn('Read as marketing', output)

    def test_approved_template_with_no_reason_prints_no_advice(self):
        graph = FakeGraph(list_payload=self.rows('APPROVED'))
        error, output, graph = run('check_wa_templates', graph=graph, **WA_ON)
        self.assertNotIn('rejected_reason', output)

    def test_flags_a_template_missing_from_the_waba(self):
        graph = FakeGraph(list_payload=self.rows('APPROVED'))
        error, output, graph = run('check_wa_templates', graph=graph, **WA_ON)
        self.assertIn('not on the WABA', output)

    def test_flags_templates_created_but_not_wired_into_env(self):
        """The WABA name is worthless unless send_typed() can resolve it."""
        graph = FakeGraph(list_payload={'data': [
            {**APPROVED_ROW, 'name': e['suggested_name']} for e in wa_templates.templates()
        ]})
        error, output, graph = run('check_wa_templates', graph=graph, **WA_ON)
        self.assertIn('not wired into .env', output)
        self.assertIn('WHATSAPP_TEMPLATE_PAYMENT_CONFIRMATION', output)

    def test_confirms_everything_wired_when_env_matches(self):
        graph = FakeGraph(list_payload={'data': [
            {**APPROVED_ROW, 'name': e['suggested_name']} for e in wa_templates.templates()
        ]})
        env = {**WA_ON, **{
            e['env_setting']: e['suggested_name'] for e in wa_templates.templates()
        }}
        error, output, graph = run('check_wa_templates', graph=graph, **env)
        self.assertIsNone(error)
        self.assertIn('wired to .env', output)
        self.assertNotIn('not on the WABA', output)

    def test_pending_is_shown_without_being_called_a_failure(self):
        graph = FakeGraph(list_payload=self.rows('PENDING'))
        error, output, graph = run('check_wa_templates', graph=graph, **WA_ON)
        self.assertIsNone(error)
        self.assertIn('PENDING', output)


class SpecToServiceConsistencyTest(TestCase):
    """The spec file and the send path must not drift apart."""

    def test_every_template_in_the_spec_is_sendable_by_send_typed(self):
        for entry in wa_templates.templates():
            self.assertIn(entry['notification_type'], WhatsAppService.TEMPLATE_SETTING_BY_TYPE)

    def test_send_typed_setting_names_match_the_spec_env_settings(self):
        spec = {e['notification_type']: e['env_setting'] for e in wa_templates.templates()}
        self.assertEqual(spec, WhatsAppService.TEMPLATE_SETTING_BY_TYPE)

    def test_no_duplicate_suggested_names(self):
        names = [e['suggested_name'] for e in wa_templates.templates()]
        self.assertEqual(len(names), len(set(names)))

    def test_the_waba_is_not_required_to_send_messages(self):
        """WABA id is provisioning-only; sends must keep working without it."""
        env = {**WA_ON, 'WHATSAPP_WABA_ID': ''}
        with override_settings(**env):
            self.assertEqual('', WhatsAppService._templates_url())