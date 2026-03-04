from django.contrib import admin
from .models import Alert, AIAnalysis


class AIAnalysisInline(admin.StackedInline):
    model = AIAnalysis
    extra = 0
    readonly_fields = ('analyzed_at',)


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('wazuh_id', 'severity', 'rule_level', 'rule_description', 'agent_name', 'timestamp')
    list_filter = ('severity', 'agent_name')
    search_fields = ('wazuh_id', 'rule_description', 'agent_name', 'mitre_id')
    readonly_fields = ('created_at',)
    inlines = [AIAnalysisInline]
    ordering = ('-timestamp',)


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ('alert', 'attack_type', 'severity_assessment', 'false_positive_pct', 'analyzed_at')
    readonly_fields = ('analyzed_at',)
