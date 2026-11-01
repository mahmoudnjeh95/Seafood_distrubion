import {
  ApiError,
  createSale,
  type SaleDetail,
  type SalePaymentMethodEnum,
  type SaleWrite,
  updateSale,
  useGetSale,
  useListCustomers,
  useListLocations,
  useListPriceLists,
  useListProducts,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  EmptyState,
  Field,
  Icon,
  Input,
  MoneyInput,
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useMemo, useState } from "react";
import { Link, Navigate, useOutletContext, useParams } from "react-router";

import { subtract, sum } from "../lib/decimal";
import { useLeave } from "../lib/embedded";
import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
import { choosePlace, type Need, needsOf, placesOf, totalsOf, usePlacesStock } from "../lib/placeStock";
import { usePartnerProducts } from "../partnerships/usePartnerProducts";
import {
  amountsOf,
  asTyped,
  filled,
  isZero,
  type Line,
  newLine,
  netUnderMinimum,
  rateAsTyped,
  shownPrice,
  withSpare,
} from "../lib/lines";
import { BelowMinimumReason } from "../lib/BelowMinimumReason";
import { LinesGrid } from "../lib/LinesGrid";
import { LotPicker } from "../lib/LotPicker";
import { VatHint } from "../lib/VatHint";
import { addressOf } from "../transfers/formLines";
import { canSell, localInputOf, momentOf, PAYMENT_METHODS, refreshAfterSale } from "./shared";

type Errors = Record<string, string>;

// Radix Select has no empty choice: these values stand for "the walk-in customer" and "not paid".
const WALK_IN = "walk-in";
const NO_METHOD = "none";

const lineKey = (index: number, field: string) => `lines.${index}.${field}`;

/** "Nouvelle vente": a draft, or a sale confirmed at once. */
export function SaleFormPage() {
  return <SaleForm />;
}

/** "Modifier VE-0003": a draft changed, or confirmed. */
export function SaleEditPage() {
  const { t } = useTranslation();
  const { saleId } = useParams();
  const id = Number(saleId);
  const validId = Number.isInteger(id) && id > 0;
  const sale = useGetSale(id, { query: { enabled: validId, retry: false } });
  if (validId && sale.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!sale.data) {
    const missing = !validId || (sale.error instanceof ApiError && sale.error.status === 404);
    return (
      <EmptyState illustration="mix" title={missing ? t("admin.sales.notFound") : t("common.serverUnreachable")} />
    );
  }
  if (sale.data.status !== "draft") return <Navigate to={`/ventes/${id}`} replace />;
  return <SaleForm key={sale.data.id} draft={sale.data} />;
}

