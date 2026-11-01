"""Demo employees and payroll: the stand-ins of docs/spec/sample/employees.csv (invented, not real people).

Seven employees (the owner and the external accountant of the sample are not paid by the company here).
Last month is generated, approved and mostly paid, two salaries are left unpaid so the "impayé" badge
shows; this month is generated as drafts. A few days on a lot show the days × salary / 26 cost.
Known by the employee reference, so the seed adds them only once.
"""

import datetime as dt
from decimal import Decimal

from django.utils import timezone

from apps.core.models import Organization, User
from apps.hr import selectors, services
from apps.inventory import selectors as inventory

# reference, name, position, monthly salary, hire date, CNSS number
EMPLOYEES = [
    ("E-002", "Rim K.", "Responsable administrative", "1600.000", dt.date(2021, 2, 1), "10234567-81"),
    ("E-003", "Sami B.", "Chauffeur-vendeur", "1250.000", dt.date(2022, 6, 15), "10345678-92"),
    ("E-004", "Anis M.", "Chauffeur-vendeur", "1250.000", dt.date(2023, 1, 9), "10456789-03"),
    ("E-005", "Walid G.", "Chauffeur-vendeur", "1250.000", dt.date(2023, 9, 1), "10567890-14"),
    ("E-006", "Hedi Z.", "Magasinier chambre froide", "1100.000", dt.date(2020, 11, 2), "10678901-25"),
    ("E-007", "Mouna T.", "Vendeuse comptoir", "1000.000", dt.date(2024, 3, 4), "10789012-36"),
    ("E-008", "Karim S.", "Manutentionnaire", "950.000", dt.date(2024, 8, 19), "10890123-47"),
]
DRIVER_REFERENCE = "E-003"  # Sami B., the `driver` login
OVERTIME = {"E-006": "40.000"}
UNPAID = {"E-007", "E-008"}
# reference, days on the lot, N days ago
LOT_DAYS = [("E-006", "1", 2), ("E-008", "0.5", 2), ("E-006", "0.5", 1)]


def seed_employees(*, organization: Organization, actor: User | None, driver: User | None) -> int:
    """Create the demo employees, last month's payroll and some days on a lot. Returns how many employees."""
    if selectors.employees_of(organization, status="all").filter(reference=EMPLOYEES[0][0]).exists():
        return 0
    created = []
    for reference, name, position, salary, hired, cnss_number in EMPLOYEES:
        created.append(
            services.create_employee(
                organization=organization,
                actor=actor,
                reference=reference,
                name=name,
                position=position,
                monthly_salary=Decimal(salary),
                hire_date=hired,
                cnss_number=cnss_number,
                user=driver if reference == DRIVER_REFERENCE else None,
            )
        )
    today = timezone.localdate()
    last_month = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    for record in services.generate_month(organization=organization, actor=actor, month=last_month):
        overtime = OVERTIME.get(record.employee.reference)
        if overtime:
            services.update_salary_record(record=record, actor=actor, overtime=overtime, notes="Heures de nuit")
    services.approve_month(organization=organization, actor=actor, month=last_month)
    for record in selectors.salary_records_of(organization, month=last_month):
        if record.employee.reference in UNPAID:
            continue
        due = selectors.due_amount(record)
        services.record_payment(
            organization=organization,
            actor=actor,
            employee=record.employee,
            paid_on=today,
            amount=due,
            method="cash" if due < Decimal("1100") else "transfer",
            allocations=[{"salary_record": record, "amount": due}],
        )
    services.generate_month(organization=organization, actor=actor, month=today.replace(day=1))

    batch = inventory.batches_of(organization).first()
    by_reference = {employee.reference: employee for employee in created}
    for reference, days, ago in LOT_DAYS:
        services.add_lot_work_day(
            organization=organization,
            actor=actor,
            employee=by_reference[reference],
            work_date=today - dt.timedelta(days=ago),
            days=days,
            batch=batch,
            notes="Tri et glaçage",
        )
    return len(created)
