# The treasury counter moves to core's NumberSeries (D-223). Each counter keeps its last number, so no number is
# reused. The account transfers' counter ("MT", D-219) was kind "transfer" here; core's "transfer" is the stock
# transfer, so it becomes "account_transfer".

from django.db import migrations

RENAMED = {"transfer": "account_transfer"}
BACK = {new: old for old, new in RENAMED.items()}


def copy_forward(apps, schema_editor):
    old = apps.get_model("treasury", "TreasuryCounter")
    numbers = apps.get_model("core", "NumberSeries")
    for row in old.objects.all():
        numbers.objects.create(
            organization_id=row.organization_id,
            kind=RENAMED.get(row.kind, row.kind),
            year=row.year,
            last_number=row.last_number,
        )


def copy_back(apps, schema_editor):
    old = apps.get_model("treasury", "TreasuryCounter")
    numbers = apps.get_model("core", "NumberSeries")
    for row in numbers.objects.filter(kind__in=["deposit", "account_transfer"]):
        old.objects.create(
            organization_id=row.organization_id,
            kind=BACK.get(row.kind, row.kind),
            year=row.year,
            last_number=row.last_number,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('treasury', '0003_accounts'),
    ]

    operations = [
        migrations.RunPython(copy_forward, copy_back),
        migrations.DeleteModel(
            name='TreasuryCounter',
        ),
    ]
