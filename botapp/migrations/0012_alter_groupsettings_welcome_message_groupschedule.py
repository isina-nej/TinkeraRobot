import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0011_groupsettings_open_permissions_snapshot'),
    ]

    operations = [
        migrations.AlterField(
            model_name='groupsettings',
            name='welcome_message',
            field=models.TextField(default='سلام #name عزیز به گروه #title خوش آمدی 🌷 ✅ ساعت: ( #time ) ✅ تاریخ: ( #date )'),
        ),
        migrations.CreateModel(
            name='GroupSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('lock', 'Lock'), ('unlock', 'Unlock')], max_length=10)),
                ('time_of_day', models.TimeField()),
                ('is_active', models.BooleanField(default=True)),
                ('last_enqueued_date', models.DateField(blank=True, null=True)),
                ('created_by_user_id', models.BigIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='schedules', to='botapp.groupsettings')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('group', 'action', 'time_of_day'), name='unique_group_daily_schedule')],
            },
        ),
    ]
