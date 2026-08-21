from django.db import models
from django.contrib.auth.models import User


class NotificationLog(models.Model):
    CHANNEL_CHOICES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('whatsapp', 'WhatsApp'),
    ]
    TYPE_CHOICES = [
        ('installment_reminder', 'Installment Reminder'),
        ('overdue_payment', 'Overdue Payment'),
        ('payment_confirmation', 'Payment Confirmation'),
        ('receipt_notification', 'Receipt Notification'),
        ('booking_notification', 'Booking Notification'),
        ('booking_approval', 'Booking Approval'),
        ('general', 'General'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    recipient_name = models.CharField(max_length=200)
    recipient_contact = models.CharField(max_length=200)  # email or phone
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    subject = models.CharField(max_length=300, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=50, blank=True, help_text="Gateway message/delivery ID (e.g. SendPK messageid)")
    related_customer_id = models.CharField(max_length=20, blank=True)
    related_booking_id = models.CharField(max_length=20, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.channel} to {self.recipient_name}: {self.subject or self.message[:50]}"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'channel']),
            models.Index(fields=['notification_type']),
        ]


class NotificationPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_prefs')
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    whatsapp_enabled = models.BooleanField(default=True)
    installment_reminders = models.BooleanField(default=True)
    overdue_payments = models.BooleanField(default=True)
    payment_confirmations = models.BooleanField(default=True)
    booking_notifications = models.BooleanField(default=True)

    def __str__(self):
        return f"Preferences for {self.user.username}"
