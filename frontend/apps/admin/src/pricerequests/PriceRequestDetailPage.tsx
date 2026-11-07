import {
  ApiError,
  cancelPriceRequest,
  orderFromOffers,
  type PriceRequest,
  recordSupplierOffer,
  type SupplierOffer,
  useGetPriceRequest,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  EmptyState,
  Field,
  Input,
  MoneyInput,
  PageHeader,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { fieldErrors } from "../lib/errors";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";
import { asTyped, REQUEST_TONE, refreshPriceRequests } from "./shared";

type Errors = Record<string, string>;

const priceOf = (offer: SupplierOffer, lineId: number) =>
  offer.lines.find((row) => row.request_line === lineId)?.unit_cost ?? null;

const stillValid = (offer: SupplierOffer, today: string) => offer.valid_until === null || offer.valid_until >= today;

/** The cheapest valid offer for each line: what the comparison proposes before anyone chooses. */
function cheapest(request: PriceRequest, today: string): Record<number, number> {
  const picks: Record<number, number> = {};
  for (const line of request.lines) {
    let best: { supplier: number; cost: number } | null = null;
    for (const offer of request.offers) {
      const price = priceOf(offer, line.id);
      if (price === null || !stillValid(offer, today)) continue;
      if (best === null || Number(price) < best.cost) best = { supplier: offer.supplier.id, cost: Number(price) };
    }
    if (best) picks[line.id] = best.supplier;
  }
  return picks;
}

/** One supplier's answer, typed as it comes: reference, dates and a price per kg per product. */
function OfferCard({ request, offer, canWrite }: { request: PriceRequest; offer: SupplierOffer; canWrite: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const open = request.status === "open" && canWrite;
  const [reference, setReference] = useState(offer.reference);
  const [receivedOn, setReceivedOn] = useState(offer.received_on ?? "");
  const [validUntil, setValidUntil] = useState(offer.valid_until ?? "");
  const [prices, setPrices] = useState<Record<number, string>>(() =>
    Object.fromEntries(request.lines.map((line) => [line.id, asTyped(priceOf(offer, line.id) ?? "")])),
  );
  const [errors, setErrors] = useState<Errors>({});

  const save = useMutation({
    mutationFn: () =>
      recordSupplierOffer(request.id, {
        supplier: offer.supplier.id,
        reference: reference.trim(),
        received_on: receivedOn || null,
        valid_until: validUntil || null,
        prices: request.lines.map((line) => ({
          request_line: line.id,
          unit_cost: prices[line.id]?.trim() ? (parseDecimalInput(prices[line.id].trim(), 3) ?? prices[line.id]) : null,
        })),
      }),
    onSuccess: async () => {
      setErrors({});
      toast.success(t("admin.priceRequests.offer.saved", { supplier: offer.supplier.name }));
      await refreshPriceRequests(queryClient);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.priceRequests.offer.error") });
    },
  });

  const id = (name: string) => `${formId}-${name}`;
  return (
    <Card className="flex flex-col gap-3">
      <CardTitle className="mb-0 flex flex-wrap items-center gap-2">
        {t("admin.priceRequests.offer.title", { supplier: offer.supplier.name })}
        {offer.order && (
          <Link
            to={`/achats/bons/${offer.order.id}`}
            className="num text-[0.9rem] font-semibold text-sea hover:underline"
          >
            {t("admin.priceRequests.offer.order", { number: offer.order.number })}
          </Link>
        )}
      </CardTitle>
      <div className="grid grid-cols-3 gap-3 max-[800px]:grid-cols-1">
        <Field label={t("admin.priceRequests.offer.reference")} htmlFor={id("reference")} error={errors.reference}>
          <Input
            id={id("reference")}
            value={reference}
            disabled={!open}
            maxLength={50}
            onChange={(event) => setReference(event.target.value)}
          />
        </Field>
        <Field label={t("admin.priceRequests.offer.receivedOn")} htmlFor={id("received")} error={errors.received_on}>
          <Input
            id={id("received")}
            type="date"
            max={todayInTunis()}
            value={receivedOn}
            disabled={!open}
            onChange={(event) => setReceivedOn(event.target.value)}
          />
        </Field>
        <Field label={t("admin.priceRequests.offer.validUntil")} htmlFor={id("valid")} error={errors.valid_until}>
          <Input
            id={id("valid")}
            type="date"
            value={validUntil}
            disabled={!open}
            onChange={(event) => setValidUntil(event.target.value)}
          />
        </Field>
      </div>
      <Table>
        <thead>
          <tr>
            <Th>{t("admin.priceRequests.columns.product")}</Th>
            <Th numeric>{t("admin.priceRequests.offer.cost")}</Th>
          </tr>
        </thead>
        <tbody>
          {request.lines.map((line) => (
            <tr key={line.id}>
              <Td>
                <label htmlFor={id(`price-${line.id}`)} className="font-semibold">
                  {line.product.name}
                </label>
              </Td>
              <Td className="p-0">
                <MoneyInput
                  id={id(`price-${line.id}`)}
                  className="num w-full bg-transparent px-2.5 py-1.5 text-end"
                  value={prices[line.id] ?? ""}
                  disabled={!open}
                  placeholder={t("admin.priceRequests.offer.notOffered")}
                  onChange={(event) => setPrices((current) => ({ ...current, [line.id]: event.target.value }))}
                  aria-invalid={errors[`prices.${line.id}`] ? true : undefined}
                />
                {errors[`prices.${line.id}`] && (
                  <p role="alert" className="px-2.5 pb-1.5 text-[0.75rem] font-semibold text-bad">
                    {errors[`prices.${line.id}`]}
                  </p>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {(errors.detail ?? errors.supplier ?? errors.non_field_errors) && (
        <p role="alert" className="text-[0.85rem] font-semibold text-bad">
          {errors.detail ?? errors.supplier ?? errors.non_field_errors}
        </p>
      )}
      {open && (
        <div className="flex justify-end">
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            {t("admin.priceRequests.offer.save")}
          </Button>
        </div>
      )}
    </Card>
  );
}

/** One price request (D-289): the suppliers' offers side by side; the chosen ones become purchase orders. */
export function PriceRequestDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const queryClient = useQueryClient();
  const { requestId } = useParams();
  const id = Number(requestId);
  const validId = Number.isInteger(id) && id > 0;
  const query = useGetPriceRequest(id, { query: { enabled: validId, retry: false } });
  const suppliers = useListSuppliers({ status: "active" });
  const today = todayInTunis();
  const [picks, setPicks] = useState<Record<number, number> | null>(null);
  const [orderedOn, setOrderedOn] = useState(today);
  const [expectedOn, setExpectedOn] = useState("");
  const [adding, setAdding] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const onError = (failure: unknown) => {
    const fromServer = fieldErrors(failure);
    setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.priceRequests.detail.error") });
  };
  const order = useMutation({
    mutationFn: (choices: Record<number, number>) =>
      orderFromOffers(id, {
        ordered_on: orderedOn,
        expected_on: expectedOn || null,
        choices: Object.entries(choices).map(([line, supplier]) => ({ request_line: Number(line), supplier })),
      }),
    onSuccess: async () => {
      setErrors({});
      toast.success(t("admin.priceRequests.detail.ordered"));
      await refreshPriceRequests(queryClient);
    },
    onError,
  });
  const cancel = useMutation({
    mutationFn: () => cancelPriceRequest(id),
    onSuccess: async () => {
      toast.success(t("admin.priceRequests.detail.cancelled"));
      await refreshPriceRequests(queryClient);
    },
    onError,
  });
  const addSupplier = useMutation({
    mutationFn: (supplier: number) => recordSupplierOffer(id, { supplier, prices: [] }),
    onSuccess: async () => {
      setAdding("");
      await refreshPriceRequests(queryClient);
    },
    onError,
  });

  const back = (
    <Link to="/achats/demandes" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.priceRequests.back")}
    </Link>
  );
  if (validId && query.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!query.data) {
    const missing = !validId || (query.error instanceof ApiError && query.error.status === 404);
    return (
      <>
        {back}
        <EmptyState
          illustration="fish"
          title={missing ? t("admin.priceRequests.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }

  const request = query.data;
  const canWrite = canRecordReceipts(session);
  const open = request.status === "open" && canWrite;
  const chosen = picks ?? cheapest(request, today);
  const asked = new Set(request.offers.map((offer) => offer.supplier.id));
  const others = (suppliers.data ?? []).filter((supplier) => !asked.has(supplier.id));
  const answered = request.offers.filter((offer) => offer.lines.length > 0).length;

  return (
    <>
      {back}
      <PageHeader eyebrow={formatDate(request.requested_on)} title={request.number}>
        <Pill tone={REQUEST_TONE[request.status]}>{t(`admin.priceRequests.status.${request.status}`)}</Pill>
        {open && (
          <Button variant="danger" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
            {t("admin.priceRequests.detail.cancel")}
          </Button>
        )}
      </PageHeader>

      <Card className="flex flex-col gap-3">
        <CardTitle className="mb-0">{t("admin.priceRequests.detail.comparison")}</CardTitle>
        {answered < 3 && request.status === "open" && (
          <p className="text-[0.85rem] text-ink-2">{t("admin.priceRequests.detail.fewOffers", { count: answered })}</p>
        )}
        <div className="overflow-x-auto">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.priceRequests.columns.product")}</Th>
                <Th numeric>{t("admin.priceRequests.columns.quantity")}</Th>
                {request.offers.map((offer) => (
                  <Th key={offer.id} numeric>
                    {offer.supplier.name}
                    {offer.valid_until && (
                      <span
                        className={cn(
                          "block text-[0.75rem] font-normal",
                          stillValid(offer, today) ? "text-ink-2" : "text-bad",
                        )}
                      >
                        {t("admin.priceRequests.detail.validUntil", { date: formatDate(offer.valid_until) })}
                      </span>
                    )}
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {request.lines.map((line) => (
                <tr key={line.id}>
                  <Td className="font-semibold">{line.product.name}</Td>
                  <Td numeric>{formatQuantity(line.quantity)}</Td>
                  {request.offers.map((offer) => {
                    const price = priceOf(offer, line.id);
                    const retained = offer.lines.find((row) => row.request_line === line.id)?.retained ?? false;
                    const usable = price !== null && stillValid(offer, today);
                    return (
                      <Td
                        key={offer.id}
                        numeric
                        className={cn(
                          "whitespace-nowrap",
                          (retained || (open && chosen[line.id] === offer.supplier.id)) && "bg-good-soft",
                        )}
                      >
                        {open && usable ? (
                          <label className="flex items-center justify-end gap-2">
                            <input
                              type="radio"
                              name={`line-${line.id}`}
                              className="size-4 accent-coral"
                              checked={chosen[line.id] === offer.supplier.id}
                              onChange={() => setPicks({ ...chosen, [line.id]: offer.supplier.id })}
                              aria-label={t("admin.priceRequests.detail.choose", {
                                supplier: offer.supplier.name,
                                product: line.product.name,
                              })}
                            />
                            <span className="num">{formatMoney(price)}</span>
                          </label>
                        ) : price !== null ? (
                          <span className="num">{formatMoney(price)}</span>
                        ) : (
                          "—"
                        )}
                        {errors[`choices.${line.id}`] && chosen[line.id] === offer.supplier.id && (
                          <p role="alert" className="text-[0.75rem] font-semibold text-bad">
                            {errors[`choices.${line.id}`]}
                          </p>
                        )}
                      </Td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
        {open && (
          <div className="flex flex-wrap items-end gap-3">
            <Field label={t("admin.priceRequests.detail.orderedOn")} htmlFor="price-request-ordered-on">
              <Input
                id="price-request-ordered-on"
                type="date"
                max={today}
                value={orderedOn}
                onChange={(event) => setOrderedOn(event.target.value)}
              />
            </Field>
            <Field label={t("admin.priceRequests.detail.expectedOn")} htmlFor="price-request-expected-on">
              <Input
                id="price-request-expected-on"
                type="date"
                min={orderedOn}
                value={expectedOn}
                onChange={(event) => setExpectedOn(event.target.value)}
              />
            </Field>
            <Button
              variant="primary"
              className="ms-auto"
              disabled={order.isPending || Object.keys(chosen).length === 0}
              onClick={() => order.mutate(chosen)}
            >
              {t("admin.priceRequests.detail.order", { count: new Set(Object.values(chosen)).size })}
            </Button>
          </div>
        )}
        {(errors.detail ?? errors.choices ?? errors.non_field_errors) && (
          <p role="alert" className="text-[0.85rem] font-semibold text-bad">
            {errors.detail ?? errors.choices ?? errors.non_field_errors}
          </p>
        )}
      </Card>

      {request.offers.map((offer) => (
        <OfferCard key={`${offer.id}-${offer.lines.length}`} request={request} offer={offer} canWrite={canWrite} />
      ))}

      {open && others.length > 0 && (
        <Card className="flex flex-wrap items-end gap-3">
          <Field label={t("admin.priceRequests.detail.addSupplier")} htmlFor="price-request-add" className="min-w-64">
            <Select value={adding} onValueChange={setAdding}>
              <SelectTrigger id="price-request-add">
                <SelectValue placeholder={t("admin.priceRequests.form.choose")} />
              </SelectTrigger>
              <SelectContent>
                {others.map((supplier) => (
                  <SelectItem key={supplier.id} value={String(supplier.id)}>
                    {supplier.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Button disabled={!adding || addSupplier.isPending} onClick={() => addSupplier.mutate(Number(adding))}>
            {t("admin.priceRequests.detail.add")}
          </Button>
        </Card>
      )}

      {request.notes && (
        <Card>
          <p className="text-[0.9rem] whitespace-pre-line">{request.notes}</p>
        </Card>
      )}
    </>
  );
}
