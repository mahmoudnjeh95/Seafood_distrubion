import {
  createSale,
  type LocationBatch,
  type SaleDetail,
  type SalePaymentMethodEnum,
  type SaleWrite,
  useListCustomers,
  useListLocationBatches,
  useListLocations,
  useListPriceLists,
  useListProducts,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
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
import { useId, useMemo, useState } from "react";
import { Link, Navigate, useOutletContext } from "react-router";

import { fromThousandths, sum, toThousandths } from "../lib/decimal";
import { useLeave } from "../lib/embedded";
import { fieldErrors } from "../lib/errors";
import { amountsOf, filled, isShort, isZero, type Line, type LotPick, newLine, shownPrice } from "../lib/lines";
import { LinesGrid } from "../lib/LinesGrid";
import { choosePlace, needsOf, placesOf, totalsOf, usePlacesStock } from "../lib/placeStock";
import { usePartnerProducts } from "../partnerships/usePartnerProducts";
import { type ReactNode } from "react";
import { canSell, PAYMENT_METHODS, refreshAfterSale } from "./shared";

// Radix Select has no empty choice: this value stands for the walk-in customer ("Client de passage").
const WALK_IN = "walk-in";

const isPositive = (value: string | null): value is string =>
  value !== null && !value.startsWith("-") && !/^0+(\.0+)?$/.test(value);
// The messages the grid shows in its own cells; every other one goes in the alert.
const inGrid = (key: string) => /^lines\.\d+\.(product|quantity|unit_price|picks)$/.test(key);

/**
 * The lots a row takes its kilos from first. Lots of the row's product at this room, oldest first: a hint of
 * where they sit and who supplied them, never printed on a devis or a BL (D-121). Several lots may be picked,
 * each with the kilos to take from it; the rest comes from the oldest lot (FIFO, the default, D-208).
 */
function LotCell({ room, line, onChange }: { room: string; line: Line; onChange: (picks: LotPick[]) => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const batches = useListLocationBatches(Number(room), Number(line.product), {
    query: { enabled: room !== "" && line.product !== "" },
  });
  if (!line.product) return null;
  const lots = batches.data ?? [];
  const lotOf = (batch: string) => lots.find((option) => String(option.batch_id) === batch);
  return (
    <>
      <button
        type="button"
        aria-label={t("admin.sales.counterSale.lot")}
        onClick={() => setOpen(true)}
        className="w-full truncate px-2.5 py-2 text-start"
      >
        {line.picks.length === 0
          ? t("admin.sales.counterSale.lotAuto")
          : line.picks
              .map((pick) =>
                t("admin.sales.counterSale.lotPicked", {
                  batch: lotOf(pick.batch)?.batch_number ?? "",
                  quantity: pick.quantity,
                }),
              )
              .join(" + ")}
      </button>
      {line.picks.map((pick) => {
        const lot = lotOf(pick.batch);
        return lot && isShort(pick.quantity, lot.quantity) ? (
          <p key={pick.batch} className="px-2.5 pb-1.5 text-[0.78rem] font-semibold text-bad">
            {t("admin.sales.counterSale.lotShort", { quantity: formatQuantity(lot.quantity) })}
          </p>
        ) : null;
      })}
      <Dialog open={open} onOpenChange={setOpen}>
        <LotsDialog
          lots={lots}
          quantity={line.quantity}
          picks={line.picks}
          onSave={(picks) => {
            onChange(picks);
            setOpen(false);
          }}
          onCancel={() => setOpen(false)}
        />
      </Dialog>
    </>
  );
}

/** The lots picked for one row, each with its kilos, and what the picks leave over for the oldest lot. */
function LotsDialog({
  lots,
  quantity,
  picks,
  onSave,
  onCancel,
}: {
  lots: LocationBatch[];
  quantity: string;
  picks: LotPick[];
  onSave: (picks: LotPick[]) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<LotPick[]>(picks.length > 0 ? picks : [{ batch: "", quantity: "" }]);
  const [problem, setProblem] = useState("");
  const weight = parseDecimalInput(quantity.trim(), 3);
  const kgOf = (row: LotPick) => parseDecimalInput(row.quantity.trim(), 3);
  const taken = rows.reduce((total, row) => {
    const kg = kgOf(row);
    return kg === null ? total : total + toThousandths(kg);
  }, 0n);

  function update(index: number, fields: Partial<LotPick>) {
    setRows(rows.map((row, at) => (at === index ? { ...row, ...fields } : row)));
  }

  function save() {
    const chosen = rows.filter((row) => row.batch !== "");
    const weights = chosen.map((row) => kgOf(row));
    if (weights.some((kg) => kg === null || isZero(kg) || kg.startsWith("-"))) {
      setProblem(t("admin.sales.counterSale.lotNoKg"));
      return;
    }
    if (weight !== null && taken > toThousandths(weight)) {
      setProblem(t("admin.sales.counterSale.lotTooMuch", { quantity: formatQuantity(weight) }));
      return;
    }
    onSave(chosen.map((row, index) => ({ batch: row.batch, quantity: weights[index] ?? "" })));
  }

  return (
    <DialogContent>
      <DialogTitle>{t("admin.sales.counterSale.lotsTitle")}</DialogTitle>
      <DialogDescription>{t("admin.sales.counterSale.lotsHint")}</DialogDescription>
      <div className="flex flex-col gap-3">
        {rows.map((row, index) => {
          const others = rows.filter((_, at) => at !== index).map((other) => other.batch);
          const lot = lots.find((option) => String(option.batch_id) === row.batch);
          return (
            <div key={index} className="flex flex-col gap-1">
              <div className="grid grid-cols-[1fr_7rem_auto] items-center gap-2">
                <Select value={row.batch} onValueChange={(batch) => update(index, { batch })}>
                  <SelectTrigger aria-label={t("admin.sales.counterSale.lot")}>
                    <SelectValue placeholder={t("admin.sales.form.choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {lots
                      .filter((option) => !others.includes(String(option.batch_id)))
                      .map((option) => (
                        <SelectItem key={option.batch_id} value={String(option.batch_id)}>
                          {t("admin.sales.counterSale.lotChoice", {
                            batch: option.batch_number,
                            supplier: option.supplier_name,
                            quantity: formatQuantity(option.quantity),
                          })}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <Input
                  aria-label={t("admin.sales.counterSale.lotKg")}
                  inputMode="decimal"
                  value={row.quantity}
                  onChange={(event) => update(index, { quantity: event.target.value })}
                />
                <Button
                  aria-label={t("admin.sales.counterSale.lotRemove")}
                  onClick={() => setRows(rows.filter((_, at) => at !== index))}
                >
                  <Icon name="trash" />
                </Button>
              </div>
              {lot && isShort(row.quantity, lot.quantity) && (
                <p className="text-[0.78rem] font-semibold text-bad">
                  {t("admin.sales.counterSale.lotShort", { quantity: formatQuantity(lot.quantity) })}
                </p>
              )}
            </div>
          );
        })}
      </div>
      <Button onClick={() => setRows([...rows, { batch: "", quantity: "" }])}>
        {t("admin.sales.counterSale.lotAdd")}
      </Button>
      {weight !== null && (
        <p className={cn("text-[0.9rem] text-ink-2", taken > toThousandths(weight) && "font-semibold text-bad")}>
          {taken > toThousandths(weight)
            ? t("admin.sales.counterSale.lotTooMuch", { quantity: formatQuantity(weight) })
            : t("admin.sales.counterSale.lotRest", {
                quantity: formatQuantity(fromThousandths(toThousandths(weight) - taken)),
              })}
        </p>
      )}
      {problem && (
        <p role="alert" className="text-bad">
          {problem}
        </p>
      )}
      <DialogFooter className="items-center">
        <Button onClick={onCancel}>{t("admin.sales.counterSale.lotCancel")}</Button>
        <Button variant="primary" onClick={save}>
          {t("admin.sales.counterSale.lotSave")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** "Vente comptoir": weigh, type the rows of the basket, take the money. The sale is confirmed at once (D-052). */
export function CounterSalePage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const queryClient = useQueryClient();
  const { embedded, leave } = useLeave();
  const formId = useId();
  const id = (name: string) => `${formId}-${name}`;

  const locations = useListLocations({ status: "active", kind: "cold_room" });
  const customers = useListCustomers({ status: "active" });
  const products = useListProducts({ status: "active" });
  const rooms = (locations.data ?? []).filter((location) => location.counter_sales);

  const [customer, setCustomer] = useState(WALK_IN);
  const [method, setMethod] = useState<SalePaymentMethodEnum>("cash");
  const [basket, setBasket] = useState<Line[]>(() => [newLine()]);
  // Counts the baskets started: a new one is a new grid, with the cursor back in its first cell.
  const [baskets, setBaskets] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [lastSale, setLastSale] = useState<SaleDetail | null>(null);

  // The counter sale leaves from one open cold room: the one that holds the whole basket (D-144).
  const byRoom = usePlacesStock(rooms.map((option) => option.id));
  const totals = useMemo(() => totalsOf(byRoom), [byRoom]);
  const roomNames = useMemo(() => new Map(rooms.map((option) => [option.id, option.name])), [rooms]);
  const placesOfProduct = useMemo(() => placesOf(byRoom, roomNames), [byRoom, roomNames]);
  const partnerProducts = usePartnerProducts(session);
  const room = choosePlace(needsOf(filled(basket)), byRoom);
  const roomName = rooms.find((option) => option.id === room)?.name;
  const origin = roomName ? new Map(needsOf(filled(basket)).map((need) => [need.product, roomName])) : undefined;
  const dailyPrice = useMemo(() => {
    const byProduct = new Map<string, string | null>();
    for (const product of products.data ?? []) byProduct.set(String(product.id), product.current_price);
    return byProduct;
  }, [products.data]);
  const realCustomer = customer !== WALK_IN;
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
  // The customer's own price list wins over the daily price, as on the server (D-049).
  const proposedPrice = (product: string): string | null => listPrice.get(product) ?? dailyPrice.get(product) ?? null;
  const priceOf = (line: Line): string => shownPrice(line, proposedPrice(line.product));
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

  function startBasket() {
    setBasket([newLine()]);
    setBaskets((count) => count + 1);
    setErrors({});
  }

  const collect = useMutation({
    mutationFn: (payload: SaleWrite) => createSale(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.sales.counterSale.done", { number: saved.number }));
      setLastSale(saved);
      startBasket();
      setCustomer(WALK_IN);
      await refreshAfterSale(queryClient);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.sales.counterSale.error") });
    },
  });

  if (!canSell(session)) return <Navigate to="/ventes" replace />;

  // The grid's blank rows are places to type in, not lines of the sale.
  const rows = filled(basket);
  const total = sum(basket.flatMap((line) => amountsOf(line, priceOf(line))?.amount ?? []));

  function pay() {
    const found: Record<string, string> = {};
    const lines: SaleWrite["lines"] = [];
    rows.forEach((line, index) => {
      const kg = parseDecimalInput(line.quantity.trim(), 3);
      const perKg = parseDecimalInput(priceOf(line).trim(), 3);
      if (!line.product) found[`lines.${index}.product`] = t("admin.sales.form.required");
      if (!isPositive(kg)) found[`lines.${index}.quantity`] = t("admin.sales.form.weight");
      if (!isPositive(perKg)) found[`lines.${index}.unit_price`] = t("admin.sales.form.money");
      lines.push({
        product: Number(line.product),
        quantity: kg ?? "",
        unit_price: perKg,
        picks: line.picks
          .filter((pick) => pick.batch !== "")
          .map((pick) => ({ batch: Number(pick.batch), quantity: parseDecimalInput(pick.quantity.trim(), 3) ?? "" })),
      });
    });
    if (room === null && rows.length > 0) {
      found.basket = t("admin.sales.form.noSinglePlace", {
        products: rows
          .map((line) => products.data?.find((option) => String(option.id) === line.product)?.name ?? "")
          .join(", "),
      });
    }
    setErrors(found);
    if (rows.length === 0 || room === null || Object.keys(found).length > 0) return;
    collect.mutate({
      customer: realCustomer ? Number(customer) : null,
      location: room,
      lines,
      paid_in_full: true,
      payment_method: method,
      confirm_now: true,
    });
  }

  const choose = (
    name: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    options: { value: string; label: string; detail?: ReactNode }[],
  ) => (
    <Field label={label} htmlFor={id(name)} error={errors[name]}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id(name)} aria-invalid={errors[name] ? true : undefined}>
          <SelectValue placeholder={t("admin.sales.form.choose")} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.detail ?? option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
  const alerts = Object.entries(errors)
    .filter(([key]) => !inGrid(key))
    .map(([, message]) => message);

  return (
    <>
      {!embedded && (
        <Link to="/ventes" className="text-[0.85rem] font-semibold text-sea hover:underline">
          {t("admin.sales.back")}
        </Link>
      )}
      <PageHeader eyebrow={t("admin.sales.title")} title={t("admin.sales.counterSale.title")} />
      <p className="text-ink-2">{t("admin.sales.counterSale.intro")}</p>

      {locations.data && rooms.length === 0 ? (
        <p role="alert" className="text-bad">
          {t("admin.sales.counterSale.noRoom")}
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <Card className="grid grid-cols-2 gap-4 max-[600px]:grid-cols-1">
            {choose("customer", t("admin.sales.counterSale.customer"), customer, setCustomer, [
              { value: WALK_IN, label: t("admin.sales.form.walkIn") },
              ...(customers.data ?? [])
                .filter((option) => !option.is_walk_in)
                .map((option) => ({ value: String(option.id), label: `${option.name} · ${option.reference}` })),
            ])}
          </Card>
          <Card className="flex flex-col gap-3" aria-labelledby={id("basket")} role="region">
            <CardTitle id={id("basket")} className="mb-0">
              {t("admin.sales.counterSale.basket")}
            </CardTitle>
            <LinesGrid
              key={baskets}
              autoFocus
              label={t("admin.sales.counterSale.basket")}
              lines={basket}
              onChange={setBasket}
              products={products.data ?? []}
              proposedPrice={proposedPrice}
              stock={rooms.length > 0 ? totals : undefined}
              origin={origin}
              places={placesOfProduct}
              partners={partnerProducts}
              errors={errors}
              extra={{
                header: t("admin.sales.counterSale.lot"),
                field: "picks",
                cell: (line, change) => (
                  <LotCell
                    room={room === null ? "" : String(room)}
                    line={line}
                    onChange={(picks) => change({ picks })}
                  />
                ),
              }}
              hint={priceHint}
            />
          </Card>

          <Card className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3">
            <div role="group" aria-label={t("admin.sales.counterSale.method")} className="flex flex-wrap gap-2">
              {PAYMENT_METHODS.map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={method === value}
                  onClick={() => setMethod(value)}
                  className={cn(
                    "rounded-control border border-line px-3 py-2 text-[0.9rem] font-semibold text-ink-2",
                    method === value && "border-sea bg-sea-soft text-sea",
                  )}
                >
                  {t(`admin.sales.methods.${value}`)}
                </button>
              ))}
            </div>
            <div className="ms-auto flex flex-wrap items-center gap-x-6 gap-y-3">
              <p className="flex items-baseline gap-3">
                <span className="font-semibold">{t("admin.sales.counterSale.total")}</span>
                <span className="num text-[1.8rem] font-bold" aria-live="polite">
                  {formatMoney(total)}
                </span>
              </p>
              <Button variant="primary" disabled={rows.length === 0 || collect.isPending} onClick={pay}>
                <Icon name="cash" />
                {collect.isPending
                  ? t("admin.sales.counterSale.collecting")
                  : t("admin.sales.counterSale.collect", { total: formatMoney(total) })}
              </Button>
            </div>
            {alerts.length > 0 && (
              <p
                role="alert"
                className="w-full rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad"
              >
                {alerts.join(" ")}
              </p>
            )}
            {embedded && <Button onClick={() => leave("/ventes")}>{t("admin.docHub.back")}</Button>}
            {lastSale && (
              <p role="status" className="w-full text-[0.9rem] text-ink-2">
                {t("admin.sales.counterSale.done", { number: lastSale.number })}{" "}
                {!embedded && (
                  <Link to={`/ventes/${lastSale.id}`} className="font-semibold text-sea hover:underline">
                    {t("admin.sales.counterSale.open")}
                  </Link>
                )}
              </p>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
