import uuid
from decimal import Decimal

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel
from apps.core.money import MoneyField, QuantityField, line_total


class GoodsReceipt(OrganizationScopedModel, TimeStampedModel):
    """Goods received from a supplier on one day into one location, with their real net weight (Q12).

    Saving it creates one batch per line and posts the receipt movements (P1-T07). A receipt is never
    edited afterwards: a mistake is corrected by a supplier return or an adjustment (ARCHITECTURE §4.5).
    """

    # "BR-0001", "BR-0002"... per organization, given by `services.create_receipt`.
    number = models.CharField(max_length=20)
    # By name, not by import: an app only uses another app's services and selectors (ARCHITECTURE §3).
    supplier = models.ForeignKey("partners.Supplier", on_delete=models.PROTECT, related_name="receipts")
    location = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT, related_name="receipts")
    # The purchase order this delivery is against, or empty for goods that came without an order (D-076).
    # One order is received in as many receipts as the supplier delivers it in.
    purchase_order = models.ForeignKey(
        "PurchaseOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="receipts"
    )
    received_on = models.DateField()
    # The supplier's delivery note or invoice number, as printed on their paper.
    supplier_reference = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-received_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="receipt_number_unique_per_organization"),
        ]

    def __str__(self) -> str:
        return self.number


class GoodsReceiptLine(OrganizationScopedModel):
    """One product of a receipt: what was ordered, what the supplier invoices, what was accepted.

    Weights are net (Q12): no gross weight or ice glaze. The accepted weight enters stock as a new batch
    at the line's cost; the invoiced weight is what the supplier will charge (P1-T08).
    """

    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    batch = models.OneToOneField("inventory.Batch", on_delete=models.PROTECT, related_name="receipt_line")
    # The order line this delivers against; its accepted weight counts as received on the order (D-076).
    order_line = models.ForeignKey(
        "PurchaseOrderLine", null=True, blank=True, on_delete=models.PROTECT, related_name="receipt_lines"
    )
    # Empty when nothing was ordered beforehand (the boat came in with what it had).
    # A QuantityField that may be empty (QuantityField itself is typed as never empty).
    ordered_quantity = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    invoiced_quantity = QuantityField()
    accepted_quantity = QuantityField()
    # DT per kg without VAT, typed on every receipt: purchase prices change daily (D-020).
    unit_cost = MoneyField()

    class Meta:
        ordering = ["receipt", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(accepted_quantity__gt=0), name="receipt_line_accepted_positive"),
            models.CheckConstraint(condition=models.Q(invoiced_quantity__gt=0), name="receipt_line_invoiced_positive"),
            models.CheckConstraint(
                condition=models.Q(ordered_quantity__isnull=True) | models.Q(ordered_quantity__gt=0),
                name="receipt_line_ordered_positive",
            ),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="receipt_line_cost_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.receipt} · {self.batch}"

    @property
    def invoiced_amount(self) -> Decimal:
        """What the supplier charges for this line: invoiced weight × cost."""
        return line_total(self.invoiced_quantity, self.unit_cost)

    @property
    def accepted_amount(self) -> Decimal:
        """Value of what entered stock: accepted weight × cost."""
        return line_total(self.accepted_quantity, self.unit_cost)

    @property
    def has_difference(self) -> bool:
        """Accepted weight differs from the invoiced weight, or from the ordered weight when there was an order."""
        ordered_differs = self.ordered_quantity is not None and self.ordered_quantity != self.accepted_quantity
        return self.invoiced_quantity != self.accepted_quantity or ordered_differs


class ReceiptCounter(OrganizationScopedModel):
    """The last receipt number given in an organization, locked while a number is taken."""

    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization"], name="one_receipt_counter_per_organization")]

    def __str__(self) -> str:
        return f"{self.organization} · {self.last_number}"


