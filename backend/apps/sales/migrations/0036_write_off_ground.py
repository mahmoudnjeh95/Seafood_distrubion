from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0035_invoice_rebilled_from'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerbalancewriteoff',
            name='ground',
            field=models.CharField(choices=[('gap', 'Écart de règlement ou geste commercial'), ('irrecoverable', 'Créance irrécouvrable')], default='gap', max_length=20),
        ),
    ]
