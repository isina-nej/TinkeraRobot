import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("botapp", "0017_telegramuser_welcomed_at")]

    operations = [
        migrations.RenameField(
            model_name="telegramuser",
            old_name="user_id",
            new_name="telegram_user_id",
        ),
        migrations.RenameField(
            model_name="telegramuser",
            old_name="last_check_at",
            new_name="last_live_check_at",
        ),
        migrations.RemoveField(model_name="telegramuser", name="warned"),
        migrations.RemoveField(model_name="telegramuser", name="welcomed_at"),
        migrations.RenameModel(
            old_name="BotStartUserState",
            new_name="GroupUserGateState",
        ),
        migrations.RenameField(
            model_name="groupusergatestate",
            old_name="last_notice_at",
            new_name="last_warning_update_at",
        ),
        migrations.RenameField(
            model_name="groupusergatestate",
            old_name="notice_message_id",
            new_name="warning_message_id",
        ),
        migrations.AlterField(
            model_name="groupusergatestate",
            name="group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="user_gate_states",
                to="botapp.groupsettings",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="groupusergatestate",
            name="uniq_bot_start_state_group_user",
        ),
        migrations.AddConstraint(
            model_name="groupusergatestate",
            constraint=models.UniqueConstraint(
                fields=("group", "telegram_user_id"),
                name="unique_group_user_gate_state",
            ),
        ),
        migrations.RenameIndex(
            model_name="groupusergatestate",
            old_name="botapp_bots_group_i_e88239_idx",
            new_name="botapp_grou_group_i_c551c6_idx",
        ),
    ]
