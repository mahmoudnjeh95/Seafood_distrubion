import datetime as dt
import threading
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import services as stock
from apps.inventory.models import Batch, MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners import services as partners
from apps.partners.tests.factories import CustomerFactory
from apps.sales import selectors, services
from apps.sales.models import CreditNoteKind, FinanceSettings, Invoice, InvoiceStatus, SaleLineBatch, SaleStatus

pytestmark = pytest.mark.django_db

D = Decimal
YEAR = timezone.localdate().year


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(
        organization=organization,
        name="Restaurant Le Corail",
        address="Avenue Hédi Chaker",
        city="Sfax",
        tax_id="0000101A/A/M/000",
        payment_terms_days=30,
    )


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


def product(organization, name, reference, price, vat_rate=None):
    item = ProductFactory.create(organization=organization, name=name, reference=reference, vat_rate=vat_rate)
    ProductPriceFactory.create(product=item, price=D(price), valid_from=timezone.now() - dt.timedelta(days=30))
    return item


@pytest.fixture
def crevette(organization):
    return product(organization, "Crevette Royale", "CR-001", "42.000")


@pytest.fixture
def dorade(organization):
    return product(organization, "Dorade royale", "DO-003", "24.500")


def receive(organization, item, location, kg, *, cost="20.000"):
    batch = BatchFactory.create(organization=organization, product=item, unit_cost=D(cost))
    stock.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity=kg, to_location=location
    )
    return batch


def confirmed_sale(organization, actor, customer, location, lines):
    for line in lines:
        receive(organization, line["product"], location, D(line["quantity"]) + 10)
    return services.create_sale(
        organization=organization, actor=actor, customer=customer, location=location, lines=lines, confirm=True
    )


@pytest.fixture
def sale(organization, actor, customer, counter, crevette, dorade):
    """The sample invoice's first two lines: 5 kg × 42.000 + 10 kg × 24.500 = 455.000 without VAT."""
    return confirmed_sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "5"}, {"product": dorade, "quantity": "10"}],
    )


def settings_of(organization) -> FinanceSettings:
    version = selectors.finance_settings_on(organization)
    assert version is not None
    return version


# ---- finance settings ----


def test_a_new_organization_starts_with_the_answers_of_q5(organization):
    version = settings_of(organization)

    assert version.vat_rate == D("19.00")
    assert version.fiscal_stamp == D("1.000")
    assert version.prices_include_vat is False
    assert version.withholding_rate == D("0.00")
    assert version.legal_name == organization.name
    assert version.valid_from <= timezone.localdate()


def test_settings_change_from_a_day_and_keep_their_history(organization, actor):
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    services.save_finance_settings(
        organization=organization, actor=actor, valid_from=tomorrow, vat_rate="7", withholding_rate="1.5"
    )

    assert settings_of(organization).vat_rate == D("19.00")
    planned = selectors.finance_settings_on(organization, tomorrow)
    assert planned is not None
    assert planned.vat_rate == D("7.00")
    assert planned.withholding_rate == D("1.50")
    # Values not given are kept from the version in force.
    assert planned.fiscal_stamp == D("1.000")
    assert selectors.finance_settings_history(organization).count() == 2
    assert AuditLog.objects.filter(action="finance_settings.saved").count() == 1


def test_saving_the_same_day_again_replaces_that_version(organization, actor):
    services.save_finance_settings(organization=organization, actor=actor, fiscal_stamp="0.600")
    services.save_finance_settings(organization=organization, actor=actor, fiscal_stamp="1.000", tax_id="1234567A")

    today = FinanceSettings.objects.filter(organization=organization, valid_from=timezone.localdate())
    assert today.count() == 1
    assert today.get().tax_id == "1234567A"


