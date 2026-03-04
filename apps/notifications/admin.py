from django.contrib import admin
from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('alert', 'channel', 'status', 'sent_at')
    list_filter = ('channel', 'status')
    readonly_fields = ('sent_at',)
