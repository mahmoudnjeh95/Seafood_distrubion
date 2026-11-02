"""The cash limit (D-273, owner: 5 000 DT): a cash line at or above it needs an explicit confirmation, enforced by the
server, recorded on the payment and in the audit; other means are not concerned; the limit is a finance setting."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.partners.tests.factories import CustomerFactory, SupplierFactory
from apps.purchasing import services as purchasing
from apps.sales import services

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(organization=organization, name="Restaurant Le Corail")


def pay(organization, actor, customer, amount, method="cash", **extra):
    return services.record_customer_payment(
        organization=organization,
        actor=actor,
        customer=customer,
        lines=[{"method": method, "amount": amount}],
        **extra,
    )


def test_a_cash_line_at_the_limit_is_refused_until_it_is_confirmed(organization, actor, customer):
    with pytest.raises(ValidationError) as refused:
        pay(organization, actor, customer, "5000.000")

    assert "cash_limit" in refused.value.message_dict


def test_a_cash_line_below_the_limit_goes_through_without_a_flag(organization, actor, customer):
    payment = pay(organization, actor, customer, "4999.999")

    assert payment.cash_limit_confirmed is False


def test_a_confirmed_cash_line_is_recorded_on_the_payment_and_in_the_audit(organization, actor, customer):
    payment = pay(organization, actor, customer, "5000.000", confirm_cash_limit=True)

    assert payment.cash_limit_confirmed is True
    entry = AuditLog.objects.get(action="customer_payment.recorded", target_id=str(payment.pk))
    assert entry.after["cash_limit_confirmed"] is True


def test_a_transfer_above_the_limit_needs_no_confirmation(organization, actor, customer):
    payment = pay(organization, actor, customer, "8000.000", method="transfer")

    assert payment.cash_limit_confirmed is False


def test_the_limit_is_a_setting_the_owner_changes(organization, actor, customer):
    services.save_finance_settings(organization=organization, actor=actor, cash_limit="1000.000")

    with pytest.raises(ValidationError) as refused:
        pay(organization, actor, customer, "1000.000")
    assert "cash_limit" in refused.value.message_dict
    assert pay(organization, actor, customer, "999.999").cash_limit_confirmed is False


def test_the_limit_must_be_above_zero(organization, actor):
    with pytest.raises(ValidationError) as refused:
        services.save_finance_settings(organization=organization, actor=actor, cash_limit="0.000")

    assert "cash_limit" in refused.value.message_dict


def test_a_supplier_payment_follows_the_same_rule(organization, actor):
    supplier = SupplierFactory.create(organization=organization)
    today = timezone.localdate()

    def pay_supplier(**extra):
        return purchasing.record_payment(
            organization=organization,
            actor=actor,
            supplier=supplier,
            paid_on=today,
            amount="5000.000",
            method="cash",
            allocations=[],
            **extra,
        )

    with pytest.raises(ValidationError) as refused:
        pay_supplier()
    assert "cash_limit" in refused.value.message_dict
    assert pay_supplier(confirm_cash_limit=True).cash_limit_confirmed is True
