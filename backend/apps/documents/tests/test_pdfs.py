import datetime as dt
import io
from decimal import Decimal

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.documents import rendering, services
from apps.documents.models import GeneratedDocument
from apps.documents.templatetags.pdf_format import kilos, money, one_line, percent, quantity, rate
from apps.documents.words import dinars_in_words, number_in_words
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerContactFactory, CustomerFactory
from apps.sales import services as sales
from apps.sales.models import CreditNoteKind, CreditNoteStock, FinanceSettings, SalePaymentMethod
from apps.sales.printing import customer_type, unique_identifier

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture(autouse=True)
def storage(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture(autouse=True)
def commit_at_once(monkeypatch):
    """The tests run inside a transaction that never commits: run `on_commit` callbacks straight away."""
    monkeypatch.setattr(transaction, "on_commit", lambda func, using=None, robust=False: func())


@pytest.fixture(autouse=True)
def fake_pdf(monkeypatch):
    """Rendering needs Pango, which not every machine has: the logic is tested with a stand-in renderer, and
    `test_the_real_renderer_makes_a_pdf` covers WeasyPrint where it loads."""
    calls = []

    def render(html: str) -> bytes:
        calls.append(html)
        return b"%PDF-1.7 fake " + str(len(calls)).encode()

    monkeypatch.setattr(rendering, "html_to_pdf", render)
    return calls


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


@pytest.fixture
def api(manager):
    client = APIClient()
    client.force_authenticate(manager.user)
    return client


@pytest.fixture
def setup(organization, manager):
    customer = CustomerFactory.create(
        organization=organization, name="Restaurant Le Corail", address="Avenue Hédi Chaker", city="Sfax"
    )
    counter = StockLocationFactory.create(organization=organization, counter_sales=True)
    crevette = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(product=crevette, price=D("42.000"), valid_from=timezone.now() - dt.timedelta(days=30))
    batch = BatchFactory.create(organization=organization, product=crevette, unit_cost=D("20.000"))
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("50"),
        to_location=counter,
    )
    return customer, counter, crevette


@pytest.fixture
def sale(organization, manager, setup):
    customer, counter, crevette = setup
    return sales.create_sale(
        organization=organization,
        actor=manager.user,
        customer=customer,
        location=counter,
        lines=[{"product": crevette, "quantity": "5"}],
        confirm=True,
    )


@pytest.fixture
def invoice(sale, manager):
    return sales.create_invoice(sale=sale, actor=manager.user, issue=True)


def url(kind, object_id, **query):
    suffix = "".join(f"?{key}={value}" for key, value in query.items())
    return reverse("document-pdf", args=[kind, object_id]) + suffix


# ---- formats ----


def test_amounts_use_a_comma_and_thin_spaces():
    assert money(D("1234567.5")) == "1 234 567,500"
    assert money(D("-0.250")) == "-0,250"
    assert kilos(D("5")) == "5,000 kg"
    assert percent(D("19.00")) == "19 %"
    assert percent(D("1.50")) == "1,50 %"


def test_quantities_and_rates_as_in_the_invoice_columns():
    assert quantity(D("90.000")) == "90"
    assert quantity(D("1097.900")) == "1\u202f097,9"
    assert rate(D("0")) == "0,00"
    assert rate(D("19")) == "19,00"
    assert one_line("Route Mahdia KM4\n3011 Sfax\n") == "Route Mahdia KM4 - 3011 Sfax"


@pytest.mark.parametrize(
    ("number", "words"),
    [
        (0, "zéro"),
        (1, "un"),
        (16, "seize"),
        (17, "dix-sept"),
        (21, "vingt et un"),
        (71, "soixante et onze"),
        (77, "soixante-dix-sept"),
        (80, "quatre-vingts"),
        (81, "quatre-vingt-un"),
        (91, "quatre-vingt-onze"),
        (100, "cent"),
        (200, "deux cents"),
        (201, "deux cent un"),
        (1000, "mille"),
        (3515, "trois mille cinq cent quinze"),
        (80000, "quatre-vingt mille"),
        (200000, "deux cent mille"),
        (1_000_000, "un million"),
        (2_380_000, "deux millions trois cent quatre-vingt mille"),
    ],
)
def test_numbers_in_french_words(number, words):
    assert number_in_words(number) == words


