from django.db import models
from apps.alerts.models import Alert


class NotificationLog(models.Model):
    CHANNEL_CHOICES = [
        ('LINE', 'LINE Notify'),
        ('MOPH', 'MOPH Notify'),
        ('Slack', 'Slack'),
        ('Email', 'Email'),
    ]
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='notifications')
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    message_preview = models.TextField()
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f"[{self.channel}] {self.status} - Alert #{self.alert_id}"