def test_settings_refuse_the_past_and_wrong_values_field_by_field(organization, actor):
    with pytest.raises(ValidationError) as refused:
        services.save_finance_settings(
            organization=organization,
            actor=actor,
            valid_from=timezone.localdate() - dt.timedelta(days=1),
            vat_rate="101",
            withholding_rate="1.234",
            fiscal_stamp="0.0005",
        )

    assert set(refused.value.message_dict) == {"valid_from", "vat_rate", "withholding_rate", "fiscal_stamp"}


# ---- drafts ----


def test_a_draft_takes_the_sale_lines_and_the_settings(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor)

    assert invoice.status == InvoiceStatus.DRAFT
    assert invoice.number == ""
    lines = list(invoice.lines.order_by("id"))
    assert [(line.product_reference, line.quantity, line.unit_price, line.amount) for line in lines] == [
        ("CR-001", D("5.000"), D("42.000"), D("210.000")),
        ("DO-003", D("10.000"), D("24.500"), D("245.000")),
    ]
    assert lines[0].lots != ""
    assert all(line.vat_rate == D("19.00") and not line.vat_rate_overridden for line in lines)
    assert invoice.total_excl_tax == D("455.000")
    assert invoice.vat_total == D("86.450")
    assert invoice.fiscal_stamp == D("1.000")
    assert invoice.total_incl_tax == D("542.450")
    assert invoice.net_to_pay == D("542.450")
    assert invoice.withholding_amount == D("0.000")
    # The sale is not touched until the invoice is issued.
    sale.refresh_from_db()
    assert sale.tax_amount is None
    assert sale.total == D("455.000")


def test_an_exempt_product_has_its_own_rate(organization, actor, customer, counter, crevette):
    sardine = product(organization, "Sardine", "SA-010", "6.000", vat_rate=D("0.00"))
    invoice = services.create_invoice(
        sale=confirmed_sale(
            organization,
            actor,
            customer,
            counter,
            [{"product": crevette, "quantity": "5"}, {"product": sardine, "quantity": "10"}],
        ),
        actor=actor,
    )

    rates = {row.rate: (row.base, row.amount) for row in invoice.vat_lines.all()}
    assert rates == {D("19.00"): (D("210.000"), D("39.900")), D("0.00"): (D("60.000"), D("0.000"))}
    assert invoice.vat_total == D("39.900")


def test_prices_including_vat_come_from_the_settings(organization, actor, sale):
    services.save_finance_settings(organization=organization, actor=actor, prices_include_vat=True)

    invoice = services.create_invoice(sale=sale, actor=actor)

    assert invoice.prices_include_vat is True
    # 455.000 / 1.19 = 382.352...
    assert invoice.total_excl_tax == D("382.353")
    assert invoice.vat_total == D("72.647")
    assert invoice.total_incl_tax == D("456.000")


def test_an_invoice_without_vat(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, apply_vat=False)

    assert invoice.apply_vat is False
    assert invoice.vat_lines.count() == 0
    assert invoice.vat_total == D("0.000")
    assert invoice.total_incl_tax == D("456.000")


def test_goods_bought_with_vat_are_never_invoiced_without_it(sale, actor):
    Batch.objects.filter(pk__in=SaleLineBatch.objects.filter(line__sale=sale).values("batch")).update(
        bought_with_vat=True
    )
    draft = services.create_invoice(sale=sale, actor=actor, apply_vat=False)

    with pytest.raises(ValidationError) as refused:
        services.issue_invoice(invoice=draft, actor=actor)

    assert "TVA" in refused.value.message_dict["apply_vat"][0]
    assert services.issue_invoice(invoice=services.update_invoice(invoice=draft, actor=actor), actor=actor).number


