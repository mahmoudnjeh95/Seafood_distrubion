"""The TTN e-invoicing settings (P11-T05a, D-310): what TTN needs before the switch can be turned on. Nothing is
sent yet; these tests cover only the settings, their checks, and the audit."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.sales import selectors, services

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


def complete(**extra):
    """Every value TTN needs, with a certificate valid for a year."""
    values = {
        "api_base_url": "https://ttn.example.test",
        "auth_mode": "certificate",
        "certificate_holder": "Frutti del Mare",
        "certificate_expires_on": timezone.localdate() + dt.timedelta(days=365),
    }
    values.update(extra)
    return values


def missing_keys(organization):
    today = timezone.localdate()
    row = selectors.einvoicing_settings_of(organization)
    checks = selectors.einvoicing_checks(row, selectors.finance_settings_on(organization, today), today)
    return {check.key for check in checks if not check.ok}


def test_the_settings_start_off_and_say_what_is_missing(organization):
    row = selectors.einvoicing_settings_of(organization)

    assert row.enabled is False
    assert row.environment == "sandbox"
    # The seller's identity is there (conftest), so only the TTN values are missing.
    assert missing_keys(organization) == {"api_base_url", "auth_mode", "certificate"}


def test_the_switch_is_refused_until_every_check_passes_and_names_what_is_missing(organization, actor):
    with pytest.raises(ValidationError) as refused:
        services.save_einvoicing_settings(organization=organization, actor=actor, enabled=True)

    message = refused.value.message_dict["enabled"][0]
    assert "https" in message or "API" in message or "Certificat" in message
    assert selectors.einvoicing_settings_of(organization).enabled is False


@pytest.mark.blank_seller
def test_the_seller_identity_is_required_before_switching_on(organization, actor):
    with pytest.raises(ValidationError) as refused:
        services.save_einvoicing_settings(organization=organization, actor=actor, enabled=True, **complete())

    message = refused.value.message_dict["enabled"][0]
    assert "Matricule fiscal" in message
    assert "Adresse" in message


def test_the_address_must_be_https(organization, actor):
    with pytest.raises(ValidationError) as refused:
        services.save_einvoicing_settings(
            organization=organization, actor=actor, api_base_url="http://ttn.example.test"
        )

    assert "api_base_url" in refused.value.message_dict


def test_a_complete_setup_switches_on_audited_and_switches_off_at_any_time(organization, actor):
    services.save_einvoicing_settings(organization=organization, actor=actor, enabled=True, **complete())

    row = selectors.einvoicing_settings_of(organization)
    assert row.enabled is True
    assert missing_keys(organization) == set()
    assert AuditLog.objects.filter(action="einvoicing_settings.saved").exists()

    services.save_einvoicing_settings(organization=organization, actor=actor, enabled=False)

    assert selectors.einvoicing_settings_of(organization).enabled is False


def test_client_secret_mode_needs_the_api_identifier(organization, actor):
    values = complete(auth_mode="client_secret")
    with pytest.raises(ValidationError) as refused:
        services.save_einvoicing_settings(organization=organization, actor=actor, enabled=True, **values)
    assert "Identifiant d'API" in refused.value.message_dict["enabled"][0]

    services.save_einvoicing_settings(
        organization=organization, actor=actor, enabled=True, client_id="frutti-sandbox", **values
    )
    assert selectors.einvoicing_settings_of(organization).client_id == "frutti-sandbox"


def test_an_expired_certificate_blocks_the_switch_and_an_expiring_one_warns(organization, actor):
    today = timezone.localdate()
    expired = complete(certificate_expires_on=today - dt.timedelta(days=1))
    with pytest.raises(ValidationError):
        services.save_einvoicing_settings(organization=organization, actor=actor, enabled=True, **expired)

    services.save_einvoicing_settings(
        organization=organization, actor=actor, **complete(certificate_expires_on=today + dt.timedelta(days=10))
    )
    row = selectors.einvoicing_settings_of(organization)
    assert selectors.certificate_expiring_soon(row, today) is True

    services.save_einvoicing_settings(
        organization=organization, actor=actor, **complete(certificate_expires_on=today + dt.timedelta(days=300))
    )
    assert selectors.certificate_expiring_soon(selectors.einvoicing_settings_of(organization), today) is False
