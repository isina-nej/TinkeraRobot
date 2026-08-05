from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("botapp", "0026_alter_groupsettings_max_warnings_action_duration_minutes"),
    ]

    operations = [
        migrations.AddField(
            model_name="staffapikey",
            name="allowed_chat_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
