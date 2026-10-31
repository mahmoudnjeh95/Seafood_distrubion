"""Only the office corrects a driver's day (D-220): the driver does not send a sent day again, and each office
correction is a tracked revision (who, when, why, the figures before and after)."""

import pytest
from django.urls import reverse

from apps.dayclose.models import DayClosing, DayClosingRevision, DayClosingStatus
from apps.dayclose.tests.test_dayclose import day as base_day
from apps.dayclose.tests.test_dayclose import sell

pytestmark = pytest.mark.django_db


@pytest.fixture
def day(base_day):
    """A driver with a loaded truck and the day started, as in test_dayclose."""
    return base_day


def send(day):
    return day["api"].post(reverse("my-day-closing"), {"note": ""}, format="json")


def closing_of(day) -> DayClosing:
    return DayClosing.objects.get(organization=day["organization"])


def moved(closing: DayClosing) -> None:
    """The records now differ from what was sent (a sale received after the send, D-132): the sent expected cash is
    set aside, so the comparison with the records finds a change."""
    DayClosing.objects.filter(pk=closing.pk).update(summary={**closing.summary, "expected_cash": "1.000"})


def test_the_driver_does_not_send_a_sent_day_again_once_its_records_moved(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    moved(closing_of(day))

    again = send(day)

    assert again.status_code == 403
    assert "bureau corrige" in again.json()["detail"]


def test_the_driver_cannot_send_again_after_a_justification_once_the_records_moved(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    asked = day["office"].post(
        reverse("day-closing-justification", args=[closing.pk]), {"reason": "Expliquez la vente"}, format="json"
    )
    assert asked.status_code == 200
    moved(closing)

    assert send(day).status_code == 403


def test_the_driver_sends_again_after_a_justification_when_nothing_moved(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    day["office"].post(
        reverse("day-closing-justification", args=[closing.pk]), {"reason": "Expliquez la vente"}, format="json"
    )

    assert send(day).status_code == 201
    closing.refresh_from_db()
    assert closing.status == DayClosingStatus.SUBMITTED


def test_the_office_corrects_a_moved_day_and_the_correction_is_a_revision(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    moved(closing)

    response = day["office"].post(
        reverse("day-closing-correct", args=[closing.pk]), {"reason": "Vente oubliée"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changed_since_sent"] is False
    assert [(r["number"], r["reason"]) for r in body["revisions"]] == [(1, "Vente oubliée")]
    assert body["revisions"][0]["actor_name"] != ""
    revision = DayClosingRevision.objects.get(closing=closing)
    assert (revision.before["expected_cash"], revision.after["expected_cash"]) == ("1.000", "150.000")


def test_a_correction_needs_a_reason_and_a_change(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    url = reverse("day-closing-correct", args=[closing.pk])

    assert day["office"].post(url, {"reason": " "}, format="json").status_code == 400
    # Nothing moved and no count given: there is nothing to correct.
    assert day["office"].post(url, {"reason": "Pour rien"}, format="json").status_code == 400
    assert DayClosingRevision.objects.count() == 0


def test_a_saved_count_changes_only_by_a_correction(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    counted = day["office"].post(
        reverse("day-closing-count", args=[closing.pk]), {"office_counted_cash": "150.000"}, format="json"
    )
    assert counted.status_code == 200

    recount = day["office"].post(
        reverse("day-closing-count", args=[closing.pk]), {"office_counted_cash": "140.000"}, format="json"
    )
    corrected = day["office"].post(
        reverse("day-closing-correct", args=[closing.pk]),
        {"reason": "Compté deux fois", "office_counted_cash": "140.000"},
        format="json",
    )

    assert recount.status_code == 400
    assert corrected.status_code == 200
    body = corrected.json()
    assert (body["office_counted_cash"], body["office_difference"]) == ("140.000", "-10.000")
    revision = DayClosingRevision.objects.get(closing=closing)
    assert (revision.before["office_counted_cash"], revision.after["office_counted_cash"]) == ("150.000", "140.000")


def test_the_office_cannot_approve_a_moved_day_before_correcting_it(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    moved(closing)

    approved = day["office"].post(
        reverse("day-closing-approve", args=[closing.pk]), {"office_counted_cash": "150.000"}, format="json"
    )

    assert approved.status_code == 400
    closing.refresh_from_db()
    assert closing.status == DayClosingStatus.SUBMITTED


def test_only_the_office_corrects_a_day(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    moved(closing)

    response = day["api"].post(
        reverse("day-closing-correct", args=[closing.pk]), {"reason": "Je corrige"}, format="json"
    )

    assert response.status_code == 403


def test_a_day_a_new_load_reopened_is_not_corrected_on_its_old_send(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    DayClosing.objects.filter(pk=closing.pk).update(status=DayClosingStatus.REOPENED)

    response = day["office"].post(
        reverse("day-closing-correct", args=[closing.pk]), {"reason": "Trop tard"}, format="json"
    )

    assert response.status_code == 400