class PurchaseOrderStatus(models.TextChoices):
    # Sent to the supplier, nothing delivered yet.
    OPEN = "open", _("En attente")
    # Some of it delivered (a receipt per delivery), some still to come.
    PARTLY_RECEIVED = "partly_received", _("Reçu en partie")
    # Every line delivered in full (or more).
    RECEIVED = "received", _("Reçu")
    # Closed by hand while part was never delivered: the rest will not come.
    CLOSED = "closed", _("Clôturé")
    # Cancelled before anything was delivered.
    CANCELLED = "cancelled", _("Annulé")


# The orders that can still be delivered against.
RECEIVABLE_ORDER_STATUSES = (PurchaseOrderStatus.OPEN, PurchaseOrderStatus.PARTLY_RECEIVED)


class PurchaseOrder(OrganizationScopedModel, TimeStampedModel):
    """What we ask a supplier to deliver: the "bon d'achat" (D-076).

    It moves no stock and owes nothing: only goods receipts do. It is never edited; a mistake is
    cancelled (before any delivery) and typed again. Its status follows its receipts.
    """

    # "BA-0001", "BA-0002"... per organization, given by `services.create_order`.
    number = models.CharField(max_length=20)
    supplier = models.ForeignKey("partners.Supplier", on_delete=models.PROTECT, related_name="purchase_orders")
    ordered_on = models.DateField()
    # When the supplier promised to deliver; empty when no date was agreed.
    expected_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=PurchaseOrderStatus.choices, default=PurchaseOrderStatus.OPEN)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-ordered_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="order_number_unique_per_organization"),
            models.CheckConstraint(
                condition=models.Q(expected_on__isnull=True) | models.Q(expected_on__gte=models.F("ordered_on")),
                name="order_expected_not_before_ordered",
            ),
        ]

    def __str__(self) -> str:
        return self.number


class PurchaseOrderLine(OrganizationScopedModel):
    """One product of an order: the weight asked for and the price agreed (per kg, without VAT)."""

    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    ordered_quantity = QuantityField()
    # The agreed price. The receipt line has its own cost, because the real price can differ on the day.
    unit_cost = MoneyField()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="order_line_one_per_product"),
            models.CheckConstraint(condition=models.Q(ordered_quantity__gt=0), name="order_line_quantity_positive"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="order_line_cost_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.order} · {self.product}"

    @property
    def ordered_amount(self) -> Decimal:
        return line_total(self.ordered_quantity, self.unit_cost)


class SupplierInvoiceStatus(models.TextChoices):
    # Typed but not checked yet: its receipts, dates and reference can still change, or it can be deleted.
    DRAFT = "draft", _("Brouillon")
    # Checked and owed: it no longer changes; only payments move it on.
    POSTED = "posted", _("Validée")
    PARTLY_PAID = "partly_paid", _("Payée en partie")
    PAID = "paid", _("Payée")


class SupplierInvoice(OrganizationScopedModel, TimeStampedModel):
    """What a supplier charges for one or more goods receipts: a trade payable (P1-T08, D-043).

    Its amount is the invoiced amount of its receipts (invoiced kg × cost, D-039), never typed. Once
    posted it is immutable; payments change its status only. A partner's capital and profit share are
    other balances (D-040) and never pass through it.
    """

    # "FF-0001", "FF-0002"... per organization, given by `services.create_invoice`.
    number = models.CharField(max_length=20)
    supplier = models.ForeignKey("partners.Supplier", on_delete=models.PROTECT, related_name="invoices")
    # The number printed on the supplier's invoice.
    supplier_reference = models.CharField(max_length=50, blank=True)
    invoice_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=SupplierInvoiceStatus.choices, default=SupplierInvoiceStatus.DRAFT)
    # The sum of its receipts' invoiced amounts, kept by the services; frozen once posted.
    total = MoneyField(default=Decimal("0.000"))
    notes = models.TextField(blank=True)
    # What the supplier was owed when the system started (P4-T01, D-112): a posted invoice with no receipts.
    is_opening = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-invoice_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="invoice_number_unique_per_organization"),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="invoice_total_not_negative"),
            models.CheckConstraint(
                condition=models.Q(due_date__gte=models.F("invoice_date")), name="invoice_due_after_invoice_date"
            ),
        ]

    def __str__(self) -> str:
        return self.number


