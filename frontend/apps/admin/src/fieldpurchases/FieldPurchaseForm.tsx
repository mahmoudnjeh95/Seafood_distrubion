import {
  createFieldPurchase,
  type FieldPurchase,
  type FieldPurchaseCreate,
  type PaymentMethodEnum,
  type PaymentTermsEnum,
  refuseFieldPurchase,
  updateFieldPurchase,
  useListLocations,
  useListProducts,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Icon,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";

import { BoxCountsFields } from "../boxes/BoxCountsFields";
import { type BoxCountInputs, boxCountsFromInputs, boxInputsFromCounts, NO_BOX_INPUTS } from "../boxes/shared";
import { lineTotal, subtract, sum } from "../lib/decimal";
import { useLeave } from "../lib/embedded";
import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
import { canWriteResults } from "../partnerships/shared";
import { ProductDialog } from "../products/ProductDialog";
import { todayInTunis } from "../receipts/shared";
import { SupplierDialog } from "../suppliers/SupplierDialog";
import { dueDateOf, refreshAfterFieldPurchase } from "./shared";

type Line = {
  key: number;
  product: string;
  proposed_product: string;
  declared_quantity: string;
  received_quantity: string;
  unit_cost: string;
  partner: string;
};
type Payment = { key: number; method: PaymentMethodEnum; amount: string; reference: string; cash_on: string };
type Errors = Record<string, string>;

// "No partner" in a line's partner select (a Radix item cannot have an empty value).
const NO_PARTNER = "none";
const TERMS: PaymentTermsEnum[] = ["cash", "days", "month_end"];
const METHODS: PaymentMethodEnum[] = ["cash", "cheque", "bill", "transfer", "other"];

let nextKey = 0;
const key = () => (nextKey += 1);

// The API writes "20.250"; people here write "20,250". Both are read back by parseDecimalInput.
const asTyped = (value: string | null | undefined) => (value ?? "").replace(".", ",");
const lineKey = (index: number, field: string) => `lines.${index}.${field}`;
const paymentKey = (index: number, field: string) => `payments.${index}.${field}`;

function linesOf(purchase?: FieldPurchase): Line[] {
  if (!purchase) {
    return [
      {
        key: key(),
        product: "",
        proposed_product: "",
        declared_quantity: "",
        received_quantity: "",
        unit_cost: "",
        partner: NO_PARTNER,
      },
    ];
  }
  return purchase.lines.map((line) => ({
    key: key(),
    product: line.product ? String(line.product.id) : "",
    proposed_product: line.proposed_product,
    declared_quantity: asTyped(line.declared_quantity),
    received_quantity: asTyped(line.received_quantity),
    unit_cost: asTyped(line.unit_cost),
    partner: line.partner ? String(line.partner.id) : NO_PARTNER,
  }));
}

function paymentsOf(purchase?: FieldPurchase): Payment[] {
  return (purchase?.payments ?? []).map((payment) => ({
    key: key(),
    method: payment.method,
    amount: asTyped(payment.amount),
    reference: payment.reference,
    cash_on: payment.cash_on ?? "",
  }));
}

/**
 * Check a purchase at the port (`purchase` given) or type one phoned in (absent). The office fixes the supplier, the
 * products, the kilos really received and the prices, picks where the goods go, then saves (a new revision),
 * validates or refuses it. Owners and managers only; the server checks it too.
 */
export function FieldPurchaseForm({
  purchase,
  session,
  onReload,
}: {
  purchase?: FieldPurchase;
  session: Session;
  onReload?: () => void;
}) {
  const { t } = useTranslation();
  const { leave } = useLeave();
  const queryClient = useQueryClient();
  const formId = useId();
  const isOwner = canWriteResults(session);

  const suppliers = useListSuppliers({ status: "all" });
  const locations = useListLocations({ status: "all" });
  const products = useListProducts({ status: "all" });

  const [supplier, setSupplier] = useState(purchase?.supplier ? String(purchase.supplier.id) : "");
  const [location, setLocation] = useState(purchase?.location ? String(purchase.location.id) : "");
  const [boughtOn, setBoughtOn] = useState(purchase?.bought_on ?? todayInTunis());
  const [terms, setTerms] = useState<PaymentTermsEnum>(purchase?.terms ?? "cash");
  const [dueDays, setDueDays] = useState(purchase ? String(purchase.due_days) : "0");
  const [supplierReference, setSupplierReference] = useState(purchase?.supplier_reference ?? "");
  const [notes, setNotes] = useState(purchase?.notes ?? "");
  const [officeNote, setOfficeNote] = useState(purchase?.office_note ?? "");
  const [lines, setLines] = useState<Line[]>(() => linesOf(purchase));
  const [payments, setPayments] = useState<Payment[]>(() => paymentsOf(purchase));
  const [boxes, setBoxes] = useState<BoxCountInputs>(() =>
    purchase ? boxInputsFromCounts(purchase.boxes) : NO_BOX_INPUTS,
  );
  const [errors, setErrors] = useState<Errors>({});
  const [conflict, setConflict] = useState(false);
  const [confirming, setConfirming] = useState<"validate" | "refuse" | null>(null);
  const [refusal, setRefusal] = useState("");
  const [creatingSupplier, setCreatingSupplier] = useState(false);
  const [creatingProduct, setCreatingProduct] = useState<string | null>(null);

  // Goods usually go to a cold room: the first one is chosen until the person picks another place.
  const firstColdRoom = locations.data?.find((place) => place.is_active && place.kind === "cold_room")?.id;
  const chosenLocation = location || (firstColdRoom !== undefined ? String(firstColdRoom) : "");

  const setLine = (lineKeyValue: number, change: Partial<Line>) =>
    setLines((current) => current.map((line) => (line.key === lineKeyValue ? { ...line, ...change } : line)));
  const setPayment = (paymentKeyValue: number, change: Partial<Payment>) =>
    setPayments((current) =>
      current.map((payment) => (payment.key === paymentKeyValue ? { ...payment, ...change } : payment)),
    );

  const onFailure = (failure: unknown) => {
    const fromServer = fieldErrors(failure);
    if (fromServer.revision) setConflict(true);
    setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.fieldPurchases.form.error") });
  };

  const save = useMutation({
    mutationFn: ({ payload, confirm }: { payload: FieldPurchaseCreate; confirm: boolean }) =>
      purchase
        ? updateFieldPurchase(purchase.id, {
            ...payload,
            revision: purchase.revision,
            office_note: officeNote.trim(),
            confirm,
          })
        : createFieldPurchase(payload),
    onSuccess: async (saved, { confirm }) => {
      setConfirming(null);
      if (!purchase) toast.success(t("admin.fieldPurchases.form.created", { number: saved.number }));
      else if (confirm) toast.success(t("admin.fieldPurchases.form.validated", { number: saved.number }));
      else toast.success(t("admin.fieldPurchases.form.saved", { number: saved.number, revision: saved.revision }));
      await refreshAfterFieldPurchase(queryClient);
      if (!purchase) leave(`/achats/terrain/${saved.id}`);
    },
    onError: (failure) => {
      setConfirming(null);
      onFailure(failure);
    },
  });

  const refuse = useMutation({
    mutationFn: () =>
      refuseFieldPurchase(purchase?.id ?? 0, { revision: purchase?.revision ?? 0, office_note: refusal.trim() }),
    onSuccess: async (saved) => {
      setConfirming(null);
      toast.success(t("admin.fieldPurchases.form.refused", { number: saved.number }));
      await refreshAfterFieldPurchase(queryClient);
    },
    onError: (failure) => {
      setConfirming(null);
      onFailure(failure);
    },
  });

  /** The payload once checked here; problems found go to the form, and null means do not send. */
  function payloadOf(): FieldPurchaseCreate | null {
    const found: Errors = {};
    if (!supplier && !purchase?.proposed_supplier) found.supplier = t("admin.fieldPurchases.form.required");
    if (!boughtOn) found.bought_on = t("admin.fieldPurchases.form.required");
    const days = terms === "cash" ? 0 : Number(dueDays || "0");
    if (!Number.isInteger(days) || days < 0 || days > 365) found.due_days = t("admin.fieldPurchases.form.days");
    if (lines.length === 0) found.lines = t("admin.fieldPurchases.form.noLines");
    const weight = (typed: string, field: string, optional: boolean) => {
      const value = typed.trim();
      if (optional && value === "") return null;
      const parsed = parseDecimalInput(value, 3);
      if (parsed === null || parsed.startsWith("-") || /^0+(\.0+)?$/.test(parsed)) {
        found[field] = t("admin.fieldPurchases.form.weight");
        return null;
      }
      return parsed;
    };
    const money = (typed: string, field: string) => {
      const parsed = parseDecimalInput(typed.trim(), 3);
      if (parsed === null || parsed.startsWith("-")) found[field] = t("admin.fieldPurchases.form.money");
      return parsed ?? "";
    };
    const payloadLines = lines.map((line, index) => {
      if (!line.product && !line.proposed_product)
        found[lineKey(index, "product")] = t("admin.fieldPurchases.form.required");
      return {
        product: line.product ? Number(line.product) : null,
        proposed_product: line.product ? "" : line.proposed_product,
        declared_quantity: weight(line.declared_quantity, lineKey(index, "declared_quantity"), false) ?? "",
        received_quantity: weight(line.received_quantity, lineKey(index, "received_quantity"), true),
        unit_cost: money(line.unit_cost, lineKey(index, "unit_cost")),
        partner: line.partner === NO_PARTNER ? null : Number(line.partner),
      };
    });
    const payloadPayments = payments.map((payment, index) => ({
      method: payment.method,
      amount: money(payment.amount, paymentKey(index, "amount")),
      reference: payment.reference.trim(),
      cash_on: payment.cash_on || null,
    }));
    // More given than the purchase is worth is refused, as on the server: the bigger of the driver's kg and the kg
    // received per line, so a lot counted lighter keeps what was really given (the rest becomes an advance).
    if (Object.keys(found).length === 0 && payloadPayments.length > 0) {
      const ceiling = sum(
        payloadLines.map((line) => {
          const kilos =
            line.received_quantity && !subtract(line.received_quantity, line.declared_quantity).startsWith("-")
              ? line.received_quantity
              : line.declared_quantity;
          return lineTotal(kilos, line.unit_cost);
        }),
      );
      const given = sum(payloadPayments.map((payment) => payment.amount));
      if (subtract(ceiling, given).startsWith("-"))
        found[paymentKey(payloadPayments.length - 1, "amount")] = t("admin.fieldPurchases.form.overpaid", {
          paid: formatMoney(given),
          total: formatMoney(ceiling),
        });
    }
    const boxCounts = boxCountsFromInputs(boxes);
    for (const boxType of boxCounts.invalid) found[`boxes.${boxType}`] = t("admin.boxes.form.invalid");
    setErrors(found);
    if (Object.keys(found).length > 0) return null;
    return {
      supplier: supplier ? Number(supplier) : null,
      proposed_supplier: supplier ? "" : (purchase?.proposed_supplier ?? ""),
      proposed_supplier_phone: supplier ? "" : (purchase?.proposed_supplier_phone ?? ""),
      bought_on: boughtOn,
      terms,
      due_days: days,
      supplier_reference: supplierReference.trim(),
      notes: notes.trim(),
      location: chosenLocation ? Number(chosenLocation) : null,
      boxes: boxCounts.counts,
      lines: payloadLines,
      payments: payloadPayments,
    };
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const payload = payloadOf();
    if (payload) save.mutate({ payload, confirm: false });
  }

  // What is owed: the kilos received, else the driver's kilos, × the price.
  const owedOf = (line: Line) => {
    const declared = parseDecimalInput(line.declared_quantity.trim(), 3);
    const received = parseDecimalInput(line.received_quantity.trim(), 3);
    const cost = parseDecimalInput(line.unit_cost.trim(), 3);
    const kilos = received ?? declared;
    return {
      kilos,
      declared: declared && cost ? lineTotal(declared, cost) : null,
      owed: kilos && cost ? lineTotal(kilos, cost) : null,
    };
  };
  const amounts = lines.map(owedOf);
  const total = sum(amounts.flatMap(({ owed }) => (owed ? [owed] : [])));
  const declaredTotal = sum(amounts.flatMap(({ declared }) => (declared ? [declared] : [])));
  const kilos = sum(amounts.flatMap(({ kilos: value }) => (value ? [value] : [])));
  const paid = sum(payments.flatMap((payment) => parseDecimalInput(payment.amount.trim(), 3) ?? []));
  const rest = subtract(total, paid);
  // The three-step choice of D-192: nothing, a part, or all of the total; the rest is for the office to define.
  const givenChoice: "none" | "part" | "all" =
    payments.length === 0 ? "none" : paid === total && total !== "0.000" ? "all" : "part";
  const chooseGiven = (choice: "none" | "part" | "all") => {
    if (choice === "none") setPayments([]);
    else if (choice === "all") {
      const first = payments[0];
      setPayments([
        {
          key: first?.key ?? key(),
          method: first?.method ?? "cash",
          amount: asTyped(total),
          reference: first?.reference ?? "",
          cash_on: first?.cash_on ?? "",
        },
      ]);
    } else if (payments.length === 0) {
      setPayments([{ key: key(), method: "cash", amount: "", reference: "", cash_on: "" }]);
    }
  };
  const due = dueDateOf(boughtOn, terms, terms === "cash" ? 0 : Number(dueDays || "0") || 0);

  const productOptions = pickable(
    products.data ?? [],
    lines.map((line) => line.product),
  ).map((product) => ({ value: String(product.id), label: `${product.name} · ${product.reference}` }));
  const supplierOptions = pickable(suppliers.data ?? [], [supplier]).map((one) => ({
    value: String(one.id),
    label: one.name,
  }));
  const kept = new Set(lines.map((line) => line.partner));
  const partnerOptions = [
    { value: NO_PARTNER, label: t("admin.fieldPurchases.form.noPartner") },
    ...pickable(suppliers.data ?? [], [...kept]).map((one) => ({
      value: String(one.id),
      label: String(one.id) === supplier ? t("admin.fieldPurchases.form.sameSupplier") : one.name,
    })),
  ];

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
          <SelectValue placeholder={t("admin.fieldPurchases.form.choose")} />
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
  const textInput = (
    name: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    options: { numeric?: boolean; placeholder?: string; type?: string; min?: string; max?: string } = {},
  ) => (
    <Field label={label} htmlFor={id(name)} error={errors[name]}>
      <Input
        id={id(name)}
        type={options.type ?? "text"}
        inputMode={options.numeric ? "decimal" : undefined}
        value={value}
        placeholder={options.placeholder}
        min={options.min}
        max={options.max}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={errors[name] ? true : undefined}
        autoComplete="off"
        className={options.numeric ? "num" : undefined}
      />
    </Field>
  );
  const busy = save.isPending || refuse.isPending;

  return (
    <>
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
        <p className="text-[0.9rem] text-ink-2">
          {t(purchase ? "admin.fieldPurchases.form.checkHint" : "admin.fieldPurchases.form.newHint")}
        </p>

        {conflict && (
          <div role="alert" className="flex flex-wrap items-center gap-3 rounded-card bg-bad-soft p-3 text-bad">
            <b className="flex-1">{t("admin.fieldPurchases.form.conflict")}</b>
            {onReload && (
              <Button
                onClick={() => {
                  setConflict(false);
                  onReload();
                }}
              >
                {t("admin.fieldPurchases.form.reload")}
              </Button>
            )}
          </div>
        )}

        <Card className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <div className="flex flex-col gap-1">
            {select("supplier", t("admin.fieldPurchases.form.supplier"), supplier, setSupplier, supplierOptions)}
            {!supplier && purchase?.proposed_supplier && (
              <p className="text-[0.85rem] font-semibold text-warn">
                {t("admin.fieldPurchases.form.proposedSupplier", { name: purchase.proposed_supplier })}
                {purchase.proposed_supplier_phone &&
                  ` · ${t("admin.fieldPurchases.form.proposedPhone", { phone: purchase.proposed_supplier_phone })}`}
              </p>
            )}
            {!supplier && (
              <button
                type="button"
                className="w-fit text-[0.85rem] font-semibold text-sea hover:underline"
                onClick={() => setCreatingSupplier(true)}
              >
                {t(
                  purchase?.proposed_supplier
                    ? "admin.fieldPurchases.form.createSupplier"
                    : "admin.fieldPurchases.form.newSupplier",
                )}
              </button>
            )}
          </div>
          {select(
            "location",
            t("admin.fieldPurchases.form.location"),
            chosenLocation,
            setLocation,
            pickable(locations.data ?? [], [chosenLocation]).map((place) => ({
              value: String(place.id),
              label: place.name,
            })),
          )}
          {textInput("bought_on", t("admin.fieldPurchases.form.date"), boughtOn, setBoughtOn, {
            type: "date",
            max: todayInTunis(),
          })}
          {textInput(
            "supplier_reference",
            t("admin.fieldPurchases.form.supplierReference"),
            supplierReference,
            setSupplierReference,
          )}
          {select(
            "terms",
            t("admin.fieldPurchases.form.terms"),
            terms,
            (value) => setTerms(value as PaymentTermsEnum),
            TERMS.map((choice) => ({ value: choice, label: t(`admin.fieldPurchases.termsChoice.${choice}`) })),
          )}
          <div className="flex flex-col gap-1">
            {terms !== "cash" &&
              textInput("due_days", t("admin.fieldPurchases.form.dueDays"), dueDays, setDueDays, {
                type: "number",
                min: "0",
                max: "365",
              })}
            <p className="num text-[0.85rem] font-semibold text-ink-2" aria-live="polite">
              {t("admin.fieldPurchases.form.dueDate", { date: formatDate(due) })}
            </p>
          </div>
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.fieldPurchases.form.lines")}</CardTitle>
          {lines.map((line, index) => {
            const amount = amounts[index];
            const declared = parseDecimalInput(line.declared_quantity.trim(), 3);
            const received = parseDecimalInput(line.received_quantity.trim(), 3);
            const gap = declared && received ? subtract(received, declared) : null;
            return (
              <div
                key={line.key}
                role="group"
                aria-label={t("admin.fieldPurchases.form.lineNumber", { number: index + 1 })}
                className="grid grid-cols-[2fr_repeat(3,1fr)_auto] items-start gap-3 rounded-card border border-line p-3 max-[960px]:grid-cols-2"
              >
                <div className="flex flex-col gap-1 max-[960px]:col-span-2">
                  {select(
                    lineKey(index, "product"),
                    t("admin.fieldPurchases.form.product"),
                    line.product,
                    (value) => setLine(line.key, { product: value }),
                    productOptions,
                  )}
                  {!line.product && line.proposed_product && (
                    <p className="text-[0.85rem] font-semibold text-warn">
                      {t("admin.fieldPurchases.form.proposedProduct", { name: line.proposed_product })}{" "}
                      <button
                        type="button"
                        className="text-sea hover:underline"
                        onClick={() => setCreatingProduct(line.proposed_product)}
                      >
                        {t("admin.fieldPurchases.form.createProduct")}
                      </button>
                    </p>
                  )}
                </div>
                {textInput(
                  lineKey(index, "declared_quantity"),
                  t("admin.fieldPurchases.form.declared"),
                  line.declared_quantity,
                  (value) => setLine(line.key, { declared_quantity: value }),
                  { numeric: true },
                )}
                {textInput(
                  lineKey(index, "received_quantity"),
                  t("admin.fieldPurchases.form.received"),
                  line.received_quantity,
                  (value) => setLine(line.key, { received_quantity: value }),
                  { numeric: true, placeholder: line.declared_quantity },
                )}
                {textInput(
                  lineKey(index, "unit_cost"),
                  t("admin.fieldPurchases.form.cost"),
                  line.unit_cost,
                  (value) => setLine(line.key, { unit_cost: value }),
                  { numeric: true },
                )}
                <div className="flex items-end self-stretch max-[960px]:col-span-2 max-[960px]:justify-end">
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("admin.fieldPurchases.form.removeLine")}
                    title={t("admin.fieldPurchases.form.removeLine")}
                    onClick={() => setLines((current) => current.filter((other) => other.key !== line.key))}
                  >
                    <Icon name="trash" />
                  </Button>
                </div>
                {isOwner ? (
                  select(
                    lineKey(index, "partner"),
                    t("admin.fieldPurchases.form.partner"),
                    line.partner,
                    (value) => setLine(line.key, { partner: value }),
                    partnerOptions,
                    "col-span-2",
                  )
                ) : (
                  <span className="col-span-2 max-[960px]:hidden" />
                )}
                <p className="num self-end text-[0.85rem] text-ink-2" aria-live="polite">
                  {gap && !/^-?0\.000$/.test(gap) && (
                    <span className="font-semibold text-warn">
                      {t("admin.fieldPurchases.form.gap")} {formatQuantity(gap)}
                    </span>
                  )}
                </p>
                <p className="num col-span-2 self-end text-end font-semibold max-[960px]:col-span-1">
                  {amount?.owed ? formatMoney(amount.owed) : ""}
                </p>
              </div>
            );
          })}
          {errors.lines && <p className="text-[0.78rem] font-semibold text-bad">{errors.lines}</p>}
          <div>
            <Button
              onClick={() =>
                setLines((current) => [
                  ...current,
                  {
                    key: key(),
                    product: "",
                    proposed_product: "",
                    declared_quantity: "",
                    received_quantity: "",
                    unit_cost: "",
                    partner: NO_PARTNER,
                  },
                ])
              }
            >
              <Icon name="plus" />
              {t("admin.fieldPurchases.form.addLine")}
            </Button>
          </div>
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.fieldPurchases.form.payments")}</CardTitle>
          <p className="text-[0.85rem] text-ink-2">{t("admin.fieldPurchases.form.paymentsHint")}</p>
          <p className="font-semibold">{t("admin.fieldPurchases.form.givenNow")}</p>
          <div className="flex flex-wrap gap-2" role="group" aria-label={t("admin.fieldPurchases.form.givenNow")}>
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
          {payments.length === 0 && <p className="text-ink-2">{t("admin.fieldPurchases.form.noPayments")}</p>}
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
              {textInput(
                paymentKey(index, "amount"),
                t("admin.fieldPurchases.form.paymentAmount"),
                payment.amount,
                (value) => setPayment(payment.key, { amount: value }),
                { numeric: true },
              )}
              {textInput(
                paymentKey(index, "reference"),
                t("admin.fieldPurchases.form.reference"),
                payment.reference,
                (value) => setPayment(payment.key, { reference: value }),
              )}
              {textInput(
                paymentKey(index, "cash_on"),
                t("admin.fieldPurchases.form.cashOn"),
                payment.cash_on,
                (value) => setPayment(payment.key, { cash_on: value }),
                { type: "date", min: boughtOn },
              )}
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
          <div>
            <Button
              onClick={() =>
                setPayments((current) => [
                  ...current,
                  { key: key(), method: "cash", amount: "", reference: "", cash_on: "" },
                ])
              }
            >
              <Icon name="plus" />
              {t("admin.fieldPurchases.form.addPayment")}
            </Button>
          </div>
        </Card>

        <Card>
          <dl className="flex flex-wrap justify-end gap-x-8 gap-y-2">
            {declaredTotal !== total && (
              <div>
                <dt className="text-[0.78rem] font-semibold text-ink-2">
                  {t("admin.fieldPurchases.form.totalDeclared")}
                </dt>
                <dd className="num">{formatMoney(declaredTotal)}</dd>
              </div>
            )}
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.fieldPurchases.form.total")}</dt>
              <dd className="num font-bold">{formatMoney(total)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.fieldPurchases.form.paid")}</dt>
              <dd className="num">{formatMoney(paid)}</dd>
            </div>
            <div>
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.fieldPurchases.form.rest")}</dt>
              <dd className="num font-bold">{formatMoney(rest.startsWith("-") ? "0.000" : rest)}</dd>
            </div>
          </dl>
        </Card>

        <BoxCountsFields
          title={t("admin.fieldPurchases.form.boxesTitle")}
          hint={t("admin.fieldPurchases.form.boxesHint")}
          value={boxes}
          onChange={setBoxes}
          errors={errors}
        />

        <Card className="flex flex-col gap-4">
          <Field label={t("admin.fieldPurchases.form.driverNote")} htmlFor={id("notes")} error={errors.notes}>
            <textarea
              id={id("notes")}
              rows={2}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
            />
          </Field>
          {purchase && (
            <Field
              label={t("admin.fieldPurchases.form.officeNote")}
              htmlFor={id("office_note")}
              error={errors.office_note}
            >
              <textarea
                id={id("office_note")}
                rows={2}
                value={officeNote}
                onChange={(event) => setOfficeNote(event.target.value)}
                className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
              />
              <p className="mt-1 text-[0.8rem] text-ink-2">{t("admin.fieldPurchases.form.officeNoteHint")}</p>
            </Field>
          )}
        </Card>

        {(errors.detail || errors.revision) && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail ?? errors.revision}
          </p>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={() => leave("/achats/terrain")}>{t("admin.fieldPurchases.form.cancel")}</Button>
          {purchase && (
            <Button variant="danger" disabled={busy} onClick={() => setConfirming("refuse")}>
              {t("admin.fieldPurchases.form.refuse")}
            </Button>
          )}
          <Button type="submit" variant={purchase ? "secondary" : "primary"} disabled={busy}>
            {save.isPending && !confirming
              ? t("admin.fieldPurchases.form.saving")
              : t("admin.fieldPurchases.form.save")}
          </Button>
          {purchase && (
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => {
                if (payloadOf()) setConfirming("validate");
              }}
            >
              {t("admin.fieldPurchases.form.validate")}
            </Button>
          )}
        </div>
      </form>

      {purchase && (
        <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
          <DialogContent>
            {confirming === "validate" ? (
              <>
                <DialogTitle>{t("admin.fieldPurchases.form.validateTitle", { number: purchase.number })}</DialogTitle>
                <DialogDescription>
                  {t("admin.fieldPurchases.form.validateBody", {
                    kilos: formatQuantity(kilos),
                    total: formatMoney(total),
                    due: formatDate(due),
                    paid: formatMoney(paid),
                  })}
                </DialogDescription>
                <DialogFooter>
                  <DialogClose asChild>
                    <Button>{t("admin.fieldPurchases.form.cancel")}</Button>
                  </DialogClose>
                  <Button
                    variant="primary"
                    disabled={busy}
                    onClick={() => {
                      const payload = payloadOf();
                      if (payload) save.mutate({ payload, confirm: true });
                    }}
                  >
                    {save.isPending
                      ? t("admin.fieldPurchases.form.validating")
                      : t("admin.fieldPurchases.form.validate")}
                  </Button>
                </DialogFooter>
              </>
            ) : (
              <>
                <DialogTitle>{t("admin.fieldPurchases.form.refuseTitle", { number: purchase.number })}</DialogTitle>
                <DialogDescription>{t("admin.fieldPurchases.form.refuseBody")}</DialogDescription>
                <Field label={t("admin.fieldPurchases.form.refuseReason")} htmlFor={id("refusal")}>
                  <textarea
                    id={id("refusal")}
                    rows={3}
                    value={refusal}
                    onChange={(event) => setRefusal(event.target.value)}
                    className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
                  />
                </Field>
                <DialogFooter>
                  <DialogClose asChild>
                    <Button>{t("admin.fieldPurchases.form.cancel")}</Button>
                  </DialogClose>
                  <Button variant="danger" disabled={busy || refusal.trim() === ""} onClick={() => refuse.mutate()}>
                    {t("admin.fieldPurchases.form.refuse")}
                  </Button>
                </DialogFooter>
              </>
            )}
          </DialogContent>
        </Dialog>
      )}

      <Dialog open={creatingSupplier} onOpenChange={setCreatingSupplier}>
        {creatingSupplier && (
          <SupplierDialog
            start={
              purchase?.proposed_supplier
                ? { name: purchase.proposed_supplier, phone: purchase.proposed_supplier_phone }
                : undefined
            }
            onDone={(created) => {
              setCreatingSupplier(false);
              if (created) setSupplier(String(created.id));
            }}
          />
        )}
      </Dialog>
      <Dialog open={creatingProduct !== null} onOpenChange={(open) => !open && setCreatingProduct(null)}>
        {creatingProduct !== null && (
          <ProductDialog startName={creatingProduct} onDone={() => setCreatingProduct(null)} />
        )}
      </Dialog>
    </>
  );
}
