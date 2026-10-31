import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel
from apps.core.money import MoneyField, QuantityField


class DocumentCounter(OrganizationScopedModel):
    """The last number given to one series of sales documents ("DV" quotes...) in an organization.

    Locked while a number is taken (same scheme as batches, D-034), so two documents saved at once never
    share one. Sales and invoices (P2-T04, P2-T05) take their own series here.
    """

    series = models.CharField(max_length=20)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "series"], name="sales_one_counter_per_series"),
        ]

    def __str__(self) -> str:
        return f"{self.organization} · {self.series} · {self.last_number}"


# ---- Quotes (P2-T03, D-050) ----


class QuoteStatus(models.TextChoices):
    # Being prepared: customer, dates, lines and prices may still change.
    DRAFT = "draft", _("Brouillon")
    # Given to the customer: frozen, waiting for the answer until its validity date.
    SENT = "sent", _("Envoyé")
    # The customer said yes before the validity date: ready to become a sale (P2-T04).
    ACCEPTED = "accepted", _("Accepté")
    # The customer said no.
    REFUSED = "refused", _("Refusé")
    # Sent, but its validity date passed without an answer.
    EXPIRED = "expired", _("Expiré")


class Quote(OrganizationScopedModel, TimeStampedModel):
    """A price offer to a customer: products, kg and prices, valid until a date.

    Its prices are kept on its lines, so later price changes never touch it (D-020). Only a draft
    changes; once sent it is frozen, and the customer's answer (accepted, refused) or its validity date
    (expired) closes it. An accepted quote becomes one or several sales (BL, D-115). Nothing is reserved in the stock.
    """

    # "DV-0001", "DV-0002"... per organization, given by `services.create_quote`.
    number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=QuoteStatus.choices, default=QuoteStatus.DRAFT)
    # By name, not by import: an app only uses another app's services and selectors (ARCHITECTURE §3).
    customer = models.ForeignKey("partners.Customer", on_delete=models.PROTECT, related_name="quotes")
    # Where the goods would leave from (a cold room or a truck), if known. Information only: the stock it
    # holds is shown while typing, nothing is reserved; the sale (P2-T04) may start from it.
    location = models.ForeignKey(
        "inventory.StockLocation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    quoted_on = models.DateField()
    # The last day the customer may accept (included).
    valid_until = models.DateField()
    notes = models.TextField(blank=True)
    # Totals are computed by the services from the lines and frozen with them.
    # Sum of kg × price of the lines, before discounts.
    subtotal = MoneyField(default=Decimal("0.000"))
    discount_total = MoneyField(default=Decimal("0.000"))
    # subtotal − discount_total: what the customer pays before VAT.
    total_excl_tax = MoneyField(default=Decimal("0.000"))
    # VAT hook (P2-T05): empty until the finance settings (rate, prices with or without VAT, D-018) exist.
    # Nothing computes it yet, so `total` is the amount without VAT.
    # A MoneyField that may be empty (MoneyField itself is typed as never empty).
    tax_amount = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    total = MoneyField(default=Decimal("0.000"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    # Who recorded the customer's answer (accepted or refused), and when.
    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    answered_at = models.DateTimeField(null=True, blank=True)
    refusal_reason = models.CharField(max_length=255, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    # Sent by an app that may retry (the demo seed today): the same request never creates two quotes.
    client_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["-quoted_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="quote_number_unique_per_organization"),
            models.UniqueConstraint(
                fields=["organization", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="quote_client_uuid_unique_per_organization",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__gte=models.F("quoted_on")), name="quote_valid_after_quote_date"
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0, discount_total__gte=0, total_excl_tax__gte=0, total__gte=0),
                name="quote_totals_not_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "valid_until"], name="quote_status_validity_idx"),
            models.Index(fields=["organization", "quoted_on"], name="quote_day_idx"),
        ]

    def __str__(self) -> str:
        return self.number


class QuoteLine(OrganizationScopedModel):
    """One product of a quote: kg, price per kg and an optional discount in percent.

    The amounts are computed by the services: gross = kg × price (rounded once), discount = gross ×
    rate / 100 (rounded once), amount = gross − discount.
    """

    # A draft's lines are replaced as a whole when it changes; a quote itself is never deleted.
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quantity = QuantityField()
    # The lot the kilos should come from, carried to the BL made from the quote; empty: FIFO (D-121, D-201).
    requested_batch = models.ForeignKey(
        "inventory.Batch", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # DT per kg: the sale price in force when it was typed, or the one agreed with the customer.
    unit_price = MoneyField()
    # Percent, 2 decimals: 5.00 = 5 %.
    discount_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    gross_amount = MoneyField()
    discount_amount = MoneyField(default=Decimal("0.000"))
    amount = MoneyField()

    class Meta:
        ordering = ["quote", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="quote_line_quantity_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gt=0), name="quote_line_price_positive"),
            models.CheckConstraint(
                condition=models.Q(discount_rate__gte=0, discount_rate__lte=100), name="quote_line_discount_percent"
            ),
            models.CheckConstraint(
                condition=models.Q(gross_amount__gte=0, discount_amount__gte=0, amount__gte=0),
                name="quote_line_amounts_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quote} · {self.product_id}"


# ---- Sales (P2-T04, D-051) ----


class SaleStatus(models.TextChoices):
    # Being typed: customer, place, lines and prices may still change; no stock has moved.
    DRAFT = "draft", _("Brouillon")
    # The goods left the stock (oldest batch first) and the customer owes the amount not paid.
    CONFIRMED = "confirmed", _("Confirmée")
    # Given up: a draft simply stops; a confirmed sale brings its kilos back to the same batches.
    CANCELLED = "cancelled", _("Annulée")


class DeliveryStatus(models.TextChoices):
    """Where the BL of a truck load stands (D-178). Empty on a sale that was not prepared with a load."""

    # Validated and printed by the office: the goods are on the truck, nothing is sold yet.
    TO_DELIVER = "to_deliver", _("À livrer")
    # Delivered as written, or more (the weight at the client).
    DELIVERED = "delivered", _("Livré")
    # Less than written, or a product taken off: the rest stays on the truck.
    PARTIAL = "partial", _("Livré en partie")
    # Not delivered at all (the client refused, was closed, or the office gave it up): nothing was sold.
    CANCELLED = "cancelled", _("Non livré")


class SalePaymentMethod(models.TextChoices):
    """How the customer paid at the sale. Full customer payments are P2-T06's `CustomerPayment`."""

    CASH = "cash", _("Espèces")
    CHEQUE = "cheque", _("Chèque")
    TRANSFER = "transfer", _("Virement")
    CARD = "card", _("Carte bancaire")


class PriceSource(models.TextChoices):
    """Where the price of a sale line came from."""

    # The customer's own price list (D-049).
    PRICE_LIST = "price_list", _("Liste du client")
    # The daily price in force at the sale's moment (D-030).
    DAILY = "daily", _("Prix du jour")
    # The accepted quote's line (D-050).
    QUOTE = "quote", _("Devis")
    # Typed by the seller.
    TYPED = "typed", _("Saisi")
    # The price the driver's phone showed when the sale was made, checked by the server (P3-T02).
    SHOWN = "shown", _("Affiché au chauffeur")


class CreditStatus(models.TextChoices):
    """Where a sale stands against its customer's credit limit (P2-T06)."""

    PENDING = "pending", _("En attente d'approbation")
    APPROVED = "approved", _("Approuvée")
    WARNED = "warned", _("Limite dépassée")


class CreditPolicy(models.TextChoices):
    """What happens when a sale takes a customer above their credit limit: a company setting (D-018, Q16)."""

    BLOCK = "block", _("Bloquer la vente")
    APPROVAL = "approval", _("Demander l'approbation du propriétaire ou du gérant")
    WARN = "warn", _("Avertir et consigner")


class Sale(OrganizationScopedModel, TimeStampedModel):
    """Goods sold to a customer from one place (a cold room's counter or a truck), at one moment.

    A draft moves nothing. Confirming it takes each line's kilos out of the place oldest batch first
    (`inventory.services.post_fifo_movements`) and keeps, per line, which batches went at what cost
    (`SaleLineBatch`), so a lot's sales and profit are known later (D-040). A confirmed sale never changes:
    cancelling it brings the same kilos back to the same batches by `customer_return` movements, and the
    sale stays, marked cancelled. Never deleted.
    """

    # "VE-0001", "VE-0002"... per organization, given when the draft is created.
    number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=SaleStatus.choices, default=SaleStatus.DRAFT)
    # The walk-in customer ("Client de passage") for counter sales without a name (D-047).
    customer = models.ForeignKey("partners.Customer", on_delete=models.PROTECT, related_name="sales")
    # Where the goods leave from: a cold room open to counter sales, or a truck.
    location = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT, related_name="+")
    # When the sale was made: its prices are the ones in force then, and its movements happen then.
    sold_at = models.DateTimeField()
    # The accepted quote it came from, if any. A quote may be delivered in several sales (BL), each taking
    # part of its kilos (D-115).
    quote = models.ForeignKey(Quote, null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    notes = models.TextField(blank=True)
    # Where this delivery goes when it is not the customer's own address (D-160): typed on this BL only, never
    # written back to the customer. Empty means the customer's address.
    delivery_address = models.CharField(max_length=255, blank=True)
    # The truck load this BL was prepared with, if any (D-160): a draft made for each client when the load is
    # validated, confirmed at the delivery.
    transfer = models.ForeignKey(
        "inventory.Transfer", null=True, blank=True, on_delete=models.PROTECT, related_name="delivery_notes"
    )
    # Totals computed by the services from the lines, as on quotes.
    subtotal = MoneyField(default=Decimal("0.000"))
    discount_total = MoneyField(default=Decimal("0.000"))
    total_excl_tax = MoneyField(default=Decimal("0.000"))
    # The VAT of its issued invoice (D-057): empty while not invoiced, and again once that invoice is cancelled
    # by a credit note; 0.000 for an invoice without VAT. The sale's own amounts never change: `total` is the
    # sum of the lines as charged, and the invoice holds the tax detail (without VAT, VAT, stamp, with VAT).
    tax_amount = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    total = MoneyField(default=Decimal("0.000"))
    # Cost of the goods sold (FIFO batches × their cost per kg), known once confirmed.
    cost_total = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    # Paid on the spot (cash at the counter, a cheque handed to the driver...). P2-T06 brings full customer
    # payments; until then the receivable of a confirmed sale is `amount_due`.
    amount_paid = MoneyField(default=Decimal("0.000"))
    payment_method = models.CharField(max_length=20, choices=SalePaymentMethod.choices, blank=True)
    # Cheque number, transfer reference...
    payment_reference = models.CharField(max_length=50, blank=True)
    # total − amount_paid: what the customer still owes for this sale (P2-T06 hook).
    amount_due = MoneyField(default=Decimal("0.000"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    # The credit limit check at confirmation (P2-T06, D-018, D-062): "" = within the limit (or nothing owed),
    # `pending` = above it and waiting for the owner or a manager (a draft), `approved` = they accepted it,
    # `warned` = above it under the "warn and log" policy. `credit_over_by` is by how much the customer's
    # balance, with this sale, was above their limit.
    credit_status = models.CharField(max_length=20, choices=CreditStatus.choices, blank=True)
    credit_over_by = MoneyField(default=Decimal("0.000"))
    credit_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    credit_decided_at = models.DateTimeField(null=True, blank=True)
    # What a customer owed when the system started (P4-T01, D-112): no lines, no stock, never invoiced.
    is_opening = models.BooleanField(default=False)
    # Sent by an app that may retry (the driver app, the seed): the same request never makes two sales.
    client_uuid = models.UUIDField(null=True, blank=True)
    # The BL of a truck load (D-178): validated with its BL number when the load is validated (`issued_at`), then
    # delivered by the driver, in full or in part, or not at all. Nothing is sold before the delivery: the sale
    # stays a draft until then, so the client owes only what was delivered and the rest never left the truck.
    delivery_status = models.CharField(max_length=20, choices=DeliveryStatus.choices, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    # Each change of the BL after it was printed makes a new version (`SaleRevision`): 1 is the one printed.
    version = models.PositiveSmallIntegerField(default=1)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # The driver's word on the delivery (what changed, why it was not delivered); optional.
    delivery_note = models.CharField(max_length=255, blank=True)
    # Sent by the phone with the delivery: a retry answers with the delivery already recorded.
    delivery_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["-sold_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="sale_number_unique_per_organization"),
            models.UniqueConstraint(
                fields=["organization", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="sale_client_uuid_unique_per_organization",
            ),
            models.UniqueConstraint(
                fields=["organization", "delivery_uuid"],
                condition=models.Q(delivery_uuid__isnull=False),
                name="sale_delivery_uuid_unique_per_organization",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    subtotal__gte=0,
                    discount_total__gte=0,
                    total_excl_tax__gte=0,
                    total__gte=0,
                    amount_paid__gte=0,
                    amount_due__gte=0,
                ),
                name="sale_amounts_not_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "sold_at"], name="sale_status_day_idx"),
            models.Index(fields=["organization", "customer", "sold_at"], name="sale_customer_idx"),
            models.Index(fields=["organization", "location", "sold_at"], name="sale_location_idx"),
        ]

    def __str__(self) -> str:
        return self.number


class SaleBoxLine(OrganizationScopedModel):
    """Boxes left with the client for one sale, per box type (D-122): a count, not kg. Written with the draft,
    posted as `leave` movements when the sale is confirmed, reversed by `collect` when it is cancelled. The box
    type is checked by `boxes.services`, not here, so this app never imports the boxes models."""

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="box_lines")
    box_type = models.CharField(max_length=10)
    count = models.PositiveIntegerField()

    class Meta:
        ordering = ["sale", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(count__gt=0), name="sale_box_line_count_positive"),
            models.UniqueConstraint(fields=["sale", "box_type"], name="one_sale_box_line_per_type"),
        ]

    def __str__(self) -> str:
        return f"{self.sale} · {self.box_type} · {self.count}"


class SaleLine(OrganizationScopedModel):
    """One product of a sale: kg, the price per kg actually charged and an optional discount in percent.

    The price is kept here, so later price changes never touch the sale (D-020). Amounts as on quotes.
    Once confirmed, `batches` says which lots the kilos came from and at what cost.
    """

    # A draft's lines are replaced as a whole when it changes; a sale itself is never deleted.
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quantity = QuantityField()
    # Picked by hand instead of FIFO (D-121); empty takes the oldest lot first, as always. Honoured at
    # confirmation: this lot is taken from first; short, the rest still comes from the other lots oldest
    # first (`batches` then lists more than one), stock never going negative.
    requested_batch = models.ForeignKey(
        "inventory.Batch", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    unit_price = MoneyField()
    price_source = models.CharField(max_length=20, choices=PriceSource.choices)
    # The price was below the product's minimum when typed: a warning, never a block (D-049).
    below_minimum = models.BooleanField(default=False)
    discount_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    gross_amount = MoneyField()
    discount_amount = MoneyField(default=Decimal("0.000"))
    # gross − discount, without VAT: the line's revenue.
    amount = MoneyField()
    # Cost of the goods of this line (sum of its batches), known once confirmed.
    cost_amount = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    # On the BL of a truck load (D-178): the kg written on the BL the office printed. `quantity` is then what was
    # delivered. Null on any other sale.
    ordered_quantity = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=12, decimal_places=3, null=True, blank=True
    )

    class Meta:
        ordering = ["sale", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_line_quantity_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gt=0), name="sale_line_price_positive"),
            models.CheckConstraint(
                condition=models.Q(discount_rate__gte=0, discount_rate__lte=100), name="sale_line_discount_percent"
            ),
            models.CheckConstraint(
                condition=models.Q(gross_amount__gte=0, discount_amount__gte=0, amount__gte=0),
                name="sale_line_amounts_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sale} · {self.product_id}"


class SaleRevisionKind(models.TextChoices):
    ISSUED = "issued", _("Validé au chargement")
    EDITED = "edited", _("Modifié par le bureau")
    DELIVERED = "delivered", _("Livraison")
    CANCELLED = "cancelled", _("Non livré")


class SaleRevision(OrganizationScopedModel):
    """One version of the BL of a truck load, as it was then (D-178): never changed, never deleted.

    `lines` holds, per product, the kg written on the BL (`ordered`), what was delivered (`delivered`, at the
    delivery) and the price; `boxes` the boxes per type.
    """

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=20, choices=SaleRevisionKind.choices)
    lines = models.JSONField(default=list)
    boxes = models.JSONField(default=dict)
    total = MoneyField(default=Decimal("0.000"))
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sale", "id"]

    def __str__(self) -> str:
        return f"{self.sale} v{self.version} · {self.kind}"


class SaleLineBatch(OrganizationScopedModel):
    """The kilos of one sale line taken from one batch (lot) when the sale was confirmed, oldest batch
    first: the batch, its cost per kg then (snapshot), the cost and the line's revenue shared by kg.

    What a lot sold, for how much and at what cost is read from these rows (`selectors.batch_sales`), the
    base of its result (D-040). Written once at confirmation and never changed; a cancelled sale keeps them
    and its status says they no longer count.
    """

    line = models.ForeignKey(SaleLine, on_delete=models.PROTECT, related_name="batches")
    batch = models.ForeignKey("inventory.Batch", on_delete=models.PROTECT, related_name="+")
    quantity = QuantityField()
    # The batch's cost per kg when sold.
    unit_cost = MoneyField()
    # quantity × unit_cost, rounded once.
    cost_amount = MoneyField()
    # The line's amount (without VAT) shared by kg over its batches; the last batch takes the rounding rest,
    # so the parts always add up to the line.
    revenue_amount = MoneyField()

    class Meta:
        ordering = ["line", "id"]
        constraints = [
            models.UniqueConstraint(fields=["line", "batch"], name="one_row_per_sale_line_and_batch"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_line_batch_quantity_positive"),
        ]
        indexes = [models.Index(fields=["organization", "batch"], name="sale_line_batch_lot_idx")]

    def __str__(self) -> str:
        return f"{self.line} · {self.batch_id} · {self.quantity} kg"


class SaleLinePick(OrganizationScopedModel):
    """A lot a seller picked by hand for one sale line, and the kilos to take from it first (D-121, D-208).

    Several lots may be picked for one line; the kilos it asks beyond them come from the other lots, oldest
    first, and a lot too short is topped up the same way. Kept with the draft; once the sale is confirmed,
    `SaleLineBatch` says which lots the kilos really came from.
    """

    line = models.ForeignKey(SaleLine, on_delete=models.CASCADE, related_name="picks")
    batch = models.ForeignKey("inventory.Batch", on_delete=models.PROTECT, related_name="+")
    quantity = QuantityField()

    class Meta:
        ordering = ["line", "id"]
        constraints = [
            models.UniqueConstraint(fields=["line", "batch"], name="one_pick_per_sale_line_and_batch"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_line_pick_quantity_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.line} · {self.batch_id} · {self.quantity} kg"


# ---- Finance settings (P2-T05, D-018, D-056) ----


class FinanceSettings(OrganizationScopedModel, TimeStampedModel):
    """The organization's invoicing rules from `valid_from` on: VAT, fiscal stamp, prices with or without VAT,
    withholding tax, and the seller's identity printed on invoices.

    One version per day; the version in force on a day is the latest one that started on or before it
    (`selectors.finance_settings_on`). Never hard-coded: every organization starts with a first version
    holding the client's answers to Q5 (19 %, 1.000 DT, prices without VAT, no withholding), which the owner
    changes from the settings screen. These are defaults: a draft invoice may leave VAT out or change a rate,
    the stamp or the withholding rate (D-056). An invoice copies the values it used when it is issued, so a
    later version never changes it.
    """

    valid_from = models.DateField()
    # Percent, 2 decimals: the default VAT rate of every product (a product may have its own, D-056).
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("19.00"))
    # DT per invoice (droit de timbre). 0 = none.
    fiscal_stamp = MoneyField(default=Decimal("1.000"))
    # True: the sale prices already contain VAT, the invoice takes it out. False: VAT comes on top.
    prices_include_vat = models.BooleanField(default=False)
    # Percent, 2 decimals: the withholding tax (retenue à la source) some customers apply; 0 = never shown.
    withholding_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    # What happens above a customer's credit limit (P2-T06, D-018, D-062): block, ask for approval, or warn.
    credit_policy = models.CharField(max_length=20, choices=CreditPolicy.choices, default=CreditPolicy.BLOCK)
    # Who issues the invoices, as printed on them (article 18 of the VAT code).
    legal_name = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    # Matricule fiscal.
    tax_id = models.CharField(max_length=30, blank=True)
    # Registre national des entreprises.
    trade_register = models.CharField(max_length=50, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-valid_from", "-id"]
        verbose_name_plural = "finance settings"
        constraints = [
            models.UniqueConstraint(fields=["organization", "valid_from"], name="one_finance_settings_per_day"),
            models.CheckConstraint(
                condition=models.Q(vat_rate__gte=0, vat_rate__lte=100), name="finance_vat_rate_percent"
            ),
            models.CheckConstraint(
                condition=models.Q(withholding_rate__gte=0, withholding_rate__lte=100),
                name="finance_withholding_rate_percent",
            ),
            models.CheckConstraint(condition=models.Q(fiscal_stamp__gte=0), name="finance_stamp_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.organization} · {self.valid_from}"


# ---- Invoices and credit notes (P2-T05, D-057) ----


class InvoiceStatus(models.TextChoices):
    # Prepared from a confirmed sale: VAT, stamp and withholding may still change; no number yet.
    DRAFT = "draft", _("Brouillon")
    # Numbered and frozen: only a credit note corrects it.
    ISSUED = "issued", _("Émise")
    # Wholly cancelled by a credit note; the sale may be invoiced again.
    CANCELLED = "cancelled", _("Annulée par avoir")


class EInvoiceStatus(models.TextChoices):
    """TTN / El Fatoora e-invoicing hook (D-016): nothing is sent for now, so every invoice is `not_sent`."""

    NOT_SENT = "not_sent", _("Non transmise")


class Invoice(OrganizationScopedModel, TimeStampedModel):
    """The tax document of one confirmed sale: its lines, VAT per rate, fiscal stamp, total with VAT and the
    optional withholding tax.

    A draft takes the sale's lines (kg, prices and discounts as charged) and proposes VAT, stamp and
    withholding from the finance settings and each product's own rate; the person may leave VAT out, change
    a rate, an amount of VAT, the stamp or the withholding rate (each change is flagged and audited). Issuing
    it takes the next number of its year (FA-2026-0001...) in the same transaction, recomputes what was not
    changed by hand from the settings in force then, copies the seller and the customer, and freezes it. An
    issued invoice is never edited or deleted: a `CreditNote` corrects it.
    """

    # "FA-2026-0001"..., per organization and year; empty while a draft (taken only when issued: no gaps).
    number = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT)
    # The delivery notes (BL) this invoice bills, all of its customer (D-101): usually one, several for a
    # "facture récapitulative". Each line points to its own sale line.
    sales = models.ManyToManyField(Sale, through="InvoiceSale", related_name="invoices")
    customer = models.ForeignKey("partners.Customer", on_delete=models.PROTECT, related_name="invoices")
    # The finance settings version the values came from (the one in force when issued).
    settings_version = models.ForeignKey(
        FinanceSettings, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Copied from the settings: the sale prices contained VAT (taken out) or not (added on top).
    prices_include_vat = models.BooleanField(default=False)
    # False: an invoice without VAT ("sans TVA"): no rate, no VAT amount, nothing about VAT printed.
    apply_vat = models.BooleanField(default=True)
    issued_on = models.DateField(null=True, blank=True)
    # issued_on + the customer's payment terms.
    due_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # Seller and customer as printed, copied when issued (the customer's address may change later).
    seller_name = models.CharField(max_length=200, blank=True)
    seller_address = models.CharField(max_length=255, blank=True)
    seller_phone = models.CharField(max_length=50, blank=True)
    seller_tax_id = models.CharField(max_length=30, blank=True)
    seller_trade_register = models.CharField(max_length=50, blank=True)
    customer_name = models.CharField(max_length=150, blank=True)
    customer_address = models.CharField(max_length=255, blank=True)
    customer_city = models.CharField(max_length=100, blank=True)
    customer_tax_id = models.CharField(max_length=20, blank=True)
    # Totals, computed by the services from the lines and the VAT per rate.
    # kg × price before discounts, and the discounts, as charged on the sale.
    subtotal = MoneyField(default=Decimal("0.000"))
    discount_total = MoneyField(default=Decimal("0.000"))
    total_excl_tax = MoneyField(default=Decimal("0.000"))
    vat_total = MoneyField(default=Decimal("0.000"))
    fiscal_stamp = MoneyField(default=Decimal("0.000"))
    # The stamp was typed and differs from the settings.
    fiscal_stamp_overridden = models.BooleanField(default=False)
    # "Frais": fees typed by the office (delivery, packing...), outside VAT and withholding (D-126).
    fees = MoneyField(default=Decimal("0.000"))
    # total_excl_tax + vat_total + fiscal_stamp + fees.
    total_incl_tax = MoneyField(default=Decimal("0.000"))
    # Chosen before issuing; only shown when its rate is above 0 %.
    withholding_applied = models.BooleanField(default=False)
    withholding_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    withholding_rate_overridden = models.BooleanField(default=False)
    # (total_excl_tax + vat_total) × rate: the customer keeps it and pays the rest (P2-T06 records it).
    withholding_amount = MoneyField(default=Decimal("0.000"))
    # total_incl_tax − withholding_amount: what the customer pays.
    net_to_pay = MoneyField(default=Decimal("0.000"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # TTN / El Fatoora hook (D-016, Phase 8): nothing is sent yet; the reference TTN gives will land here.
    einvoice_status = models.CharField(max_length=20, choices=EInvoiceStatus.choices, default=EInvoiceStatus.NOT_SENT)
    einvoice_reference = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-issued_on", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "number"],
                condition=~models.Q(number=""),
                name="sale_invoice_number_unique_per_organization",
            ),
            models.CheckConstraint(
                condition=models.Q(status="draft") | ~models.Q(number=""), name="issued_invoice_has_number"
            ),
            models.CheckConstraint(
                condition=models.Q(withholding_rate__gte=0, withholding_rate__lte=100),
                name="invoice_withholding_rate_percent",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    subtotal__gte=0,
                    discount_total__gte=0,
                    total_excl_tax__gte=0,
                    vat_total__gte=0,
                    fiscal_stamp__gte=0,
                    total_incl_tax__gte=0,
                    withholding_amount__gte=0,
                    net_to_pay__gte=0,
                ),
                name="invoice_amounts_not_negative",
            ),
            models.CheckConstraint(condition=models.Q(fees__gte=0), name="invoice_fees_not_negative"),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "issued_on"], name="invoice_status_day_idx"),
            models.Index(fields=["organization", "customer", "issued_on"], name="invoice_customer_idx"),
        ]

    def __str__(self) -> str:
        return self.number or f"Brouillon {self.pk}"


class InvoiceSale(OrganizationScopedModel):
    """One delivery note (BL) billed by an invoice. A BL is on at most one live invoice (draft or issued);
    once the invoice is cancelled by a credit note (`is_live` false) the BL may be invoiced again."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="sale_links")
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="invoice_links")
    is_live = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["invoice", "sale"], name="one_row_per_invoice_and_sale"),
            models.UniqueConstraint(
                fields=["sale"], condition=models.Q(is_live=True), name="one_live_invoice_per_sale"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.invoice} · {self.sale_id}"


class InvoiceLine(OrganizationScopedModel):
    """One sale line on the invoice: what was charged (kg, price, discount, amount) and its VAT.

    `amount` is the line's amount as charged on the sale; with prices including VAT it already holds the VAT,
    otherwise VAT comes on top. `amount_excl_tax` and `vat_amount` are the line's share of the VAT of its rate
    (computed per rate, then shared by amount, so the lines always add up to the totals).
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    sale_line = models.ForeignKey(SaleLine, on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    # As printed, copied when issued.
    product_reference = models.CharField(max_length=30, blank=True)
    product_name = models.CharField(max_length=150, blank=True)
    # The lots the kilos came from ("L-0912, L-0918").
    lots = models.CharField(max_length=255, blank=True)
    quantity = QuantityField()
    unit_price = MoneyField()
    discount_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    gross_amount = MoneyField()
    discount_amount = MoneyField(default=Decimal("0.000"))
    amount = MoneyField()
    # Percent: the product's own rate, else the settings' rate, unless typed (`vat_rate_overridden`).
    # 0 = exempt; 0 too on an invoice without VAT.
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    vat_rate_overridden = models.BooleanField(default=False)
    # The price per kg without VAT, for printing (rounded to the millime; the amounts are exact).
    unit_price_excl_tax = MoneyField()
    amount_excl_tax = MoneyField()
    vat_amount = MoneyField(default=Decimal("0.000"))
    amount_incl_tax = MoneyField()

    class Meta:
        ordering = ["invoice", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(vat_rate__gte=0, vat_rate__lte=100), name="invoice_line_vat_rate_percent"
            ),
            models.CheckConstraint(
                condition=models.Q(amount_excl_tax__gte=0, vat_amount__gte=0, amount_incl_tax__gte=0),
                name="invoice_line_amounts_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.invoice} · {self.product_id}"


class InvoiceVatLine(OrganizationScopedModel):
    """The VAT of one rate on an invoice: base without VAT and amount. The amount may be typed on the draft
    (`amount_overridden`, audited); `computed_amount` keeps what the rate gave."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="vat_lines")
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    base = MoneyField()
    computed_amount = MoneyField()
    amount = MoneyField()
    amount_overridden = models.BooleanField(default=False)

    class Meta:
        ordering = ["invoice", "-rate"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "rate"], name="one_vat_line_per_invoice_and_rate"),
            models.CheckConstraint(condition=models.Q(base__gte=0, amount__gte=0), name="vat_line_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.invoice} · {self.rate} %"


class CreditNoteKind(models.TextChoices):
    # Everything the invoice still holds, stamp included: the invoice is cancelled.
    FULL = "full", _("Totale")
    # Some kilos or some amount of some lines (a return, a price correction).
    PARTIAL = "partial", _("Partielle")


class CreditNoteStock(models.TextChoices):
    # The kilos given back are not taken back (a weight dispute, a price correction): the stock is untouched.
    NONE = "none", _("Aucun mouvement de stock")
    # The goods come back to the stock, to the batches and place they left.
    RESTOCK = "restock", _("Remis en stock")
    # The goods come back but cannot be sold again: they are written off, on the lot they came from.
    LOSS = "loss", _("Mis en perte")


class CreditNote(OrganizationScopedModel, TimeStampedModel):
    """The only correction of an issued invoice (avoir): numbered AV-2026-0001... when made, never changed.

    A full credit note gives back everything the invoice still holds (lines, VAT, stamp, withholding) and
    cancels the invoice; a partial one gives back kilos or amounts of some lines with their VAT. `stock` says
    whether the kilos go back to the stock, are written off, or move nothing (customer returns, D-070).
    """

    number = models.CharField(max_length=20)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_notes")
    kind = models.CharField(max_length=20, choices=CreditNoteKind.choices)
    issued_on = models.DateField()
    reason = models.CharField(max_length=255)
    # What happened to the kilos given back (P2-T07, D-070).
    stock = models.CharField(max_length=20, choices=CreditNoteStock.choices, default=CreditNoteStock.NONE)
    total_excl_tax = MoneyField(default=Decimal("0.000"))
    vat_total = MoneyField(default=Decimal("0.000"))
    fiscal_stamp = MoneyField(default=Decimal("0.000"))
    # The invoice's fees given back: all of what is left on a full credit note, none on a partial one (D-126).
    fees = MoneyField(default=Decimal("0.000"))
    total_incl_tax = MoneyField(default=Decimal("0.000"))
    withholding_amount = MoneyField(default=Decimal("0.000"))
    # total_incl_tax − withholding_amount: what the customer no longer owes (or gets back).
    net_amount = MoneyField(default=Decimal("0.000"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    einvoice_status = models.CharField(max_length=20, choices=EInvoiceStatus.choices, default=EInvoiceStatus.NOT_SENT)
    einvoice_reference = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-issued_on", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "number"], name="credit_note_number_unique_per_organization"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    total_excl_tax__gte=0,
                    vat_total__gte=0,
                    fiscal_stamp__gte=0,
                    total_incl_tax__gte=0,
                    withholding_amount__gte=0,
                    net_amount__gte=0,
                ),
                name="credit_note_amounts_not_negative",
            ),
            models.CheckConstraint(condition=models.Q(fees__gte=0), name="credit_note_fees_not_negative"),
        ]

    def __str__(self) -> str:
        return self.number


class CreditNoteLine(OrganizationScopedModel):
    """What a credit note gives back on one invoice line: kilos (0 for a price correction) and amounts."""

    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="lines")
    invoice_line = models.ForeignKey(InvoiceLine, on_delete=models.PROTECT, related_name="credit_lines")
    quantity = QuantityField(default=Decimal("0.000"))
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    amount_excl_tax = MoneyField()
    vat_amount = MoneyField(default=Decimal("0.000"))
    amount_incl_tax = MoneyField()

    class Meta:
        ordering = ["credit_note", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0, amount_excl_tax__gte=0, vat_amount__gte=0),
                name="credit_note_line_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.credit_note} · {self.invoice_line_id}"


class CreditNoteLineBatch(OrganizationScopedModel):
    """What a credit note line takes back from one batch (lot) of the sale line: the revenue it reverses and,
    when the goods come back, their kilos and cost (the batch's cost per kg when sold).

    The lot's result nets these rows from its sales (D-070), so a return lowers the lot's revenue and cost of
    goods, and a loss movement then writes the spoiled goods off on the same lot.
    """

    line = models.ForeignKey(CreditNoteLine, on_delete=models.CASCADE, related_name="batches")
    sale_line_batch = models.ForeignKey(SaleLineBatch, on_delete=models.PROTECT, related_name="credit_rows")
    # Kilos that came back (0: a price correction, or goods not taken back).
    quantity = QuantityField(default=Decimal("0.000"))
    revenue_amount = MoneyField()
    cost_amount = MoneyField(default=Decimal("0.000"))

    class Meta:
        ordering = ["line", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0, revenue_amount__gte=0, cost_amount__gte=0),
                name="credit_note_line_batch_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.line} · {self.sale_line_batch_id} · {self.quantity} kg"


# ---- Customer payments (P2-T06, D-062) ----


def certificate_path(certificate: "WithholdingCertificate", filename: str) -> str:
    # A random name: the address of a customer's certificate cannot be guessed.
    extension = ".pdf" if filename.lower().endswith(".pdf") else ".webp"
    return f"withholding/{certificate.organization_id}/{uuid.uuid4().hex}{extension}"


class CustomerPaymentMethod(models.TextChoices):
    """How a customer settles after the sale (D-197): the sale's methods, the traite, and `mixed` for a
    règlement whose lines use several of them."""

    CASH = "cash", _("Espèces")
    CHEQUE = "cheque", _("Chèque")
    # A bill of exchange, common between Tunisian businesses.
    BILL = "bill", _("Traite")
    TRANSFER = "transfer", _("Virement")
    CARD = "card", _("Carte bancaire")
    # Only on the règlement itself, never on a line.
    MIXED = "mixed", _("Plusieurs moyens")


# The methods of a line that hand over an effet (a cheque or a traite) followed by the treasury.
INSTRUMENT_METHODS = frozenset({CustomerPaymentMethod.CHEQUE, CustomerPaymentMethod.BILL})


class CustomerPayment(OrganizationScopedModel, TimeStampedModel):
    """A règlement: money a customer paid after the sale, `RG-0001`... per organization.

    It holds one or more lines (`CustomerPaymentLine`: some cash, cheques, traites...; D-197) whose sum is
    `amount`, and is allocated to one or more sales (`PaymentAllocation`); what is not allocated stays as the
    customer's credit and lowers their balance all the same. Never edited or deleted: a mistake is voided
    (reason, who, when) and typed again. What a customer paid on the spot, at the sale, stays on the sale
    (`amount_paid`).
    """

    number = models.CharField(max_length=20)
    customer = models.ForeignKey("partners.Customer", on_delete=models.PROTECT, related_name="payments")
    # The sum of the lines.
    amount = MoneyField()
    # The lines' method, or `mixed` when they differ.
    method = models.CharField(max_length=20, choices=CustomerPaymentMethod.choices)
    # The day the money was received (not in the future).
    received_on = models.DateField()
    # When the driver's phone says it was received (D-133); empty for a payment entered at the office.
    made_at = models.DateTimeField(null=True, blank=True)
    # Cheque number, transfer reference...
    reference = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    void_reason = models.CharField(max_length=255, blank=True)
    # Sent by the driver app, which may retry: the same value never records a payment twice (P3-T11).
    client_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["-received_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="customer_payment_number_unique"),
            models.UniqueConstraint(
                fields=["organization", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="customer_payment_client_uuid_unique",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="customer_payment_amount_positive"),
        ]
        indexes = [
            models.Index(fields=["organization", "customer", "received_on"], name="customer_payment_idx"),
        ]

    def __str__(self) -> str:
        return self.number


class CustomerPaymentLine(OrganizationScopedModel):
    """One means of payment inside a règlement: some cash, a cheque, a traite, a transfer, a card (D-197).

    A cheque or a traite is an effet of the treasury (`instrument`), followed there until the bank pays it.
    Written once with its règlement, never changed.
    """

    payment = models.ForeignKey(CustomerPayment, on_delete=models.PROTECT, related_name="lines")
    method = models.CharField(max_length=20, choices=CustomerPaymentMethod.choices)
    amount = MoneyField()
    # A transfer or card reference; for an effet its number is on the instrument.
    reference = models.CharField(max_length=50, blank=True)
    instrument = models.OneToOneField(
        "treasury.Instrument", null=True, blank=True, on_delete=models.PROTECT, related_name="customer_line"
    )

    class Meta:
        ordering = ["payment", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="customer_payment_line_amount_positive"),
            models.CheckConstraint(condition=~models.Q(method="mixed"), name="customer_payment_line_method_not_mixed"),
        ]

    def __str__(self) -> str:
        return f"{self.payment} · {self.method} · {self.amount}"


class PaymentAllocation(OrganizationScopedModel):
    """The part of a payment that settles one sale. Written once; a voided payment's rows stop counting."""

    payment = models.ForeignKey(CustomerPayment, on_delete=models.PROTECT, related_name="allocations")
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="allocations")
    amount = MoneyField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["payment", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_allocation_amount_positive"),
        ]
        indexes = [models.Index(fields=["organization", "sale"], name="payment_allocation_sale_idx")]

    def __str__(self) -> str:
        return f"{self.payment} -> {self.sale} · {self.amount}"


class WithholdingCertificate(OrganizationScopedModel, TimeStampedModel):
    """The certificate (retenue à la source) a customer gives for what they withheld on an issued invoice:
    its number, date and file, and the amount really withheld (D-063).

    The invoice's receivable already took its own withholding off at issue (D-057); the certificate's amount
    replaces it, so a customer who withheld more or less than planned changes what they still owe. One live
    certificate per invoice; a mistake is voided and typed again.
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="certificates")
    number = models.CharField(max_length=50)
    issued_on = models.DateField()
    amount = MoneyField()
    # A photo (stored as WebP) or a PDF; may be joined later.
    file = models.FileField(upload_to=certificate_path, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-issued_on", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="withholding_cert_amount_positive"),
            models.UniqueConstraint(
                fields=["invoice"],
                condition=models.Q(voided_at__isnull=True),
                name="one_live_certificate_per_invoice",
            ),
        ]
        indexes = [models.Index(fields=["organization", "issued_on"], name="withholding_cert_day_idx")]

    def __str__(self) -> str:
        return self.number
