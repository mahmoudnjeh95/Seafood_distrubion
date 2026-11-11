import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0003_message_membership_backfill"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assistantmessage",
            name="membership",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="assistant_messages",
                to="core.membership",
            ),
        ),
    ]