def test_typed_values_are_flagged_and_audited(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor)
    services.update_invoice(
        invoice=invoice,
        actor=actor,
        vat_rates=["7", ""],
        vat_amounts={"19": "46.000"},
        fiscal_stamp="0.600",
        withholding_applied=True,
        withholding_rate="1.5",
        notes="Livraison du matin",
    )
    invoice.refresh_from_db()

    lines = list(invoice.lines.order_by("id"))
    assert (lines[0].vat_rate, lines[0].vat_rate_overridden) == (D("7.00"), True)
    assert (lines[1].vat_rate, lines[1].vat_rate_overridden) == (D("19.00"), False)
    vat = {row.rate: row for row in invoice.vat_lines.all()}
    assert vat[D("7.00")].amount == D("14.700")
    assert (vat[D("19.00")].computed_amount, vat[D("19.00")].amount) == (D("46.550"), D("46.000"))
    assert vat[D("19.00")].amount_overridden
    assert (invoice.fiscal_stamp, invoice.fiscal_stamp_overridden) == (D("0.600"), True)
    assert (invoice.withholding_rate, invoice.withholding_rate_overridden) == (D("1.50"), True)
    assert invoice.total_incl_tax == D("455.000") + D("60.700") + D("0.600")
    # (455.000 + 60.700) × 1.5 % = 7.7355 → 7.736
    assert invoice.withholding_amount == D("7.736")
    assert invoice.net_to_pay == invoice.total_incl_tax - D("7.736")
    entry = AuditLog.objects.get(action="invoice.updated")
    assert entry.after is not None
    assert entry.after["overrides"]["vat_amounts"] == {"19.00": {"computed": "46.550", "typed": "46.000"}}
    assert entry.after["overrides"]["fiscal_stamp"] == "0.600"


def test_typing_the_settings_value_is_not_an_override(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, vat_rates=["19", "19"], fiscal_stamp="1.000")

    assert not invoice.fiscal_stamp_overridden
    assert not invoice.lines.filter(vat_rate_overridden=True).exists()


def test_wrong_typed_values_come_back_on_their_field(sale, actor):
    with pytest.raises(ValidationError) as refused:
        services.create_invoice(
            sale=sale,
            actor=actor,
            vat_rates=["120", "x"],
            fiscal_stamp="-1",
            fees="abc",
            withholding_rate="1.555",
        )

    assert set(refused.value.message_dict) == {
        "lines.0.vat_rate",
        "lines.1.vat_rate",
        "fiscal_stamp",
        "fees",
        "withholding_rate",
    }


def test_a_typed_vat_amount_above_its_lines_is_refused(sale, actor):
    with pytest.raises(ValidationError) as refused:
        services.create_invoice(sale=sale, actor=actor, vat_amounts={"19": "999.000"})

    assert "vat_amounts.19.00" in refused.value.message_dict


def test_withholding_with_a_zero_rate_shows_nothing(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, withholding_applied=True)

    assert invoice.withholding_rate == D("0.00")
    assert invoice.withholding_amount == D("0.000")
    assert invoice.net_to_pay == invoice.total_incl_tax


def test_only_a_confirmed_sale_with_a_named_customer_is_invoiced_once(
    organization, actor, customer, counter, crevette, sale
):
    draft = services.create_sale(
        organization=organization,
        actor=actor,
        customer=customer,
        location=counter,
        lines=[{"product": crevette, "quantity": "1"}],
    )
    with pytest.raises(ValidationError, match="confirmée"):
        services.create_invoice(sale=draft, actor=actor)

    walk_in_sale = services.create_sale(
        organization=organization,
        actor=actor,
        customer=partners.ensure_walk_in_customer(organization=organization, actor=actor),
        location=counter,
        lines=[{"product": crevette, "quantity": "1"}],
        payment={"paid_in_full": True, "payment_method": "cash"},
        confirm=True,
    )
    with pytest.raises(ValidationError) as refused:
        services.create_invoice(sale=walk_in_sale, actor=actor)
    assert "customer" in refused.value.message_dict

    services.create_invoice(sale=sale, actor=actor)
    with pytest.raises(ValidationError, match="déjà sa facture"):
        services.create_invoice(sale=sale, actor=actor)


def test_a_draft_can_be_deleted(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor)
    services.delete_invoice(invoice=invoice, actor=actor)

    assert not Invoice.objects.exists()
    assert services.create_invoice(sale=sale, actor=actor).status == InvoiceStatus.DRAFT


