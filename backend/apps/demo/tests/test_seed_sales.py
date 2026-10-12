from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.core.models import Organization
from apps.sales import selectors as sales

pytestmark = pytest.mark.django_db


def test_the_seed_gives_a_counter_sale_a_truck_sale_a_converted_quote_and_a_draft(settings):
    settings.DEBUG = True

    call_command("seed_dev")
    call_command("seed_dev")  # running it again creates nothing

    organization = Organization.objects.get()
    found = {sale.customer.name: sale for sale in sales.sales_of(organization)}
    assert {name: (sale.status, sale.location.name) for name, sale in found.items()} == {
        "Client de passage": ("confirmed", "Chambre froide 1 (frais)"),
        "Restaurant Le Corail": ("confirmed", "Camion 1"),
        "Hôtel Thyna": ("draft", "Chambre froide 1 (frais)"),
        "Café-Resto Sidi Mansour": ("confirmed", "Chambre froide 1 (frais)"),
        # The whole of Surgelés du Sahel's partnership lot (P6-T01, D-060).
        "Poissonnerie El Bahr": ("confirmed", "Chambre froide 2 (congelé)"),
    }
    counter = found["Client de passage"]
    assert (counter.amount_paid, counter.amount_due, counter.payment_method) == (counter.total, Decimal("0"), "cash")
    truck = found["Restaurant Le Corail"]
    assert truck.created_by is not None
    assert (truck.created_by.username, truck.amount_paid) == ("driver", Decimal("50.000"))
    converted = found["Café-Resto Sidi Mansour"]
    assert converted.quote is not None
    assert converted.amount_due == converted.total
    bahr = found["Poissonnerie El Bahr"]
    assert (bahr.amount_paid, bahr.amount_due) == (bahr.total, Decimal("0"))
    # Every confirmed line knows the lots it came from and their cost.
    for sale in (counter, truck, converted, bahr):
        assert sale.cost_total is not None
        assert sale.cost_total > 0
        for line in sale.lines.all():
            assert sum(row.quantity for row in line.batches.all()) == line.quantity
