from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0007_attachments'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attachment',
            name='kind',
            field=models.CharField(choices=[('quote', 'Devis'), ('delivery_note', 'Bon de livraison'), ('invoice', 'Facture'), ('credit_note', 'Avoir'), ('purchase_order', 'Bon de commande fournisseur'), ('goods_receipt', 'Bon de réception'), ('supplier_invoice', 'Facture fournisseur'), ('customer_write_off', "Remise à zéro d'un solde client")], max_length=20),
        ),
    ]