# ---- issuing ----


def test_issuing_numbers_freezes_and_copies(organization, actor, customer, sale):
    services.save_finance_settings(
        organization=organization, actor=actor, legal_name="Frutti Del Mare SARL", tax_id="0000000A/A/M/000"
    )
    invoice = services.create_invoice(sale=sale, actor=actor, issue=True)

    assert invoice.status == InvoiceStatus.ISSUED
    assert invoice.number == f"FA-{YEAR}-0001"
    assert invoice.issued_on == timezone.localdate()
    assert invoice.due_on == timezone.localdate() + dt.timedelta(days=30)
    assert (invoice.seller_name, invoice.seller_tax_id) == ("Frutti Del Mare SARL", "0000000A/A/M/000")
    assert (invoice.customer_name, invoice.customer_city, invoice.customer_tax_id) == (
        "Restaurant Le Corail",
        "Sfax",
        "0000101A/A/M/000",
    )
    assert invoice.einvoice_status == "not_sent"
    assert invoice.einvoice_reference == ""
    sale.refresh_from_db()
    assert sale.tax_amount == D("86.450")
    assert sale.total == D("455.000")
    assert AuditLog.objects.filter(action="invoice.issued").count() == 1

    # A later change of the customer or the settings never touches it.
    customer.name = "Le Corail (nouveau nom)"
    customer.save()
    services.save_finance_settings(organization=organization, actor=actor, vat_rate="7")
    invoice.refresh_from_db()
    assert invoice.customer_name == "Restaurant Le Corail"
    assert invoice.vat_total == D("86.450")


def test_an_issued_invoice_never_changes(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, issue=True)

    with pytest.raises(ValidationError, match="avoir"):
        services.update_invoice(invoice=invoice, actor=actor, apply_vat=False)
    with pytest.raises(ValidationError, match="avoir"):
        services.delete_invoice(invoice=invoice, actor=actor)
    with pytest.raises(ValidationError, match="avoir"):
        services.issue_invoice(invoice=invoice, actor=actor)


def test_issuing_takes_the_settings_in_force_then_but_keeps_what_was_typed(organization, actor, sale):
    invoice = services.create_invoice(sale=sale, actor=actor, fiscal_stamp="0.500")
    services.save_finance_settings(organization=organization, actor=actor, vat_rate="7", fiscal_stamp="2.000")

    invoice = services.issue_invoice(invoice=invoice, actor=actor)

    assert invoice.vat_total == D("31.850")
    assert invoice.fiscal_stamp == D("0.500")
    assert invoice.fiscal_stamp_overridden


def test_numbers_follow_each_other_and_a_failed_issue_uses_none(
    organization, actor, customer, counter, crevette, sale, monkeypatch
):
    other = confirmed_sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "2"}])
    first = services.create_invoice(sale=sale, actor=actor)
    second = services.create_invoice(sale=other, actor=actor)

    def broken(invoice):
        raise RuntimeError("printer on fire")

    monkeypatch.setattr(services, "record_invoice_receivable", broken)
    with pytest.raises(RuntimeError):
        services.issue_invoice(invoice=first, actor=actor)
    monkeypatch.undo()

    first.refresh_from_db()
    assert first.status == InvoiceStatus.DRAFT
    assert first.number == ""
    assert services.issue_invoice(invoice=second, actor=actor).number == f"FA-{YEAR}-0001"
    assert services.issue_invoice(invoice=first, actor=actor).number == f"FA-{YEAR}-0002"