def test_amounts_in_words_as_on_the_paper_invoice():
    assert dinars_in_words(D("3515.500")) == "Trois mille cinq cent quinze Dinars 500 Millimes"
    assert dinars_in_words(D("1.000")) == "Un Dinar"
    assert dinars_in_words(D("12.050")) == "Douze Dinars 050 Millimes"


def test_tax_id_gives_the_unique_identifier_and_the_customer_type():
    assert unique_identifier("1902781/R/N/M/000") == "1902781R"
    assert unique_identifier("") == ""
    assert customer_type("1796419/D/N/M/000", "restaurant") == "Personne morale"
    assert customer_type("1234567/A/P/P/000", "restaurant") == "Personne physique"
    assert customer_type("", "individual") == "Personne physique"
    assert customer_type("", "restaurant") == ""


# ---- what each document shows ----


def test_the_invoice_page_shows_the_frozen_figures(organization, invoice):
    html = services.render_html(services.printable(organization, "invoice", invoice.pk))

    assert invoice.number in html
    assert "Restaurant Le Corail" in html
    assert "210,000" in html  # 5 kg × 42.000
    assert "39,900" in html  # VAT 19 %
    assert "1,000" in html  # fiscal stamp
    assert "250,900 DT" not in html  # separators are thin spaces, never a plain one in numbers
    assert "250,900 TND" in html


def test_the_invoice_follows_the_paper_form(organization, invoice):
    FinanceSettings.objects.filter(organization=organization).update(tax_id="1902781/R/N/M/000")
    invoice.customer.reference = "0047"
    invoice.customer.save()

    html = services.render_html(services.printable(organization, "invoice", invoice.pk))

    assert f"Facture N° {invoice.number}" in html
    assert "Code Client:" in html
    assert "0047" in html
    assert "CR-001" in html  # the product code in the Code Art column
    assert "Total H.T Avant Remise" in html
    assert "Arrêtée la présente Facture à la somme de : Deux cent cinquante Dinars 900 Millimes" in html


def test_the_frais_box_prints_the_invoice_fees(organization, sale, manager):
    invoice = sales.create_invoice(sale=sale, actor=manager.user, issue=True, fees="7.250")

    html = services.render_html(services.printable(organization, "invoice", invoice.pk))

    assert "<tr><th>Frais</th><td>7,250 TND</td></tr>" in html


def test_every_pdf_prints_the_logo_and_a_new_logo_makes_the_file_stale(organization, invoice, manager, fake_pdf):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    from apps.core import services as core

    first = services.request_pdf(organization=organization, kind="invoice", object_id=invoice.pk)
    assert first is None
    assert "data:image/webp;base64," not in fake_pdf[-1]
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), "navy").save(buffer, format="PNG")
    organization = core.set_organization_logo(
        organization=organization,
        actor=manager.user,
        upload=SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png"),
    )

    # The stored file shows the old logo: asking again makes a new one, with the logo in it.
    assert services.request_pdf(organization=organization, kind="invoice", object_id=invoice.pk) is None
    assert "data:image/webp;base64," in fake_pdf[-1]
    # The other documents print it in the shared header.
    payment = sales.record_customer_payment(
        organization=organization,
        actor=manager.user,
        customer=invoice.customer,
        amount=D("10.000"),
        method=SalePaymentMethod.CASH,
    )
    receipt_html = services.render_html(services.printable(organization, "receipt", payment.pk), organization)
    assert '<img src="data:image/webp;base64,' in receipt_html


