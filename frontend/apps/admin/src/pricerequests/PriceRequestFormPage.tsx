import { createPriceRequest, type PriceRequestWrite, useListProducts, useListSuppliers } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
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
import { type FormEvent, useId, useState } from "react";
import { Navigate, useOutletContext } from "react-router";

import { useLeave } from "../lib/embedded";
import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";
import { refreshPriceRequests } from "./shared";

type Line = { key: number; product: string; quantity: string };
type Errors = Record<string, string>;

let nextKey = 0;
function newLine(): Line {
  nextKey += 1;
  return { key: nextKey, product: "", quantity: "" };
}

const lineKey = (index: number, field: string) => `lines.${index}.${field}`;

/** A new price request (D-289): the products and kilos, and the suppliers asked. */
export function PriceRequestFormPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { leave } = useLeave();
  const queryClient = useQueryClient();
  const formId = useId();

  const suppliers = useListSuppliers({ status: "active" });
  const products = useListProducts({ status: "active" });
  const [requestedOn, setRequestedOn] = useState(todayInTunis);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>(() => [newLine()]);
  const [errors, setErrors] = useState<Errors>({});

  const save = useMutation({
    mutationFn: (payload: PriceRequestWrite) => createPriceRequest(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.priceRequests.form.created", { number: saved.number }));
      await refreshPriceRequests(queryClient);
      leave(`/achats/demandes/${saved.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.priceRequests.form.error") });
    },
  });

  if (!canRecordReceipts(session)) return <Navigate to="/achats/demandes" replace />;

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (chosen.size === 0) found.suppliers = t("admin.priceRequests.form.noSupplier");
    if (lines.length === 0) found.lines = t("admin.priceRequests.form.noLines");
    const payloadLines: PriceRequestWrite["lines"] = [];
    lines.forEach((line, index) => {
      if (!line.product) found[lineKey(index, "product")] = t("admin.priceRequests.form.required");
      const quantity = parseDecimalInput(line.quantity.trim(), 3);
      if (quantity === null || quantity.startsWith("-") || /^0+(\.0+)?$/.test(quantity)) {
        found[lineKey(index, "quantity")] = t("admin.priceRequests.form.weight");
      }
      payloadLines.push({ product: Number(line.product), quantity: quantity ?? "" });
    });
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    save.mutate({ requested_on: requestedOn, suppliers: [...chosen], lines: payloadLines, notes: notes.trim() });
  }

  const id = (name: string) => `${formId}-${name}`;
  const setLine = (key: number, change: Partial<Line>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...change } : line)));

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.priceRequests.form.title")} />
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-3 gap-4 max-[960px]:grid-cols-1">
          <Field label={t("admin.priceRequests.form.date")} htmlFor={id("requested_on")} error={errors.requested_on}>
            <Input
              id={id("requested_on")}
              type="date"
              max={todayInTunis()}
              value={requestedOn}
              onChange={(event) => setRequestedOn(event.target.value)}
            />
          </Field>
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.priceRequests.form.suppliers")}</CardTitle>
          <p className="text-[0.85rem] text-ink-2">{t("admin.priceRequests.form.suppliersHint")}</p>
          <div
            role="group"
            aria-label={t("admin.priceRequests.form.suppliers")}
            className="flex flex-wrap gap-x-6 gap-y-2"
          >
            {(suppliers.data ?? []).map((supplier) => (
              <label key={supplier.id} className="flex items-center gap-2 text-[0.9rem]">
                <input
                  type="checkbox"
                  className="size-4 accent-coral"
                  checked={chosen.has(supplier.id)}
                  onChange={(event) =>
                    setChosen((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(supplier.id);
                      else next.delete(supplier.id);
                      return next;
                    })
                  }
                />
                {supplier.name}
              </label>
            ))}
          </div>
          {errors.suppliers && <p className="text-[0.78rem] font-semibold text-bad">{errors.suppliers}</p>}
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle className="mb-0">{t("admin.priceRequests.form.lines")}</CardTitle>
          {lines.map((line, index) => (
            <div
              key={line.key}
              role="group"
              aria-label={t("admin.priceRequests.form.lineNumber", { number: index + 1 })}
              className="grid grid-cols-[2fr_1fr_auto] items-start gap-3 rounded-card border border-line p-3 max-[700px]:grid-cols-1"
            >
              <Field
                label={t("admin.priceRequests.form.product")}
                htmlFor={id(lineKey(index, "product"))}
                error={errors[lineKey(index, "product")]}
              >
                <Select value={line.product} onValueChange={(value) => setLine(line.key, { product: value })}>
                  <SelectTrigger id={id(lineKey(index, "product"))}>
                    <SelectValue placeholder={t("admin.priceRequests.form.choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {pickable(
                      products.data ?? [],
                      lines.map((item) => item.product),
                    ).map((product) => (
                      <SelectItem key={product.id} value={String(product.id)}>
                        {`${product.name} · ${product.reference}`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field
                label={t("admin.priceRequests.form.quantity")}
                htmlFor={id(lineKey(index, "quantity"))}
                error={errors[lineKey(index, "quantity")]}
              >
                <Input
                  id={id(lineKey(index, "quantity"))}
                  inputMode="decimal"
                  className="num"
                  autoComplete="off"
                  value={line.quantity}
                  onChange={(event) => setLine(line.key, { quantity: event.target.value })}
                />
              </Field>
              <div className="flex items-end self-stretch">
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t("admin.priceRequests.form.removeLine")}
                  title={t("admin.priceRequests.form.removeLine")}
                  onClick={() => setLines((current) => current.filter((other) => other.key !== line.key))}
                >
                  <Icon name="trash" />
                </Button>
              </div>
            </div>
          ))}
          {errors.lines && <p className="text-[0.78rem] font-semibold text-bad">{errors.lines}</p>}
          <div>
            <Button onClick={() => setLines((current) => [...current, newLine()])}>
              <Icon name="plus" />
              {t("admin.priceRequests.form.addLine")}
            </Button>
          </div>
        </Card>

        <Card>
          <Field label={t("admin.priceRequests.form.notes")} htmlFor={id("notes")}>
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
          <Button onClick={() => leave("/achats/demandes")}>{t("admin.priceRequests.form.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.priceRequests.form.save")}
          </Button>
        </div>
      </form>
    </>
  );
}