def test_each_organization_has_its_own_series(actor, counter):
    other_org = OrganizationFactory.create()
    other_location = StockLocationFactory.create(organization=other_org, counter_sales=True)
    item = product(other_org, "Calamar", "CA-005", "29.000")
    other_customer = CustomerFactory.create(organization=other_org)
    other_sale = confirmed_sale(other_org, actor, other_customer, other_location, [{"product": item, "quantity": "1"}])

    assert services.create_invoice(sale=other_sale, actor=actor, issue=True).number == f"FA-{YEAR}-0001"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_invoices_issued_at_once_never_share_a_number_nor_skip_one():
    organization = OrganizationFactory.create()
    customer = CustomerFactory.create(organization=organization)
    location = StockLocationFactory.create(organization=organization, counter_sales=True)
    item = product(organization, "Crevette Royale", "CR-001", "42.000")
    drafts = [
        services.create_invoice(
            sale=confirmed_sale(organization, None, customer, location, [{"product": item, "quantity": "1"}]),
            actor=None,
        )
        for _ in range(4)
    ]
    numbers: list[str] = []
    failures: list[BaseException] = []

    def issue(invoice: Invoice) -> None:
        try:
            numbers.append(services.issue_invoice(invoice=invoice, actor=None).number)
        except BaseException as error:  # noqa: BLE001 - reported below
            failures.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=issue, args=(draft,)) for draft in drafts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert sorted(numbers) == [f"FA-{YEAR}-{n:04d}" for n in range(1, 5)]


# ---- credit notes ----


