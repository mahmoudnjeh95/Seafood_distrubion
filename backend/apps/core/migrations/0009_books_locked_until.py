from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_custom_roles'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='books_locked_until',
            field=models.DateField(blank=True, null=True),
        ),
    ]
