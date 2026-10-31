# The treasury counter moves to core's NumberSeries (D-223). Each counter keeps its last number, so no number is
# reused.

from django.db import migrations


def copy_forward(apps, schema_editor):
    old = apps.get_model("treasury", "TreasuryCounter")
    numbers = apps.get_model("core", "NumberSeries")
    for row in old.objects.all():
        numbers.objects.create(
            organization_id=row.organization_id, kind=row.kind, year=row.year, last_number=row.last_number
        )


def copy_back(apps, schema_editor):
    old = apps.get_model("treasury", "TreasuryCounter")
    numbers = apps.get_model("core", "NumberSeries")
    for row in numbers.objects.filter(kind="deposit"):
        old.objects.create(organization_id=row.organization_id, kind=row.kind, year=row.year, last_number=row.last_number)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('treasury', '0002_deposits'),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_back),
        migrations.DeleteModel(
            name='TreasuryCounter',
        ),
    ]
