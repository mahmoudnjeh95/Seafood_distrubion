"""The assistant's read tools (P12-T01)."""

import pytest

from apps.assistant import tools
from apps.assistant.api_caller import ApiResult
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def names(membership):
    return {tool.name for tool in tools.tools_for(membership)}


def test_driver_gets_his_tools_not_the_office_ones():
    offered = names(MembershipFactory.create(role=Role.DRIVER))
    assert {"my_stock", "my_truck_day", "find_product"} <= offered
    assert "receivables_ageing" not in offered
    assert "customer_balance" not in offered


def test_owner_gets_office_tools():
    offered = names(MembershipFactory.create(role=Role.OWNER))
    assert {"receivables_ageing", "customer_balance", "stock_overview", "sales_report"} <= offered
    assert "my_stock" not in offered


def test_tool_not_offered_is_not_run(monkeypatch):
    called = []
    monkeypatch.setattr(tools, "call_api", lambda **kwargs: called.append(kwargs))
    driver = MembershipFactory.create(role=Role.DRIVER)
    assert tools.run_tool(driver, "receivables_ageing", {}) == tools.UNAVAILABLE
    assert tools.run_tool(driver, "no_such_tool", {}) == tools.UNAVAILABLE
    assert called == []


@pytest.mark.parametrize(("status", "text"), [(403, tools.REFUSED), (404, tools.NOT_FOUND)])
def test_refusals_are_told_as_data(monkeypatch, status, text):
    monkeypatch.setattr(tools, "call_api", lambda **kwargs: ApiResult(status, {"detail": "secret detail"}))
    owner = MembershipFactory.create(role=Role.OWNER)
    assert tools.run_tool(owner, "customer_balance", {"customer_id": 7}) == text


def test_long_result_is_cut(monkeypatch):
    monkeypatch.setattr(tools, "call_api", lambda **kwargs: ApiResult(200, ["x" * 100] * 500))
    owner = MembershipFactory.create(role=Role.OWNER)
    text = tools.run_tool(owner, "stock_overview", {})
    assert text.endswith("… (tronqué)")
    assert len(text) == tools.MAX_RESULT + len("… (tronqué)")


def test_bad_arguments_are_not_sent(monkeypatch):
    monkeypatch.setattr(tools, "call_api", lambda **kwargs: pytest.fail("must not call the API"))
    owner = MembershipFactory.create(role=Role.OWNER)
    assert tools.run_tool(owner, "customer_balance", {"customer_id": "../users"}) == tools.UNAVAILABLE


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("find_customer", {"query": "Mohamed"}, ("customers", {"search": "Mohamed"})),
        ("customer_balance", {"customer_id": 7}, ("customers/7/balance", {})),
        ("receivables_ageing", {}, ("receivables/ageing", {})),
        ("find_product", {"query": "dorade"}, ("products", {"search": "dorade"})),
        ("stock_overview", {}, ("stock/overview", {})),
        ("product_stock", {"product_id": 3}, ("stock/products/3", {})),
        (
            "sales_report",
            {"date_from": "2026-11-09", "date_to": "2026-11-09", "group_by": "product"},
            ("reports/sales", {"date_from": "2026-11-09", "date_to": "2026-11-09", "group_by": "product"}),
        ),
        ("my_stock", {}, ("my-stock", {})),
        ("my_truck_day", {}, ("my-truck-day", {})),
    ],
)
def test_each_tool_builds_its_request(name, arguments, expected):
    tool = next(tool for tool in tools.READ_TOOLS if tool.name == name)
    assert tool.request(arguments) == expected


def test_real_call_as_owner_reaches_the_endpoint():
    owner = MembershipFactory.create(role=Role.OWNER)
    assert tools.run_tool(owner, "receivables_ageing", {}) not in (tools.REFUSED, tools.NOT_FOUND, tools.UNAVAILABLE)
