"""Tests for the AI feature layer (LangChain + OpenRouter).

The OpenRouter provider call is mocked so the suite never touches the network.
The AiDisabledError path is tested with AI_ENABLED=False.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking, InstallmentPlan
from core.forms import CompanySettingsForm
from core.models import CompanySettings, UserProfile, Lead
from customers.models import Customer
from properties.models import Plot, Project

from .models import AiInteractionLog


class AiServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.project = Project.objects.create(name='AI Project', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='AI-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('5000000'),
        )
        self.customer = Customer.objects.create(
            first_name='Ai', last_name='Customer', phone='+92-300-1112222',
            cnic='35202-1212121-1',
        )
        self.lead = Lead.objects.create(
            name='Ai Lead', phone='+92-300-3334444', budget=Decimal('5000000'),
            source='agent', status='new',
        )

    @override_settings(AI_ENABLED=False)
    def test_disabled_raises_and_logs(self):
        from .services import AiDisabledError, ask_assistant
        with self.assertRaises(AiDisabledError):
            ask_assistant('hi')
        self.assertEqual(
            AiInteractionLog.objects.filter(status='disabled').count(), 1)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_assistant_returns_content(self):
        from .services import ask_assistant
        mock_llm = type('FakeLLM', (), {'invoke': staticmethod(
            lambda msgs: type('R', (), {'content': 'AI answer'})())})()
        with patch('ai.services._llm', return_value=mock_llm):
            out = ask_assistant('question?', user=self.user)
        self.assertEqual(out, 'AI answer')
        log = AiInteractionLog.objects.get(feature='assistant')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.user, self.user)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_lead_score_parses_json(self):
        from .services import score_lead
        mock_llm = type('FakeLLM', (), {'invoke': staticmethod(
            lambda msgs: type('R', (), {
                'content': '{"score": 80, "tier": "hot", "reason": "High budget, agent source."}'
            })())})()
        with patch('ai.services._llm', return_value=mock_llm):
            out = score_lead(self.lead, user=self.user)
        self.assertEqual(out['score'], 80)
        self.assertEqual(out['tier'], 'hot')

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_lead_score_handles_bad_json(self):
        from .services import score_lead
        mock_llm = type('FakeLLM', (), {'invoke': staticmethod(
            lambda msgs: type('R', (), {'content': 'not json at all'})())})()
        with patch('ai.services._llm', return_value=mock_llm):
            out = score_lead(self.lead)
        self.assertEqual(out['score'], None)
        self.assertEqual(out['tier'], 'unknown')

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_failed_call_logs_error(self):
        from .services import ask_assistant
        def boom(msgs):
            raise RuntimeError('provider down')
        mock_llm = type('FakeLLM', (), {'invoke': staticmethod(boom)})()
        with patch('ai.services._llm', return_value=mock_llm):
            with self.assertRaises(RuntimeError):
                ask_assistant('hi')
        log = AiInteractionLog.objects.get(feature='assistant')
        self.assertEqual(log.status, 'failed')
        self.assertIn('provider down', log.error_message)


class AiApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.client.force_authenticate(user=self.admin)
        self.project = Project.objects.create(name='API AI Project', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='API-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('5000000'),
        )
        self.customer = Customer.objects.create(
            first_name='Api', last_name='Customer', phone='+92-300-2223333',
            cnic='35202-2121212-2',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('5000000'),
            advance_paid=Decimal('1000000'), status='active', created_by=self.admin,
        )
        self.plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=2, installment_amount=Decimal('1000000'),
            down_payment_amount=Decimal('1000000'), start_date=date.today(), frequency='monthly',
        )
        self.plan.auto_generate()
        self.installment = self.plan.installments.first()

    def _mock_llm(self, content='AI response'):
        mock_llm = type('FakeLLM', (), {'invoke': staticmethod(
            lambda msgs: type('R', (), {'content': content})())})()
        return patch('ai.services._llm', return_value=mock_llm)

    def test_health_reports_config(self):
        resp = self.client.get(reverse('ai_health'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('ai_enabled', resp.data)

    def test_assistant_requires_question(self):
        resp = self.client.post(reverse('ai_assistant'), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assistant_disabled_returns_503(self):
        with override_settings(AI_ENABLED=False):
            resp = self.client.post(reverse('ai_assistant'), {'question': 'hi'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(resp.data['ok'])

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_assistant_success(self):
        with self._mock_llm('Total revenue is Rs. 5,000,000.'):
            resp = self.client.post(reverse('ai_assistant'), {'question': 'Revenue?'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])
        self.assertEqual(resp.data['result'], 'Total revenue is Rs. 5,000,000.')

    def _mock_llm_capture(self):
        """Mock that records the system prompt sent to the LLM."""
        captured = {}

        def fake_invoke(messages):
            for m in messages:
                if getattr(m, 'type', '') == 'system':
                    captured['system'] = m.content
            return type('R', (), {'content': 'Reply'})()
        mock_llm = type('FakeLLM', (), {'invoke': staticmethod(fake_invoke)})()
        return patch('ai.services._llm', return_value=mock_llm), captured

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_assistant_default_language_is_english(self):
        obj = CompanySettings.load()
        obj.ai_language = 'english'
        obj.save()
        patcher, captured = self._mock_llm_capture()
        with patcher:
            resp = self.client.post(reverse('ai_assistant'), {'question': 'Revenue?'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('Respond in clear English.', captured.get('system', ''))

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_assistant_roman_urdu_language_instruction(self):
        obj = CompanySettings.load()
        obj.ai_language = 'roman_urdu'
        obj.save()
        patcher, captured = self._mock_llm_capture()
        with patcher:
            resp = self.client.post(reverse('ai_assistant'), {'question': 'Revenue?'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('ROMAN URDU', captured.get('system', ''))
        # reset for other tests
        obj = CompanySettings.load()
        obj.ai_language = 'english'
        obj.save()

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_insights_honors_roman_urdu_language_setting(self):
        obj = CompanySettings.load()
        obj.ai_language = 'roman_urdu'
        obj.save()
        patcher, captured = self._mock_llm_capture()
        with patcher:
            resp = self.client.get(reverse('ai_insights'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('ROMAN URDU', captured.get('system', ''))
        obj = CompanySettings.load()
        obj.ai_language = 'english'
        obj.save()

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_insights_focus_honors_roman_urdu_language_setting(self):
        obj = CompanySettings.load()
        obj.ai_language = 'roman_urdu'
        obj.save()
        patcher, captured = self._mock_llm_capture()
        with patcher:
            resp = self.client.get(reverse('ai_insights'), {'focus': 'inventory'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('ROMAN URDU', captured.get('system', ''))
        obj = CompanySettings.load()
        obj.ai_language = 'english'
        obj.save()

    def test_company_settings_form_persists_ai_language(self):
        settings_obj = CompanySettings.load()
        form = CompanySettingsForm(
            data={'company_name': 'Samana Builders & Developers',
                  'currency': 'PKR', 'currency_symbol': 'Rs.',
                  'tax_rate': '0', 'ai_language': 'roman_urdu'},
            instance=settings_obj,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        settings_obj.refresh_from_db()
        self.assertEqual(settings_obj.ai_language, 'roman_urdu')
        obj = CompanySettings.load()
        obj.ai_language = 'english'
        obj.save()

    def test_language_endpoint_get_returns_current(self):
        obj = CompanySettings.load()
        obj.ai_language = 'english'
        obj.save()
        resp = self.client.get(reverse('ai_language'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['language'], 'english')

    def test_language_endpoint_post_admin_updates_global(self):
        resp = self.client.post(reverse('ai_language'), {'language': 'roman_urdu'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])
        self.assertEqual(CompanySettings.load().ai_language, 'roman_urdu')
        obj = CompanySettings.load()
        obj.ai_language = 'english'
        obj.save()

    def test_language_endpoint_post_invalid_rejected(self):
        resp = self.client.post(reverse('ai_language'), {'language': 'french'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CompanySettings.load().ai_language, 'english')

    def test_language_endpoint_post_non_admin_denied(self):
        sales = User.objects.create_user('sales2', 's2@example.com', 'salespass123')
        UserProfile.objects.create(user=sales, role='sales')
        self.client.force_authenticate(user=sales)
        resp = self.client.post(reverse('ai_language'), {'language': 'roman_urdu'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(CompanySettings.load().ai_language, 'english')

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_lead_score_success(self):
        lead = Lead.objects.create(name='Scored', phone='+92-300-5556666')
        with self._mock_llm('{"score": 70, "tier": "warm", "reason": "Engaged."}'):
            resp = self.client.post(reverse('ai_lead_score'), {'lead_id': lead.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['result']['tier'], 'warm')

    def test_lead_score_missing_lead(self):
        resp = self.client.post(reverse('ai_lead_score'), {'lead_id': 99999}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_property_description_success(self):
        with self._mock_llm('Beautiful 5 marla plot in Lahore.'):
            resp = self.client.post(
                reverse('ai_property_description'), {'plot_id': self.plot.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    def test_property_description_missing_plot(self):
        resp = self.client.post(
            reverse('ai_property_description'), {'plot_id': 99999}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_reminder_draft_success(self):
        with self._mock_llm('Dear customer, installment #1 is due.'):
            resp = self.client.post(
                reverse('ai_reminder_draft'), {'installment_id': self.installment.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    def test_reminder_draft_missing_installment(self):
        resp = self.client.post(
            reverse('ai_reminder_draft'), {'installment_id': 99999}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_insights_finance_role_allowed(self):
        with self._mock_llm('Collections are healthy.'):
            resp = self.client.get(reverse('ai_insights'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_insights_focus_param_passes_through(self):
        with self._mock_llm('Inventory focus analysis.'):
            resp = self.client.get(reverse('ai_insights'), {'focus': 'inventory'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_insights_invalid_focus_rejected(self):
        resp = self.client.get(reverse('ai_insights'), {'focus': 'bogus'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_insights_hr_focus_uses_hr_context(self):
        with self._mock_llm('Workforce analysis.'):
            resp = self.client.get(reverse('ai_insights'), {'focus': 'hr'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_insights_sales_role_denied(self):
        sales = User.objects.create_user('sales', 's@example.com', 'salespass123')
        UserProfile.objects.create(user=sales, role='sales')
        self.client.force_authenticate(user=sales)
        resp = self.client.get(reverse('ai_insights'))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_ai_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(reverse('ai_health'))
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


# ─── HR AI FEATURES ──────────────────────────────────────────────────────────
class HrAiApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.client.force_authenticate(user=self.admin)
        from hr.models import Department, Designation, Employee, Leave, PayrollRun, SalaryComponent, EmployeeSalary
        from datetime import date
        self.dept = Department.objects.create(name='Sales')
        self.designation = Designation.objects.create(title='Sales Executive')
        self.emp = Employee.objects.create(
            first_name='HR', last_name='Employee', department=self.dept,
            designation=self.designation, joining_date=date(2024, 1, 1),
            cnic='35202-1231231-1', phone='+92-300-1231231',
        )
        self.leave = Leave.objects.create(
            employee=self.emp, leave_type='annual',
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 3), days=3,
            reason='Family trip', status='pending',
        )
        self.run = PayrollRun.objects.create(month=8, year=2026, status='processed')
        comp = SalaryComponent.objects.create(name='Basic', component_type='earning')
        EmployeeSalary.objects.create(employee=self.emp, component=comp, amount=Decimal('100000'))
        self.run.generate_slips()

    def _mock_llm(self, content='AI response'):
        mock_llm = type('FakeLLM', (), {'invoke': staticmethod(
            lambda msgs: type('R', (), {'content': content})())})()
        return patch('ai.services._llm', return_value=mock_llm)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_hr_assistant_success(self):
        with self._mock_llm('You have 1 active employee.'):
            resp = self.client.post(reverse('ai_hr_assistant'), {'question': 'Headcount?'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])
        self.assertEqual(resp.data['result'], 'You have 1 active employee.')

    def test_hr_assistant_requires_question(self):
        resp = self.client.post(reverse('ai_hr_assistant'), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_hr_assistant_denied_for_sales_role(self):
        sales = User.objects.create_user('saleshr', 's@example.com', 'salespass123')
        UserProfile.objects.create(user=sales, role='sales')
        self.client.force_authenticate(user=sales)
        resp = self.client.post(reverse('ai_hr_assistant'), {'question': 'Hi'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_leave_review_success(self):
        with self._mock_llm('Your leave is approved.'):
            resp = self.client.post(reverse('ai_leave_review'), {
                'leave_id': self.leave.pk, 'decision': 'approve'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    def test_leave_review_invalid_decision(self):
        resp = self.client.post(reverse('ai_leave_review'), {
            'leave_id': self.leave.pk, 'decision': 'maybe'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_leave_review_missing_leave(self):
        resp = self.client.post(reverse('ai_leave_review'), {
            'leave_id': 99999, 'decision': 'approve'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_payroll_insights_success(self):
        with self._mock_llm('Payroll looks healthy.'):
            resp = self.client.post(reverse('ai_payroll_insights'), {
                'payroll_run_id': self.run.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    def test_payroll_insights_missing_run(self):
        resp = self.client.post(reverse('ai_payroll_insights'), {'payroll_run_id': 99999}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_attendance_insights_success(self):
        with self._mock_llm('Attendance rate is 95%.'):
            resp = self.client.post(reverse('ai_attendance_insights'), {
                'month': 8, 'year': 2026}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    def test_attendance_insights_bad_month(self):
        resp = self.client.post(reverse('ai_attendance_insights'), {
            'month': 13, 'year': 2026}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_attendance_insights_bad_type(self):
        resp = self.client.post(reverse('ai_attendance_insights'), {
            'month': 'abc', 'year': 2026}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_job_description_success(self):
        with self._mock_llm('Job Description for Sales Executive.'):
            resp = self.client.post(reverse('ai_job_description'), {
                'designation': 'Sales Executive', 'department': 'Sales'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['ok'])

    def test_job_description_empty_ok(self):
        with override_settings(AI_ENABLED=False):
            resp = self.client.post(reverse('ai_job_description'), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @override_settings(AI_ENABLED=True, OPENROUTER_API_KEY='test-key')
    def test_hr_assistant_disabled_503(self):
        with override_settings(AI_ENABLED=False):
            resp = self.client.post(reverse('ai_hr_assistant'), {'question': 'Hi'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
