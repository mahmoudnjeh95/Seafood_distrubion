import {
  createReceipt,
  type LastCost,
  type Order,
  type PaymentMethodEnum,
  type PaymentTermsEnum,
  type ReceiptWrite,
  useGetPurchaseOrder,
  useListLastPurchaseCosts,
  useListLocations,
  useListProducts,
  useListPurchaseOrders,
  useListReceipts,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import {
  formatDate,
  formatMoney,
  formatPercent,
  formatQuantity,
  parseDecimalInput,
  useTranslation,
} from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Combobox,
  type ComboboxOption,
  Field,
  Icon,
  Input,
  PageHeader,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
  cn,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useMemo, useState } from "react";
import { Navigate, useOutletContext, useSearchParams } from "react-router";

import { BoxCountsFields } from "../boxes/BoxCountsFields";
import { type BoxCountInputs, NO_BOX_INPUTS, boxCountsFromInputs } from "../boxes/shared";
import { lineTotal, percentChange, subtract, sum } from "../lib/decimal";
import { useLeave } from "../lib/embedded";
import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
import { useDebounced } from "../lib/useDebounced";
import { dueDateOf } from "../fieldpurchases/shared";
import { canWriteResults } from "../partnerships/shared";
import { idFrom } from "../purchasing/shared";
import { canRecordReceipts, refreshAfterReceipt, todayInTunis } from "./shared";

type LineField =
  "product" | "ordered_quantity" | "invoiced_quantity" | "accepted_quantity" | "unit_cost" | "use_by" | "partner";
type Line = Record<LineField, string> & {
  key: number;
  // Once a person types in these, the form stops filling them in.
  acceptedTouched: boolean;
  costTouched: boolean;
};
type Errors = Record<string, string>;
// A sum given now, with the delivery (D-192): same fields as the payments of a purchase at the port.
type Payment = { key: number; method: PaymentMethodEnum; amount: string; reference: string; cash_on: string };
const METHODS: PaymentMethodEnum[] = ["cash", "cheque", "bill", "transfer", "other"];
const paymentKey = (index: number, field: string) => `payments.${index}.${field}`;
// The line fields typed as kilos or money: each one is a cell of the lines table.
type WeightField = "ordered_quantity" | "invoiced_quantity" | "accepted_quantity" | "unit_cost";

// "No partner" in a line's partner select (a Radix item cannot have an empty value).
const NO_PARTNER = "none";

// Gives each line a stable React key, also for lines not saved yet.
let nextKey = 0;
const newPayment = (): Payment => {
  nextKey += 1;
  return { key: nextKey, method: "cash", amount: "", reference: "", cash_on: "" };
};
function newLine(): Line {
  nextKey += 1;
  return {
    key: nextKey,
    product: "",
    ordered_quantity: "",
    invoiced_quantity: "",
    accepted_quantity: "",
    unit_cost: "",
    use_by: "",
    partner: NO_PARTNER,
    acceptedTouched: false,
    costTouched: false,
  };
}

// The API writes "20.250"; people here write "20,250". Both are read back by parseDecimalInput.
const asTyped = (value: string) => value.replace(".", ",");

const lineKey = (index: number, field: string) => `lines.${index}.${field}`;

// "No purchase order" in the order select (a Radix item cannot have an empty value).
const NO_ORDER = "none";

// A product line is a row of a spreadsheet (D-162): its cells are borderless fields that fill the cell.
const CELL_INPUT =
  "block w-full rounded-none border-0 bg-transparent px-2.5 py-2 text-ink outline-none placeholder:text-ink-2/70 focus:bg-sea-soft focus:inset-ring-2 focus:inset-ring-sea aria-invalid:bg-bad-soft";

/** The lines of a delivery against an order: what is still to come, at the agreed price. Most deliveries
 * arrive as agreed, so the weights start at the remaining weight and the person lowers what did not come. */
