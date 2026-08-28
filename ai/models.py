"""AI interaction audit model.

Every AI call (assistant chat, lead scoring, property description,
reminder drafting, insights) is logged here so usage, cost, and quality
can be reviewed.
"""
from django.db import models
from django.contrib.auth.models import User


class AiInteractionLog(models.Model):
    FEATURE_CHOICES = [
        ('assistant', 'Assistant Chat'),
        ('lead_score', 'Lead Scoring'),
        ('property_description', 'Property Description'),
        ('reminder_draft', 'Reminder Draft'),
        ('insights', 'Business Insights'),
        ('hr_assistant', 'HR Assistant Chat'),
        ('leave_review', 'Leave Review'),
        ('payroll_insights', 'Payroll Insights'),
        ('attendance_insights', 'Attendance Insights'),
        ('job_description', 'Job Description'),
    ]
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('disabled', 'Disabled'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    feature = models.CharField(max_length=30, choices=FEATURE_CHOICES)
    prompt = models.TextField(blank=True)
    response = models.TextField(blank=True)
    model = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='success')
    error_message = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_feature_display()} - {self.get_status_display()} - {self.created_at:%Y-%m-%d %H:%M}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'AI Interaction Log'
        verbose_name_plural = 'AI Interaction Logs'
        indexes = [
            models.Index(fields=['feature', 'status']),
            models.Index(fields=['created_at']),
        ]
