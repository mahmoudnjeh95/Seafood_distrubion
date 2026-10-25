import {
  acceptQuote,
  ApiError,
  createQuote,
  type QuoteDetail,
  type QuoteWrite,
  updateQuote,
  type WebRequest,
  useGetQuote,
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
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, Navigate, useOutletContext, useParams } from "react-router";

import { subtract, sum } from "../lib/decimal";
import { useLeave } from "../lib/embedded";
import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
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
import { placesOf, totalsOf, usePlacesStock, usePlacesStockLoaded } from "../lib/placeStock";
import { usePartnerProducts } from "../partnerships/usePartnerProducts";
import { todayInTunis } from "../receipts/shared";
import { DeliverDialog } from "./DeliverDialog";
import { canWriteQuotes, refreshAfterQuote } from "./shared";

type Errors = Record<string, string>;

// The server's default validity (D-050); the form shows it so it can be changed before saving.
const VALIDITY_DAYS = 3;

const lineKey = (index: number, field: string) => `lines.${index}.${field}`;

/** The last eight digits of a phone number: the same number with or without +216, spaces or dashes. */
const digitsOf = (phone: string) => phone.replace(/\D/g, "").slice(-8);
const samePhone = (a: string, b: string) => digitsOf(a) !== "" && digitsOf(a) === digitsOf(b);

