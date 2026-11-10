from decimal import Decimal

import apps.core.money
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0036_write_off_ground'),
    ]

    operations = [
        migrations.AddField(
            model_name='financesettings',
            name='vat_withholding_rate',
            field=models.DecimalField(decimal_places=2, default=Decimal('25.00'), max_digits=5),
        ),
        migrations.AddField(
            model_name='invoice',
            name='vat_withholding_rate',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=5),
        ),
        migrations.AddField(
            model_name='invoice',
            name='vat_withholding_amount',
            field=apps.core.money.MoneyField(decimal_places=3, default=Decimal('0.000'), max_digits=14),
        ),
    ]
