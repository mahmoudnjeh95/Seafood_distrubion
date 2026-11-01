import {
  bookLateAdjustments,
  type LotSettlementView,
  type PaymentMethodEnum,
  settleLot,
  useGetLotSettlement,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  MoneyInput,
  Pill,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useState } from "react";

import { CostSelect } from "../expenses/CostSelect";
import { PAYMENT_METHODS } from "../expenses/shared";
import { fieldErrors } from "../lib/errors";
import { canWriteResults, refreshLotResult, typed } from "../partnerships/shared";
import { remainingToPay } from "./settlement";

type Payment = { amount: string; method: PaymentMethodEnum; reference: string };

function Row({ label, amount, strong }: { label: string; amount: string; strong?: boolean }) {
  return (
    <div className={`flex items-baseline gap-3 px-2.5 py-1.5 ${strong ? "border-t border-line font-bold" : ""}`}>
      <span className="me-auto">{label}</span>
      <span className="num whitespace-nowrap">{formatMoney(amount)}</span>
    </div>
  );
}

function Balance({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className="num font-semibold">{children}</dd>
    </div>
  );
}

/** The payments of a settlement: one or more lines whose amounts must add up to the total to pay. */
function SettleDialog({ view, number, onDone }: { view: LotSettlementView; number: string; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  const total = view.preview?.total ?? "0.000";
  const [payments, setPayments] = useState<Payment[]>(
    total === "0.000" ? [] : [{ amount: typed(total), method: "cash", reference: "" }],
  );
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const settle = useMutation({
    mutationFn: () =>
      settleLot(view.batch_id, {
        payments: payments.map((payment) => ({
          amount: parseDecimalInput(payment.amount.trim(), 3) ?? "",
          method: payment.method,
          reference: payment.reference.trim(),
        })),
        notes: notes.trim(),
      }),
    onSuccess: async () => {
      toast.success(t("admin.settlement.settledToast"));
      await refreshLotResult(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.settlement.settleError") });
    },
  });
  const remaining = remainingToPay(
    total,
    payments.map((payment) => parseDecimalInput(payment.amount.trim(), 3) ?? payment.amount.trim()),
  );
  function change(index: number, patch: Partial<Payment>) {
    setPayments((current) => current.map((payment, at) => (at === index ? { ...payment, ...patch } : payment)));
  }
  return (
    <DialogContent className="w-[min(560px,calc(100vw-2rem))]">
      <DialogTitle>{t("admin.settlement.dialogTitle", { number, name: view.partner_name })}</DialogTitle>
      <DialogDescription>{t("admin.settlement.dialogDescription")}</DialogDescription>
      <form
        id={formId}
        noValidate
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setErrors({});
          settle.mutate();
        }}
      >
        <p className="font-semibold">
          {t("admin.settlement.total")} : <span className="num">{formatMoney(total)}</span>
          {remaining !== null && remaining !== "0.000" && (
            <span className="ms-3 text-[0.88rem] font-normal text-warn">
              {t("admin.settlement.remaining")} : <span className="num">{formatMoney(remaining)}</span>
            </span>
          )}
        </p>
        {payments.map((payment, index) => (
          <div key={index} className="grid grid-cols-3 items-end gap-3 max-[720px]:grid-cols-1">
            <Field label={t("admin.settlement.amount")} htmlFor={`${formId}-amount-${index}`}>
              <MoneyInput
                id={`${formId}-amount-${index}`}
                inputMode="decimal"
                className="num"
                value={payment.amount}
                onChange={(event) => change(index, { amount: event.target.value })}
                autoComplete="off"
              />
            </Field>
            <CostSelect
              id={`${formId}-method-${index}`}
              label={t("admin.settlement.method")}
              value={payment.method}
              onChange={(value) => change(index, { method: value as PaymentMethodEnum })}
              options={PAYMENT_METHODS.map((value) => ({ value, label: t(`admin.expenses.methods.${value}`) }))}
              placeholder={t("admin.settlement.choose")}
            />
            <div className="flex items-end gap-2">
              <Field label={t("admin.settlement.reference")} htmlFor={`${formId}-ref-${index}`}>
                <Input
                  id={`${formId}-ref-${index}`}
                  value={payment.reference}
                  onChange={(event) => change(index, { reference: event.target.value })}
                  autoComplete="off"
                />
              </Field>
              <Button type="button" onClick={() => setPayments((current) => current.filter((_, at) => at !== index))}>
                {t("admin.settlement.removePayment")}
              </Button>
            </div>
          </div>
        ))}
        <div>
          <Button
            type="button"
            onClick={() => setPayments((current) => [...current, { amount: "", method: "cash", reference: "" }])}
          >
            {t("admin.settlement.addPayment")}
          </Button>
        </div>
        <Field label={t("admin.settlement.notes")} htmlFor={`${formId}-notes`}>
          <Input id={`${formId}-notes`} value={notes} onChange={(event) => setNotes(event.target.value)} />
        </Field>
      </form>
      {(errors.payments || errors.detail) && (
        <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
          {errors.payments ?? errors.detail}
        </p>
      )}
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.settlement.back")}</Button>
        <Button type="submit" form={formId} variant="primary" disabled={settle.isPending}>
          {settle.isPending ? t("admin.settlement.saving") : t("admin.settlement.confirm")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** "Règlement du partenaire" (P6-T03, D-066): on a closed partnership lot, what the partner is paid (capital
 * back ± share), the costs that arrived after the closing, and the partner's three separate balances. A lot
 * without partner, or not closed yet, shows nothing. The owner settles; the accountant reads. */
export function SettlementCard({ batchId, number, session }: { batchId: number; number: string; session: Session }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const view = useGetLotSettlement(batchId, { query: { enabled: Number.isInteger(batchId) && batchId > 0 } });
  const [open, setOpen] = useState(false);
  const canWrite = canWriteResults(session);
  const book = useMutation({
    mutationFn: () => bookLateAdjustments(batchId),
    onSuccess: async () => {
      toast.success(t("admin.settlement.late.booked"));
      await refreshLotResult(queryClient);
    },
    onError: () => toast.error(t("admin.settlement.late.error")),
  });
  const data = view.data;
  if (view.isPending || !data || data.state === "none" || data.state === "not_closed") {
    return view.isError ? (
      <p role="alert" className="text-bad">
        {t("admin.settlement.loadError")}
      </p>
    ) : null;
  }
  const preview = data.preview;
  const settlement = data.settlement;
  const late = data.late;
  const hasLate = late !== null && late.pending_basis !== "0.000";
  return (
    <section aria-labelledby="lot-settlement" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="lot-settlement" className="me-auto">
          {t("admin.settlement.title")}
        </h2>
        {canWrite && data.state === "ready" && (
          <Button variant="primary" onClick={() => setOpen(true)}>
            {t("admin.settlement.settle")}
          </Button>
        )}
      </div>
      <Card className="flex flex-col gap-4 p-4">
        {data.state === "ready" && preview && (
          <div className="flex flex-col">
            <p className="px-2.5 pb-2 text-[0.88rem] text-ink-2">{t("admin.settlement.readyHint")}</p>
            <Row label={t("admin.settlement.capitalBack")} amount={preview.capital_to_return} />
            {Number(preview.lot_share) > 0 && <Row label={t("admin.settlement.share")} amount={preview.lot_share} />}
            {Number(preview.lot_share) < 0 && (
              <Row label={t("admin.settlement.lossShare")} amount={preview.lot_share} />
            )}
            {Number(preview.uncovered_loss) > 0 && (
              <Row label={t("admin.settlement.uncoveredLoss")} amount={`-${preview.uncovered_loss}`} />
            )}
            {Number(preview.pending_adjustments) !== 0 && (
              <Row label={t("admin.settlement.pendingAdjustments")} amount={preview.pending_adjustments} />
            )}
            {Number(preview.carried_in) !== 0 && (
              <Row label={t("admin.settlement.carriedIn")} amount={preview.carried_in} />
            )}
            <Row label={t("admin.settlement.total")} amount={preview.total} strong />
            {Number(preview.carried_out) !== 0 && (
              <Row label={t("admin.settlement.carriedOut")} amount={preview.carried_out} />
            )}
          </div>
        )}
        {data.state === "settled" && settlement && (
          <div className="flex flex-col gap-2">
            <Pill tone="good">{t("admin.settlement.settledOn", { date: formatDate(settlement.settled_on) })}</Pill>
            <div className="flex flex-col">
              <Row label={t("admin.settlement.capitalBack")} amount={settlement.capital_returned} />
              <Row label={t("admin.settlement.share")} amount={settlement.share_paid} />
              <Row label={t("admin.settlement.paid")} amount={settlement.amount_paid} strong />
            </div>
            <ul className="flex flex-col gap-1 text-[0.88rem] text-ink-2">
              {settlement.payments.map((payment, index) => (
                <li key={index}>
                  {formatDate(payment.paid_on)} · {t(`admin.expenses.methods.${payment.method}`)} ·{" "}
                  <span className="num">{formatMoney(payment.amount)}</span>
                  {payment.reference && ` · ${payment.reference}`}
                </li>
              ))}
            </ul>
          </div>
        )}
        {hasLate && late && (
          <div className="flex flex-col gap-2 rounded-chip bg-warn-soft px-3 py-2 text-[0.88rem] text-warn">
            <p className="font-semibold">{t("admin.settlement.late.title")}</p>
            <p>
              {t("admin.settlement.late.text", {
                drift: formatMoney(late.drift),
                share: formatMoney(late.pending_share),
              })}
            </p>
            {canWrite && (
              <div>
                <Button onClick={() => book.mutate()} disabled={book.isPending}>
                  {t("admin.settlement.late.book")}
                </Button>
              </div>
            )}
          </div>
        )}
        {data.balances && (
          <div className="flex flex-col gap-2">
            <h3 className="text-[0.95rem]">{t("admin.settlement.balances.title", { name: data.partner_name })}</h3>
            <dl className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(10rem,1fr))]">
              <Balance label={t("admin.settlement.balances.tradePayable")}>
                {formatMoney(data.balances.trade_payable)}
              </Balance>
              <Balance label={t("admin.settlement.balances.capital")}>{formatMoney(data.balances.capital)}</Balance>
              <Balance label={t("admin.settlement.balances.profitShare")}>
                {formatMoney(data.balances.profit_share)}
              </Balance>
            </dl>
          </div>
        )}
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        {open && <SettleDialog view={data} number={number} onDone={() => setOpen(false)} />}
      </Dialog>
    </section>
  );
}
