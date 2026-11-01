import {
  createPurchaseOrder,
  type LastCost,
  type OrderWrite,
  useListLastPurchaseCosts,
  useListProducts,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
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
import { Navigate, useOutletContext, useSearchParams } from "react-router";

import { lineTotal, sum } from "../lib/decimal";
import { useLeave } from "../lib/embedded";
import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
import { idFrom } from "../purchasing/shared";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";
import { refreshOrders } from "./shared";

type LineField = "product" | "ordered_quantity" | "unit_cost";
type Line = Record<LineField, string> & {
  key: number;
  // Once a person types a price, the form stops filling in the last one.
  costTouched: boolean;
};
type Errors = Record<string, string>;

// Gives each line a stable React key, also for lines not saved yet.
let nextKey = 0;
function newLine(): Line {
  nextKey += 1;
  return { key: nextKey, product: "", ordered_quantity: "", unit_cost: "", costTouched: false };
}

// The API writes "20.250"; people here write "20,250". Both are read back by parseDecimalInput.
const asTyped = (value: string) => value.replace(".", ",");

const lineKey = (index: number, field: string) => `lines.${index}.${field}`;

/** Record a purchase order (commande d'achat): what a supplier is asked to deliver, at what price. */
export function PurchaseOrderFormPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { leave } = useLeave();
  const queryClient = useQueryClient();
  const formId = useId();
  const [params] = useSearchParams();

  // Archived ones leave the pickers unless this order already uses them (pickable).
  const suppliers = useListSuppliers({ status: "all" });
  const products = useListProducts({ status: "all" });

  const [supplier, setSupplier] = useState(() => String(idFrom(params.get("fournisseur")) ?? ""));
  const [orderedOn, setOrderedOn] = useState(todayInTunis);
  const [expectedOn, setExpectedOn] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>(() => [newLine()]);
  const [errors, setErrors] = useState<Errors>({});

  const lastCosts = useListLastPurchaseCosts({ supplier: Number(supplier) }, { query: { enabled: supplier !== "" } });
  const lastCostOf = useMemo(() => {
    const byProduct = new Map<string, LastCost>();
    for (const cost of lastCosts.data ?? []) byProduct.set(String(cost.product_id), cost);
    return byProduct;
  }, [lastCosts.data]);

  // Until a price is typed, the line shows the last cost paid to this supplier for the product.
  const costOf = (line: Line): string => {
    if (line.costTouched) return line.unit_cost;
    const last = lastCostOf.get(line.product);
    return last ? asTyped(last.unit_cost) : "";
  };

  const setLine = (key: number, change: (line: Line) => Partial<Line>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...change(line) } : line)));

  const save = useMutation({
    mutationFn: (payload: OrderWrite) => createPurchaseOrder(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.purchaseOrders.form.created", { number: saved.number }));
      await refreshOrders(queryClient);
      leave(`/achats/bons/${saved.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.purchaseOrders.form.error") });
    },
  });

  if (!canRecordReceipts(session)) return <Navigate to="/achats/bons" replace />;

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!supplier) found.supplier = t("admin.purchaseOrders.form.required");
    if (!orderedOn) found.ordered_on = t("admin.purchaseOrders.form.required");
    if (lines.length === 0) found.lines = t("admin.purchaseOrders.form.noLines");
    const payloadLines: OrderWrite["lines"] = [];
    lines.forEach((line, index) => {
      if (!line.product) found[lineKey(index, "product")] = t("admin.purchaseOrders.form.required");
      const quantity = parseDecimalInput(line.ordered_quantity.trim(), 3);
      if (quantity === null || quantity.startsWith("-") || /^0+(\.0+)?$/.test(quantity)) {
        found[lineKey(index, "ordered_quantity")] = t("admin.purchaseOrders.form.weight");
      }
      const cost = parseDecimalInput(costOf(line).trim(), 3);
      if (cost === null || cost.startsWith("-")) {
        found[lineKey(index, "unit_cost")] = t("admin.purchaseOrders.form.money");
      }
      payloadLines.push({
        product: Number(line.product),
        ordered_quantity: quantity ?? "",
        unit_cost: cost ?? "",
      });
    });
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    save.mutate({
      supplier: Number(supplier),
      ordered_on: orderedOn,
      expected_on: expectedOn || null,
      notes: notes.trim(),
      lines: payloadLines,
    });
  }

  // Amounts of the lines whose weight and price are already readable.
  const amounts = lines.map((line) => {
    const quantity = parseDecimalInput(line.ordered_quantity.trim(), 3);
    const cost = parseDecimalInput(costOf(line).trim(), 3);
    return quantity && cost ? lineTotal(quantity, cost) : null;
  });
  const total = sum(amounts.flatMap((amount) => (amount ? [amount] : [])));

  function lastCostHint(line: Line): string | null {
    if (!supplier || !line.product) return null;
    const last = lastCostOf.get(line.product);
    if (!last) return lastCosts.data ? t("admin.purchaseOrders.form.noLastCost") : null;
    return t("admin.purchaseOrders.form.lastCost", {
      cost: formatMoney(last.unit_cost),
      date: formatDate(last.received_on),
    });
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
          <SelectValue placeholder={t("admin.purchaseOrders.form.choose")} />
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

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.purchaseOrders.form.title")} />

      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-3 gap-4 max-[960px]:grid-cols-1">
          {select(
            "supplier",
            t("admin.purchaseOrders.form.supplier"),
            supplier,
            setSupplier,
            pickable(suppliers.data ?? [], [supplier]).map((one) => ({ value: String(one.id), label: one.name })),
          )}
          <Field label={t("admin.purchaseOrders.form.date")} htmlFor={id("ordered_on")} error={errors.ordered_on}>
            <Input
              id={id("ordered_on")}
              type="date"
              max={todayInTunis()}
              value={orderedOn}
              onChange={(event) => setOrderedOn(event.target.value)}
              aria-invalid={errors.ordered_on ? true : undefined}
            />
          </Field>
          <Field label={t("admin.purchaseOrders.form.expected")} htmlFor={id("expected_on")} error={errors.expected_on}>
            <Input
              id={id("expected_on")}
              type="date"
              min={orderedOn}
              value={expectedOn}
              onChange={(event) => setExpectedOn(event.target.value)}
              aria-invalid={errors.expected_on ? true : undefined}
            />
          </Field>
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.purchaseOrders.form.lines")}</CardTitle>
          {lines.map((line, index) => {
            const hint = lastCostHint(line);
            const amount = amounts[index];
            const input = (field: LineField, label: string, onChange: (value: string) => void) => {
              const Control = field === "unit_cost" ? MoneyInput : Input;
              return (
                <Field label={label} htmlFor={id(lineKey(index, field))} error={errors[lineKey(index, field)]}>
                  <Control
                    id={id(lineKey(index, field))}
                    inputMode="decimal"
                    value={field === "unit_cost" ? costOf(line) : line[field]}
                    onChange={(event) => onChange(event.target.value)}
                    aria-invalid={errors[lineKey(index, field)] ? true : undefined}
                    autoComplete="off"
                    className="num"
                  />
                </Field>
              );
            };
            return (
              <div
                key={line.key}
                role="group"
                aria-label={t("admin.purchaseOrders.form.lineNumber", { number: index + 1 })}
                className="grid grid-cols-[2fr_1fr_1fr_auto] items-start gap-3 rounded-card border border-line p-3 max-[960px]:grid-cols-2"
              >
                {select(
                  lineKey(index, "product"),
                  t("admin.purchaseOrders.form.product"),
                  line.product,
                  (value) => setLine(line.key, () => ({ product: value })),
                  pickable(
                    products.data ?? [],
                    lines.map((item) => item.product),
                  ).map((product) => ({
                    value: String(product.id),
                    label: `${product.name} · ${product.reference}`,
                  })),
                  "max-[960px]:col-span-2",
                )}
                {input("ordered_quantity", t("admin.purchaseOrders.form.quantity"), (value) =>
                  setLine(line.key, () => ({ ordered_quantity: value })),
                )}
                {input("unit_cost", t("admin.purchaseOrders.form.cost"), (value) =>
                  setLine(line.key, () => ({ unit_cost: value, costTouched: true })),
                )}
                <div className="flex items-end self-stretch max-[960px]:col-span-2 max-[960px]:justify-end">
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("admin.purchaseOrders.form.removeLine")}
                    title={t("admin.purchaseOrders.form.removeLine")}
                    onClick={() => setLines((current) => current.filter((other) => other.key !== line.key))}
                  >
                    <Icon name="trash" />
                  </Button>
                </div>
                <p className="col-span-2 self-end text-[0.85rem] text-ink-2 max-[960px]:col-span-2" aria-live="polite">
                  {hint}
                </p>
                <p className="num col-span-2 self-end text-end font-semibold max-[960px]:col-span-2">
                  {amount ? formatMoney(amount) : ""}
                </p>
              </div>
            );
          })}
          {errors.lines && <p className="text-[0.78rem] font-semibold text-bad">{errors.lines}</p>}
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
            <Button onClick={() => setLines((current) => [...current, newLine()])}>
              <Icon name="plus" />
              {t("admin.purchaseOrders.form.addLine")}
            </Button>
            <dl className="ms-auto">
              <dt className="text-[0.78rem] font-semibold text-ink-2">{t("admin.purchaseOrders.form.total")}</dt>
              <dd className="num font-bold">{formatMoney(total)}</dd>
            </dl>
          </div>
        </Card>

        <Card>
          <Field label={t("admin.purchaseOrders.form.notes")} htmlFor={id("notes")} error={errors.notes}>
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
          <Button onClick={() => leave("/achats/bons")}>{t("admin.purchaseOrders.form.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? t("admin.purchaseOrders.form.saving") : t("admin.purchaseOrders.form.save")}
          </Button>
        </div>
      </form>
    </>
  );
}
