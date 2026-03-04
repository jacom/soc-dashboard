from django.db import models


class IntegrationConfig(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)
    label = models.CharField(max_length=200)
    group = models.CharField(max_length=50)
    is_secret = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['group', 'key']

    def __str__(self):
        return f'{self.group}/{self.key}'
