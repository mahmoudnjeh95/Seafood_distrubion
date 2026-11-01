# The customer and supplier counters (D-223) start after the highest reference already in use, so that the next
# customer is not C-001 when C-007 exists. The counters themselves are created by core's numbering helper.

import re

from django.db import migrations

# (number kind, model, prefix of the references the company already had)
SEEDS = (("customer", "Customer", "C-"), ("supplier", "Supplier", "F-"))


def seed_counters(apps, schema_editor):
    series_model = apps.get_model("core", "NumberSeries")
    for kind, model_name, prefix in SEEDS:
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.IGNORECASE)
        highest: dict[int, int] = {}
        for organization_id, reference in apps.get_model("partners", model_name).objects.values_list(
            "organization_id", "reference"
        ):
            match = pattern.match(reference)
            if match:
                highest[organization_id] = max(highest.get(organization_id, 0), int(match.group(1)))
        series_model.objects.bulk_create(
            [
                series_model(organization_id=organization_id, kind=kind, year=0, last_number=last_number)
                for organization_id, last_number in highest.items()
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('partners', '0003_customer_place'),
    ]

    operations = [
        migrations.RunPython(seed_counters, migrations.RunPython.noop),
    ]
