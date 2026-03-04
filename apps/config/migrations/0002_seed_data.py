from django.db import migrations

INITIAL_CONFIGS = [
    # Wazuh
    {'key': 'WAZUH_API_URL',  'label': 'Wazuh API URL',  'group': 'wazuh',  'is_secret': False, 'description': 'e.g. https://wazuh-server:55000', 'value': 'https://localhost:55000'},
    {'key': 'WAZUH_USER',     'label': 'Username',        'group': 'wazuh',  'is_secret': False, 'description': 'Wazuh API username', 'value': 'wazuh'},
    {'key': 'WAZUH_PASSWORD', 'label': 'Password',        'group': 'wazuh',  'is_secret': True,  'description': 'Wazuh API password', 'value': 'change-this-to-wazuh-password'},
    # Ollama
    {'key': 'OLLAMA_URL',     'label': 'Ollama URL',      'group': 'ollama', 'is_secret': False, 'description': 'e.g. http://localhost:11434', 'value': 'http://localhost:11434'},
    {'key': 'OLLAMA_MODEL',   'label': 'Model Name',      'group': 'ollama', 'is_secret': False, 'description': 'e.g. openchat or llama3.2', 'value': 'openchat'},
    # TheHive
    {'key': 'THEHIVE_URL',    'label': 'TheHive URL',     'group': 'thehive','is_secret': False, 'description': 'e.g. http://thehive:9000', 'value': 'http://localhost:9000'},
    {'key': 'THEHIVE_API_KEY','label': 'API Key',         'group': 'thehive','is_secret': True,  'description': 'TheHive API key', 'value': 'change-this-to-thehive-api-key'},
    # LINE
    {'key': 'LINE_NOTIFY_TOKEN', 'label': 'LINE Notify Token', 'group': 'line', 'is_secret': True, 'description': 'From notify.line.me/my — leave empty to disable', 'value': 'change-this-to-line-notify-token'},
    # System
    {'key': 'POLL_INTERVAL',        'label': 'Poll Interval (sec)',    'group': 'system', 'is_secret': False, 'description': 'How often to poll Wazuh (seconds)', 'value': '30'},
    {'key': 'LOG_LEVEL',            'label': 'Log Level',              'group': 'system', 'is_secret': False, 'description': 'DEBUG / INFO / WARNING / ERROR', 'value': 'INFO'},
    {'key': 'WAZUH_MIN_LEVEL',      'label': 'Min Rule Level',         'group': 'system', 'is_secret': False, 'description': 'Minimum Wazuh rule level to process (1-15)', 'value': '4'},
    {'key': 'WAZUH_MAX_ALERTS',     'label': 'Max Alerts / Poll',      'group': 'system', 'is_secret': False, 'description': 'Max alerts fetched per polling cycle', 'value': '100'},
    {'key': 'DJANGO_DASHBOARD_URL', 'label': 'Dashboard Public URL',   'group': 'system', 'is_secret': False, 'description': 'Public URL of this dashboard (for bot callbacks)', 'value': 'http://localhost:8500'},
]


def _read_env_value(key, default):
    """Try to read current value from soc-bot .env file."""
    try:
        with open('/home/jong2/soc-bot/.env') as f:
            for line in f:
                line = line.strip()
                if line.startswith(f'{key}='):
                    return line.split('=', 1)[1]
    except Exception:
        pass
    return default


def seed_configs(apps, schema_editor):
    IntegrationConfig = apps.get_model('config_app', 'IntegrationConfig')
    for cfg in INITIAL_CONFIGS:
        value = _read_env_value(cfg['key'], cfg['value'])
        IntegrationConfig.objects.get_or_create(
            key=cfg['key'],
            defaults={
                'value': value,
                'label': cfg['label'],
                'group': cfg['group'],
                'is_secret': cfg['is_secret'],
                'description': cfg['description'],
            }
        )


def unseed_configs(apps, schema_editor):
    IntegrationConfig = apps.get_model('config_app', 'IntegrationConfig')
    keys = [c['key'] for c in INITIAL_CONFIGS]
    IntegrationConfig.objects.filter(key__in=keys).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('config_app', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_configs, unseed_configs),
    ]
