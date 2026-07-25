import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('botapp', '0007_alter_chatlink_created_at_alter_chatlink_token_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='groupsettings',
            name='allowed_domains',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='anti_forward_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='anti_link_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='anti_spam_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='blocked_words',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='captcha_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='duplicate_limit',
            field=models.PositiveIntegerField(default=3),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='flood_limit',
            field=models.PositiveIntegerField(default=6),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='flood_window_seconds',
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='goodbye_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='goodbye_message',
            field=models.TextField(default='{name} از گروه خارج شد.'),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='log_retention_days',
            field=models.PositiveIntegerField(default=90),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='max_warnings',
            field=models.PositiveIntegerField(default=3),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='moderation_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='mute_duration_minutes',
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='rules_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='rules_text',
            field=models.TextField(default='قوانین گروه هنوز تنظیم نشده است.'),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='warning_expiry_days',
            field=models.PositiveIntegerField(default=30),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='welcome_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='groupsettings',
            name='welcome_message',
            field=models.TextField(default='خوش آمدی {mention} به {group}! قوانین را با /rules بخوانید.'),
        ),
        migrations.CreateModel(
            name='ModerationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_user_id', models.BigIntegerField(blank=True, null=True)),
                ('target_name', models.CharField(blank=True, max_length=255)),
                ('actor_user_id', models.BigIntegerField(blank=True, null=True)),
                ('actor_name', models.CharField(blank=True, max_length=255)),
                ('action', models.CharField(choices=[('warn', 'Warn'), ('unwarn', 'Unwarn'), ('mute', 'Mute'), ('unmute', 'Unmute'), ('ban', 'Ban'), ('unban', 'Unban'), ('delete', 'Delete'), ('filter', 'Filter')], max_length=20)),
                ('reason', models.CharField(blank=True, max_length=500)),
                ('duration_minutes', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='moderation_logs', to='botapp.groupsettings')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['group', '-created_at'], name='botapp_mode_group_i_ad6734_idx')],
            },
        ),
        migrations.CreateModel(
            name='Warning',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_id', models.BigIntegerField()),
                ('user_name', models.CharField(blank=True, max_length=255)),
                ('issued_by_user_id', models.BigIntegerField()),
                ('issued_by_name', models.CharField(blank=True, max_length=255)),
                ('reason', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='warnings', to='botapp.groupsettings')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['group', 'user_id', '-created_at'], name='botapp_warn_group_i_605948_idx')],
            },
        ),
    ]