def test_every_document_has_the_invoice_header_and_footer(organization, invoice, sale, setup, manager):
    """D-131: the logo/company block, boxed number, Date | Client box, client block and address footer of the
    paper invoice are on every document, not only on the invoice."""
    FinanceSettings.objects.filter(organization=organization).update(
        address="Route Mahdia KM4\n3011 Sakiet Ezzit", phone="74 000 000", tax_id="1902781/R/N/M/000"
    )
    customer = setup[0]
    customer.reference = "0047"
    customer.phone = "98 111 222"
    customer.save()
    quote = sales.create_quote(
        organization=organization,
        actor=manager.user,
        customer=customer,
        quoted_on=timezone.localdate(),
        lines=[{"product": setup[2], "quantity": "5"}],
        send=True,
    )
    payment = sales.record_customer_payment(
        organization=organization, actor=manager.user, customer=customer, amount="10.000", method=SalePaymentMethod.CASH
    )
    note = sales.create_credit_note(
        invoice=invoice,
        actor=manager.user,
        kind=CreditNoteKind.PARTIAL,
        reason="Produit avarié",
        lines=[{"invoice_line": invoice.lines.get(), "quantity": "1"}],
        stock=CreditNoteStock.LOSS,
    )
    documents = [
        ("invoice", invoice.pk, f"Facture N° {invoice.number}"),
        ("quote", quote.pk, f"Devis N° {quote.number}"),
        ("delivery_note", sale.pk, f"Bon de livraison N° {sale.number}"),
        ("credit_note", note.pk, f"Avoir N° {note.number}"),
        ("receipt", payment.pk, f"Reçu N° {payment.number}"),
    ]
    for kind, object_id, heading in documents:
        html = services.render_html(services.printable(organization, kind, object_id))
        assert heading in html, kind
        assert "<th>Date</th><th>Client</th>" in html, kind
        assert "Code Client:" in html, kind
        assert "0047" in html, kind
        assert "98 111 222" in html, kind
        assert 'class="page-footer"' in html, kind
        if kind in {"invoice", "credit_note"}:
            continue  # they print the seller frozen when the invoice was issued, before the change above
        assert "Identifiant Unique : 1902781R" in html, kind
        assert "Adresse : Route Mahdia KM4 - 3011 Sakiet Ezzit · Téléphone : 74 000 000" in html, kind


def test_a_draft_invoice_has_no_pdf(organization, sale, manager):
    draft = sales.create_invoice(sale=sale, actor=manager.user)

    with pytest.raises(Exception, match="brouillon"):
        services.printable(organization, "invoice", draft.pk)


def test_a_quote_page_lists_its_lines(organization, manager, setup):
    customer, _counter, crevette = setup
    quote = sales.create_quote(
        organization=organization,
        actor=manager.user,
        customer=customer,
        quoted_on=timezone.localdate(),
        lines=[{"product": crevette, "quantity": "5"}],
        send=True,
    )

    html = services.render_html(services.printable(organization, "quote", quote.pk))

    assert quote.number in html
    assert "Crevette Royale" in html
    assert "210,000" in html


def test_a_credit_note_page_says_why_and_what_became_of_the_goods(organization, invoice, manager):
    line = invoice.lines.get()
    note = sales.create_credit_note(
        invoice=invoice,
        actor=manager.user,
        kind=CreditNoteKind.PARTIAL,
        reason="Produit avarié",
        lines=[{"invoice_line": line, "quantity": "1"}],
        stock=CreditNoteStock.LOSS,
    )

    html = services.render_html(services.printable(organization, "credit_note", note.pk))

    assert note.number in html
    assert invoice.number in html
    assert "Produit avarié" in html
    assert "Mis en perte" in html
    assert "42,000" in html


def test_a_receipt_names_the_sales_it_settled(organization, invoice, sale, setup, manager):
    customer = setup[0]
    payment = sales.record_customer_payment(
        organization=organization,
        actor=manager.user,
        customer=customer,
        amount="100.000",
        method=SalePaymentMethod.CASH,
    )

    html = services.render_html(services.printable(organization, "receipt", payment.pk))

    assert payment.number in html
    assert sale.number in html
    assert invoice.number in html
    assert "100,000" in html
    assert "Espèces" in html