class SupplierInvoiceReceipt(OrganizationScopedModel):
    """A goods receipt charged on an invoice. A receipt is on one invoice at most, draft or posted."""

    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name="receipt_links")
    receipt = models.OneToOneField(GoodsReceipt, on_delete=models.PROTECT, related_name="invoice_link")
    # The receipt's invoiced total when it was linked. Receipts never change, so neither does this.
    amount = MoneyField()

    class Meta:
        ordering = ["invoice", "receipt__received_on", "receipt_id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gte=0), name="invoice_receipt_not_negative")]

    def __str__(self) -> str:
        return f"{self.invoice} · {self.receipt}"


class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Espèces")
    CHEQUE = "cheque", _("Chèque")
    TRANSFER = "transfer", _("Virement")
    # "Traite": a bill of exchange, common between Tunisian businesses.
    BILL = "bill", _("Traite")
    OTHER = "other", _("Autre")


class SupplierPayment(OrganizationScopedModel, TimeStampedModel):
    """Money paid to a supplier, allocated to their posted invoices: all of it, part of it or none (D-043).

    The part not allocated yet is an advance: it already lowers the supplier balance and can be allocated
    to a later invoice. A recorded payment is never edited.
    """

    # "RF-0001", "RF-0002"... per organization ("règlement fournisseur").
    number = models.CharField(max_length=20)
    supplier = models.ForeignKey("partners.Supplier", on_delete=models.PROTECT, related_name="payments")
    paid_on = models.DateField()
    amount = MoneyField()
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    # Cheque or bill number, transfer reference.
    reference = models.CharField(max_length=50, blank=True)
    # The day a cheque or a traite may be cashed (post-dated); empty when it is paid at once (D-176).
    cash_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-paid_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="payment_number_unique_per_organization"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self) -> str:
        return self.number


class SupplierPaymentAllocation(OrganizationScopedModel, TimeStampedModel):
    """The part of a payment that settles one invoice: given with the payment, or later for an advance."""

    payment = models.ForeignKey(SupplierPayment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.PROTECT, related_name="allocations")
    amount = MoneyField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["payment", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="allocation_amount_positive")]

    def __str__(self) -> str:
        return f"{self.payment} → {self.invoice}"


class PlanLineStatus(models.TextChoices):
    OPEN = "open", _("Planifiée")
    PAID = "paid", _("Payée")
    CANCELLED = "cancelled", _("Annulée")


class SupplierPaymentPlanLine(OrganizationScopedModel, TimeStampedModel):
    """A part of what is still owed on an invoice that the office decided how and when to pay (D-192).

    A plan is not a payment: creating, changing or cancelling a line never touches the supplier balance.
    Recording the real payment can name the line it settles; the line then becomes `paid`.
    """

    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.PROTECT, related_name="plan_lines")
    amount = MoneyField()
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    planned_on = models.DateField()
    # Cheque or bill number, transfer reference.
    reference = models.CharField(max_length=50, blank=True)
    # The day a cheque or a traite may be cashed.
    cash_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=PlanLineStatus.choices, default=PlanLineStatus.OPEN)
    # The payment that settled it.
    payment = models.ForeignKey(SupplierPayment, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["planned_on", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="plan_line_amount_positive")]

    def __str__(self) -> str:
        return f"{self.invoice} · {self.amount}"


class DocumentKind(models.TextChoices):
    SUPPLIER_INVOICE = "supplier_invoice", _("Facture fournisseur")
    SUPPLIER_PAYMENT = "supplier_payment", _("Paiement fournisseur")
    PURCHASE_ORDER = "purchase_order", _("Bon d'achat")
    FIELD_PURCHASE = "field_purchase", _("Achat terrain")


