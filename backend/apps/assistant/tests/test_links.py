"""Phone links of the WhatsApp assistant (P12-T01)."""

import pytest
from django.core.exceptions import ValidationError

from apps.assistant import access, selectors, services
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("raw", ["+216 22 123 456", "21622123456", "0021622123456", "22123456", "22 123 456"])
def test_normalize_phone_forms(raw):
    assert services.normalize_phone(raw) == "21622123456"


@pytest.mark.parametrize("raw", ["123", "", "abc"])
def test_normalize_phone_refuses_garbage(raw):
    with pytest.raises(ValueError, match="invalide"):
        services.normalize_phone(raw)


def test_link_phone_is_found_by_any_form():
    owner = MembershipFactory.create(role=Role.OWNER)
    services.link_phone(membership=owner, phone="+216 22 123 456", actor=owner.user)
    link = selectors.link_for_phone(services.normalize_phone("22123456"))
    assert link is not None
    assert link.membership == owner


def test_link_replaced_not_duplicated():
    owner = MembershipFactory.create(role=Role.OWNER)
    services.link_phone(membership=owner, phone="22123456", actor=owner.user)
    services.link_phone(membership=owner, phone="98765432", actor=owner.user)
    assert selectors.link_for_phone("21622123456") is None
    link = selectors.link_for_phone("21698765432")
    assert link is not None
    assert link.membership == owner


def test_phone_unique_across_memberships():
    organization = OrganizationFactory.create()
    owner = MembershipFactory.create(organization=organization, role=Role.OWNER)
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    services.link_phone(membership=owner, phone="22123456", actor=owner.user)
    with pytest.raises(ValidationError):
        services.link_phone(membership=driver, phone="+21622123456", actor=owner.user)


def test_inactive_membership_not_found():
    owner = MembershipFactory.create(role=Role.OWNER)
    services.link_phone(membership=owner, phone="22123456", actor=owner.user)
    owner.is_active = False
    owner.save()
    assert selectors.link_for_phone("21622123456") is None


def test_link_is_audited():
    owner = MembershipFactory.create(role=Role.OWNER)
    services.link_phone(membership=owner, phone="22123456", actor=owner.user)
    services.unlink_phone(membership=owner, actor=owner.user)
    actions = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
    assert actions == ["assistant.phone_linked", "assistant.phone_unlinked"]
    assert selectors.link_for_phone("21622123456") is None


@pytest.mark.parametrize(
    ("role", "allowed"),
    [(Role.OWNER, True), (Role.MANAGER, False), (Role.ACCOUNTANT, False), (Role.DRIVER, False)],
)
def test_may_use_owner_only_until_matrix(role, allowed):
    assert access.may_use(MembershipFactory.create(role=role)) is allowed
