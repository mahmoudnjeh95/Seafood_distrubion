import pytest
from django.db import IntegrityError

from apps.core import audit
from apps.core.models import AuditLog, Role

from .factories import MembershipFactory, OrganizationFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_scoped_queries_never_return_another_organization_rows():
    ours, theirs = OrganizationFactory.create(), OrganizationFactory.create()
    our_entry = audit.record(organization=ours, actor=None, action="test.ours")
    audit.record(organization=theirs, actor=None, action="test.theirs")

    assert list(AuditLog.objects.for_organization(ours)) == [our_entry]
    assert AuditLog.objects.for_organization(theirs).filter(action="test.ours").count() == 0


def test_scoping_survives_further_filtering_and_ordering():
    ours, theirs = OrganizationFactory.create(), OrganizationFactory.create()
    for organization in (ours, theirs):
        audit.record(organization=organization, actor=None, action="test.shared")

    rows = AuditLog.objects.for_organization(ours).filter(action="test.shared").order_by("id")

    assert {row.organization_id for row in rows} == {ours.id}


def test_a_user_has_one_membership_per_organization():
    membership = MembershipFactory.create()

    with pytest.raises(IntegrityError):
        MembershipFactory.create(user=membership.user, organization=membership.organization, role=Role.DRIVER)


def test_the_four_roles_and_the_custom_one_exist():
    # "custom": a role the owner made in Paramètres › Rôles (D-306).
    assert set(Role.values) == {"owner", "manager", "driver", "accountant", "custom"}


def test_users_default_to_french_and_can_choose_arabic():
    assert UserFactory.create().language == "fr"
    assert UserFactory.create(language="ar").language == "ar"
