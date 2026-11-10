"""A supplier's tax regime and withholding flag (D-312, P11-T10)."""

import pytest
from django.core.exceptions import ValidationError

from apps.core.tests.factories import OrganizationFactory
from apps.partners import services
from apps.partners.models import SupplierTaxRegime

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return OrganizationFactory.create()


def test_a_supplier_without_tax_id_is_always_without_regime(organization):
    supplier = services.create_supplier(
        organization=organization, actor=None, name="Pêcheur Ali", tax_regime=SupplierTaxRegime.REAL
    )

    assert supplier.tax_regime == SupplierTaxRegime.NONE
    assert supplier.subject_to_withholding is True


def test_a_supplier_with_tax_id_is_real_by_default_and_may_be_flat(organization):
    real = services.create_supplier(organization=organization, actor=None, name="Mareyeur", tax_id="1234567A/A/M/000")
    flat = services.create_supplier(
        organization=organization,
        actor=None,
        name="Petit pêcheur",
        tax_id="7654321B",
        tax_regime=SupplierTaxRegime.FLAT,
        subject_to_withholding=False,
    )

    assert real.tax_regime == SupplierTaxRegime.REAL
    assert (flat.tax_regime, flat.subject_to_withholding) == (SupplierTaxRegime.FLAT, False)


def test_an_unknown_regime_is_refused(organization):
    with pytest.raises(ValidationError) as refused:
        services.create_supplier(organization=organization, actor=None, name="X", tax_id="7654321B", tax_regime="odd")
    assert set(refused.value.message_dict) == {"tax_regime"}