def test_one_organization_cannot_print_another_ones_document(invoice):
    other = OrganizationFactory.create()

    with pytest.raises(ObjectDoesNotExist):
        services.printable(other, "invoice", invoice.pk)


# ---- the job and the stored file ----


def test_the_file_is_made_once_and_again_only_when_the_document_changes(organization, invoice, fake_pdf):
    first = services.request_pdf(organization=organization, kind="invoice", object_id=invoice.pk)
    assert first is None  # queued; the job ran inline and stored the file
    row = services.current_file(organization=organization, kind="invoice", object_id=invoice.pk)
    assert row is not None
    assert row.file.read().startswith(b"%PDF-1.7 fake")
    assert len(fake_pdf) == 1

    again = services.request_pdf(organization=organization, kind="invoice", object_id=invoice.pk)
    assert again is not None
    assert again.pk == row.pk
    assert len(fake_pdf) == 1  # nothing was made a second time

    sales.create_credit_note(invoice=invoice, actor=None, kind=CreditNoteKind.FULL, reason="Erreur")
    services.request_pdf(organization=organization, kind="invoice", object_id=invoice.pk)
    assert len(fake_pdf) == 2  # the invoice changed (cancelled): its file was remade
    assert GeneratedDocument.objects.filter(kind="invoice").count() == 1
    assert "ANNULÉE" in fake_pdf[-1]


def test_a_job_queued_a_moment_ago_is_not_queued_again(organization, invoice, monkeypatch):
    queued = []
    monkeypatch.setattr("apps.documents.tasks.generate_pdf.delay", lambda *args: queued.append(args))

    services.request_pdf(organization=organization, kind="invoice", object_id=invoice.pk)
    services.request_pdf(organization=organization, kind="invoice", object_id=invoice.pk)

    assert len(queued) == 1


def test_a_failed_job_is_reported_and_only_retried_on_request(organization, invoice, monkeypatch, api):
    def broken(html: str) -> bytes:
        raise RuntimeError("no pango")

    monkeypatch.setattr(rendering, "html_to_pdf", broken)
    failed = api.get(url("invoice", invoice.pk))
    assert failed.status_code == 500
    assert failed.json() == {"status": "failed"}

    monkeypatch.setattr(rendering, "html_to_pdf", lambda html: b"%PDF-1.7 fixed")
    assert api.get(url("invoice", invoice.pk)).status_code == 500  # polling does not retry
    fixed = api.get(url("invoice", invoice.pk, retry=1))
    assert fixed.status_code == 200


# ---- the API ----


def test_the_api_answers_the_pdf_with_the_right_headers(api, invoice):
    response = api.get(url("invoice", invoice.pk))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == f'inline; filename="facture-{invoice.number.lower()}.pdf"'
    assert response["Cache-Control"] == "private, no-store"
    assert b"".join(response.streaming_content).startswith(b"%PDF")


def test_the_api_answers_404_for_unknown_kinds_and_other_organizations(api, invoice):
    assert api.get(url("nope", invoice.pk)).status_code == 404
    assert api.get(url("invoice", invoice.pk + 999)).status_code == 404
    stranger = APIClient()
    stranger.force_authenticate(MembershipFactory.create(role=Role.MANAGER).user)
    assert stranger.get(url("invoice", invoice.pk)).status_code == 404


def test_a_draft_invoice_is_refused_with_a_reason(api, sale, manager):
    draft = sales.create_invoice(sale=sale, actor=manager.user)

    response = api.get(url("invoice", draft.pk))

    assert response.status_code == 400


def test_drivers_get_403_and_the_accountant_may_read(organization, invoice):
    driver = APIClient()
    driver.force_authenticate(MembershipFactory.create(organization=organization, role=Role.DRIVER).user)
    accountant = APIClient()
    accountant.force_authenticate(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT).user)

    assert driver.get(url("invoice", invoice.pk)).status_code == 403
    assert accountant.get(url("invoice", invoice.pk)).status_code == 200
    assert APIClient().get(url("invoice", invoice.pk)).status_code in {401, 403}