def test_a_full_credit_note_cancels_the_invoice(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, issue=True)

    note = services.create_credit_note(
        invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Erreur de client"
    )

    assert note.number == f"AV-{YEAR}-0001"
    assert note.total_excl_tax == D("455.000")
    assert note.vat_total == D("86.450")
    assert note.fiscal_stamp == D("1.000")
    assert note.net_amount == D("542.450")
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.CANCELLED
    sale.refresh_from_db()
    assert sale.tax_amount is None
    # The sale may be invoiced again, with the next number.
    again = services.create_invoice(sale=sale, actor=actor, issue=True)
    assert again.number == f"FA-{YEAR}-0002"
    with pytest.raises(ValidationError, match="déjà annulée"):
        services.create_credit_note(invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Encore")


def test_fees_add_to_the_total_outside_vat_and_withholding(organization, sale, actor):
    services.save_finance_settings(organization=organization, actor=actor, withholding_rate="1.5")
    invoice = services.create_invoice(sale=sale, actor=actor, fees="12.500", withholding_applied=True)

    assert invoice.fees == D("12.500")
    assert invoice.vat_total == D("86.450")  # no VAT on the fees
    assert invoice.total_incl_tax == D("554.950")  # 455 + 86.450 + 1 stamp + 12.500 fees
    assert invoice.withholding_amount == D("8.122")  # 1.5 % of 541.450, fees left out
    assert invoice.net_to_pay == D("546.828")
    # Issuing keeps them; saving the draft again without them removes them.
    issued = services.update_invoice(invoice=invoice, actor=actor, issue=True, fees="12.500", withholding_applied=True)
    assert (issued.fees, issued.total_incl_tax) == (D("12.500"), D("554.950"))
    entry = AuditLog.objects.filter(action="invoice.issued").latest("id")
    assert entry.after is not None
    assert entry.after["fees"] == "12.500"


def test_saving_a_draft_without_fees_removes_them(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, fees="5")

    invoice = services.update_invoice(invoice=invoice, actor=actor)

    assert invoice.fees == D("0.000")
    assert invoice.total_incl_tax == D("542.450")


def test_a_full_credit_note_gives_the_fees_back_a_partial_one_does_not(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, fees="10", issue=True)
    crevette_line = invoice.lines.order_by("id").first()

    partial = services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Casse",
        lines=[{"invoice_line": crevette_line, "quantity": "1"}],
    )
    full = services.create_credit_note(invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Erreur")

    assert partial.fees == D("0.000")
    assert full.fees == D("10.000")
    assert partial.net_amount + full.net_amount == invoice.net_to_pay


def test_a_partial_credit_note_by_kilos_and_by_amount(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, issue=True)
    crevette_line, dorade_line = list(invoice.lines.order_by("id"))

    note = services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Retour et geste commercial",
        lines=[
            {"invoice_line": crevette_line, "quantity": "1"},
            {"invoice_line": dorade_line, "amount": "10.000"},
        ],
    )

    rows = list(note.lines.order_by("id"))
    assert [(row.quantity, row.amount_excl_tax, row.vat_amount) for row in rows] == [
        (D("1.000"), D("42.000"), D("7.980")),
        (D("0.000"), D("10.000"), D("1.900")),
    ]
    assert note.fiscal_stamp == D("0.000")
    assert note.net_amount == D("61.880")
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.ISSUED

    # The rest of a line, then a full note: everything adds up to the invoice exactly.
    services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Reste des crevettes",
        lines=[{"invoice_line": crevette_line, "quantity": "4"}],
    )
    last = services.create_credit_note(invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Annulation")
    totals = invoice.credit_notes.all()
    assert sum(n.total_excl_tax for n in totals) == invoice.total_excl_tax
    assert sum(n.vat_total for n in totals) == invoice.vat_total
    assert sum(n.net_amount for n in totals) == invoice.net_to_pay
    assert last.lines.count() == 1


def test_a_credit_note_never_gives_back_more_than_the_line(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, issue=True)
    line = invoice.lines.order_by("id").first()

    with pytest.raises(ValidationError) as refused:
        services.create_credit_note(
            invoice=invoice,
            actor=actor,
            kind=CreditNoteKind.PARTIAL,
            reason="Trop",
            lines=[{"invoice_line": line, "quantity": "6"}, {"invoice_line": line, "amount": "1"}],
        )
    assert set(refused.value.message_dict) == {"lines.0.quantity", "lines.1.invoice_line"}

    with pytest.raises(ValidationError) as refused:
        services.create_credit_note(
            invoice=invoice,
            actor=actor,
            kind=CreditNoteKind.PARTIAL,
            reason="Trop",
            lines=[{"invoice_line": line, "amount": "210.001"}],
        )
    assert "lines.0.amount" in refused.value.message_dict


def test_a_credit_note_needs_an_issued_invoice_and_a_reason(sale, actor):
    draft = services.create_invoice(sale=sale, actor=actor)
    with pytest.raises(ValidationError, match="brouillon"):
        services.create_credit_note(invoice=draft, actor=actor, kind=CreditNoteKind.FULL, reason="x")

    issued = services.issue_invoice(invoice=draft, actor=actor)
    with pytest.raises(ValidationError) as refused:
        services.create_credit_note(invoice=issued, actor=actor, kind=CreditNoteKind.FULL, reason="  ")
    assert "reason" in refused.value.message_dict


def test_withholding_is_given_back_in_proportion(organization, actor, sale):
    services.save_finance_settings(organization=organization, actor=actor, withholding_rate="1.5")
    invoice = services.create_invoice(sale=sale, actor=actor, withholding_applied=True, issue=True)
    assert invoice.withholding_amount == D("8.122")  # (455 + 86.450) × 1.5 % = 8.12175

    line = invoice.lines.order_by("id").first()
    note = services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Retour",
        lines=[{"invoice_line": line, "quantity": "5"}],
    )
    # (210 + 39.900) × 1.5 % = 3.7485 → 3.749
    assert note.withholding_amount == D("3.749")
    rest = services.create_credit_note(invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Annulation")
    assert rest.withholding_amount == D("4.373")


# ---- the sale side ----


def test_an_invoiced_sale_is_cancelled_only_after_a_credit_note(sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, issue=True)

    with pytest.raises(ValidationError, match="avoir"):
        services.cancel_sale(sale=sale, actor=actor, reason="Erreur")

    services.create_credit_note(invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Erreur")
    assert services.cancel_sale(sale=sale, actor=actor, reason="Erreur").status == SaleStatus.CANCELLED


def test_cancelling_a_sale_throws_its_draft_invoice_away(sale, actor):
    services.create_invoice(sale=sale, actor=actor)

    services.cancel_sale(sale=sale, actor=actor, reason="Erreur")

    assert not Invoice.objects.exists()
    assert AuditLog.objects.filter(action="invoice.deleted").count() == 1


def test_lists_and_live_invoice(organization, sale, actor):
    invoice = services.create_invoice(sale=sale, actor=actor, issue=True)
    services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Retour",
        lines=[{"invoice_line": invoice.lines.order_by("id").first(), "quantity": "1"}],
    )

    listed = selectors.invoice_of(organization, invoice.pk)
    assert getattr(listed, "credited_total") == D("49.980")  # noqa: B009 - an annotation
    assert selectors.invoices_of(organization, search="Corail").count() == 1
    assert selectors.invoices_of(organization, status="draft").count() == 0
    assert selectors.live_invoice_of(selectors.sale_of(organization, sale.pk)) == invoice
    assert selectors.credit_notes_of(organization).count() == 1


# ---- one invoice for several BL (D-096) ----


def second_sale(organization, actor, customer, counter, crevette):
    return confirmed_sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "2"}])