class DocumentCounter(OrganizationScopedModel):
    """The last number given to one kind of purchasing document in an organization, locked while taken."""

    kind = models.CharField(max_length=30, choices=DocumentKind.choices)
    # 0 for a kind numbered without a year (FF-0001, order numbers); the year for a kind that restarts yearly (D-120).
    year = models.PositiveIntegerField(default=0)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "kind", "year"], name="one_document_counter_per_kind_year"),
        ]

    def __str__(self) -> str:
        return f"{self.organization} · {self.kind} · {self.year} · {self.last_number}"


# ---- Buying at the port, the "achat terrain" (P3-T12, D-176) ----


class FieldPurchaseStatus(models.TextChoices):
    # Sent by the driver: the driver and the office may still change it (each save is a revision).
    SUBMITTED = "submitted", _("À valider")
    # Checked by the owner or the manager: its receipt, invoice and payments exist. Final.
    VALIDATED = "validated", _("Validé")
    # Not taken: nothing entered stock and nothing is owed. Final.
    REFUSED = "refused", _("Refusé")


class PaymentTerms(models.TextChoices):
    """The deal made with the supplier for one purchase (Q28): it gives the due date of what is owed."""

    # Due the day of the purchase.
    CASH = "cash", _("Comptant")
    # Due `due_days` days after the purchase.
    DAYS = "days", _("À N jours")
    # Due at the end of the purchase's month, plus `due_days` days (0 = the last day of the month).
    MONTH_END = "month_end", _("Fin de mois")


def paper_path(purchase: "FieldPurchase", filename: str) -> str:
    # A random name: the photo's address cannot be guessed from the purchase number.
    return f"field-purchases/{purchase.organization_id}/{uuid.uuid4().hex}.webp"


class FieldPurchase(OrganizationScopedModel, TimeStampedModel):
    """Goods a driver bought from a fisherman or at the port, sent from the phone to be checked (D-176).

    Nothing counts until the owner or the manager validates it: then a goods receipt puts the kg really received
    in stock, a posted supplier invoice records what is owed for them, and each sum given at the port becomes a
    supplier payment. Until then the driver and the office may change it; every save keeps a revision.
    """

    # "AT-2026-0001"... per organization and year ("achat terrain").
    number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=FieldPurchaseStatus.choices, default=FieldPurchaseStatus.SUBMITTED)
    # Empty while the driver bought from someone not in the list yet: then `proposed_supplier` holds the name.
    supplier = models.ForeignKey(
        "partners.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="field_purchases"
    )
    proposed_supplier = models.CharField(max_length=150, blank=True)
    proposed_supplier_phone = models.CharField(max_length=30, blank=True)
    bought_on = models.DateField()
    # Who bought it (the driver).
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # The deal made with the supplier for this purchase.
    terms = models.CharField(max_length=20, choices=PaymentTerms.choices, default=PaymentTerms.CASH)
    due_days = models.PositiveSmallIntegerField(default=0)
    # The number printed on the supplier's paper, when there is one, and a photo of that paper (D-159).
    supplier_reference = models.CharField(max_length=50, blank=True)
    paper = models.FileField(upload_to=paper_path, blank=True)
    # The driver's note, and the office's note to the driver.
    notes = models.TextField(blank=True)
    office_note = models.TextField(blank=True)
    # Where the goods go: chosen by the office before validating.
    location = models.ForeignKey(
        "inventory.StockLocation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Returnable boxes that came with the goods, per box type ("small", "big"), as on a receipt (D-122).
    boxes = models.JSONField(default=dict, blank=True)
    # The number of the last revision: a save must name it, so two people never overwrite each other.
    revision = models.PositiveIntegerField(default=1)
    receipt = models.OneToOneField(
        GoodsReceipt, null=True, blank=True, on_delete=models.PROTECT, related_name="field_purchase"
    )
    invoice = models.OneToOneField(
        SupplierInvoice, null=True, blank=True, on_delete=models.PROTECT, related_name="field_purchase"
    )
    # Sent by the phone, which may retry: the same value never makes two purchases (D-158).
    client_uuid = models.UUIDField(null=True, blank=True)
    # When the phone says it was bought (D-133); empty for one typed at the office. The day's cash counts it then.
    made_at = models.DateTimeField(null=True, blank=True)
    # Who validated or refused it, and when.
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-bought_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="field_purchase_number_unique_per_org"),
            models.UniqueConstraint(
                fields=["organization", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="field_purchase_client_uuid_unique_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(supplier__isnull=False) | ~models.Q(proposed_supplier=""),
                name="field_purchase_has_a_supplier",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="validated")
                | (models.Q(receipt__isnull=False) & models.Q(invoice__isnull=False)),
                name="field_purchase_validated_has_documents",
            ),
        ]

    def __str__(self) -> str:
        return self.number


