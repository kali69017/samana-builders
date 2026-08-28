"""AI feature API endpoints.

All endpoints return a consistent envelope:
    {"ok": true, "result": ...}           on success
    {"ok": false, "error": "..."}         when AI is disabled or the call failed

Auth: any authenticated staff user can call the assistant; lead scoring,
property description and reminder drafting need at least an authenticated
user; insights are restricted to finance/management roles.
"""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Installment
from core.models import Lead
from core.permissions import get_user_role
from hr.models import Department, Designation, Leave, PayrollRun
from properties.models import Plot

from .services import (
    AiDisabledError, analyze_attendance, analyze_payroll, ask_assistant,
    ask_hr_assistant, draft_leave_review, draft_reminder, generate_insights,
    generate_job_description, generate_property_description, score_lead,
)


FINANCE_ROLES = ('super_admin', 'admin', 'management', 'accounts')
HR_ROLES = ('super_admin', 'admin', 'management', 'hr')
PAYROLL_ROLES = ('super_admin', 'admin', 'management', 'hr', 'accounts')


def _handle(exc):
    return Response({'ok': False, 'error': str(exc)},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE)


class AssistantView(APIView):
    """POST /api/ai/assistant/  {"question": "..."}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        question = (request.data.get('question') or '').strip()
        if not question:
            return Response({'ok': False, 'error': 'question is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            answer = ask_assistant(question, user=request.user)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': answer})


class LeadScoreView(APIView):
    """POST /api/ai/lead-score/  {"lead_id": N}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        lead_id = request.data.get('lead_id')
        if not lead_id:
            return Response({'ok': False, 'error': 'lead_id is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            lead = Lead.objects.get(pk=lead_id)
        except (Lead.DoesNotExist, ValueError, TypeError):
            return Response({'ok': False, 'error': 'Lead not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            result = score_lead(lead, user=request.user)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': result})


class PropertyDescriptionView(APIView):
    """POST /api/ai/property-description/  {"plot_id": N}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        plot_id = request.data.get('plot_id')
        if not plot_id:
            return Response({'ok': False, 'error': 'plot_id is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            plot = Plot.objects.select_related('project', 'phase').get(pk=plot_id)
        except (Plot.DoesNotExist, ValueError, TypeError):
            return Response({'ok': False, 'error': 'Plot not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            description = generate_property_description(plot, user=request.user)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': description})


class ReminderDraftView(APIView):
    """POST /api/ai/reminder-draft/  {"installment_id": N}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        installment_id = request.data.get('installment_id')
        if not installment_id:
            return Response({'ok': False, 'error': 'installment_id is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            installment = Installment.objects.select_related(
                'plan__booking__customer', 'plan__booking__plot__project'
            ).get(pk=installment_id)
        except (Installment.DoesNotExist, ValueError, TypeError):
            return Response({'ok': False, 'error': 'Installment not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            message = draft_reminder(installment, user=request.user)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': message})


class InsightsView(APIView):
    """GET /api/ai/insights/?focus=revenue|collections|inventory|hr — finance/management only"""

    ALLOWED_FOCUS = ('revenue', 'collections', 'inventory', 'hr')

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        role = get_user_role(request)
        if request.user.is_superuser:
            role = 'super_admin'
        if role not in FINANCE_ROLES:
            return Response({'ok': False, 'error': 'Insufficient permissions.'},
                            status=status.HTTP_403_FORBIDDEN)
        focus = (request.query_params.get('focus') or '').strip().lower()
        if focus and focus not in self.ALLOWED_FOCUS:
            return Response({'ok': False, 'error': f'focus must be one of: {", ".join(self.ALLOWED_FOCUS)}'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            insights = generate_insights(user=request.user, focus=focus or None)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': insights})


class HealthView(APIView):
    """GET /api/ai/health/ — is the AI layer configured?"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.conf import settings
        return Response({
            'ai_enabled': bool(getattr(settings, 'AI_ENABLED', False)),
            'api_key_configured': bool(getattr(settings, 'DEEPSEEK_API_KEY', '')),
            'model': getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-chat'),
        })


class LanguageView(APIView):
    """GET/POST /api/ai/language/ — global assistant language (admin only).

    GET returns the current language; POST {'language': 'english'|'roman_urdu'}
    updates the global CompanySettings preference.
    """

    ALLOWED_LANGUAGES = ('english', 'roman_urdu')

    permission_classes = [permissions.IsAuthenticated]

    def _deny(self):
        return Response({'ok': False, 'error': 'Insufficient permissions.'},
                        status=status.HTTP_403_FORBIDDEN)

    def get(self, request):
        from core.models import CompanySettings
        return Response({'ok': True, 'language': CompanySettings.load().ai_language})

    def post(self, request):
        from core.models import CompanySettings
        from core.permissions import ADMIN_ROLES
        role = _role(request)
        if role not in ADMIN_ROLES:
            return self._deny()
        language = (request.data.get('language') or '').strip().lower()
        if language not in self.ALLOWED_LANGUAGES:
            return Response(
                {'ok': False, 'error': f'language must be one of: {", ".join(self.ALLOWED_LANGUAGES)}'},
                status=status.HTTP_400_BAD_REQUEST)
        obj = CompanySettings.load()
        obj.ai_language = language
        obj.save()
        return Response({'ok': True, 'language': obj.ai_language})


# ─── HR AI FEATURES ──────────────────────────────────────────────────────────

def _role(request):
    if request.user.is_superuser:
        return 'super_admin'
    return get_user_role(request)


def _deny_if_not_in(request, roles):
    if _role(request) not in roles:
        return Response({'ok': False, 'error': 'Insufficient permissions.'},
                        status=status.HTTP_403_FORBIDDEN)
    return None


class HrAssistantView(APIView):
    """POST /api/ai/hr/assistant/  {"question": "..."} — HR staff only"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        denied = _deny_if_not_in(request, HR_ROLES)
        if denied:
            return denied
        question = (request.data.get('question') or '').strip()
        if not question:
            return Response({'ok': False, 'error': 'question is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            answer = ask_hr_assistant(question, user=request.user)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': answer})


class LeaveReviewView(APIView):
    """POST /api/ai/hr/leave-review/  {"leave_id": N, "decision": "approve"|"reject"}"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        denied = _deny_if_not_in(request, HR_ROLES)
        if denied:
            return denied
        leave_id = request.data.get('leave_id')
        decision = (request.data.get('decision') or '').strip().lower()
        if not leave_id:
            return Response({'ok': False, 'error': 'leave_id is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if decision not in ('approve', 'reject'):
            return Response({'ok': False, 'error': "decision must be 'approve' or 'reject'."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            leave = Leave.objects.select_related('employee').get(pk=leave_id)
        except (Leave.DoesNotExist, ValueError, TypeError):
            return Response({'ok': False, 'error': 'Leave request not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            message = draft_leave_review(leave, decision, user=request.user)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': message})


class PayrollInsightsView(APIView):
    """POST /api/ai/hr/payroll/  {"payroll_run_id": N} — payroll roles only"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        denied = _deny_if_not_in(request, PAYROLL_ROLES)
        if denied:
            return denied
        run_id = request.data.get('payroll_run_id')
        if not run_id:
            return Response({'ok': False, 'error': 'payroll_run_id is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            run = PayrollRun.objects.get(pk=run_id)
        except (PayrollRun.DoesNotExist, ValueError, TypeError):
            return Response({'ok': False, 'error': 'Payroll run not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            result = analyze_payroll(run, user=request.user)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': result})


class AttendanceInsightsView(APIView):
    """POST /api/ai/hr/attendance/  {"month": 1-12, "year": 2026} — HR roles only"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        denied = _deny_if_not_in(request, HR_ROLES)
        if denied:
            return denied
        try:
            month = int(request.data.get('month', 0)) or None
            year = int(request.data.get('year', 0)) or None
        except (ValueError, TypeError):
            return Response({'ok': False, 'error': 'month and year must be integers.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if month is not None and not 1 <= month <= 12:
            return Response({'ok': False, 'error': 'month must be between 1 and 12.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            result = analyze_attendance(month=month, year=year, user=request.user)
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': result})


class JobDescriptionView(APIView):
    """POST /api/ai/hr/job-description/  {"designation": str, "department": str} — HR roles only"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        denied = _deny_if_not_in(request, HR_ROLES)
        if denied:
            return denied
        designation = (request.data.get('designation') or '').strip()
        department = (request.data.get('department') or '').strip()
        try:
            result = generate_job_description(
                designation=designation or None,
                department=department or None,
                user=request.user,
            )
        except AiDisabledError as exc:
            return _handle(exc)
        except Exception as exc:
            return Response({'ok': False, 'error': f'AI call failed: {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({'ok': True, 'result': result})
