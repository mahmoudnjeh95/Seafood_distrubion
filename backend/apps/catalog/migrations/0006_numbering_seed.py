# The product counter (D-223) starts after the highest article code already in use (ART0060 in the owner's list),
# so the next product is ART0061 and not a code the owner has given.

import re

from django.db import migrations


def seed_counter(apps, schema_editor):
    series_model = apps.get_model("core", "NumberSeries")
    pattern = re.compile(r"^ART(\d+)$", re.IGNORECASE)
    highest: dict[int, int] = {}
    for organization_id, reference in apps.get_model("catalog", "Product").objects.values_list(
        "organization_id", "reference"
    ):
        match = pattern.match(reference)
        if match:
            highest[organization_id] = max(highest.get(organization_id, 0), int(match.group(1)))
    series_model.objects.bulk_create(
        [
            series_model(organization_id=organization_id, kind="product", year=0, last_number=last_number)
            for organization_id, last_number in highest.items()
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('catalog', '0005_product_vat_rate'),
    ]

    operations = [
        migrations.RunPython(seed_counter, migrations.RunPython.noop),
    ]
