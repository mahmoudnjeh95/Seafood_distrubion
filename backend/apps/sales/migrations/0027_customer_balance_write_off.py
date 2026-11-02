import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.core.money


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0006_numbering"),
        ("partners", "0004_numbering_seed"),
        ("sales", "0026_numbering_series"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerBalanceWriteOff",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("written_on", models.DateField()),
                ("amount", apps.core.money.MoneyField(decimal_places=3, max_digits=14)),
                ("reason", models.CharField(max_length=255)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="balance_write_offs",
                        to="partners.customer",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.organization"
                    ),
                ),
            ],
            options={
                "ordering": ["-written_on", "-id"],
            },
        ),
        migrations.CreateModel(
            name="CustomerWriteOffAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", apps.core.money.MoneyField(decimal_places=3, max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.organization"
                    ),
                ),
                (
                    "sale",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="write_off_allocations",
                        to="sales.sale",
                    ),
                ),
                (
                    "write_off",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="allocations",
                        to="sales.customerbalancewriteoff",
                    ),
                ),
            ],
            options={
                "ordering": ["write_off", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="customerbalancewriteoff",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gt", 0)), name="customer_write_off_amount_positive"
            ),
        ),
        migrations.AddConstraint(
            model_name="customerwriteoffallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gt", 0)), name="write_off_allocation_amount_positive"
            ),
        ),
    ]
