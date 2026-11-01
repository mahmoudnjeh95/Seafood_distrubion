# The purchasing counters move to core's NumberSeries (D-223). Each counter keeps its last number, so no number is reused.

from django.db import migrations

# The kinds the purchasing document counter already numbered: supplier invoices and payments, orders, field purchases.
COUNTED_KINDS = ("supplier_invoice", "supplier_payment", "purchase_order", "field_purchase")


def copy_forward(apps, schema_editor):
    numbers = apps.get_model("core", "NumberSeries")
    counters = apps.get_model("purchasing", "DocumentCounter")
    receipts = apps.get_model("purchasing", "ReceiptCounter")
    for row in counters.objects.all():
        numbers.objects.create(
            organization_id=row.organization_id, kind=row.kind, year=row.year, last_number=row.last_number
        )
    for row in receipts.objects.all():
        numbers.objects.create(
            organization_id=row.organization_id, kind="receipt", year=0, last_number=row.last_number
        )


def copy_back(apps, schema_editor):
    numbers = apps.get_model("core", "NumberSeries")
    counters = apps.get_model("purchasing", "DocumentCounter")
    receipts = apps.get_model("purchasing", "ReceiptCounter")
    for row in numbers.objects.all():
        if row.kind == "receipt":
            receipts.objects.create(organization_id=row.organization_id, last_number=row.last_number)
        elif row.kind in COUNTED_KINDS:
            counters.objects.create(
                organization_id=row.organization_id, kind=row.kind, year=row.year, last_number=row.last_number
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('purchasing', '0016_supplierpayment_reason'),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_back),
        migrations.RemoveField(
            model_name='receiptcounter',
            name='organization',
        ),
        migrations.DeleteModel(
            name='DocumentCounter',
        ),
        migrations.DeleteModel(
            name='ReceiptCounter',
        ),
    ]
