from django.db import models


class Alert(models.Model):
    SEVERITY = [
        ('CRITICAL', 'Critical'),
        ('HIGH', 'High'),
        ('MEDIUM', 'Medium'),
        ('LOW', 'Low'),
        ('INFO', 'Info'),
    ]

    wazuh_id = models.CharField(max_length=100, unique=True)
    timestamp = models.DateTimeField()
    agent_name = models.CharField(max_length=200)
    agent_ip = models.GenericIPAddressField(null=True, blank=True)
    rule_id = models.CharField(max_length=20)
    rule_level = models.IntegerField()
    rule_description = models.TextField()
    rule_groups = models.JSONField(default=list)
    mitre_id = models.CharField(max_length=50, blank=True)
    src_ip = models.GenericIPAddressField(null=True, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY)
    raw_data = models.JSONField()
    dismissed = models.BooleanField(default=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['severity']),
            models.Index(fields=['agent_name']),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.rule_description[:60]} - {self.agent_name}"

    @property
    def severity_color(self):
        colors = {
            'CRITICAL': 'danger',
            'HIGH': 'warning',
            'MEDIUM': 'info',
            'LOW': 'secondary',
            'INFO': 'light',
        }
        return colors.get(self.severity, 'secondary')


class AIAnalysisChat(models.Model):
    """Second AI analysis using OpenAI chat-completions format."""
    RISK_LEVELS = [('Low','Low'),('Medium','Medium'),('High','High'),('Critical','Critical')]

    alert = models.OneToOneField('Alert', on_delete=models.CASCADE, related_name='ai_analysis_chat')
    model_used = models.CharField(max_length=100, blank=True)
    risk_level = models.CharField(max_length=20, blank=True)
    is_malicious = models.CharField(max_length=50, blank=True)   # malicious / misconfiguration / benign
    root_cause = models.TextField(blank=True)
    root_cause_th = models.TextField(blank=True)
    recommended_action = models.TextField(blank=True)
    recommended_action_th = models.TextField(blank=True)
    should_create_incident = models.BooleanField(default=False)
    raw_response = models.TextField(blank=True)
    analyzed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ChatAnalysis for Alert #{self.alert_id}: {self.risk_level}"


class AIAnalysis(models.Model):
    alert = models.OneToOneField(Alert, on_delete=models.CASCADE, related_name='ai_analysis')
    # Thai fields (original)
    attack_type = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    impact = models.TextField()
    recommendations = models.TextField()
    remediation_steps = models.TextField(blank=True, default='')
    # English fields (bilingual support)
    attack_type_en = models.CharField(max_length=200, blank=True, default='')
    summary_en = models.TextField(blank=True, default='')
    impact_en = models.TextField(blank=True, default='')
    recommendations_en = models.TextField(blank=True, default='')
    remediation_steps_en = models.TextField(blank=True, default='')
    # Common fields
    mitre_technique = models.CharField(max_length=50, blank=True)
    severity_assessment = models.CharField(max_length=20)
    false_positive_pct = models.IntegerField(default=0)
    raw_response = models.TextField()
    analyzed_at = models.DateTimeField(auto_now_add=True)

    @property
    def remediation_steps_list(self):
        return [s.strip() for s in self.remediation_steps.split('|') if s.strip()]

    @property
    def remediation_steps_en_list(self):
        return [s.strip() for s in self.remediation_steps_en.split('|') if s.strip()]

    def __str__(self):
        return f"AI Analysis for Alert #{self.alert_id}: {self.attack_type}"
