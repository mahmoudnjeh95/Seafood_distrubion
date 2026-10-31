import {
  ApiError,
  createTransfer,
  type StockLocation,
  type TransferDetail,
  type TransferKindEnum,
  type TransferWrite,
  updateTransfer,
  useGetTransfer,
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
import { type FormEvent, useId, useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useOutletContext, useParams } from "react-router";

import { BoxCountsFields } from "../boxes/BoxCountsFields";
import { type BoxCountInputs, NO_BOX_INPUTS, boxCountsFromInputs, boxInputsFromCounts } from "../boxes/shared";
import { subtract, sum, toThousandths } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { amountsOf, asTyped, filled, isZero, type Line, newLine, shownPrice, withSpare } from "../lib/lines";
import { lotColumn } from "../lib/lotColumn";
import { LinesGrid } from "../lib/LinesGrid";
import { placesOf, totalsOf, usePlacesStock } from "../lib/placeStock";
import { todayInTunis } from "../receipts/shared";
import { ClientPart } from "./ClientPart";
import { newPart, type Part } from "./formLines";
import { canRecordTransfers, refreshAfterTransfer } from "./shared";

type Errors = Record<string, string>;

/** "Départ" for a load from the cold rooms together: each product leaves from the rooms that hold it (D-174). */
const COLD_ROOMS = "cold_rooms";
/** The key of the part kept on the truck, without a client, among the parts' keys. */
const KEPT = 0;

/** Into a truck is a load, out of one a return: the server decides the same way. */
function kindOf(from: StockLocation | undefined, to: StockLocation | undefined): TransferKindEnum | null {
  if (!from || !to) return null;
  const fromTruck = from.kind === "truck";
  const toTruck = to.kind === "truck";
  if (toTruck && !fromTruck) return "load";
  if (fromTruck && !toTruck) return "return";
  return "internal";
}

/** A saved line as the grid shows it: its price was chosen, so it is not replaced by a proposed one. */
function typedLine(line: TransferDetail["lines"][number]): Line {
  return newLine({
    product: String(line.product.id),
    quantity: asTyped(line.quantity),
    unit_price: line.unit_price ? asTyped(line.unit_price) : "",
    priceTouched: line.unit_price !== null,
    picks: line.picks.map((pick) => ({ batch: String(pick.batch), quantity: asTyped(pick.quantity) })),
  });
}

/** Kilos per product typed in some rows. */
function kilosOf(rows: readonly Line[]): Map<string, string> {
  const byProduct = new Map<string, string>();
  for (const line of filled(rows)) {
    const kg = parseDecimalInput(line.quantity.trim(), 3);
    if (!line.product || kg === null || kg.startsWith("-")) continue;
    byProduct.set(line.product, sum([byProduct.get(line.product) ?? "0", kg]));
  }
  return byProduct;
}

/** "Nouveau transfert": a new draft, or one validated at once. */
export function TransferFormPage() {
  return <TransferForm />;
}

/** "Modifier TR-0003": a draft changed, or validated. */
export function TransferEditPage() {
  const { t } = useTranslation();
  const { transferId } = useParams();
  const id = Number(transferId);
  const validId = Number.isInteger(id) && id > 0;
  const transfer = useGetTransfer(id, { query: { enabled: validId, retry: false } });
  if (validId && transfer.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!transfer.data) {
    const missing = !validId || (transfer.error instanceof ApiError && transfer.error.status === 404);
    return (
      <EmptyState
        illustration="truck"
        title={missing ? t("admin.transfers.notFound") : t("common.serverUnreachable")}
      />
    );
  }
  if (transfer.data.status !== "draft") return <Navigate to={`/stock/transferts/${id}`} replace />;
  return <TransferForm key={transfer.data.id} draft={transfer.data} />;
}

/**
 * A transfer typed like a spreadsheet (D-174): from the cold rooms (no room to pick, the products say where they
 * are) or a truck, into a truck; a load is split by client, each with their grid, address, boxes and BL.
 */
function TransferForm({ draft }: { draft?: TransferDetail }) {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const formId = useId();

  // Archived places too: a draft may name one archived since (it shows, and the server refuses it on save).
  const locations = useListLocations({ status: "all" });
  const products = useListProducts({ status: "all" });
  // The clients of a load (D-160), archived ones too so a saved part still shows its client.
  const customers = useListCustomers({ status: "all" });
  // Every client's own prices: each client of a load is proposed theirs, as on a sale (D-049).
  const priceLists = useListPriceLists({ status: "active" });

  const [from, setFrom] = useState(() => {
    if (!draft) return COLD_ROOMS;
    return draft.from_cold_rooms || draft.from_location.kind === "cold_room"
      ? COLD_ROOMS
      : String(draft.from_location.id);
  });
  const [to, setTo] = useState(draft ? String(draft.to_location.id) : "");
  const [day, setDay] = useState(draft?.transferred_on ?? todayInTunis());
  const [notes, setNotes] = useState(draft?.notes ?? "");
  // The part kept on the truck, without a client (sold on the road); every product of any other transfer.
  const [lines, setLines] = useState<Line[]>(() =>
    withSpare((draft?.lines ?? []).filter((line) => line.customer === null).map(typedLine)),
  );
  // The boxes of a load (D-122). A draft's saved boxes come back here, since saving replaces them.
  const [boxes, setBoxes] = useState<BoxCountInputs>(() => (draft ? boxInputsFromCounts(draft.boxes) : NO_BOX_INPUTS));
  // The clients of a load, each with their own products, boxes and delivery address (D-160).
  const [parts, setParts] = useState<Part[]>(() =>
    (draft?.deliveries ?? []).map((delivery) =>
      newPart({
        customer: String(delivery.customer.id),
        address: delivery.delivery_address,
        lines: withSpare(
          (draft?.lines ?? []).filter((line) => line.customer?.id === delivery.customer.id).map(typedLine),
        ),
        boxes: boxInputsFromCounts(delivery.boxes),
      }),
    ),
  );
  const [errors, setErrors] = useState<Errors>({});

  const places = useMemo(() => locations.data ?? [], [locations.data]);
  const coldRooms = useMemo(
    () => places.filter((place) => place.kind === "cold_room" && place.is_active).sort((a, b) => a.id - b.id),
    [places],
  );
  // From the cold rooms, the boxes leave from the first one, as on the server.
  const fromPlace = from === COLD_ROOMS ? coldRooms[0] : places.find((place) => String(place.id) === from);
  // Lots are picked where the kg leave from, unless several cold rooms give them (D-215).
  const lotRoom = from === COLD_ROOMS || !fromPlace ? undefined : String(fromPlace.id);
  const toPlace = places.find((place) => String(place.id) === to);
  const kind = kindOf(fromPlace, toPlace);
  const isLoad = kind === "load";

  // The stock of where the goods leave from: every cold room together, or the one truck.
  const sourceIds = from === COLD_ROOMS ? coldRooms.map((place) => place.id) : from ? [Number(from)] : [];
  const byPlace = usePlacesStock(sourceIds);
  const totals = useMemo(() => totalsOf(byPlace), [byPlace]);
  const placeNames = useMemo(() => new Map(places.map((place) => [place.id, place.name])), [places]);
  const placesOfProduct = useMemo(() => placesOf(byPlace, placeNames), [byPlace, placeNames]);

  const dailyPrice = useMemo(() => {
    const byProduct = new Map<string, string | null>();
    for (const product of products.data ?? []) byProduct.set(String(product.id), product.current_price);
    return byProduct;
  }, [products.data]);
  const listOf = (customer: string) => (priceLists.data ?? []).find((list) => String(list.customer) === customer);
  const proposedFor =
    (customer: string) =>
    (product: string): string | null =>
      listOf(customer)?.items.find((item) => String(item.product) === product)?.price ??
      dailyPrice.get(product) ??
      null;
  const hintFor = (customer: string) => (line: Line) => {
    const list = listOf(customer);
    const fromList = list?.items.find((item) => String(item.product) === line.product)?.price;
    if (list && fromList) return t("admin.sales.form.listPrice", { list: list.name, price: formatMoney(fromList) });
    const inForce = dailyPrice.get(line.product);
    return inForce
      ? t("admin.transfers.form.priceInForce", { price: formatMoney(inForce) })
      : t("admin.transfers.form.noPrice");
  };

  // What each part takes, so a grid shows the kilos left once the other parts are served.
  const clientParts = isLoad ? parts : [];
  const taken = new Map<number, Map<string, string>>([
    [KEPT, kilosOf(lines)],
    ...clientParts.map((part): [number, Map<string, string>] => [part.key, kilosOf(part.lines)]),
  ]);
  const stockFor = (key: number): Map<string, string> | undefined => {
    if (sourceIds.length === 0) return undefined;
    const left = new Map<string, string>();
    for (const product of new Set([...totals.keys(), ...[...taken.values()].flatMap((kg) => [...kg.keys()])])) {
      const others = [...taken.entries()].filter(([other]) => other !== key).map(([, kg]) => kg.get(product) ?? "0");
      left.set(product, subtract(totals.get(product) ?? "0", sum(others)));
    }
    return left;
  };

  const save = useMutation({
    mutationFn: (payload: TransferWrite) => (draft ? updateTransfer(draft.id, payload) : createTransfer(payload)),
    onSuccess: async (saved) => {
      toast.success(
        t(saved.status === "validated" ? "admin.transfers.form.validated" : "admin.transfers.form.created", {
          number: saved.number,
        }),
      );
      await refreshAfterTransfer(queryClient);
      void navigate(`/stock/transferts/${saved.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.transfers.form.error") });
    },
  });

  if (!canRecordTransfers(session)) return <Navigate to="/stock/transferts" replace />;

  function submit(validateNow: boolean) {
    const found: Errors = {};
    if (!from || (from === COLD_ROOMS && !fromPlace)) found.from_location = t("admin.transfers.form.required");
    if (!to) found.to_location = t("admin.transfers.form.required");
    if (from && from === to) found.to_location = t("admin.transfers.form.samePlace");
    if (!day) found.transferred_on = t("admin.transfers.form.required");
    if (filled(lines).length === 0 && clientParts.length === 0) found.lines = t("admin.transfers.form.noLines");
    // The rows sent, in the grid's order: their messages come back on `<prefix>lines.<n>.<field>`.
    const rowsOf = (rows: Line[], proposed: (product: string) => string | null, prefix: string) =>
      filled(rows).map((line, index) => {
        const key = (field: string) => `${prefix}lines.${index}.${field}`;
        if (!line.product) found[key("product")] = t("admin.transfers.form.required");
        const quantity = parseDecimalInput(line.quantity.trim(), 3);
        if (quantity === null || quantity.startsWith("-") || isZero(quantity)) {
          found[key("quantity")] = t("admin.transfers.form.weight");
        }
        let price: string | null = null;
        if (isLoad) {
          const typed = shownPrice(line, line.product ? proposed(line.product) : null).trim();
          if (typed !== "") {
            price = parseDecimalInput(typed, 3);
            if (price === null || price.startsWith("-")) found[key("unit_price")] = t("admin.transfers.form.money");
          }
        }
        const picks = line.picks
          .filter((pick) => pick.batch !== "")
          .map((pick) => ({
            batch: Number(pick.batch),
            quantity: parseDecimalInput(pick.quantity.trim(), 3) ?? "",
          }));
        return { product: Number(line.product), quantity: quantity ?? "", unit_price: price, picks };
      });
    const payloadLines = rowsOf(lines, (product) => dailyPrice.get(product) ?? null, "");
    const deliveries: NonNullable<TransferWrite["deliveries"]> = clientParts.map((part, index) => {
      const prefix = `deliveries.${index}.`;
      if (!part.customer) found[`${prefix}customer`] = t("admin.transfers.form.required");
      if (filled(part.lines).length === 0) found[`${prefix}lines`] = t("admin.transfers.form.noLines");
      const partBoxes = boxCountsFromInputs(part.boxes);
      for (const boxType of partBoxes.invalid) found[`${prefix}boxes.${boxType}`] = t("admin.boxes.form.invalid");
      return {
        customer: Number(part.customer),
        delivery_address: part.address.trim(),
        lines: rowsOf(part.lines, proposedFor(part.customer), prefix),
        boxes: partBoxes.counts,
      };
    });
    // Boxes travel with a load only here: the server refuses any other kind that carries them.
    const boxCounts = boxCountsFromInputs(boxes);
    if (isLoad) {
      for (const boxType of boxCounts.invalid) found[`boxes.${boxType}`] = t("admin.boxes.form.invalid");
    }
    setErrors(found);
    if (Object.keys(found).length > 0 || !fromPlace) return;
    save.mutate({
      from_location: fromPlace.id,
      from_cold_rooms: from === COLD_ROOMS,
      to_location: Number(to),
      transferred_on: day,
      notes: notes.trim(),
      lines: payloadLines,
      validate_now: validateNow,
      boxes: isLoad ? boxCounts.counts : {},
      deliveries,
    });
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit(false);
  }

  // Emptying a truck in the evening: everything it holds comes back.
  const truckStock = fromPlace?.kind === "truck" ? byPlace.get(fromPlace.id) : undefined;
  function takeAll() {
    const rows = [...(truckStock ?? new Map<string, string>())].filter(([, kg]) => toThousandths(kg) > 0n);
    setLines(withSpare(rows.map(([product, kg]) => newLine({ product, quantity: asTyped(kg) }))));
  }

  const keptTotal = sum(
    filled(lines).flatMap((line) => {
      const amounts = amountsOf(line, shownPrice(line, line.product ? (dailyPrice.get(line.product) ?? null) : null));
      return amounts ? [amounts.amount] : [];
    }),
  );

  const id = (name: string) => `${formId}-${name}`;
  const select = (
    name: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    options: { value: string; label: string }[],
  ) => (
    <Field label={label} htmlFor={id(name)} error={errors[name]}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id(name)} aria-invalid={errors[name] ? true : undefined}>
          <SelectValue placeholder={t("admin.transfers.form.choose")} />
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
  // Goods leave the cold rooms or a truck and go into a truck, or come back from a truck into a cold room (the
  // evening return); a truck never goes into itself (a truck picked on one side is missing from the other).
  const placeOption = (place: StockLocation) => ({
    value: String(place.id),
    label: place.is_active ? place.name : t("admin.transfers.form.archivedPlace", { name: place.name }),
  });
  const usable = (place: StockLocation, chosen: string) => place.is_active || String(place.id) === chosen;
  const fromOptions = [
    { value: COLD_ROOMS, label: t("admin.transfers.form.coldRooms") },
    ...places
      .filter((place) => place.kind === "truck" && usable(place, from) && String(place.id) !== to)
      .map(placeOption),
  ];
  const toOptions = places
    .filter(
      (place) =>
        (place.kind === "truck" || (fromPlace?.kind === "truck" && place.kind === "cold_room")) && usable(place, to),
    )
    .filter((place) => String(place.id) !== from)
    .map(placeOption);
  const back = draft ? `/stock/transferts/${draft.id}` : "/stock/transferts";
  const productList = products.data ?? [];

  return (
    <>
      <Link to={back} className="text-[0.85rem] font-semibold text-sea hover:underline">
        {t("admin.transfers.back")}
      </Link>
      <PageHeader
        eyebrow={t("admin.transfers.title")}
        title={
          draft ? t("admin.transfers.form.titleEdit", { number: draft.number }) : t("admin.transfers.form.titleNew")
        }
      />

      <form id={formId} onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-3 gap-4 max-[800px]:grid-cols-1">
          {select("from_location", t("admin.transfers.form.from"), from, setFrom, fromOptions)}
          {select("to_location", t("admin.transfers.form.to"), to, setTo, toOptions)}
          <Field label={t("admin.transfers.form.date")} htmlFor={id("transferred_on")} error={errors.transferred_on}>
            <Input
              id={id("transferred_on")}
              type="date"
              value={day}
              onChange={(event) => setDay(event.target.value)}
              aria-invalid={errors.transferred_on ? true : undefined}
            />
          </Field>
          {kind && (
            <p className="col-span-full flex items-center gap-2 text-[0.88rem] text-ink-2" aria-live="polite">
              <Icon name={kind === "load" ? "truck" : kind === "return" ? "return" : "snow"} />
              {t(`admin.transfers.form.kindHint.${kind}`)}
            </p>
          )}
        </Card>

        {isLoad && (
          <section className="flex flex-col gap-4" aria-label={t("admin.transfers.form.clients")}>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-[1rem] font-bold">{t("admin.transfers.form.clients")}</h2>
              <p className="text-[0.85rem] text-ink-2">{t("admin.transfers.form.clientsHint")}</p>
            </div>
            {parts.map((part, index) => (
              <ClientPart
                key={part.key}
                index={index}
                part={part}
                customers={customers.data ?? []}
                products={productList}
                proposedPrice={proposedFor(part.customer)}
                priceHint={hintFor(part.customer)}
                stock={stockFor(part.key)}
                places={placesOfProduct}
                errors={errors}
                lotRoom={lotRoom}
                onChange={(next) =>
                  setParts((current) => current.map((other) => (other.key === part.key ? next : other)))
                }
                onRemove={() => setParts((current) => current.filter((other) => other.key !== part.key))}
              />
            ))}
            {errors.deliveries && <p className="text-[0.78rem] font-semibold text-bad">{errors.deliveries}</p>}
            <div>
              <Button onClick={() => setParts((current) => [...current, newPart()])}>
                <Icon name="plus" />
                {t("admin.transfers.form.addClient")}
              </Button>
            </div>
          </section>
        )}

        <Card className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle className="mb-0">
              {isLoad && parts.length > 0 ? t("admin.transfers.form.keptLines") : t("admin.transfers.form.lines")}
            </CardTitle>
            {(truckStock?.size ?? 0) > 0 && (
              <Button className="ms-auto" title={t("admin.transfers.form.takeAllHint")} onClick={takeAll}>
                <Icon name="return" />
                {t("admin.transfers.form.takeAll")}
              </Button>
            )}
          </div>
          {isLoad && parts.length > 0 && (
            <p className="text-[0.85rem] text-ink-2">{t("admin.transfers.form.keptHint")}</p>
          )}
          <LinesGrid
            label={t("admin.transfers.form.lines")}
            lines={lines}
            onChange={setLines}
            products={productList}
            proposedPrice={(product) => dailyPrice.get(product) ?? null}
            price={isLoad}
            stock={stockFor(KEPT)}
            places={placesOfProduct}
            errors={errors}
            hint={isLoad ? hintFor("") : undefined}
            extra={lotColumn(t("admin.sales.counterSale.lot"), lotRoom)}
          />
          {errors.lines && <p className="text-[0.78rem] font-semibold text-bad">{errors.lines}</p>}
          {isLoad && (
            <dl className="ms-auto text-end">
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.transfers.detail.totalAmount")}</dt>
              <dd className="num font-bold">{formatMoney(keptTotal)}</dd>
            </dl>
          )}
        </Card>

        {isLoad && (
          <BoxCountsFields
            title={t("admin.boxes.form.loadTitle")}
            hint={t("admin.boxes.form.loadHint")}
            value={boxes}
            onChange={setBoxes}
            errors={errors}
          />
        )}

        <Card>
          <Field label={t("admin.transfers.form.notes")} htmlFor={id("notes")} error={errors.notes}>
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
          <Button onClick={() => void navigate(back)}>{t("admin.transfers.form.cancel")}</Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? t("admin.transfers.form.saving") : t("admin.transfers.form.saveDraft")}
          </Button>
          <Button variant="primary" disabled={save.isPending} onClick={() => submit(true)}>
            <Icon name="check" />
            {t("admin.transfers.form.validate")}
          </Button>
        </div>
      </form>
    </>
  );
}
