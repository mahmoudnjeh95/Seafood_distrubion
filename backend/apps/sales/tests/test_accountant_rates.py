"""The rates the accountant sets in the finance settings (D-325): empty until typed, kept from version to version."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.sales import services
from apps.sales.services import OPTIONAL_RATES

pytestmark = pytest.mark.django_db


def test_a_new_organization_withholds_one_percent_from_suppliers_and_has_no_other_rate():
    version = services.ensure_finance_settings(organization=OrganizationFactory.create())

    assert version.supplier_withholding_rate == Decimal("1.00")
    assert [getattr(version, name) for name in OPTIONAL_RATES[1:]] == [None] * 6


def test_typed_rates_are_kept_and_an_empty_one_is_cleared():
    organization = OrganizationFactory.create()
    services.save_finance_settings(
        organization=organization, actor=None, rent_withholding_rate="10", tcl_rate="0.2", css_rate="0.50"
    )

    version = services.save_finance_settings(
        organization=organization, actor=None, tcl_rate="", supplier_withholding_rate=None
    )

    assert (version.rent_withholding_rate, version.css_rate) == (Decimal("10.00"), Decimal("0.50"))
    assert (version.tcl_rate, version.supplier_withholding_rate) == (None, None)


def test_a_rate_that_is_not_a_percent_is_refused_on_its_field():
    with pytest.raises(ValidationError) as refused:
        services.save_finance_settings(organization=OrganizationFactory.create(), actor=None, tfp_rate="120")

    assert list(refused.value.message_dict) == ["tfp_rate"]


def test_the_api_reads_and_saves_the_rates():
    owner = MembershipFactory.create(role=Role.OWNER)
    client = APIClient()
    client.force_authenticate(owner.user)
    current = client.get(reverse("finance-settings")).json()["in_force"]
    assert (current["supplier_withholding_rate"], current["foprolos_rate"]) == ("1.00", None)

    saved = client.post(
        reverse("finance-settings"),
        {
            "vat_rate": "19",
            "fiscal_stamp": "1.000",
            "prices_include_vat": False,
            "withholding_rate": "1",
            "fees_withholding_rate": "3",
            "foprolos_rate": "1",
            "supplier_withholding_rate": "",
        },
        format="json",
    )

    assert saved.status_code == 200
    in_force = saved.json()["in_force"]
    assert (in_force["fees_withholding_rate"], in_force["foprolos_rate"]) == ("3.00", "1.00")
    assert in_force["supplier_withholding_rate"] is None
