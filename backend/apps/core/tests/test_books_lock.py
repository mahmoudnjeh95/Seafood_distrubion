"""The period lock (D-315, P11-T16): a declared month takes no new dated entry; only the owner moves it."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import periods, services
from apps.core.models import AuditLog, Role

from .factories import MembershipFactory, OrganizationFactory

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
LAST_MONTH_END = TODAY.replace(day=1) - dt.timedelta(days=1)


@pytest.fixture
def organization():
    return OrganizationFactory.create()


def client_for(organization, role):
    client = APIClient()
    client.force_authenticate(MembershipFactory.create(organization=organization, role=role).user)
    return client


def test_a_locked_day_refuses_a_record_and_the_next_day_is_open(organization):
    services.set_books_lock(organization=organization, actor=None, until=LAST_MONTH_END)

    with pytest.raises(ValidationError) as refused:
        periods.ensure_open(organization, LAST_MONTH_END, field="spent_on")
    assert set(refused.value.message_dict) == {"spent_on"}
    periods.ensure_open(organization, LAST_MONTH_END + dt.timedelta(days=1), field="spent_on")


def test_nothing_is_locked_by_default(organization):
    assert periods.locked_until(organization) is None
    periods.ensure_open(organization, dt.date(2000, 1, 1))


def test_today_cannot_be_locked(organization):
    with pytest.raises(ValidationError) as refused:
        services.set_books_lock(organization=organization, actor=None, until=TODAY)
    assert set(refused.value.message_dict) == {"until"}


def test_opening_a_declared_period_again_needs_a_reason_and_is_audited(organization):
    services.set_books_lock(organization=organization, actor=None, until=LAST_MONTH_END)

    with pytest.raises(ValidationError) as refused:
        services.set_books_lock(organization=organization, actor=None, until=None)
    assert set(refused.value.message_dict) == {"reason"}

    services.set_books_lock(organization=organization, actor=None, until=None, reason="Correction du comptable")
    assert periods.locked_until(organization) is None
    actions = list(AuditLog.objects.filter(organization=organization).values_list("action", flat=True))
    assert sorted(actions) == ["organization.books_locked", "organization.books_unlocked"]


def test_a_stale_organization_object_still_sees_the_lock(organization):
    stale = type(organization).objects.get(pk=organization.pk)
    services.set_books_lock(organization=organization, actor=None, until=LAST_MONTH_END)

    assert periods.is_locked(stale, LAST_MONTH_END)


def test_a_backfill_of_existing_records_passes_the_lock(organization):
    services.set_books_lock(organization=organization, actor=None, until=LAST_MONTH_END)

    with periods.writing_history():
        periods.ensure_open(organization, LAST_MONTH_END)


def test_the_office_reads_the_lock_and_only_the_owner_moves_it(organization):
    owner = client_for(organization, Role.OWNER)
    manager = client_for(organization, Role.MANAGER)
    accountant = client_for(organization, Role.ACCOUNTANT)
    url = reverse("books-lock")

    assert manager.put(url, {"until": LAST_MONTH_END.isoformat()}, format="json").status_code == 403
    answer = owner.put(url, {"until": LAST_MONTH_END.isoformat()}, format="json")
    assert answer.status_code == 200
    assert answer.json()["until"] == LAST_MONTH_END.isoformat()
    assert accountant.get(url).json()["until"] == LAST_MONTH_END.isoformat()
    assert client_for(organization, Role.DRIVER).get(url).status_code == 403
