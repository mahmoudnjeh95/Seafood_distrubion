from django.db import migrations
from django.db.models import OuterRef, Subquery


def fill_membership(apps, schema_editor):
    """Every message so far came from WhatsApp: its membership is its phone link's."""
    message = apps.get_model("assistant", "AssistantMessage")
    link = apps.get_model("assistant", "WhatsAppLink")
    message.objects.filter(membership__isnull=True).update(
        membership_id=Subquery(link.objects.filter(pk=OuterRef("link_id")).values("membership_id")[:1])
    )


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0002_message_channel"),
    ]

    operations = [
        migrations.RunPython(fill_membership, migrations.RunPython.noop),
    ]
