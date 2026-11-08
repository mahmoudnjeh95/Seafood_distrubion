"""D-288: files attached to a document (a signed quote, a supplier's delivery note scan...)."""

import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.documents import services
from apps.documents.models import Attachment
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import services as purchasing
from apps.purchasing.models import PurchaseOrder

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


@pytest.fixture
def receipt(organization):
    from apps.catalog.tests.factories import ProductFactory

    return purchasing.create_receipt(
        organization=organization,
        actor=None,
        supplier=SupplierFactory.create(organization=organization),
        location=StockLocationFactory.create(organization=organization),
        received_on=timezone.localdate(),
        lines=[
            {
                "product": ProductFactory.create(organization=organization),
                "invoiced_quantity": "10",
                "accepted_quantity": "10",
                "unit_cost": "5",
            }
        ],
    )


def photo(width=3000, height=2000):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 120, 200)).save(buffer, format="JPEG")
    return SimpleUploadedFile("bl-fournisseur.jpg", buffer.getvalue(), content_type="image/jpeg")


def test_a_pdf_is_kept_and_a_photo_shrunk_then_removing_hides_it(media, manager, organization, receipt):
    pdf = services.add_attachment(
        organization=organization,
        actor=manager.user,
        kind="goods_receipt",
        object_id=receipt.pk,
        upload=SimpleUploadedFile("bl.pdf", PDF, content_type="application/pdf"),
        note="BL du fournisseur",
    )
    scan = services.add_attachment(
        organization=organization, actor=manager.user, kind="goods_receipt", object_id=receipt.pk, upload=photo()
    )

    assert (pdf.content_type, pdf.name, pdf.note) == ("application/pdf", "bl.pdf", "BL du fournisseur")
    with Image.open(scan.file.path) as stored:
        assert (stored.format, stored.size) == ("WEBP", (2400, 1600))
    assert [row.pk for row in services.attachments_of(organization, "goods_receipt", receipt.pk)] == [pdf.pk, scan.pk]

    services.remove_attachment(attachment=pdf, actor=manager.user)
    assert [row.pk for row in services.attachments_of(organization, "goods_receipt", receipt.pk)] == [scan.pk]
    assert Attachment.objects.get(pk=pdf.pk).removed_by == manager.user
    assert AuditLog.objects.filter(action__startswith="attachment.").count() == 3


def test_an_unknown_document_or_file_is_refused(media, manager, organization, receipt):
    other = OrganizationFactory.create()
    with pytest.raises(ValidationError) as unknown:
        services.add_attachment(
            organization=other, actor=None, kind="goods_receipt", object_id=receipt.pk, upload=photo()
        )
    assert "kind" in unknown.value.message_dict
    with pytest.raises(ValidationError) as not_a_file:
        services.add_attachment(
            organization=organization,
            actor=None,
            kind="goods_receipt",
            object_id=receipt.pk,
            upload=SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain"),
        )
    assert "file" in not_a_file.value.message_dict
    assert not services.is_attachable(organization, "purchase_order", 999999)
    assert not PurchaseOrder.objects.exists()


def test_the_office_attaches_reads_and_removes_through_the_api(media, manager, organization, receipt):
    client = APIClient()
    client.force_authenticate(manager.user)
    created = client.post(
        reverse("attachment-list"),
        {"kind": "goods_receipt", "object_id": receipt.pk, "file": photo(800, 600), "note": "Photo"},
        format="multipart",
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["content_type"] == "image/webp"

    listed = client.get(reverse("attachment-list"), {"kind": "goods_receipt", "object_id": receipt.pk}).json()
    assert [row["id"] for row in listed] == [body["id"]]
    opened = client.get(body["file_url"])
    assert opened.status_code == 200
    assert opened["Content-Type"] == "image/webp"

    accountant = MembershipFactory.create(role=Role.ACCOUNTANT, organization=organization)
    reader = APIClient()
    reader.force_authenticate(accountant.user)
    assert reader.get(body["file_url"]).status_code == 200
    assert reader.delete(reverse("attachment-detail", args=[body["id"]])).status_code == 403

    assert client.delete(reverse("attachment-detail", args=[body["id"]])).status_code == 204
    assert client.get(body["file_url"]).status_code == 404
    assert client.get(reverse("attachment-list"), {"kind": "goods_receipt", "object_id": "999999"}).status_code == 404