/** An ISO day plus some days, in the calendar (no time zone involved). */
function addDays(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** "Nouveau devis": a new draft, or one sent at once. From a web request, its products are already in (D-186). */
export function QuoteFormPage({ fromRequest }: { fromRequest?: WebRequest }) {
  return <QuoteForm fromRequest={fromRequest} />;
}

/** "Modifier DV-2026-0003": a draft changed, or sent. */
export function QuoteEditPage() {
  const { t } = useTranslation();
  const { quoteId } = useParams();
  const id = Number(quoteId);
  const validId = Number.isInteger(id) && id > 0;
  const quote = useGetQuote(id, { query: { enabled: validId, retry: false } });
  if (validId && quote.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!quote.data) {
    const missing = !validId || (quote.error instanceof ApiError && quote.error.status === 404);
    return (
      <EmptyState illustration="mix" title={missing ? t("admin.quotes.notFound") : t("common.serverUnreachable")} />
    );
  }
  if (quote.data.status !== "draft") return <Navigate to={`/devis/${id}`} replace />;
  return <QuoteForm key={quote.data.id} draft={quote.data} />;
}

function QuoteForm({ draft, fromRequest }: { draft?: QuoteDetail; fromRequest?: WebRequest }) {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { embedded, leave } = useLeave();
  const queryClient = useQueryClient();
  const formId = useId();

  // All of them, archived ones left out of the pickers unless the quote already uses them (pickable).
  const customers = useListCustomers({ status: "all" });
  const locations = useListLocations({ status: "all" });
  const products = useListProducts({ status: "all" });

  const [customer, setCustomer] = useState(draft ? String(draft.customer.id) : "");
  const [day, setDay] = useState(draft?.quoted_on ?? todayInTunis());
  const [validUntil, setValidUntil] = useState(draft?.valid_until ?? addDays(todayInTunis(), VALIDITY_DAYS));
  // Until the validity is typed, it follows the quote's day.
  const [validTouched, setValidTouched] = useState(draft !== undefined);
  const [notes, setNotes] = useState(draft?.notes ?? "");
  // A web request's products come in with their kilos; the price is proposed as for any line, until typed.
  const [lines, setLines] = useState<Line[]>(() =>
    withSpare(
      draft
        ? draft.lines.map((line) =>
            newLine({
              product: String(line.product.id),
              quantity: asTyped(line.quantity),
              unit_price: asTyped(line.unit_price),
              discount_rate: isZero(line.discount_rate) ? "" : rateAsTyped(line.discount_rate),
              priceTouched: true,
            }),
          )
        : (fromRequest?.lines ?? []).map((line) =>
            newLine({ product: String(line.product), quantity: asTyped(line.quantity) }),
          ),
    ),
  );
  // A site request whose phone is a customer's: that customer is picked once, the office can change it (D-192).
  const customerOfRequest = useMemo(() => {
    if (!fromRequest) return undefined;
    const matches = (customers.data ?? []).filter(
      (option) => option.is_active && samePhone(option.phone, fromRequest.phone),
    );
    const [only] = matches;
    return matches.length === 1 && only ? String(only.id) : undefined;
  }, [customers.data, fromRequest]);
  const suggested = useRef(false);
  useEffect(() => {
    if (suggested.current || customerOfRequest === undefined) return;
    suggested.current = true;
    setCustomer((current) => current || customerOfRequest);
  }, [customerOfRequest]);
  const [errors, setErrors] = useState<Errors>({});
  const [belowReason, setBelowReason] = useState("");

  // A quote has no place of its own: the kilos left are those in all the places (D-144).
  const activePlaces = (locations.data ?? []).filter((option) => option.is_active).map((option) => option.id);
  const byPlace = usePlacesStock(activePlaces);
  const stockLoaded = usePlacesStockLoaded(activePlaces);
  // No places are known until the list of places has loaded: the grid then shows no stock line yet.
  const placesLoaded = locations.data !== undefined && stockLoaded;
  const availableOf = useMemo(() => totalsOf(byPlace), [byPlace]);
  // Where each product is kept, by the place's name: listed under the product in the grid (D-144).
  const placeNames = useMemo(
    () => new Map((locations.data ?? []).map((place) => [place.id, place.name])),
    [locations.data],
  );
  const placesOfProduct = useMemo(() => placesOf(byPlace, placeNames), [byPlace, placeNames]);
  const partnerProducts = usePartnerProducts(session);
  const dailyPrice = useMemo(() => {
    const byProduct = new Map<string, string | null>();
    for (const product of products.data ?? []) byProduct.set(String(product.id), product.current_price);
    return byProduct;
  }, [products.data]);
  // The customer's own price list wins over the daily price, as on the server (D-049).
  const priceLists = useListPriceLists(
    { customer: Number(customer), status: "active" },
    { query: { enabled: customer !== "" } },
  );
  const customerList = priceLists.data?.[0];
  const listPrice = useMemo(() => {
    const byProduct = new Map<string, string>();
    for (const item of customerList?.items ?? []) byProduct.set(String(item.product), item.price);
    return byProduct;
  }, [customerList]);
  const proposedPrice = (product: string): string | null => listPrice.get(product) ?? dailyPrice.get(product) ?? null;

  // A line shows the price the customer is charged until a price is typed; the server keeps it on the line.
  const priceOf = (line: Line): string => shownPrice(line, proposedPrice(line.product));
  // Said under the grid for the row being typed in: where its price comes from.
  const priceHint = (line: Line): string => {
    const fromList = listPrice.get(line.product);
    const inForce = dailyPrice.get(line.product);
    if (fromList && customerList) {
      return t("admin.quotes.form.listPrice", { list: customerList.name, price: formatMoney(fromList) });
    }
    return inForce
      ? t("admin.quotes.form.priceInForce", { price: formatMoney(inForce) })
      : t("admin.quotes.form.noPrice");
  };

  // Set once a quote is accepted from its window: the BL dialog then opens over the form (D-192).
  const [converting, setConverting] = useState<number | null>(null);
  const save = useMutation({
    mutationFn: ({ payload }: { payload: QuoteWrite; approve: boolean }) =>
      draft ? updateQuote(draft.id, payload) : createQuote(payload),
    onSuccess: async (saved, { approve }) => {
      toast.success(
        t(saved.status === "sent" ? "admin.quotes.form.sent" : "admin.quotes.form.created", { number: saved.number }),
      );
      await refreshAfterQuote(queryClient);
      if (!approve) {
        leave(`/devis/${saved.id}`);
        return;
      }
      // "Accepter et créer le BL" (D-192): the customer's yes is recorded, then the BL is made in this window.
      try {
        await acceptQuote(saved.id);
      } catch {
        // Already saved and sent: the person accepts it on its page, so nothing is saved twice.
        toast.error(t("admin.quotes.detail.actionError"));
        leave(`/devis/${saved.id}`);
        return;
      }
      await refreshAfterQuote(queryClient);
      setConverting(saved.id);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.quotes.form.error") });
    },
  });

  if (!canWriteQuotes(session)) return <Navigate to="/devis" replace />;

  // Rows whose price after the discount is under the product's minimum (D-163): the owner and the manager may
  // accept them with a reason, the others must correct them (D-193).
  const canApprove = session.role === "owner" || session.role === "manager";
  const belowCount = filled(lines).filter((line) =>
    netUnderMinimum(
      line,
      priceOf(line),
      (products.data ?? []).find((p) => String(p.id) === line.product)?.min_price ?? null,
    ),
  ).length;

  // Browser-side preview of the server's amounts (D-050): gross, discount, net per line.
  const priced = lines.flatMap((line) => amountsOf(line, priceOf(line)) ?? []);
  const subtotal = sum(priced.map((preview) => preview.gross));
  const discountTotal = sum(priced.map((preview) => preview.discount));
  const totalExclTax = subtract(subtotal, discountTotal);

  function submit(sendNow: boolean, approve = false) {
    const found: Errors = {};
    if (!customer) found.customer = t("admin.quotes.form.required");
    if (!day) found.quoted_on = t("admin.quotes.form.required");
    if (!validUntil) found.valid_until = t("admin.quotes.form.required");
    else if (day && validUntil < day) found.valid_until = t("admin.quotes.form.validBefore");
    // The grid's blank rows are places to type in, not lines of the quote.
    const rows = filled(lines);
    if (rows.length === 0) found.lines = t("admin.quotes.form.noLines");
    const payloadLines: QuoteWrite["lines"] = [];
    rows.forEach((line, index) => {
      if (!line.product) found[lineKey(index, "product")] = t("admin.quotes.form.required");
      const quantity = parseDecimalInput(line.quantity.trim(), 3);
      if (quantity === null || quantity.startsWith("-") || isZero(quantity)) {
        found[lineKey(index, "quantity")] = t("admin.quotes.form.weight");
      }
      let price: string | null = null;
      const typedPrice = priceOf(line).trim();
      if (typedPrice !== "") {
        price = parseDecimalInput(typedPrice, 3);
        if (price === null || price.startsWith("-")) found[lineKey(index, "unit_price")] = t("admin.quotes.form.money");
      }
      let rate: string | null = null;
      const typedRate = line.discount_rate.trim();
      if (typedRate !== "") {
        rate = parseDecimalInput(typedRate, 2);
        if (rate === null || rate.startsWith("-")) found[lineKey(index, "discount_rate")] = t("admin.quotes.form.rate");
      }
      payloadLines.push({
        product: Number(line.product),
        quantity: quantity ?? "",
        unit_price: price,
        discount_rate: rate,
      });
    });
    if (belowCount > 0 && canApprove && !belowReason.trim())
      found.below_minimum_reason = t("admin.lines.floor.required");
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    save.mutate({
      payload: {
        customer: Number(customer),
        // Kept as it was: the place is chosen when the quote is delivered.
        location: draft?.location?.id ?? null,
        quoted_on: day,
        valid_until: validUntil,
        notes: notes.trim(),
        lines: payloadLines,
        send_now: sendNow,
        below_minimum_reason: belowCount > 0 && canApprove ? belowReason.trim() : "",
      },
      approve,
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
          <SelectValue placeholder={t("admin.quotes.form.choose")} />
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
  const dateInput = (name: string, label: string, value: string, onChange: (value: string) => void) => (
    <Field label={label} htmlFor={id(name)} error={errors[name]}>
      <Input
        id={id(name)}
        type="date"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={errors[name] ? true : undefined}
      />
    </Field>
  );
  const back = draft ? `/devis/${draft.id}` : "/devis";

  return (
    <>
      {!embedded && (
        <Link to={back} className="text-[0.85rem] font-semibold text-sea hover:underline">
          {t("admin.quotes.back")}
        </Link>
      )}
      <PageHeader
        eyebrow={t("admin.quotes.title")}
        title={draft ? t("admin.quotes.form.titleEdit", { number: draft.number }) : t("admin.quotes.form.titleNew")}
      />

      <form id={formId} onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-4 gap-4 max-[1000px]:grid-cols-2 max-[600px]:grid-cols-1">
          {select(
            "customer",
            t("admin.quotes.form.customer"),
            customer,
            setCustomer,
            pickable(customers.data ?? [], [customer]).map((option) => ({
              value: String(option.id),
              label: `${option.name} · ${option.reference}`,
            })),
            "col-span-2 max-[600px]:col-span-1",
          )}
          {dateInput("quoted_on", t("admin.quotes.form.date"), day, (value) => {
            setDay(value);
            if (!validTouched && value) setValidUntil(addDays(value, VALIDITY_DAYS));
          })}
          {dateInput("valid_until", t("admin.quotes.form.validUntil"), validUntil, (value) => {
            setValidUntil(value);
            setValidTouched(true);
          })}
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.quotes.form.lines")}</CardTitle>
          <LinesGrid
            label={t("admin.quotes.form.lines")}
            lines={lines}
            onChange={setLines}
            products={pickable(
              products.data ?? [],
              lines.map((line) => line.product),
            )}
            proposedPrice={proposedPrice}
            stock={locations.data ? availableOf : undefined}
            places={placesLoaded ? placesOfProduct : undefined}
            partners={partnerProducts}
            errors={errors}
            discount
            hint={priceHint}
          />
          {errors.lines && <p className="text-[0.78rem] font-semibold text-bad">{errors.lines}</p>}
          <div className="flex flex-wrap items-start gap-x-8 gap-y-2">
            <dl className="ms-auto flex flex-wrap gap-x-8 gap-y-2">
              {discountTotal !== "0.000" && (
                <>
                  <div>
                    <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.quotes.detail.subtotal")}</dt>
                    <dd className="num">{formatMoney(subtotal)}</dd>
                  </div>
                  <div>
                    <dt className="text-[0.78rem] font-semibold text-ink-2">
                      {t("admin.quotes.detail.discountTotal")}
                    </dt>
                    <dd className="num">−{formatMoney(discountTotal)}</dd>
                  </div>
                </>
              )}
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.quotes.detail.totalExclTax")}</dt>
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

        <Card>
          <Field label={t("admin.quotes.form.notes")} htmlFor={id("notes")} error={errors.notes}>
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
          <Button onClick={() => leave(back)}>{t("admin.quotes.form.cancel")}</Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? t("admin.quotes.form.saving") : t("admin.quotes.form.saveDraft")}
          </Button>
          <Button variant="primary" disabled={save.isPending} onClick={() => submit(true)}>
            <Icon name="check" />
            {t("admin.quotes.form.send")}
          </Button>
          {fromRequest && (
            <Button variant="primary" disabled={save.isPending} onClick={() => submit(true, true)}>
              <Icon name="check" />
              {t("admin.quotes.form.approveAndDeliver")}
            </Button>
          )}
        </div>
      </form>
      <DeliverDialog quoteId={converting} stayHere onClose={() => leave(back)} />
    </>
  );
}