function linesOfOrder(order: Order): Line[] {
  return order.lines
    .filter((line) => line.remaining_quantity !== "0.000")
    .map((line) => ({
      ...newLine(),
      product: String(line.product.id),
      invoiced_quantity: asTyped(line.remaining_quantity),
      accepted_quantity: asTyped(line.remaining_quantity),
      unit_cost: asTyped(line.unit_cost),
      costTouched: true,
    }));
}

/** Record goods received from a supplier. Owners and managers only; the server checks it too. */
export function ReceiptFormPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { leave } = useLeave();
  const queryClient = useQueryClient();
  const formId = useId();

  // Archived ones leave the pickers unless this receipt already uses them (pickable).
  const suppliers = useListSuppliers({ status: "all" });
  const locations = useListLocations({ status: "all" });
  const products = useListProducts({ status: "all" });

  const [params] = useSearchParams();
  // `?commande=4` (from the order page) starts a delivery against that purchase order.
  const [orderId, setOrderId] = useState<number | null>(() => idFrom(params.get("commande")));
  const order = useGetPurchaseOrder(orderId ?? 0, { query: { enabled: orderId !== null } }).data;

  const [supplier, setSupplier] = useState("");
  const [location, setLocation] = useState("");
  const [receivedOn, setReceivedOn] = useState(todayInTunis);
  const [supplierReference, setSupplierReference] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>(() => [newLine()]);
  const [boxes, setBoxes] = useState<BoxCountInputs>(NO_BOX_INPUTS);
  // Owed at once (D-159): a posted supplier invoice for the receipt, due by the deal made for this delivery.
  const [invoiceNow, setInvoiceNow] = useState(true);
  const [terms, setTerms] = useState<PaymentTermsEnum>("days");
  const [dueDays, setDueDays] = useState("30");
  const [payments, setPayments] = useState<Payment[]>([]);
  const [errors, setErrors] = useState<Errors>({});

  // Choosing an order (or arriving from its page) fills the supplier and the lines, once per order.
  const [filledFrom, setFilledFrom] = useState<number | null>(null);
  if (order && filledFrom !== order.id) {
    setFilledFrom(order.id);
    setSupplier(String(order.supplier.id));
    setLines(linesOfOrder(order));
  }
  const pendingOrders = useListPurchaseOrders(
    { supplier: Number(supplier), status: "pending", limit: 100 },
    { query: { enabled: supplier !== "" } },
  );

  // The same delivery note twice for one supplier is most likely a double entry: warn, never block (a note
  // can cover two deliveries).
  const typedReference = useDebounced(supplierReference.trim());
  const sameReference = useListReceipts(
    { supplier: Number(supplier), search: typedReference, limit: 20 },
    { query: { enabled: supplier !== "" && typedReference !== "" } },
  );
  const duplicate = typedReference
    ? sameReference.data?.results.find(
        (receipt) => receipt.supplier_reference.toLowerCase() === typedReference.toLowerCase(),
      )
    : undefined;

  const lastCosts = useListLastPurchaseCosts({ supplier: Number(supplier) }, { query: { enabled: supplier !== "" } });
  const lastCostOf = useMemo(() => {
    const byProduct = new Map<string, LastCost>();
    for (const cost of lastCosts.data ?? []) byProduct.set(String(cost.product_id), cost);
    return byProduct;
  }, [lastCosts.data]);

  // Goods usually go to a cold room: the first one is chosen until the person picks another place.
  const firstColdRoom = locations.data?.find((place) => place.is_active && place.kind === "cold_room")?.id;
  const chosenLocation = location || (firstColdRoom !== undefined ? String(firstColdRoom) : "");

  // Until a cost is typed, the line shows the last cost paid to this supplier for the product.
  const costOf = (line: Line): string => {
    if (line.costTouched) return line.unit_cost;
    const last = lastCostOf.get(line.product);
    return last ? asTyped(last.unit_cost) : "";
  };

  const setLine = (key: number, change: (line: Line) => Partial<Line>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...change(line) } : line)));

  const save = useMutation({
    mutationFn: (payload: ReceiptWrite) => createReceipt(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.receipts.form.created", { number: saved.number }));
      await refreshAfterReceipt(queryClient);
      leave(`/achats/${saved.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.receipts.form.error") });
    },
  });

  if (!canRecordReceipts(session)) return <Navigate to="/achats" replace />;

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!supplier) found.supplier = t("admin.receipts.form.required");
    if (!chosenLocation) found.location = t("admin.receipts.form.required");
    if (!receivedOn) found.received_on = t("admin.receipts.form.required");
    if (lines.length === 0) found.lines = t("admin.receipts.form.noLines");
    const payloadLines: ReceiptWrite["lines"] = [];
    lines.forEach((line, index) => {
      if (!line.product) found[lineKey(index, "product")] = t("admin.receipts.form.required");
      const weight = (field: LineField, optional = false) => {
        const typed = line[field].trim();
        if (optional && typed === "") return null;
        const parsed = parseDecimalInput(typed, 3);
        if (parsed === null || parsed.startsWith("-") || /^0+(\.0+)?$/.test(parsed)) {
          found[lineKey(index, field)] = t("admin.receipts.form.weight");
          return null;
        }
        return parsed;
      };
      // Against an order, the order says what was asked for: no ordered weight is typed.
      const ordered = order ? null : weight("ordered_quantity", true);
      const invoiced = weight("invoiced_quantity");
      const accepted = weight("accepted_quantity");
      const cost = parseDecimalInput(costOf(line).trim(), 3);
      if (cost === null || cost.startsWith("-")) found[lineKey(index, "unit_cost")] = t("admin.receipts.form.money");
      payloadLines.push({
        product: Number(line.product),
        ordered_quantity: ordered,
        invoiced_quantity: invoiced ?? "",
        accepted_quantity: accepted ?? "",
        unit_cost: cost ?? "",
        use_by: line.use_by || null,
        partner: line.partner === NO_PARTNER ? null : Number(line.partner),
      });
    });
    const boxCounts = boxCountsFromInputs(boxes);
    for (const boxType of boxCounts.invalid) found[`boxes.${boxType}`] = t("admin.boxes.form.invalid");
    const days = terms === "cash" ? 0 : Number(dueDays || "0");
    if (invoiceNow && (!Number.isInteger(days) || days < (terms === "days" ? 1 : 0) || days > 365)) {
      found.due_days = t("admin.receipts.form.dueDaysError");
    }
    // What is given now (D-192) only exists with the invoice; more than its total is refused, as on the server.
    const payloadPayments: NonNullable<ReceiptWrite["payments"]> = [];
    if (invoiceNow) {
      payments.forEach((payment, index) => {
        const amount = parseDecimalInput(payment.amount.trim(), 3);
        if (amount === null || amount.startsWith("-") || /^0+(\.0+)?$/.test(amount))
          found[paymentKey(index, "amount")] = t("admin.receipts.form.money");
        payloadPayments.push({
          method: payment.method,
          amount: amount ?? "",
          reference: payment.reference.trim(),
          cash_on: payment.cash_on || null,
        });
      });
      if (
        Object.keys(found).length === 0 &&
        payloadPayments.length > 0 &&
        subtract(invoicedTotal, paid).startsWith("-")
      )
        found[paymentKey(payloadPayments.length - 1, "amount")] = t("admin.receipts.form.overpaid", {
          paid: formatMoney(paid),
          total: formatMoney(invoicedTotal),
        });
    }
    setErrors(found);
    // An order picked but still loading: wait, or the delivery would be saved without it.
    if (Object.keys(found).length > 0 || (orderId !== null && !order)) return;
    save.mutate({
      supplier: Number(supplier),
      location: Number(chosenLocation),
      purchase_order: order?.id ?? null,
      received_on: receivedOn,
      supplier_reference: supplierReference.trim(),
      notes: notes.trim(),
      lines: payloadLines,
      boxes: boxCounts.counts,
      invoice_now: invoiceNow,
      terms,
      due_days: days,
      payments: payloadPayments,
    });
  }

  // Amounts of the lines whose weight and cost are already readable.
  const amounts = lines.map((line) => {
    const invoiced = parseDecimalInput(line.invoiced_quantity.trim(), 3);
    const accepted = parseDecimalInput(line.accepted_quantity.trim(), 3);
    const cost = parseDecimalInput(costOf(line).trim(), 3);
    return {
      invoiced: invoiced && cost ? lineTotal(invoiced, cost) : null,
      accepted: accepted && cost ? lineTotal(accepted, cost) : null,
    };
  });
  const invoicedTotal = sum(amounts.flatMap(({ invoiced }) => (invoiced ? [invoiced] : [])));
  const acceptedTotal = sum(amounts.flatMap(({ accepted }) => (accepted ? [accepted] : [])));
  const paid = sum(payments.flatMap((payment) => parseDecimalInput(payment.amount.trim(), 3) ?? []));
  const setPayment = (paymentKeyValue: number, change: Partial<Payment>) =>
    setPayments((current) =>
      current.map((payment) => (payment.key === paymentKeyValue ? { ...payment, ...change } : payment)),
    );
  // The three-step choice of D-192: nothing, a part, or all of what the delivery is worth; the rest is for the office.
  const givenChoice: "none" | "part" | "all" =
    payments.length === 0 ? "none" : paid === invoicedTotal && invoicedTotal !== "0.000" ? "all" : "part";
  const chooseGiven = (choice: "none" | "part" | "all") => {
    if (choice === "none") setPayments([]);
    else if (choice === "all") {
      const first = payments[0] ?? newPayment();
      setPayments([{ ...first, amount: asTyped(invoicedTotal) }]);
    } else if (payments.length === 0) setPayments([newPayment()]);
  };

  function lastCostHint(line: Line): string | null {
    if (!supplier || !line.product) return null;
    const last = lastCostOf.get(line.product);
    if (!last) return lastCosts.data ? t("admin.receipts.form.noLastCost") : null;
    const typed = parseDecimalInput(costOf(line).trim(), 3);
    const change = typed && !typed.startsWith("-") ? percentChange(typed, last.unit_cost) : null;
    const values = { cost: formatMoney(last.unit_cost), date: formatDate(last.received_on) };
    return change && change !== "0.0"
      ? t("admin.receipts.form.lastCostChange", { ...values, change: formatPercent(change) })
      : t("admin.receipts.form.lastCost", values);
  }

  // Orders of this supplier still waiting for goods, plus the chosen one if it is not (yet) among them.
  const orderOptions = [
    { value: NO_ORDER, label: t("admin.receipts.form.noPurchaseOrder") },
    ...(pendingOrders.data?.results ?? []).map((one) => ({
      value: String(one.id),
      label: `${one.number} · ${formatDate(one.ordered_on)}`,
    })),
  ];
  if (order && !orderOptions.some((option) => option.value === String(order.id))) {
    orderOptions.push({ value: String(order.id), label: order.number });
  }
  const orderLineOf = (productId: string) => order?.lines.find((line) => String(line.product.id) === productId);
  // Against an order, only its products can be received.
  const productOptions = pickable(
    products.data ?? [],
    lines.map((line) => line.product),
  )
    .filter((product) => !order || orderLineOf(String(product.id)) !== undefined)
    .map<ComboboxOption>((product) => ({
      value: String(product.id),
      label: `${product.name} · ${product.reference}`,
      keywords: [product.name_ar, product.category.name],
      detail: (
        <span className="flex items-baseline justify-between gap-4">
          <span>{product.name}</span>
          <span className="num text-[0.8rem] text-ink-2">{product.reference}</span>
        </span>
      ),
    }));

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
          <SelectValue placeholder={t("admin.receipts.form.choose")} />
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

  const weightLabels: Record<WeightField, string> = {
    ordered_quantity: t("admin.receipts.form.ordered"),
    invoiced_quantity: t("admin.receipts.form.invoiced"),
    accepted_quantity: t("admin.receipts.form.accepted"),
    unit_cost: t("admin.receipts.form.cost"),
  };

  const cellError = (name: string) =>
    errors[name] ? <p className="px-2.5 pb-1.5 text-[0.78rem] font-semibold text-bad">{errors[name]}</p> : null;

  // The same choice as `select`, inside a spreadsheet cell: the column header is its label.
  const cellSelect = (
    name: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    options: { value: string; label: string }[],
  ) => (
    <>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger
          id={id(name)}
          aria-label={label}
          aria-invalid={errors[name] ? true : undefined}
          className={cn(CELL_INPUT, "flex items-center justify-between gap-2 text-start")}
        >
          <SelectValue placeholder={t("admin.receipts.form.choose")} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {cellError(name)}
    </>
  );

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.receipts.form.title")} />

      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          {select(
            "supplier",
            t("admin.receipts.form.supplier"),
            supplier,
            (value) => {
              setSupplier(value);
              // An order belongs to one supplier: another supplier means no order.
              if (order && String(order.supplier.id) !== value) setOrderId(null);
            },
            pickable(suppliers.data ?? [], [supplier]).map((one) => ({ value: String(one.id), label: one.name })),
          )}
          {supplier !== "" &&
            orderOptions.length > 1 &&
            select(
              "purchase_order",
              t("admin.receipts.form.purchaseOrder"),
              orderId === null ? NO_ORDER : String(orderId),
              (value) => setOrderId(value === NO_ORDER ? null : Number(value)),
              orderOptions,
            )}
          {select(
            "location",
            t("admin.receipts.form.location"),
            chosenLocation,
            setLocation,
            pickable(locations.data ?? [], [chosenLocation]).map((place) => ({
              value: String(place.id),
              label: place.name,
            })),
          )}
          <Field label={t("admin.receipts.form.date")} htmlFor={id("received_on")} error={errors.received_on}>
            <Input
              id={id("received_on")}
              type="date"
              max={todayInTunis()}
              value={receivedOn}
              onChange={(event) => setReceivedOn(event.target.value)}
              aria-invalid={errors.received_on ? true : undefined}
            />
          </Field>
          <Field
            label={t("admin.receipts.form.supplierReference")}
            htmlFor={id("supplier_reference")}
            error={errors.supplier_reference}
          >
            <Input
              id={id("supplier_reference")}
              value={supplierReference}
              maxLength={50}
              onChange={(event) => setSupplierReference(event.target.value)}
              autoComplete="off"
            />
            {duplicate && supplierReference.trim() === typedReference && (
              <p role="status" className="mt-1 text-[0.8rem] font-semibold text-warn">
                {t("admin.receipts.form.duplicateReference", { number: duplicate.number })}
              </p>
            )}
          </Field>
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.receipts.form.lines")}</CardTitle>
          <p className="text-[0.85rem] text-ink-2">{t("admin.receipts.form.netWeightHint")}</p>
          {order && (
            <p className="text-[0.85rem] font-semibold text-sea">
              {t("admin.receipts.form.orderHint")} ({order.number})
            </p>
          )}
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.receipts.form.product")}</Th>
                {order ? (
                  <Th numeric>{t("admin.receipts.form.remaining")}</Th>
                ) : (
                  <Th numeric>{t("admin.receipts.form.ordered")}</Th>
                )}
                <Th numeric>{t("admin.receipts.form.invoiced")}</Th>
                <Th numeric>{t("admin.receipts.form.accepted")}</Th>
                <Th numeric>{t("admin.receipts.form.cost")}</Th>
                <Th numeric>{t("admin.receipts.form.amount")}</Th>
                <Th>{t("admin.receipts.form.useBy")}</Th>
                {canWriteResults(session) && <Th>{t("admin.receipts.form.partner")}</Th>}
                <Th className="w-10">
                  <span className="sr-only">{t("admin.receipts.form.removeLine")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, index) => {
                const hint = lastCostHint(line);
                const amount = amounts[index]?.invoiced;
                const weightCell = (
                  field: WeightField,
                  value: string,
                  onChange: (value: string) => void,
                  note?: string | null,
                ) => (
                  <Td className="p-0">
                    <input
                      id={id(lineKey(index, field))}
                      inputMode="decimal"
                      aria-label={weightLabels[field]}
                      value={value}
                      onChange={(event) => onChange(event.target.value)}
                      aria-invalid={errors[lineKey(index, field)] ? true : undefined}
                      autoComplete="off"
                      className={cn(CELL_INPUT, "num text-end")}
                    />
                    {cellError(lineKey(index, field))}
                    {note && (
                      <p className="px-2.5 pb-1.5 text-[0.75rem] text-ink-2" aria-live="polite">
                        {note}
                      </p>
                    )}
                  </Td>
                );
                return (
                  <tr key={line.key}>
                    <Td className="p-0">
                      {/* Typed like the product cell of a quote or a sale: code, name, Arabic name or category. */}
                      <Combobox
                        plain
                        id={id(lineKey(index, "product"))}
                        aria-label={t("admin.receipts.form.product")}
                        aria-invalid={errors[lineKey(index, "product")] ? true : undefined}
                        size={1}
                        placeholder={t("admin.lines.productHint")}
                        value={line.product}
                        onValueChange={(value) => setLine(line.key, () => ({ product: value }))}
                        onChosen={() =>
                          document
                            .getElementById(id(lineKey(index, order ? "invoiced_quantity" : "ordered_quantity")))
                            ?.focus()
                        }
                        options={productOptions}
                        empty={t("admin.lines.noProduct")}
                        className={CELL_INPUT}
                      />
                      {cellError(lineKey(index, "product"))}
                    </Td>
                    {order ? (
                      <Td numeric className="text-ink-2">
                        {formatQuantity(orderLineOf(line.product)?.remaining_quantity ?? "0")}
                      </Td>
                    ) : (
                      weightCell("ordered_quantity", line.ordered_quantity, (value) =>
                        setLine(line.key, () => ({ ordered_quantity: value })),
                      )
                    )}
                    {weightCell("invoiced_quantity", line.invoiced_quantity, (value) =>
                      // Most deliveries are accepted as invoiced: the accepted weight follows until it is typed.
                      setLine(line.key, (current) => ({
                        invoiced_quantity: value,
                        ...(current.acceptedTouched ? {} : { accepted_quantity: value }),
                      })),
                    )}
                    {weightCell("accepted_quantity", line.accepted_quantity, (value) =>
                      setLine(line.key, () => ({ accepted_quantity: value, acceptedTouched: true })),
                    )}
                    {weightCell(
                      "unit_cost",
                      costOf(line),
                      (value) => setLine(line.key, () => ({ unit_cost: value, costTouched: true })),
                      hint,
                    )}
                    <Td numeric className="font-semibold">
                      {amount ? formatMoney(amount) : ""}
                    </Td>
                    <Td className="p-0">
                      <input
                        id={id(lineKey(index, "use_by"))}
                        type="date"
                        aria-label={t("admin.receipts.form.useBy")}
                        min={receivedOn}
                        value={line.use_by}
                        onChange={(event) => setLine(line.key, () => ({ use_by: event.target.value }))}
                        aria-invalid={errors[lineKey(index, "use_by")] ? true : undefined}
                        className={CELL_INPUT}
                      />
                      {cellError(lineKey(index, "use_by"))}
                    </Td>
                    {canWriteResults(session) && (
                      <Td className="p-0">
                        {cellSelect(
                          lineKey(index, "partner"),
                          t("admin.receipts.form.partner"),
                          line.partner,
                          (value) => setLine(line.key, () => ({ partner: value })),
                          [
                            { value: NO_PARTNER, label: t("admin.receipts.form.noPartner") },
                            ...pickable(suppliers.data ?? [], [line.partner]).map((one) => ({
                              value: String(one.id),
                              label: String(one.id) === supplier ? t("admin.receipts.form.sameSupplier") : one.name,
                            })),
                          ],
                        )}
                      </Td>
                    )}
                    <Td className="p-0 text-center">
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label={t("admin.receipts.form.removeLine")}
                        title={t("admin.receipts.form.removeLine")}
                        onClick={() => setLines((current) => current.filter((other) => other.key !== line.key))}
                      >
                        <Icon name="trash" />
                      </Button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          {errors.lines && <p className="text-[0.78rem] font-semibold text-bad">{errors.lines}</p>}
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
            <Button onClick={() => setLines((current) => [...current, newLine()])}>
              <Icon name="plus" />
              {t("admin.receipts.form.addLine")}
            </Button>
            <dl className="ms-auto flex flex-wrap gap-x-8 gap-y-2">
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.receipts.form.invoicedTotal")}</dt>
                <dd className="num font-bold">{formatMoney(invoicedTotal)}</dd>
              </div>
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.receipts.form.acceptedTotal")}</dt>
                <dd className="num">{formatMoney(acceptedTotal)}</dd>
              </div>
            </dl>
          </div>
        </Card>

        <Card className="flex flex-col gap-3">
          <label className="flex items-center gap-2 font-semibold">
            <input
              type="checkbox"
              checked={invoiceNow}
              onChange={(event) => setInvoiceNow(event.target.checked)}
              className="size-4 accent-coral"
            />
            {t("admin.receipts.form.invoiceNow")}
          </label>
          <p className="text-[0.85rem] text-ink-2">
            {t(invoiceNow ? "admin.receipts.form.invoiceNowHint" : "admin.receipts.form.invoiceLaterHint")}
          </p>
          {invoiceNow && (
            <div className="grid grid-cols-3 items-start gap-4 max-[640px]:grid-cols-1">
              {select(
                "terms",
                t("admin.receipts.form.terms"),
                terms,
                (value) => setTerms(value as PaymentTermsEnum),
                (["cash", "days", "month_end"] as const).map((choice) => ({
                  value: choice,
                  label: t(`admin.fieldPurchases.termsChoice.${choice}`),
                })),
              )}
              {terms !== "cash" && (
                <Field label={t("admin.receipts.form.dueDays")} htmlFor={id("due_days")} error={errors.due_days}>
                  <Input
                    id={id("due_days")}
                    type="number"
                    min="0"
                    max="365"
                    value={dueDays}
                    onChange={(event) => setDueDays(event.target.value)}
                    aria-invalid={errors.due_days ? true : undefined}
                  />
                </Field>
              )}
              <p className="num self-end py-2.5 font-semibold text-ink-2">
                {t("admin.receipts.form.dueOn", {
                  date: formatDate(
                    dueDateOf(receivedOn || todayInTunis(), terms, terms === "cash" ? 0 : Number(dueDays || "0") || 0),
                  ),
                })}
              </p>
            </div>
          )}
        </Card>

        {invoiceNow && (
          <Card className="flex flex-col gap-3">
            <CardTitle className="mb-0">{t("admin.receipts.form.payments")}</CardTitle>
            <p className="font-semibold">{t("admin.receipts.form.givenNow")}</p>
            <div className="flex flex-wrap gap-2" role="group" aria-label={t("admin.receipts.form.givenNow")}>
              {(["none", "part", "all"] as const).map((choice) => (
                <Button
                  key={choice}
                  variant={givenChoice === choice ? "primary" : "secondary"}
                  aria-pressed={givenChoice === choice}
                  onClick={() => chooseGiven(choice)}
                >
                  {t(`admin.fieldPurchases.form.choice.${choice}`)}
                </Button>
              ))}
            </div>
            {payments.map((payment, index) => (
              <div
                key={payment.key}
                role="group"
                aria-label={t("admin.fieldPurchases.form.paymentNumber", { number: index + 1 })}
                className="grid grid-cols-[repeat(4,1fr)_auto] items-start gap-3 rounded-card border border-line p-3 max-[960px]:grid-cols-2"
              >
                {select(
                  paymentKey(index, "method"),
                  t("admin.fieldPurchases.form.method"),
                  payment.method,
                  (value) => setPayment(payment.key, { method: value as PaymentMethodEnum }),
                  METHODS.map((method) => ({ value: method, label: t(`admin.supplierPayments.method.${method}`) })),
                )}
                <Field
                  label={t("admin.fieldPurchases.form.paymentAmount")}
                  htmlFor={id(paymentKey(index, "amount"))}
                  error={errors[paymentKey(index, "amount")]}
                >
                  <Input
                    id={id(paymentKey(index, "amount"))}
                    inputMode="decimal"
                    value={payment.amount}
                    onChange={(event) => setPayment(payment.key, { amount: event.target.value })}
                    aria-invalid={errors[paymentKey(index, "amount")] ? true : undefined}
                  />
                </Field>
                <Field
                  label={t("admin.fieldPurchases.form.reference")}
                  htmlFor={id(paymentKey(index, "reference"))}
                  error={errors[paymentKey(index, "reference")]}
                >
                  <Input
                    id={id(paymentKey(index, "reference"))}
                    value={payment.reference}
                    onChange={(event) => setPayment(payment.key, { reference: event.target.value })}
                  />
                </Field>
                <Field
                  label={t("admin.fieldPurchases.form.cashOn")}
                  htmlFor={id(paymentKey(index, "cash_on"))}
                  error={errors[paymentKey(index, "cash_on")]}
                >
                  <Input
                    id={id(paymentKey(index, "cash_on"))}
                    type="date"
                    min={receivedOn}
                    value={payment.cash_on}
                    onChange={(event) => setPayment(payment.key, { cash_on: event.target.value })}
                  />
                </Field>
                <div className="flex items-end self-stretch max-[960px]:col-span-2 max-[960px]:justify-end">
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("admin.fieldPurchases.form.removePayment")}
                    title={t("admin.fieldPurchases.form.removePayment")}
                    onClick={() => setPayments((current) => current.filter((other) => other.key !== payment.key))}
                  >
                    <Icon name="trash" />
                  </Button>
                </div>
              </div>
            ))}
            {payments.length > 0 && (
              <div>
                <Button onClick={() => setPayments((current) => [...current, newPayment()])}>
                  <Icon name="plus" />
                  {t("admin.fieldPurchases.form.addPayment")}
                </Button>
              </div>
            )}
            <dl className="flex flex-wrap justify-end gap-x-8 gap-y-2">
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.receipts.form.owedTotal")}</dt>
                <dd className="num">{formatMoney(invoicedTotal)}</dd>
              </div>
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.receipts.form.paidNow")}</dt>
                <dd className="num">{formatMoney(paid)}</dd>
              </div>
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.receipts.form.restToDefine")}</dt>
                <dd className="num font-semibold">{formatMoney(subtract(invoicedTotal, paid))}</dd>
              </div>
            </dl>
          </Card>
        )}

        <BoxCountsFields
          title={t("admin.boxes.form.receiptTitle")}
          hint={t("admin.boxes.form.receiptHint")}
          value={boxes}
          onChange={setBoxes}
          errors={errors}
        />

        <Card>
          <Field label={t("admin.receipts.form.notes")} htmlFor={id("notes")} error={errors.notes}>
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

        <div className="flex justify-end gap-2">
          <Button onClick={() => leave("/achats")}>{t("admin.receipts.form.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? t("admin.receipts.form.saving") : t("admin.receipts.form.save")}
          </Button>
        </div>
      </form>
    </>
  );
}
