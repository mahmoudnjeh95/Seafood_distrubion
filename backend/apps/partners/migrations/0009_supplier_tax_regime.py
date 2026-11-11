from django.db import migrations, models


def none_without_tax_id(apps, schema_editor):
    Supplier = apps.get_model("partners", "Supplier")
    Supplier.objects.filter(tax_id="").update(tax_regime="none")


class Migration(migrations.Migration):

    dependencies = [
        ('partners', '0008_lot_origin'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='tax_regime',
            field=models.CharField(choices=[('real', 'Régime réel'), ('flat', 'Régime forfaitaire'), ('none', 'Sans matricule fiscal')], default='real', max_length=10),
        ),
        migrations.AddField(
            model_name='supplier',
            name='subject_to_withholding',
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(none_without_tax_id, migrations.RunPython.noop),
    ]
