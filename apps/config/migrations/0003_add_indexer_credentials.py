from django.db import migrations

NEW_CONFIGS = [
    {
        'key': 'WAZUH_INDEXER_URL',
        'label': 'Indexer URL',
        'group': 'wazuh',
        'is_secret': False,
        'description': 'Wazuh Indexer (OpenSearch) URL — e.g. https://192.168.120.252:9200',
        'value': '',
    },
    {
        'key': 'WAZUH_INDEXER_USER',
        'label': 'Indexer Username',
        'group': 'wazuh',
        'is_secret': False,
        'description': 'Wazuh Indexer admin username (default: admin)',
        'value': 'admin',
    },
    {
        'key': 'WAZUH_INDEXER_PASSWORD',
        'label': 'Indexer Password',
        'group': 'wazuh',
        'is_secret': True,
        'description': 'Wazuh Indexer admin password',
        'value': '',
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
        ('config_app', '0002_seed_data'),
    ]

    operations = [
        migrations.RunPython(add_configs, remove_configs),
    ]
