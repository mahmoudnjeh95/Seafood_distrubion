# The sales counters move to core's NumberSeries (D-223). Each counter keeps its last number, so no number is reused.

from django.db import migrations

# A series "FA-2026" is the invoices of 2026; "DV" the quotes numbered before the year (D-120).
KINDS = {
    "DV": "quote",
    "VE": "sale",
    "BL": "delivery_note",
    "OUV": "opening_receivable",
    "FA": "invoice",
    "AV": "credit_note",
    "RG": "payment",
}


def copy_forward(apps, schema_editor):
    old = apps.get_model("sales", "DocumentCounter")
    numbers = apps.get_model("core", "NumberSeries")
    for row in old.objects.all():
        prefix, _dash, year = row.series.partition("-")
        if prefix in KINDS:  # a series no code uses any more keeps no counter
            numbers.objects.create(
                organization_id=row.organization_id, kind=KINDS[prefix], year=int(year or 0), last_number=row.last_number
            )


def copy_back(apps, schema_editor):
    old = apps.get_model("sales", "DocumentCounter")
    numbers = apps.get_model("core", "NumberSeries")
    prefixes = {kind: prefix for prefix, kind in KINDS.items()}
    for row in numbers.objects.filter(kind__in=prefixes.keys()):
        series = f"{prefixes[row.kind]}-{row.year}" if row.year else prefixes[row.kind]
        old.objects.create(organization_id=row.organization_id, series=series, last_number=row.last_number)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('sales', '0023_unpaid_effets'),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_back),
        migrations.DeleteModel(
            name='DocumentCounter',
        ),
    ]
