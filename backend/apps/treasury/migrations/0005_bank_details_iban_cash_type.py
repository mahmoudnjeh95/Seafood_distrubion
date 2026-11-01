from django.db import migrations, models


def mark_existing_cash_principal(apps, schema_editor):
    # The Caisses that exist are the main ones; secondary ones are added by hand from now on.
    TreasuryAccount = apps.get_model("treasury", "TreasuryAccount")
    TreasuryAccount.objects.filter(kind="cash", cash_type="").update(cash_type="principal")


class Migration(migrations.Migration):
    dependencies = [
        ("treasury", "0004_numbering_series"),
    ]

    operations = [
        migrations.AddField(
            model_name="bank",
            name="address",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="bank",
            name="swift",
            field=models.CharField(blank=True, max_length=11),
        ),
        migrations.AddField(
            model_name="treasuryaccount",
            name="cash_type",
            field=models.CharField(
                blank=True, choices=[("principal", "Principale"), ("secondary", "Secondaire")], max_length=10
            ),
        ),
        migrations.AddField(
            model_name="treasuryaccount",
            name="iban",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.RunPython(mark_existing_cash_principal, migrations.RunPython.noop),
    ]
