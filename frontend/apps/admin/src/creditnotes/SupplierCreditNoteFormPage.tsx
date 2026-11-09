import {
  createSupplierCreditNote,
  type CreditableLine,
  type SupplierCreditKindEnum,
  type SupplierCreditNoteLineWrite,
  type SupplierCreditNoteWrite,
  useListCreditableReceiptLines,
  useListLocations,
  useListSuppliers,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Field,
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
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { Link, Navigate, useNavigate, useOutletContext, useSearchParams } from "react-router";

import { fieldErrors } from "../lib/errors";
import { idFrom, refreshPurchasing } from "../purchasing/shared";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";

const NONE = "none";
type Choice = SupplierCreditKindEnum | typeof NONE;
type Row = { kind: Choice; quantity: string; unitAmount: string; location: string };
type Errors = Record<string, string>;

const EMPTY: Row = { kind: NONE, quantity: "", unitAmount: "", location: "" };

/** What a line proposes when its motif is chosen: the weight gap, the kilos accepted, or all the invoiced kilos. */
function proposed(line: CreditableLine, kind: Choice): string {
  if (kind === "weight") return line.weight_gap;
  if (kind === "return") return "";
  if (kind === "price") return line.invoiced_quantity;
  return "";
}

/** A new avoir fournisseur (D-300): per receipt line of the supplier, a return, a weight gap or a price cut. */
export function SupplierCreditNoteFormPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const formId = useId();
  const [params] = useSearchParams();
  const invoiceId = idFrom(params.get("facture"));
  const motif = params.get("motif");
  const [supplier, setSupplier] = useState(params.get("fournisseur") ?? "");
  const [creditedOn, setCreditedOn] = useState(todayInTunis());
  const [reason, setReason] = useState("");
  const [supplierReference, setSupplierReference] = useState("");
  const [rows, setRows] = useState<Record<number, Row>>({});
  const [errors, setErrors] = useState<Errors>({});
  const suppliers = useListSuppliers({ status: "all" });
  const locations = useListLocations({ status: "all" });
  const lines = useListCreditableReceiptLines(
    { supplier: Number(supplier), ...(invoiceId ? { invoice: invoiceId } : {}) },
    { query: { enabled: supplier !== "" } },
  );
  const shown = (lines.data ?? []).filter((line) => motif !== "weight" || Number(line.weight_gap) > 0);

  const save = useMutation({
    mutationFn: (body: SupplierCreditNoteWrite) => createSupplierCreditNote(body),
    onSuccess: async (note) => {
      toast.success(t("admin.creditNotes.form.saved", { number: note.number }));
      await refreshPurchasing(queryClient);
      void navigate(`/achats/avoirs/${note.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.creditNotes.form.error") });
    },
  });

  if (!canRecordReceipts(session)) return <Navigate to="/achats/avoirs" replace />;

  const rowOf = (lineId: number): Row => rows[lineId] ?? EMPTY;
  const update = (line: CreditableLine, change: Partial<Row>) =>
    setRows((current) => {
      const before = current[line.receipt_line_id] ?? EMPTY;
      const next = { ...before, ...change };
      if (change.kind && change.kind !== before.kind) next.quantity = proposed(line, change.kind);
      return { ...current, [line.receipt_line_id]: next };
    });
  const picked = shown.filter((line) => rowOf(line.receipt_line_id).kind !== NONE);

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    if (!supplier) found.supplier = t("admin.creditNotes.form.required");
    if (!reason.trim()) found.reason = t("admin.creditNotes.form.required");
    if (picked.length === 0) found.lines = t("admin.creditNotes.form.noLine");
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    // The server reports a line's errors by its index in `lines`; the page shows them on that row.
    const sent: SupplierCreditNoteLineWrite[] = picked.map((line) => {
      const row = rowOf(line.receipt_line_id);
      return {
        receipt_line: line.receipt_line_id,
        kind: row.kind as SupplierCreditKindEnum,
        quantity: row.quantity.replace(",", "."),
        unit_amount: row.kind === "price" ? row.unitAmount.replace(",", ".") : "",
        from_location: row.kind === "return" && row.location ? Number(row.location) : null,
      };
    });
    save.mutate({
      supplier: Number(supplier),
      invoice: invoiceId,
      credited_on: creditedOn,
      reason: reason.trim(),
      supplier_reference: supplierReference.trim(),
      lines: sent,
    });
  }

  const id = (name: string) => `${formId}-${name}`;
  const lineError = (line: CreditableLine, field: string) => {
    const index = picked.findIndex((one) => one.receipt_line_id === line.receipt_line_id);
    return index < 0 ? undefined : errors[`lines.${index}.${field}`];
  };

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.creditNotes.form.title")} />
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <Field label={t("admin.creditNotes.columns.supplier")} htmlFor={id("supplier")} error={errors.supplier}>
            <Select
              value={supplier}
              disabled={invoiceId !== null}
              onValueChange={(value) => {
                setSupplier(value);
                setRows({});
              }}
            >
              <SelectTrigger id={id("supplier")}>
                <SelectValue placeholder={t("admin.creditNotes.form.choose")} />
              </SelectTrigger>
              <SelectContent>
                {(suppliers.data ?? [])
                  .filter((one) => one.is_active || String(one.id) === supplier)
                  .map((one) => (
                    <SelectItem key={one.id} value={String(one.id)}>
                      {one.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("admin.creditNotes.columns.date")} htmlFor={id("date")} error={errors.credited_on}>
            <Input
              id={id("date")}
              type="date"
              max={todayInTunis()}
              value={creditedOn}
              onChange={(event) => setCreditedOn(event.target.value)}
            />
          </Field>
          <Field
            label={t("admin.creditNotes.form.supplierReference")}
            htmlFor={id("reference")}
            error={errors.supplier_reference}
          >
            <Input
              id={id("reference")}
              value={supplierReference}
              maxLength={50}
              onChange={(event) => setSupplierReference(event.target.value)}
              autoComplete="off"
            />
          </Field>
          <Field label={t("admin.creditNotes.form.reason")} htmlFor={id("reason")} error={errors.reason}>
            <Input id={id("reason")} value={reason} onChange={(event) => setReason(event.target.value)} />
          </Field>
        </Card>

        <Card className="p-2">
          <CardTitle className="px-2.5 pt-2">{t("admin.creditNotes.form.lines")}</CardTitle>
          <p className="px-2.5 text-[0.88rem] text-ink-2">{t("admin.creditNotes.form.linesHint")}</p>
          {errors.lines && (
            <p role="alert" className="px-2.5 text-[0.88rem] font-semibold text-bad">
              {errors.lines}
            </p>
          )}
          {supplier === "" ? (
            <p className="p-2.5 text-ink-2">{t("admin.creditNotes.form.pickSupplier")}</p>
          ) : lines.isPending ? (
            <p className="p-2.5 text-ink-2">{t("common.loading")}</p>
          ) : shown.length === 0 ? (
            <p className="p-2.5 text-ink-2">{t("admin.creditNotes.form.nothing")}</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.creditNotes.form.receipt")}</Th>
                  <Th>{t("admin.creditNotes.form.lot")}</Th>
                  <Th numeric>{t("admin.creditNotes.form.invoicedAccepted")}</Th>
                  <Th>{t("admin.creditNotes.form.kind")}</Th>
                  <Th>{t("admin.creditNotes.form.quantity")}</Th>
                  <Th>{t("admin.creditNotes.form.detail")}</Th>
                </tr>
              </thead>
              <tbody>
                {shown.map((line) => {
                  const row = rowOf(line.receipt_line_id);
                  const error =
                    lineError(line, "receipt_line") ??
                    lineError(line, "kind") ??
                    lineError(line, "quantity") ??
                    lineError(line, "unit_amount") ??
                    lineError(line, "from_location");
                  return (
                    <tr key={line.receipt_line_id}>
                      <Td className="num whitespace-nowrap">
                        {line.receipt_number}
                        <div className="text-[0.8rem] text-ink-2">
                          {formatDate(line.received_on)}
                          {line.invoice_number && ` · ${line.invoice_number}`}
                        </div>
                      </Td>
                      <Td>
                        {line.product_name}
                        <div className="num text-[0.8rem] text-ink-2">
                          {line.batch_number} · {formatMoney(line.unit_cost)} / kg
                        </div>
                      </Td>
                      <Td numeric className="whitespace-nowrap">
                        {formatQuantity(line.invoiced_quantity)} / {formatQuantity(line.accepted_quantity)}
                        {Number(line.weight_gap) > 0 && (
                          <div className="text-[0.8rem] font-semibold text-warn">
                            {t("admin.creditNotes.form.gap", { quantity: formatQuantity(line.weight_gap) })}
                          </div>
                        )}
                      </Td>
                      <Td>
                        <Select value={row.kind} onValueChange={(value) => update(line, { kind: value as Choice })}>
                          <SelectTrigger aria-label={t("admin.creditNotes.form.kind")}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={NONE}>{t("admin.creditNotes.kinds.none")}</SelectItem>
                            <SelectItem value="return">{t("admin.creditNotes.kinds.return")}</SelectItem>
                            {Number(line.weight_gap) > 0 && (
                              <SelectItem value="weight">{t("admin.creditNotes.kinds.weight")}</SelectItem>
                            )}
                            <SelectItem value="price">{t("admin.creditNotes.kinds.price")}</SelectItem>
                          </SelectContent>
                        </Select>
                      </Td>
                      <Td>
                        {row.kind !== NONE && (
                          <Input
                            inputMode="decimal"
                            aria-label={t("admin.creditNotes.form.quantity")}
                            value={row.quantity}
                            onChange={(event) => update(line, { quantity: event.target.value })}
                            className="w-28"
                          />
                        )}
                      </Td>
                      <Td>
                        {row.kind === "price" && (
                          <Input
                            inputMode="decimal"
                            aria-label={t("admin.creditNotes.form.unitAmount")}
                            placeholder={t("admin.creditNotes.form.unitAmount")}
                            value={row.unitAmount}
                            onChange={(event) => update(line, { unitAmount: event.target.value })}
                            className="w-32"
                          />
                        )}
                        {row.kind === "return" && (
                          <Select value={row.location} onValueChange={(value) => update(line, { location: value })}>
                            <SelectTrigger aria-label={t("admin.creditNotes.form.fromLocation")}>
                              <SelectValue placeholder={t("admin.creditNotes.form.fromLocation")} />
                            </SelectTrigger>
                            <SelectContent>
                              {(locations.data ?? [])
                                .filter((one) => one.is_active)
                                .map((one) => (
                                  <SelectItem key={one.id} value={String(one.id)}>
                                    {one.name}
                                  </SelectItem>
                                ))}
                            </SelectContent>
                          </Select>
                        )}
                        {error && <p className="pt-1 text-[0.8rem] font-semibold text-bad">{error}</p>}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card>

        {errors.detail && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail}
          </p>
        )}
        <p className="text-end text-[0.85rem] text-ink-2">{t("admin.creditNotes.form.finalHint")}</p>
        <div className="flex flex-wrap justify-end gap-2">
          <Button asChild>
            <Link to={invoiceId ? `/achats/factures/${invoiceId}` : "/achats/avoirs"}>
              {t("admin.creditNotes.form.cancel")}
            </Link>
          </Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending ? t("admin.creditNotes.form.saving") : t("admin.creditNotes.form.save")}
          </Button>
        </div>
      </form>
    </>
  );
}
