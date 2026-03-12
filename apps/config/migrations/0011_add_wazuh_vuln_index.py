from django.db import migrations

NEW_CONFIGS = [
    {
        'key': 'WAZUH_VULN_INDEX',
        'label': 'Vulnerability Index',
        'group': 'wazuh',
        'is_secret': False,
        'description': 'Wazuh vulnerability states index name',
        'value': 'wazuh-states-vulnerabilities-wazuh-server',
    },
]


def add_configs(apps, schema_editor):
    IntegrationConfig = apps.get_model('config_app', 'IntegrationConfig')
    for cfg in NEW_CONFIGS:
        IntegrationConfig.objects.get_or_create(
            key=cfg['key'],
            defaults={
                'value':       cfg['value'],
                'label':       cfg['label'],
                'group':       cfg['group'],
                'is_secret':   cfg['is_secret'],
                'description': cfg['description'],
            }
        )


def remove_configs(apps, schema_editor):
    IntegrationConfig = apps.get_model('config_app', 'IntegrationConfig')
    IntegrationConfig.objects.filter(key__in=[c['key'] for c in NEW_CONFIGS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('config_app', '0010_add_smtp_configs'),
    ]

    operations = [
        migrations.RunPython(add_configs, remove_configs),
    ]
