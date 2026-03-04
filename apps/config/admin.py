from django.contrib import admin
from .models import IntegrationConfig


@admin.register(IntegrationConfig)
class IntegrationConfigAdmin(admin.ModelAdmin):
    list_display = ['key', 'label', 'group', 'is_secret', 'updated_at']
    list_filter = ['group', 'is_secret']
    search_fields = ['key', 'label']
    ordering = ['group', 'key']

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj and obj.is_secret:
            form.base_fields['value'].widget.attrs['type'] = 'password'
        return form
