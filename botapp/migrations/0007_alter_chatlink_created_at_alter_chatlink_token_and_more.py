import botapp.models
import django.core.validators
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0006_add_group_settings'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chatlink',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='chatlink',
            name='token',
            field=models.CharField(default=botapp.models.generate_token, editable=False, max_length=64, unique=True),
        ),
        migrations.AlterField(
            model_name='groupquota',
            name='daily_prompt_limit',
            field=models.PositiveIntegerField(default=100, validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.AlterField(
            model_name='groupquota',
            name='last_reset',
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
        migrations.AlterField(
            model_name='groupquota',
            name='tokens_used_today',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='groupsettings',
            name='group_admins',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