def test_one_invoice_bills_several_delivery_notes_of_the_same_customer(
    organization, actor, customer, counter, crevette, sale
):
    other = second_sale(organization, actor, customer, counter, crevette)

    invoice = services.create_invoice(sales=[other, sale], actor=actor, issue=True)

    # 455.000 + 2 × 42.000 = 539.000 without VAT, one stamp for the whole invoice.
    assert [row.number for row in invoice.sales.order_by("sold_at", "id")] == [sale.number, other.number]
    assert (invoice.total_excl_tax, invoice.vat_total, invoice.fiscal_stamp) == (D("539.000"), D("102.410"), D("1.000"))
    assert invoice.lines.count() == 3
    assert {row.sale_line.sale_id for row in invoice.lines.all()} == {sale.pk, other.pk}
    sale.refresh_from_db()
    other.refresh_from_db()
    # The VAT and what is owed are shared over the BLs by what each one holds on the invoice.
    assert sale.tax_amount + other.tax_amount == invoice.vat_total
    assert sale.amount_due + other.amount_due == invoice.net_to_pay
    assert sale.amount_due > other.amount_due > 0


def test_a_delivery_note_is_on_one_live_invoice_only(organization, actor, customer, counter, crevette, sale):
    other = second_sale(organization, actor, customer, counter, crevette)
    services.create_invoice(sale=sale, actor=actor)

    with pytest.raises(ValidationError, match="déjà sa facture"):
        services.create_invoice(sales=[other, sale], actor=actor)

    assert Invoice.objects.count() == 1


def test_an_invoice_does_not_mix_customers(organization, actor, customer, counter, crevette, sale):
    stranger = CustomerFactory.create(organization=organization, name="Poissonnerie El Bahr")
    other = confirmed_sale(organization, actor, stranger, counter, [{"product": crevette, "quantity": "1"}])

    with pytest.raises(ValidationError, match="même client"):
        services.create_invoice(sales=[sale, other], actor=actor)


def test_a_full_credit_note_frees_every_delivery_note_of_the_invoice(
    organization, actor, customer, counter, crevette, sale
):
    other = second_sale(organization, actor, customer, counter, crevette)
    invoice = services.create_invoice(sales=[sale, other], actor=actor, issue=True)

    services.create_credit_note(invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Erreur")

    sale.refresh_from_db()
    other.refresh_from_db()
    assert (sale.tax_amount, other.tax_amount) == (None, None)
    # Credited in full: the cancelled invoice and its credit note cancel each other, as for a single BL.
    assert (sale.amount_due, other.amount_due) == (D("0.000"), D("0.000"))
    again = services.create_invoice(sales=[sale, other], actor=actor)
    assert again.status == InvoiceStatus.DRAFT


def test_the_delivery_notes_still_to_invoice_are_listed(organization, actor, customer, counter, crevette, sale):
    other = second_sale(organization, actor, customer, counter, crevette)
    services.create_invoice(sale=sale, actor=actor)

    open_ones = selectors.sales_of(organization, uninvoiced=True)

    assert list(open_ones) == [other]
