import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.core.api.pagination import PagedList
from apps.core.models import Organization


class _View:
    ordering_columns = {"name": ("name",)}


def _page(ordering: str) -> list[str]:
    request = Request(APIRequestFactory().get("/", {"ordering": ordering}))
    page = PagedList().paginate_queryset(Organization.objects.all(), request, _View())
    return [organization.name for organization in page or []]


@pytest.mark.django_db
def test_ordering_sorts_the_whole_list_in_both_directions() -> None:
    for name in ("Beta", "Alpha", "Gamma"):
        Organization.objects.create(name=name)
    assert _page("name") == ["Alpha", "Beta", "Gamma"]
    assert _page("-name") == ["Gamma", "Beta", "Alpha"]


@pytest.mark.django_db
def test_an_unknown_column_keeps_the_default_order() -> None:
    first = Organization.objects.create(name="One")
    second = Organization.objects.create(name="Two")
    assert sorted(_page("password")) == sorted([first.name, second.name])
