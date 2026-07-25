import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0009_add_max_warnings_action'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='groupsettings',
            name='max_warnings_action_delay_minutes',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='max_warnings_action_duration_minutes',
            field=models.PositiveIntegerField(blank=True, default=10, null=True),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='message_templates',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='moderationlog',
            name='action',
            field=models.CharField(choices=[('warn', 'Warn'), ('unwarn', 'Unwarn'), ('lock', 'Lock'), ('unlock', 'Unlock'), ('mute', 'Mute'), ('unmute', 'Unmute'), ('ban', 'Ban'), ('unban', 'Unban'), ('delete', 'Delete'), ('filter', 'Filter')], max_length=20),
        ),
        migrations.CreateModel(
            name='ModerationAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('lock', 'Lock group'), ('unlock', 'Unlock group'), ('mute', 'Mute user'), ('unmute', 'Unmute user'), ('ban', 'Ban user'), ('unban', 'Unban user')], max_length=10)),
                ('target_user_id', models.BigIntegerField(blank=True, null=True)),
                ('target_name', models.CharField(blank=True, max_length=255)),
                ('actor_user_id', models.BigIntegerField(blank=True, null=True)),
                ('actor_name', models.CharField(blank=True, max_length=255)),
                ('reason', models.CharField(blank=True, max_length=500)),
                ('execute_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('duration_minutes', models.PositiveIntegerField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('executed', 'Executed'), ('cancelled', 'Cancelled'), ('failed', 'Failed')], db_index=True, default='pending', max_length=12)),
                ('idempotency_key', models.CharField(max_length=80, unique=True)),
                ('source', models.CharField(default='telegram', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('executed_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('error', models.TextField(blank=True)),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='actions', to='botapp.groupsettings')),
            ],
            options={
                'ordering': ['execute_at'],
            },
        ),
        migrations.AddField(
            model_name='moderationlog',
            name='moderation_action',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='logs', to='botapp.moderationaction'),
        ),
        migrations.CreateModel(
            name='StaffAPIKey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('prefix', models.CharField(db_index=True, max_length=12)),
                ('key_hash', models.CharField(max_length=64, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_bot_api_keys', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name='moderationaction',
            index=models.Index(fields=['status', 'execute_at'], name='botapp_mode_status_1e86d6_idx'),
        ),
        migrations.AddIndex(
            model_name='moderationaction',
            index=models.Index(fields=['group', 'target_user_id', 'status'], name='botapp_mode_group_i_aa1cd1_idx'),
        ),
    ]
