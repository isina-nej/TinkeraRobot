from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("botapp", "0027_staffapikey_allowed_chat_ids"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentconfirmation",
            name="request_chat_id",
            field=models.BigIntegerField(
                blank=True,
                db_index=True,
                help_text="Chat where the confirmation UI was shown (may differ from operational chat_id).",
                null=True,
            ),
        ),
    ]
