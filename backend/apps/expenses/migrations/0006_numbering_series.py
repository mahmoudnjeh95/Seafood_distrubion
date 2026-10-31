# The expense counter moves to core's NumberSeries (D-223). Each counter keeps its last number, so no number is reused.

from django.db import migrations


def copy_forward(apps, schema_editor):
    old = apps.get_model("expenses", "DocumentCounter")
    numbers = apps.get_model("core", "NumberSeries")
    for row in old.objects.all():
        # "DP-2026" is the expenses of 2026 (D-120); "DP" the ones numbered before it.
        _prefix, _dash, year = row.series.partition("-")
        numbers.objects.create(
            organization_id=row.organization_id, kind="expense", year=int(year or 0), last_number=row.last_number
        )


def copy_back(apps, schema_editor):
    old = apps.get_model("expenses", "DocumentCounter")
    numbers = apps.get_model("core", "NumberSeries")
    for row in numbers.objects.filter(kind="expense"):
        series = f"DP-{row.year}" if row.year else "DP"
        old.objects.create(organization_id=row.organization_id, series=series, last_number=row.last_number)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('expenses', '0005_driver_categories'),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_back),
        migrations.DeleteModel(
            name='DocumentCounter',
        ),
    ]
