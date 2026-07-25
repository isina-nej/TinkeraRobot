from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0010_groupsettings_max_warnings_action_delay_minutes_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='groupsettings',
            name='open_permissions_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
