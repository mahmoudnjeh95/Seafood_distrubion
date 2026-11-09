"""PDF documents: apps register what can be printed, a Celery job renders and stores the file (D-071).

An app that owns printable documents calls `register(kind, provider)` when it starts; the provider turns
`(organization, object_id)` into a `Printable` (a template, its context and the document's version) or raises
`ObjectDoesNotExist`. This app never reads another app's tables.
"""

import base64
import logging
import smtplib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.images import reencoded_photo
from apps.core.models import Organization, User

from . import rendering
from .models import Attachment, AttachmentKind, GeneratedDocument, SentEmail
from .models import DocumentKind as DocumentKind  # re-exported for the apps that register documents

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

logger = logging.getLogger(__name__)

# A job queued less than this long ago is still considered running: polling does not queue another.
REQUEUE_AFTER = timedelta(seconds=90)


@dataclass(frozen=True)
class Printable:
    template: str
    context: dict[str, Any]
    # Changes whenever the document does (its `updated_at`): a file made for another version is stale.
    version: str
    # The file name offered to the user, without folders.
    filename: str
    # What the document is, as the e-mail subject names it ("Facture FA-2026-0001"), and the addresses it usually
    # goes to (the party's own, then its contacts'); empty when unknown (D-206, D-222).
    title: str = ""
    email_to: list[str] = field(default_factory=list)


Provider = Callable[[Organization, int], Printable]
_providers: dict[str, Provider] = {}
# Who may read a kind of document, when it is narrower than the office (owner, manager, accountant).
_roles: dict[str, frozenset[str]] = {}


def register(kind: str, provider: Provider, *, roles: frozenset[str] | None = None) -> None:
    """`roles`: the roles allowed to read this kind (default: every office role)."""
    _providers[kind] = provider
    if roles is not None:
        _roles[kind] = roles


def may_read(kind: str, role: str) -> bool:
    return role in _roles.get(kind, frozenset({"owner", "manager", "accountant"}))


def is_known(kind: str) -> bool:
    return kind in DocumentKind.values and kind in _providers


def printable(organization: Organization, kind: str, object_id: int) -> Printable:
    """What to print for one document. Raises ObjectDoesNotExist outside the organization, KeyError for an
    unknown kind."""
    return _providers[kind](organization, object_id)


def unique_identifier(tax_id: str) -> str:
    """The "Identifiant unique" of a Tunisian tax id: its number and key letter (1902781/R/N/M/000 → 1902781R).

    Printed under the company's tax id in the header of every document (D-125, D-131)."""
    parts = [part.strip().upper() for part in (tax_id or "").replace(" ", "").split("/")]
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isalpha():
        return ""
    return parts[0] + parts[1]


def logo_data_uri(organization: Organization | None) -> str:
    """The company logo from Paramètres (D-123) as a `data:` address the PDF embeds; empty without a logo."""
    if organization is None or not organization.logo:
        return ""
    try:
        with organization.logo.open("rb") as file:
            data = file.read()
    except OSError:
        # A missing file must not stop the document: it prints with the name instead of the logo.
        logger.warning("Logo file of organization %s is missing", organization.pk)
        return ""
    return "data:image/webp;base64," + base64.b64encode(data).decode("ascii")


def render_html(document: Printable, organization: Organization | None = None) -> str:
    """Every PDF gets the company logo as `logo` (the shared header of `documents/pdf_base.html` prints it)."""
    return render_to_string(document.template, {"logo": logo_data_uri(organization), **document.context})


def render_pdf(document: Printable, organization: Organization) -> bytes:
    """The PDF of a document made on the spot and not stored: for one that depends on what the person asks, like a
    statement over chosen dates (D-156). Every other document goes through `request_pdf`."""
    return rendering.html_to_pdf(render_html(document, organization))


def render_pack_pdf(pack: list[Printable], organization: Organization) -> bytes:
    """One PDF holding several documents one after the other, each starting on its own page."""
    return rendering.htmls_to_pdf([render_html(document, organization) for document in pack])


def email_draft(organization: Organization, kind: str, object_id: int) -> dict[str, Any]:
    """What the "Envoyer par e-mail" window proposes (D-206): the usual addresses (D-222), a clear subject and a
    short message. Raises like `printable`."""
    document = printable(organization, kind, object_id)
    title = document.title or str(DocumentKind(kind).label)
    company = organization.name
    return {
        "to": document.email_to,
        "subject": f"{title} - {company}",
        "body": (
            f"Bonjour,\n\nVeuillez trouver ci-joint votre document : {title}.\n"
            f"Pour toute question, répondez simplement à ce message.\n\nCordialement,\n{company}"
        ),
    }


