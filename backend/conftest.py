"""Shared test setup for every app."""

import pytest

from apps.sales import services as sales_services


@pytest.fixture(autouse=True)
def seller_identity(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every organization's first finance settings carry an address and a tax ID, as an invoice needs them to be
    issued (D-296). A test marked `blank_seller` keeps them empty, as a new organization has them."""
    if request.node.get_closest_marker("blank_seller"):
        return
    monkeypatch.setitem(sales_services.FIRST_SETTINGS, "address", "Route de Tunis km 5, Sakiet Ezzit, Sfax")
    monkeypatch.setitem(sales_services.FIRST_SETTINGS, "tax_id", "1234567/A/M/000")
