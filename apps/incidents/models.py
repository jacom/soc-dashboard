from django.db import models
from django.contrib.auth.models import User
from apps.alerts.models import Alert


class Incident(models.Model):
    STATUS_CHOICES = [
        ('New', 'New'),
        ('InProgress', 'In Progress'),
        ('Resolved', 'Resolved'),
        ('Closed', 'Closed'),
    ]

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='incidents')
    thehive_case_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=300)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='New')
    severity = models.CharField(max_length=20, blank=True)
    thehive_url = models.URLField()
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_incidents')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Incident {self.thehive_case_id}: {self.title[:60]}"