def send_email(
    *,
    organization: Organization,
    actor: User | None,
    kind: str,
    object_id: int,
    to: list[str],
    subject: str,
    body: str,
) -> SentEmail:
    """Send the document's PDF by e-mail from the company address (`DEFAULT_FROM_EMAIL`), and keep a trace of
    it, also when sending failed (D-206). Raises ValidationError with the reason when it cannot be sent."""
    errors: dict[str, str] = {}
    # Each address once, whatever its case: the office may have ticked the same one twice (D-222).
    first_seen: dict[str, str] = {}
    for address in to:
        if address.strip():
            first_seen.setdefault(address.strip().lower(), address.strip())
    addresses = list(first_seen.values())
    if not addresses:
        errors["to"] = _("Indiquez au moins une adresse e-mail.")
    if not subject.strip():
        errors["subject"] = _("Indiquez l'objet du message.")
    if not settings.DEBUG and settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        errors["detail"] = _("L'envoi d'e-mails n'est pas encore configuré sur le serveur : prévenez l'administrateur.")
    if errors:
        raise ValidationError(errors)
    document = printable(organization, kind, object_id)
    pdf = rendering.html_to_pdf(render_html(document, organization))
    # The company's name before its address; Django encodes it when the message leaves.
    name = organization.name.replace('"', "")
    sender = f'"{name}" <{settings.DEFAULT_FROM_EMAIL}>'
    message = EmailMessage(
        subject=subject.strip(),
        body=body,
        from_email=sender,
        to=addresses,
        reply_to=[settings.DEFAULT_FROM_EMAIL],
    )
    message.attach(document.filename, pdf, "application/pdf")
    row = SentEmail(
        organization=organization,
        kind=kind,
        object_id=object_id,
        to=", ".join(addresses)[:500],
        subject=subject.strip()[:255],
        sent_by=actor,
    )
    try:
        message.send(fail_silently=False)
    except (OSError, smtplib.SMTPException) as error:
        logger.exception("E-mail of %s %s failed", kind, object_id)
        row.error = str(error)[:255]
        row.save()
        raise ValidationError({"detail": _("Le message n'a pas pu partir : %(why)s") % {"why": error}}) from None
    row.save()
    return row


def file_version(organization: Organization, document: Printable) -> str:
    """The document's version plus the logo's: a new logo makes the stored files stale (D-125)."""
    if not organization.logo:
        return document.version
    # The logo's file name is a fresh random hex on every upload; a few characters tell versions apart.
    return f"{document.version}|{(organization.logo.name or '').rsplit('/', 1)[-1][:8]}"


def _row(organization: Organization, kind: str, object_id: int) -> GeneratedDocument | None:
    return GeneratedDocument.objects.for_organization(organization).filter(kind=kind, object_id=object_id).first()


@transaction.atomic
def request_pdf(
    *, organization: Organization, kind: str, object_id: int, retry: bool = False
) -> GeneratedDocument | None:
    """Return the up-to-date file, or queue the job that makes it and return None (ask again shortly).

    A job queued less than `REQUEUE_AFTER` ago is not queued again. After a failure nothing is queued again
    until the user asks anew (`retry`), so a broken template does not loop.
    """
    current = printable(organization, kind, object_id)
    row, _created = (
        GeneratedDocument.objects.for_organization(organization)
        .select_for_update()
        .get_or_create(kind=kind, object_id=object_id, defaults={"organization": organization})
    )
    if row.file and row.version == file_version(organization, current):
        return row
    now = timezone.now()
    # Running: queued less than a moment ago and not finished since (a finished job is stale, not running).
    queued = row.requested_at
    running = (
        queued is not None
        and now - queued < REQUEUE_AFTER
        and (row.generated_at is None or queued > row.generated_at)
        and not row.error
    )
    if running or (row.error and not retry):
        return None
    row.requested_at = now
    row.error = ""
    row.save(update_fields=["requested_at", "error"])
    from .tasks import generate_pdf

    transaction.on_commit(lambda: generate_pdf.delay(organization.pk, kind, object_id))
    return None


def generate_pdf_now(*, organization: Organization, kind: str, object_id: int) -> GeneratedDocument:
    """Render the document and store the file, replacing an older one. Called by the job."""
    current = printable(organization, kind, object_id)
    pdf = rendering.html_to_pdf(render_html(current, organization))
    with transaction.atomic():
        row, _created = (
            GeneratedDocument.objects.for_organization(organization)
            .select_for_update()
            .get_or_create(kind=kind, object_id=object_id, defaults={"organization": organization})
        )
        old = row.file.name if row.file else ""
        row.file.save(current.filename, ContentFile(pdf), save=False)
        row.version = file_version(organization, current)
        row.generated_at = timezone.now()
        row.error = ""
        row.save()
        if old:
            row.file.storage.delete(old)
    return row


