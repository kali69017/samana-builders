from django.urls import path

from . import api_views

urlpatterns = [
    path('assistant/', api_views.AssistantView.as_view(), name='ai_assistant'),
    path('lead-score/', api_views.LeadScoreView.as_view(), name='ai_lead_score'),
    path('property-description/', api_views.PropertyDescriptionView.as_view(), name='ai_property_description'),
    path('reminder-draft/', api_views.ReminderDraftView.as_view(), name='ai_reminder_draft'),
    path('insights/', api_views.InsightsView.as_view(), name='ai_insights'),
    path('health/', api_views.HealthView.as_view(), name='ai_health'),
    path('language/', api_views.LanguageView.as_view(), name='ai_language'),

    # HR AI features
    path('hr/assistant/', api_views.HrAssistantView.as_view(), name='ai_hr_assistant'),
    path('hr/leave-review/', api_views.LeaveReviewView.as_view(), name='ai_leave_review'),
    path('hr/payroll/', api_views.PayrollInsightsView.as_view(), name='ai_payroll_insights'),
    path('hr/attendance/', api_views.AttendanceInsightsView.as_view(), name='ai_attendance_insights'),
    path('hr/job-description/', api_views.JobDescriptionView.as_view(), name='ai_job_description'),
]
