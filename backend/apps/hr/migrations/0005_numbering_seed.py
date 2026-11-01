# The employee counter (D-223) starts after the highest employee reference already in use (E-007 gives E-008 next).

import re

from django.db import migrations


def seed_counter(apps, schema_editor):
    series_model = apps.get_model("core", "NumberSeries")
    pattern = re.compile(r"^E-(\d+)$", re.IGNORECASE)
    highest: dict[int, int] = {}
    for organization_id, reference in apps.get_model("hr", "Employee").objects.values_list(
        "organization_id", "reference"
    ):
        match = pattern.match(reference)
        if match:
            highest[organization_id] = max(highest.get(organization_id, 0), int(match.group(1)))
    series_model.objects.bulk_create(
        [
            series_model(organization_id=organization_id, kind="employee", year=0, last_number=last_number)
            for organization_id, last_number in highest.items()
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_numbering'),
        ('hr', '0004_numbering_series'),
    ]

    operations = [
        migrations.RunPython(seed_counter, migrations.RunPython.noop),
    ]