def current_file(*, organization: Organization, kind: str, object_id: int) -> GeneratedDocument | None:
    """The stored file when it shows the document's present state (a job that just ran inline made it)."""
    row = _row(organization, kind, object_id)
    if (
        row is not None
        and row.file
        and row.version == file_version(organization, printable(organization, kind, object_id))
    ):
        return row
    return None


def failure_of(*, organization: Organization, kind: str, object_id: int) -> str:
    """The reason the last job failed, empty when it did not."""
    row = _row(organization, kind, object_id)
    return row.error if row is not None else ""


def record_failure(*, organization: Organization, kind: str, object_id: int, error: str) -> None:
    GeneratedDocument.objects.for_organization(organization).update_or_create(
        kind=kind, object_id=object_id, defaults={"organization": organization, "error": error[:255]}
    )


# ---- Files attached to a document (D-288) ----
# An app that owns a document kind says how to find one: `register_attachable(kind, exists)`, `exists` answering
# whether that id is a document of the organization. This app never reads the other apps' tables.

MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
# Scans and photos of papers stay readable: larger than a product photo.
ATTACHMENT_PHOTO_SIDE = 2400

_attachables: dict[str, Callable[[Organization, int], bool]] = {}


def register_attachable(kind: str, exists: Callable[[Organization, int], bool]) -> None:
    _attachables[kind] = exists


def is_attachable(organization: Organization, kind: str, object_id: int) -> bool:
    """Whether files may be attached to this document: a known kind, and a document of the organization."""
    exists = _attachables.get(kind)
    return kind in AttachmentKind.values and exists is not None and exists(organization, object_id)


def attached_ids(organization: Organization, kind: str, object_ids: list[int]) -> set[int]:
    """Which of these documents have at least one file still attached."""
    return set(
        Attachment.objects.for_organization(organization)
        .filter(kind=kind, object_id__in=object_ids, removed_at__isnull=True)
        .values_list("object_id", flat=True)
    )


def attachments_of(organization: Organization, kind: str, object_id: int) -> list[Attachment]:
    """The files of one document still attached, oldest first."""
    return list(
        Attachment.objects.for_organization(organization)
        .filter(kind=kind, object_id=object_id, removed_at__isnull=True)
        .select_related("uploaded_by")
        .order_by("uploaded_at", "id")
    )


def _attachment_snapshot(attachment: Attachment) -> dict[str, Any]:
    return {
        "kind": attachment.kind,
        "object_id": attachment.object_id,
        "name": attachment.name,
        "size": attachment.size,
        "note": attachment.note,
    }


@transaction.atomic
def add_attachment(
    *,
    organization: Organization,
    actor: User | None,
    kind: str,
    object_id: int,
    upload: "UploadedFile[bytes]",
    note: str = "",
) -> Attachment:
    """Attach a file to a document: a PDF (8 MB at most) kept as it is, or a photo (JPEG, PNG, WebP) turned upright,
    shrunk to 2400 px and stored as WebP. Refused on `file` otherwise; an unknown document is a `kind` error."""
    if not is_attachable(organization, kind, object_id):
        raise ValidationError({"kind": _("Document inconnu.")})
    head = upload.read(5)
    upload.seek(0)
    if head == b"%PDF-":
        if upload.size is not None and upload.size > MAX_ATTACHMENT_BYTES:
            raise ValidationError({"file": _("Le fichier dépasse 8 Mo.")})
        content = ContentFile(upload.read())
        content_type, stored_name = "application/pdf", "document.pdf"
    else:
        content = reencoded_photo(upload, field="file", side=ATTACHMENT_PHOTO_SIDE)
        content_type, stored_name = "image/webp", "document.webp"
    attachment = Attachment(
        organization=organization,
        kind=kind,
        object_id=object_id,
        name=(upload.name or stored_name)[-200:],
        content_type=content_type,
        size=content.size,
        note=note.strip()[:255],
        uploaded_by=actor,
    )
    attachment.file.save(stored_name, content, save=False)
    attachment.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="attachment.added",
        target=attachment,
        after=_attachment_snapshot(attachment),
    )
    return attachment


@transaction.atomic
def remove_attachment(*, attachment: Attachment, actor: User | None) -> Attachment:
    """Take a file off its document: it no longer shows; the row and the file are kept with who removed it."""
    locked = Attachment.objects.select_for_update().get(pk=attachment.pk)
    if locked.removed_at is not None:
        return locked
    locked.removed_at = timezone.now()
    locked.removed_by = actor
    locked.save(update_fields=["removed_at", "removed_by"])
    audit.record(
        organization=locked.organization,
        actor=actor,
        action="attachment.removed",
        target=locked,
        before=_attachment_snapshot(locked),
    )
    return locked
