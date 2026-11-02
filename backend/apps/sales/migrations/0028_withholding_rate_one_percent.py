"""The withholding rate defaults to 1 % (owner, 2026-11, D-266, provisional until the accountant confirms).

Organizations still at 0 % take 1 % from today: the settings version in force and any dated later. Earlier
versions keep what they were, so the history of the rates stays true.
"""

from decimal import Decimal

from django.db import migrations, models
from django.utils import timezone


def raise_zero_rates_to_one_percent(apps, schema_editor):
    FinanceSettings = apps.get_model("sales", "FinanceSettings")
    today = timezone.localdate()
    in_force: dict[int, int] = {}
    for version in FinanceSettings.objects.order_by("valid_from", "pk"):
        if version.valid_from <= today:
            in_force[version.organization_id] = version.pk
    FinanceSettings.objects.filter(pk__in=in_force.values(), withholding_rate=0).update(withholding_rate=1)
    FinanceSettings.objects.filter(valid_from__gt=today, withholding_rate=0).update(withholding_rate=1)


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0027_customer_balance_write_off"),
    ]

    operations = [
        migrations.AlterField(
            model_name="financesettings",
            name="withholding_rate",
            field=models.DecimalField(decimal_places=2, default=Decimal("1.00"), max_digits=5),
        ),
        migrations.RunPython(raise_zero_rates_to_one_percent, migrations.RunPython.noop),
    ]
