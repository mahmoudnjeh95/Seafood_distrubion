from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('partners', '0009_supplier_tax_regime'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='public_buyer',
            field=models.BooleanField(default=False),
        ),
    ]