def test_the_real_renderer_makes_a_pdf(organization, invoice, monkeypatch):
    try:
        import weasyprint

        weasyprint.HTML(string="<p>test</p>").write_pdf()
    except OSError:  # Pango is not installed on this machine (CI and the Docker image have it)
        pytest.skip("WeasyPrint's native libraries are not available")
    monkeypatch.undo()
    html = services.render_html(services.printable(organization, "invoice", invoice.pk))

    pdf = rendering.html_to_pdf(html)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000


# ---- by e-mail (D-206) ----


def test_an_invoice_goes_by_email_with_its_pdf_from_the_company_address(api, organization, invoice, mailoutbox):
    invoice.customer.email = "corail@example.tn"
    invoice.customer.save()
    email_url = reverse("document-email", args=["invoice", invoice.pk])

    draft = api.get(email_url).json()
    assert draft["to"] == ["corail@example.tn"]
    assert draft["subject"] == f"Facture {invoice.number} - {organization.name}"
    assert invoice.number in draft["body"]

    sent = api.post(email_url, {"to": draft["to"], "subject": draft["subject"], "body": draft["body"]}, format="json")
    assert sent.status_code == 204
    (message,) = mailoutbox
    assert message.to == ["corail@example.tn"]
    assert message.subject == draft["subject"]
    assert organization.name in message.from_email
    (attachment,) = message.attachments
    assert attachment[0].endswith(".pdf")
    assert attachment[2] == "application/pdf"
    assert api.get(email_url).json()["sent"][0]["to"] == "corail@example.tn"
    assert api.post(email_url, {"to": [], "subject": "x", "body": ""}, format="json").status_code == 400


def test_every_address_of_the_customer_is_offered_and_one_send_goes_to_the_chosen_ones(
    api, organization, invoice, mailoutbox
):
    invoice.customer.email = "corail@example.tn"
    invoice.customer.save()
    CustomerContactFactory.create(organization=organization, customer=invoice.customer, email="chef@example.tn")
    # Same address as the party's, in another case, and a contact with no address: listed once, or not at all.
    CustomerContactFactory.create(organization=organization, customer=invoice.customer, email="CORAIL@example.tn")
    CustomerContactFactory.create(organization=organization, customer=invoice.customer, email="")
    email_url = reverse("document-email", args=["invoice", invoice.pk])

    draft = api.get(email_url).json()
    assert draft["to"] == ["corail@example.tn", "chef@example.tn"]

    # For this send only: the chef is dropped, a new address is added.
    chosen = ["corail@example.tn", "compta@example.tn"]
    sent = api.post(email_url, {"to": chosen, "subject": "Facture", "body": ""}, format="json")
    assert sent.status_code == 204
    (message,) = mailoutbox
    assert message.to == ["corail@example.tn", "compta@example.tn"]
    # The party itself is unchanged.
    invoice.customer.refresh_from_db()
    assert invoice.customer.email == "corail@example.tn"
    assert api.get(email_url).json()["to"] == ["corail@example.tn", "chef@example.tn"]


def test_an_address_given_twice_is_sent_once_and_too_many_are_refused(api, invoice, mailoutbox):
    email_url = reverse("document-email", args=["invoice", invoice.pk])

    sent = api.post(
        email_url, {"to": ["a@example.tn", "A@example.tn"], "subject": "Facture", "body": ""}, format="json"
    )
    assert sent.status_code == 204
    (message,) = mailoutbox
    assert message.to == ["a@example.tn"]

    too_many = [f"client{number}@example.tn" for number in range(11)]
    refused = api.post(email_url, {"to": too_many, "subject": "Facture", "body": ""}, format="json")
    assert refused.status_code == 400
    assert len(mailoutbox) == 1