class FieldPurchaseLine(OrganizationScopedModel):
    """One product bought: the kg the driver typed at the port, the kg really received, the price per kg."""

    purchase = models.ForeignKey(FieldPurchase, on_delete=models.CASCADE, related_name="lines")
    # Empty while the product is not in the catalogue yet: then `proposed_product` holds the name.
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    proposed_product = models.CharField(max_length=150, blank=True)
    # What the driver typed at the port (the supplier's weight).
    declared_quantity = QuantityField()
    # What the office counted, empty until then. This is what is owed (Q28).
    received_quantity = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    # DT per kg, without VAT (D-020).
    unit_cost = MoneyField()
    # A lot bought together with this partner (D-100): the owner's choice, made before validating.
    partner = models.ForeignKey("partners.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["purchase", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(product__isnull=False) | ~models.Q(proposed_product=""),
                name="field_purchase_line_has_a_product",
            ),
            models.CheckConstraint(
                condition=models.Q(declared_quantity__gt=0), name="field_purchase_line_declared_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(received_quantity__isnull=True) | models.Q(received_quantity__gt=0),
                name="field_purchase_line_received_positive",
            ),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="field_purchase_line_cost_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.purchase} · {self.product or self.proposed_product}"

    @property
    def owed_quantity(self) -> Decimal:
        """The kg received once counted, else the kg typed at the port: what the supplier is paid for."""
        return self.received_quantity if self.received_quantity is not None else self.declared_quantity

    @property
    def amount(self) -> Decimal:
        """Owed kg × price per kg."""
        return line_total(self.owed_quantity, self.unit_cost)


class FieldPurchasePayment(OrganizationScopedModel):
    """A sum given to the supplier at the port. It becomes a supplier payment at validation."""

    purchase = models.ForeignKey(FieldPurchase, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    amount = MoneyField()
    # Cheque or traite number.
    reference = models.CharField(max_length=50, blank=True)
    # The day a post-dated cheque or a traite may be cashed.
    cash_on = models.DateField(null=True, blank=True)
    supplier_payment = models.OneToOneField(
        SupplierPayment, null=True, blank=True, on_delete=models.PROTECT, related_name="field_purchase_payment"
    )

    class Meta:
        ordering = ["purchase", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="field_purchase_payment_positive")]

    def __str__(self) -> str:
        return f"{self.purchase} · {self.amount}"


class FieldPurchaseAction(models.TextChoices):
    SUBMITTED = "submitted", _("Envoyé")
    EDITED = "edited", _("Modifié")
    VALIDATED = "validated", _("Validé")
    REFUSED = "refused", _("Refusé")


class FieldPurchaseRevision(OrganizationScopedModel):
    """One saved state of a purchase: who saved it, when, why, and a full copy of what it said then.

    Never changed nor deleted: the history of a purchase is its revisions, the first one as the driver sent it.
    """

    purchase = models.ForeignKey(FieldPurchase, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    action = models.CharField(max_length=20, choices=FieldPurchaseAction.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # The office's note to the driver given with that save, if any.
    note = models.TextField(blank=True)
    snapshot = models.JSONField(encoder=DjangoJSONEncoder)

    class Meta:
        ordering = ["purchase", "number"]
        constraints = [models.UniqueConstraint(fields=["purchase", "number"], name="field_purchase_revision_unique")]

    def __str__(self) -> str:
        return f"{self.purchase} · v{self.number}"
