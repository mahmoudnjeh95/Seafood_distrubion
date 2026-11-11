import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """The messages of the "Assistant IA" screen (D-314): a message belongs to a membership and a channel; only a
    WhatsApp one has a phone link."""

    dependencies = [
        ("assistant", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assistantmessage",
            name="link",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="assistant.whatsapplink",
            ),
        ),
        migrations.AddField(
            model_name="assistantmessage",
            name="channel",
            field=models.CharField(
                choices=[("whatsapp", "WhatsApp"), ("web", "Application")], default="whatsapp", max_length=10
            ),
        ),
        migrations.AddField(
            model_name="assistantmessage",
            name="spoken",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="assistantmessage",
            name="membership",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="assistant_messages",
                to="core.membership",
            ),
        ),
    ]
