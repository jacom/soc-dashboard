from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('config_app', '0003_add_indexer_credentials'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                """INSERT INTO config_app_integrationconfig (key, value, label, "group", is_secret, description, updated_at)
                   VALUES
                   ('AUTODISMISS_ENABLED',    'false', 'เปิดใช้ Auto-dismiss',        'system', false, 'เปิดใช้งาน Auto-dismiss อัตโนมัติ', NOW()),
                   ('AUTODISMISS_DAYS',       '90',    'Dismiss หลังกี่วัน',          'system', false, 'Alert ที่เก่ากว่ากี่วันจะถูก Dismiss อัตโนมัติ (ค่าแนะนำ: 90)', NOW()),
                   ('AUTODISMISS_SEVERITIES', 'INFO,LOW', 'Severity ที่ Auto-dismiss', 'system', false, 'ระดับความรุนแรงที่จะ dismiss อัตโนมัติ คั่นด้วย comma เช่น INFO,LOW', NOW())
                   ON CONFLICT (key) DO NOTHING;""",
            ],
            reverse_sql=[
                "DELETE FROM config_app_integrationconfig WHERE key IN ('AUTODISMISS_ENABLED','AUTODISMISS_DAYS','AUTODISMISS_SEVERITIES');",
            ],
        ),
    ]
