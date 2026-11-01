# The stock counters move to core's NumberSeries (D-223). Each counter keeps its last number, so no number is reused.

from django.db import migrations

# The transfer, loss and count series; the batch counter becomes the "batch" kind (no year).
SERIES = {"TR": "transfer", "PE": "loss", "INV": "count"}


def copy_forward(apps, schema_editor):
    numbers = apps.get_model("core", "NumberSeries")
    batches = apps.get_model("inventory", "BatchCounter")
    documents = apps.get_model("inventory", "DocumentCounter")
    for row in batches.objects.all():
        numbers.objects.create(organization_id=row.organization_id, kind="batch", year=0, last_number=row.last_number)
    for row in documents.objects.filter(series__in=SERIES.keys()):
        numbers.objects.create(
            organization_id=row.organization_id, kind=SERIES[row.series], year=0, last_number=row.last_number
        )


def copy_back(apps, schema_editor):
    numbers = apps.get_model("core", "NumberSeries")
    batches = apps.get_model("inventory", "BatchCounter")
    documents = apps.get_model("inventory", "DocumentCounter")
    series = {kind: name for name, kind in SERIES.items()}
    for row in numbers.objects.all():
        if row.kind == "batch":
            batches.objects.create(organization_id=row.organization_id, last_number=row.last_number)
        elif row.kind in series:
            documents.objects.create(
                organization_id=row.organization_id, series=series[row.kind], last_number=row.last_number
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('inventory', '0011_transfer_line_picks'),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_back),
        migrations.RemoveField(
            model_name='documentcounter',
            name='organization',
        ),
        migrations.DeleteModel(
            name='BatchCounter',
        ),
        migrations.DeleteModel(
            name='DocumentCounter',
        ),
    ]
