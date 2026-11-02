"""A payment order sent to one person (D-255): only they see it; the whole office's notifications are unchanged."""

import pytest

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.notifications import selectors, services

pytestmark = pytest.mark.django_db


@pytest.fixture
def team():
    owner = MembershipFactory.create(role=Role.OWNER)
    organization = owner.organization
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    other = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    accountant = MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT)
    return owner, manager, other, accountant


def send(owner, manager):
    return services.tell_person(
        organization=owner.organization,
        actor=owner.user,
        recipient=manager.user,
        kind="payment_order",
        params={"supplier": "Mareyeur", "amount": "100.000"},
    )


def test_only_the_person_told_sees_the_payment_order(team):
    owner, manager, other, accountant = team
    send(owner, manager)

    assert [row.kind for row in selectors.latest_for(manager)] == ["payment_order"]
    assert selectors.latest_for(other) == []
    assert selectors.latest_for(accountant) == []
    assert selectors.latest_for(owner) == []  # their own action


def test_a_notification_for_the_whole_office_is_still_seen_by_every_owner_and_manager(team):
    owner, manager, other, _accountant = team
    services.tell_office_of(organization=owner.organization, actor=None, kind="effet_unpaid", params={})

    assert len(selectors.latest_for(manager)) == len(selectors.latest_for(other)) == 1


def test_the_people_a_payment_order_can_go_to_are_the_active_owners_and_managers(team):
    owner, manager, other, accountant = team

    ids = set(selectors.office_recipients(owner.organization).values_list("user_id", flat=True))

    assert ids == {owner.user_id, manager.user_id, other.user_id}
    assert accountant.user_id not in ids