function SaleForm({ draft }: { draft?: SaleDetail }) {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { embedded, leave } = useLeave();
  const queryClient = useQueryClient();
  const formId = useId();

  // Archived ones leave the pickers unless this sale already uses them (pickable).
  const customers = useListCustomers({ status: "all" });
  const locations = useListLocations({ status: "active" });
  const products = useListProducts({ status: "all" });

  const [customer, setCustomer] = useState(
    draft && !draft.customer.is_walk_in ? String(draft.customer.id) : draft ? WALK_IN : "",
  );
  const [soldAt, setSoldAt] = useState(draft ? localInputOf(draft.sold_at) : "");
  const [notes, setNotes] = useState(draft?.notes ?? "");
  // Where this delivery goes when it is not the client's own address: for this BL only (D-160).
  const [deliveryAddress, setDeliveryAddress] = useState(draft?.delivery_address ?? "");
  const [paidInFull, setPaidInFull] = useState(false);
  const [amountPaid, setAmountPaid] = useState(draft && !isZero(draft.amount_paid) ? asTyped(draft.amount_paid) : "");
  const [method, setMethod] = useState<string>(draft?.payment_method || NO_METHOD);
  const [reference, setReference] = useState(draft?.payment_reference ?? "");
  const [lines, setLines] = useState<Line[]>(() =>
    withSpare(
      (draft?.lines ?? []).map((line) =>
        newLine({
          product: String(line.product.id),
          quantity: asTyped(line.quantity),
          unit_price: asTyped(line.unit_price),
          discount_rate: isZero(line.discount_rate) ? "" : rateAsTyped(line.discount_rate),
          priceTouched: true,
          batch: line.requested_batch === null ? "" : String(line.requested_batch),
        }),
      ),
    ),
  );
  // Where each lot picked on a row sits: a sale leaves from one place, so a picked lot names it (D-201).
  const [lotPlaces, setLotPlaces] = useState<Record<string, number>>({});
  const [errors, setErrors] = useState<Errors>({});
  const [belowReason, setBelowReason] = useState("");

  // The sale leaves from one place: the seller picks products, and the place that holds them is found (D-144).
  const places = (locations.data ?? []).filter((option) => option.sells);
  const byPlace = usePlacesStock(places.map((option) => option.id));
  const totals = useMemo(() => totalsOf(byPlace), [byPlace]);
  const placeNames = useMemo(() => new Map(places.map((option) => [option.id, option.name])), [places]);
  const placesOfProduct = useMemo(() => placesOf(byPlace, placeNames), [byPlace, placeNames]);
  const partnerProducts = usePartnerProducts(session);
  // Where the sale leaves from, as the rows are typed: shown under each product.
  const shipFrom = choosePlace(needsOf(filled(lines)), byPlace);
  const shipFromName = places.find((option) => option.id === shipFrom)?.name;
  const origin = shipFromName ? new Map(needsOf(filled(lines)).map((need) => [need.product, shipFromName])) : undefined;
  const nameOf = (product: string) => products.data?.find((option) => String(option.id) === product)?.name ?? product;
  const dailyPrice = useMemo(() => {
    const byProduct = new Map<string, string | null>();
    for (const product of products.data ?? []) byProduct.set(String(product.id), product.current_price);
    return byProduct;
  }, [products.data]);
  // The customer's own price list wins over the daily price, as on the server (D-049).
  const realCustomer = customer !== "" && customer !== WALK_IN;
  const priceLists = useListPriceLists(
    { customer: Number(customer), status: "active" },
    { query: { enabled: realCustomer } },
  );
  const customerList = realCustomer ? priceLists.data?.[0] : undefined;
  const listPrice = useMemo(() => {
    const byProduct = new Map<string, string>();
    for (const item of customerList?.items ?? []) byProduct.set(String(item.product), item.price);
    return byProduct;
  }, [customerList]);
  const proposedPrice = (product: string): string | null => listPrice.get(product) ?? dailyPrice.get(product) ?? null;
  const priceOf = (line: Line): string => shownPrice(line, proposedPrice(line.product));
  // Said under the grid for the row being typed in: where its price comes from.
  const priceHint = (line: Line): string => {
    const fromList = listPrice.get(line.product);
    const inForce = dailyPrice.get(line.product);
    if (fromList && customerList) {
      return t("admin.sales.form.listPrice", { list: customerList.name, price: formatMoney(fromList) });
    }
    return inForce
      ? t("admin.sales.form.priceInForce", { price: formatMoney(inForce) })
      : t("admin.sales.form.noPrice");
  };

  const save = useMutation({
    mutationFn: (payload: SaleWrite) => (draft ? updateSale(draft.id, payload) : createSale(payload)),
    onSuccess: async (saved) => {
      toast.success(
        t(saved.status === "confirmed" ? "admin.sales.form.confirmed" : "admin.sales.form.created", {
          number: saved.number,
        }),
      );
      await refreshAfterSale(queryClient);
      leave(`/ventes/${saved.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.sales.form.error") });
    },
  });

  if (!canSell(session)) return <Navigate to="/ventes" replace />;

  // Rows whose price after the discount is under the product's minimum (D-163): the owner and the manager may
  // accept them with a reason, the others must correct them (D-193).
  const canApprove = session.role === "owner" || session.role === "manager";
  const belowCount = filled(lines).filter((line) =>
    netUnderMinimum(
      line,
      priceOf(line),
      (products.data ?? []).find((product) => String(product.id) === line.product)?.min_price ?? null,
    ),
  ).length;

  // Browser-side preview of the server's amounts: gross, discount, net per line.
  const priced = lines.flatMap((line) => amountsOf(line, priceOf(line)) ?? []);
  const subtotal = sum(priced.map((preview) => preview.gross));
  const discountTotal = sum(priced.map((preview) => preview.discount));
  const totalExclTax = subtract(subtotal, discountTotal);

  function submit(confirmNow: boolean) {
    const found: Errors = {};
    if (!customer) found.customer = t("admin.sales.form.required");
    // The grid's blank rows are places to type in, not lines of the sale.
    const rows = filled(lines);
    if (rows.length === 0) found.lines = t("admin.sales.form.noLines");
    const payloadLines: SaleWrite["lines"] = [];
    rows.forEach((line, index) => {
      if (!line.product) found[lineKey(index, "product")] = t("admin.sales.form.required");
      const quantity = parseDecimalInput(line.quantity.trim(), 3);
      if (quantity === null || quantity.startsWith("-") || isZero(quantity)) {
        found[lineKey(index, "quantity")] = t("admin.sales.form.weight");
      }
      let price: string | null = null;
      const typedPrice = priceOf(line).trim();
      if (typedPrice !== "") {
        price = parseDecimalInput(typedPrice, 3);
        if (price === null || price.startsWith("-")) found[lineKey(index, "unit_price")] = t("admin.sales.form.money");
      }
      let rate: string | null = null;
      const typedRate = line.discount_rate.trim();
      if (typedRate !== "") {
        rate = parseDecimalInput(typedRate, 2);
        if (rate === null || rate.startsWith("-")) found[lineKey(index, "discount_rate")] = t("admin.sales.form.rate");
      }
      payloadLines.push({
        product: Number(line.product),
        quantity: quantity ?? "",
        unit_price: price,
        discount_rate: rate,
        batch: line.batch ? Number(line.batch) : null,
      });
    });
    let paid: string | null = null;
    if (!paidInFull && amountPaid.trim() !== "") {
      paid = parseDecimalInput(amountPaid.trim(), 3);
      if (paid === null || paid.startsWith("-")) found.amount_paid = t("admin.sales.form.money");
    }
    const needs: Need[] = needsOf(rows);
    // A lot picked by hand fixes the place; without one, the place that holds every product is found (D-144).
    const lotPlace = new Set<number>();
    for (const line of rows) {
      const where = line.batch ? (lotPlaces[line.batch] ?? draft?.location.id) : undefined;
      if (where !== undefined) lotPlace.add(where);
    }
    const [onlyLotPlace] = lotPlace;
    const place = lotPlace.size === 1 && onlyLotPlace !== undefined ? onlyLotPlace : choosePlace(needs, byPlace);
    if (lotPlace.size > 1) found.lines = t("admin.sales.counterSale.lotPlaces");
    else if (place === null && needs.length > 0) {
      found.lines = t("admin.sales.form.noSinglePlace", {
        products: needs.map((need) => nameOf(need.product)).join(", "),
      });
    }
    if (belowCount > 0 && canApprove && !belowReason.trim())
      found.below_minimum_reason = t("admin.lines.floor.required");
    setErrors(found);
    if (Object.keys(found).length > 0 || place === null) return;
    save.mutate({
      customer: customer === WALK_IN ? null : Number(customer),
      location: place,
      sold_at: momentOf(soldAt),
      notes: notes.trim(),
      delivery_address: deliveryAddress.trim(),
      lines: payloadLines,
      paid_in_full: paidInFull,
      amount_paid: paid,
      payment_method: method === NO_METHOD ? "" : (method as SalePaymentMethodEnum),
      payment_reference: reference.trim(),
      confirm_now: confirmNow,
      below_minimum_reason: belowCount > 0 && canApprove ? belowReason.trim() : "",
    });
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit(false);
  }

  const id = (name: string) => `${formId}-${name}`;
  const select = (
    name: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    options: { value: string; label: string }[],
    className?: string,
  ) => (
    <Field label={label} htmlFor={id(name)} error={errors[name]} className={className}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id(name)} aria-invalid={errors[name] ? true : undefined}>
          <SelectValue placeholder={t("admin.sales.form.choose")} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
  const back = draft ? `/ventes/${draft.id}` : "/ventes";

  return (
    <>
      {!embedded && (
        <Link to={back} className="text-[0.85rem] font-semibold text-sea hover:underline">
          {t("admin.sales.back")}
        </Link>
      )}
      <PageHeader
        eyebrow={t("admin.sales.title")}
        title={draft ? t("admin.sales.form.titleEdit", { number: draft.number }) : t("admin.sales.form.titleNew")}
      />

      <form id={formId} onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-4 gap-4 max-[1000px]:grid-cols-2 max-[600px]:grid-cols-1">
          {select(
            "customer",
            t("admin.sales.form.customer"),
            customer,
            setCustomer,
            [
              { value: WALK_IN, label: t("admin.sales.form.walkIn") },
              ...pickable(customers.data ?? [], [customer])
                .filter((option) => !option.is_walk_in)
                .map((option) => ({ value: String(option.id), label: `${option.name} · ${option.reference}` })),
            ],
            "col-span-2 max-[600px]:col-span-1",
          )}
          <Field label={t("admin.sales.form.soldAt")} htmlFor={id("sold_at")} error={errors.sold_at}>
            <Input
              id={id("sold_at")}
              type="datetime-local"
              value={soldAt}
              onChange={(event) => setSoldAt(event.target.value)}
              aria-invalid={errors.sold_at ? true : undefined}
              aria-describedby={id("sold_at_hint")}
            />
            <p id={id("sold_at_hint")} className="text-[0.8rem] text-ink-2">
              {t("admin.sales.form.soldAtHint")}
            </p>
          </Field>
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.sales.form.lines")}</CardTitle>
          <VatHint lines={lines} products={products.data ?? []} />
          <LinesGrid
            label={t("admin.sales.form.lines")}
            lines={lines}
            onChange={setLines}
            products={pickable(
              products.data ?? [],
              lines.map((line) => line.product),
            )}
            proposedPrice={proposedPrice}
            stock={places.length > 0 ? totals : undefined}
            origin={origin}
            places={placesOfProduct}
            partners={partnerProducts}
            errors={errors}
            discount
            hint={priceHint}
            extra={{
              header: t("admin.sales.counterSale.lot"),
              field: "batch",
              cell: (line, change) => (
                <LotPicker
                  line={line}
                  onChange={(batch, location) => {
                    change({ batch });
                    if (batch && location !== null) setLotPlaces((known) => ({ ...known, [batch]: location }));
                  }}
                />
              ),
            }}
          />
          {errors.lines && <p className="text-[0.78rem] font-semibold text-bad">{errors.lines}</p>}
          <div className="flex flex-wrap items-start gap-x-8 gap-y-2">
            <dl className="ms-auto flex flex-wrap gap-x-8 gap-y-2">
              {discountTotal !== "0.000" && (
                <>
                  <div>
                    <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.sales.detail.subtotal")}</dt>
                    <dd className="num">{formatMoney(subtotal)}</dd>
                  </div>
                  <div>
                    <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.sales.detail.discountTotal")}</dt>
                    <dd className="num">−{formatMoney(discountTotal)}</dd>
                  </div>
                </>
              )}
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.sales.detail.totalExclTax")}</dt>
                <dd className="num font-bold">{formatMoney(totalExclTax)}</dd>
              </div>
            </dl>
          </div>
        </Card>

        <BelowMinimumReason
          count={belowCount}
          canApprove={canApprove}
          reason={belowReason}
          onReason={setBelowReason}
          error={errors.below_minimum_reason}
        />

        <Card className="grid grid-cols-4 items-start gap-4 max-[1000px]:grid-cols-2 max-[600px]:grid-cols-1">
          <CardTitle className="col-span-4 mb-0 max-[1000px]:col-span-2 max-[600px]:col-span-1">
            {t("admin.sales.form.payment")}
          </CardTitle>
          <label className="flex items-center gap-2 self-end pb-2.5 font-semibold">
            <input
              type="checkbox"
              checked={paidInFull}
              onChange={(event) => setPaidInFull(event.target.checked)}
              className="size-4 accent-sea"
            />
            {t("admin.sales.form.paidInFull")}
          </label>
          <Field label={t("admin.sales.form.amountPaid")} htmlFor={id("amount_paid")} error={errors.amount_paid}>
            <MoneyInput
              id={id("amount_paid")}
              inputMode="decimal"
              value={paidInFull ? asTyped(totalExclTax) : amountPaid}
              disabled={paidInFull}
              onChange={(event) => setAmountPaid(event.target.value)}
              aria-invalid={errors.amount_paid ? true : undefined}
              autoComplete="off"
              className="num"
            />
          </Field>
          {select("payment_method", t("admin.sales.form.method"), method, setMethod, [
            { value: NO_METHOD, label: t("admin.sales.detail.none") },
            ...PAYMENT_METHODS.map((value) => ({ value, label: t(`admin.sales.methods.${value}`) })),
          ])}
          <Field label={t("admin.sales.form.reference")} htmlFor={id("payment_reference")}>
            <Input
              id={id("payment_reference")}
              value={reference}
              maxLength={50}
              onChange={(event) => setReference(event.target.value)}
            />
          </Field>
          {customer === WALK_IN && (
            <p className="col-span-4 text-[0.85rem] text-ink-2 max-[1000px]:col-span-2 max-[600px]:col-span-1">
              {t("admin.sales.form.walkInPays")}
            </p>
          )}
        </Card>

        <Card className="flex flex-col gap-4">
          <Field
            label={t("admin.sales.form.deliveryAddress")}
            htmlFor={id("deliveryAddress")}
            error={errors.delivery_address}
          >
            <Input
              id={id("deliveryAddress")}
              value={deliveryAddress}
              maxLength={255}
              autoComplete="off"
              placeholder={addressOf(customers.data?.find((candidate) => String(candidate.id) === customer))}
              onChange={(event) => setDeliveryAddress(event.target.value)}
            />
            <p className="text-[0.85rem] text-ink-2">{t("admin.sales.form.deliveryAddressHint")}</p>
          </Field>
          <Field label={t("admin.sales.form.notes")} htmlFor={id("notes")} error={errors.notes}>
            <textarea
              id={id("notes")}
              rows={2}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
            />
          </Field>
        </Card>

        {errors.detail && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail}
          </p>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={() => leave(back)}>{t("admin.sales.form.cancel")}</Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? t("admin.sales.form.saving") : t("admin.sales.form.saveDraft")}
          </Button>
          <Button variant="primary" disabled={save.isPending} onClick={() => submit(true)}>
            <Icon name="check" />
            {t("admin.sales.form.confirm")}
          </Button>
        </div>
      </form>
    </>
  );
}
