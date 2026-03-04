from django.contrib import admin
from .models import Incident


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ('thehive_case_id', 'title', 'status', 'severity', 'created_at')
    list_filter = ('status', 'severity')
    search_fields = ('thehive_case_id', 'title')
    readonly_fields = ('created_at', 'updated_at')
