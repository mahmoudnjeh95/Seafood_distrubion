import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";

type Errors = Partial<Record<"reason" | "expected_amount" | "lot_shares" | "detail", string>>;

/** A lot the write-off can be charged to (D-257): one the party bought or sold, not settled with its partner. */
export type WriteOffLotChoice = { batch_id: number; number: string; product: string };

type LotRow = { batch: string; amount: string };

/** Why a customer's balance is given up (D-298); an irrecoverable debt needs its evidence attached afterwards. */
export type WriteOffGround = "gap" | "irrecoverable";
const GROUNDS: readonly WriteOffGround[] = ["gap", "irrecoverable"];

export type WriteOffBody = {
  expected_amount: string;
  reason: string;
  ground?: WriteOffGround;
  lot_shares?: { batch: number; amount: string }[];
};

/** The typed amount is the balance as shown, to the millime: "10", "10,000" and "10.000" all match "10.000". */
function sameAmount(typed: string, owed: string): boolean {
  const normalized = typed.trim().replace(/\s/g, "").replace(",", ".");
  return /^\d+(\.\d{1,3})?$/.test(normalized) && Number(normalized) === Number(owed);
}

/** An amount in millimes, so the lots add up exactly; null when it is not an amount. */
function millimes(text: string): number | null {
  const parsed = parseDecimalInput(text, 3);
  return parsed === null || parsed === "" ? null : Math.round(Number(parsed) * 1000);
}

/** Clearing a balance to zero (D-252): the rest is given up, as a loss on a customer or a gain on a supplier. Steps
 * so that nothing is cleared by a misclick: the reason, the lots it is charged to (D-257: the owner picks them, the
 * amounts add up to the balance), then the exact amount typed again. */
export function BalanceWriteOffDialog({
  kind,
  party,
  owed,
  lots,
  onWrite,
  onDone,
}: {
  kind: "customer" | "supplier" | "invoice";
  party: string;
  // The balance as the server sends it ("10.000"): what the office types again.
  owed: string;
  lots: readonly WriteOffLotChoice[];
  onWrite: (body: WriteOffBody) => Promise<unknown>;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const formId = useId();
  const [step, setStep] = useState<"reason" | "lots" | "amount">("reason");
  const [reason, setReason] = useState("");
  const [ground, setGround] = useState<WriteOffGround>("gap");
  // A supplier's balance is a gain, not a debt: no ground to give.
  const asksGround = kind !== "supplier";
  const [rows, setRows] = useState<LotRow[]>(() =>
    lots.length === 1 ? [{ batch: String(lots[0]?.batch_id), amount: owed }] : [{ batch: "", amount: "" }],
  );
  const [typed, setTyped] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [pending, setPending] = useState(false);
  const amount = formatMoney(owed);
  const forInvoice = kind === "invoice";
  const owedMillimes = Math.round(Number(owed) * 1000);
  const spread = rows.reduce((total, row) => total + (millimes(row.amount) ?? 0), 0);
  const lotsReady =
    rows.length > 0 &&
    rows.every((row) => row.batch !== "" && (millimes(row.amount) ?? 0) > 0) &&
    new Set(rows.map((row) => row.batch)).size === rows.length &&
    spread === owedMillimes;

  function setRow(index: number, change: Partial<LotRow>) {
    setRows((current) => current.map((row, at) => (at === index ? { ...row, ...change } : row)));
  }

  function next(event: FormEvent) {
    event.preventDefault();
    if (!reason.trim()) {
      setErrors({ reason: t("admin.balanceWriteOff.reasonRequired") });
      return;
    }
    setErrors({});
    setStep(lots.length > 0 ? "lots" : "amount");
  }

  function lotsDone(event: FormEvent) {
    event.preventDefault();
    if (!lotsReady) {
      setErrors({ lot_shares: t("admin.balanceWriteOff.lotsMismatch", { amount }) });
      return;
    }
    setErrors({});
    setStep("amount");
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    if (!sameAmount(typed, owed)) {
      setErrors({ expected_amount: t("admin.balanceWriteOff.mismatch", { amount }) });
      return;
    }
    setPending(true);
    try {
      await onWrite({
        expected_amount: typed.trim(),
        reason: reason.trim(),
        ...(asksGround && { ground }),
        ...(lots.length > 0 && {
          lot_shares: rows.map((row) => ({
            batch: Number(row.batch),
            amount: parseDecimalInput(row.amount, 3) ?? row.amount,
          })),
        }),
      });
      toast.success(t(forInvoice ? "admin.balanceWriteOff.invoiceDone" : "admin.balanceWriteOff.done"));
      if (asksGround && ground === "irrecoverable") toast.warning(t("admin.balanceWriteOff.attachEvidence"));
      onDone();
    } catch (failure) {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.balanceWriteOff.error") });
    } finally {
      setPending(false);
    }
  }

  if (step === "reason") {
    return (
      <DialogContent>
        <DialogTitle>
          {t(forInvoice ? "admin.balanceWriteOff.invoiceTitle" : "admin.balanceWriteOff.title")}
        </DialogTitle>
        <DialogDescription>{t(`admin.balanceWriteOff.${kind}Hint`, { party, amount })}</DialogDescription>
        <form id={formId} onSubmit={next} noValidate className="flex flex-col gap-4">
          {asksGround && (
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-[0.86rem] font-semibold">{t("admin.balanceWriteOff.ground")}</legend>
              {GROUNDS.map((value) => (
                <label
                  key={value}
                  className={
                    "flex cursor-pointer items-start gap-2 rounded-control border px-3 py-2 text-[0.86rem] " +
                    (ground === value ? "border-sea bg-sea-soft font-semibold text-sea" : "border-line text-ink")
                  }
                >
                  <input
                    type="radio"
                    className="mt-0.5 size-3.5 accent-sea"
                    name={`${formId}-ground`}
                    checked={ground === value}
                    onChange={() => setGround(value)}
                  />
                  <span>
                    {t(`admin.balanceWriteOff.grounds.${value}`)}
                    <span className="block font-normal text-ink-2">
                      {t(`admin.balanceWriteOff.groundHints.${value}`)}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          <Field label={t("admin.balanceWriteOff.reason")} htmlFor={`${formId}-reason`} error={errors.reason}>
            <Input
              id={`${formId}-reason`}
              maxLength={255}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              aria-invalid={errors.reason ? true : undefined}
              autoComplete="off"
            />
          </Field>
          <DialogFooter>
            <Button type="submit" variant="danger">
              {t("admin.balanceWriteOff.continue")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    );
  }

  if (step === "lots") {
    return (
      <DialogContent>
        <DialogTitle>{t("admin.balanceWriteOff.lotsTitle")}</DialogTitle>
        <DialogDescription>{t(`admin.balanceWriteOff.${kind}LotsHint`, { amount })}</DialogDescription>
        <form id={formId} onSubmit={lotsDone} noValidate className="flex flex-col gap-3">
          {rows.map((row, index) => (
            <div key={index} className="flex items-end gap-2">
              <div className="flex-1">
                <Field label={t("admin.balanceWriteOff.lot")} htmlFor={`${formId}-lot-${index}`}>
                  <Select value={row.batch} onValueChange={(value) => setRow(index, { batch: value })}>
                    <SelectTrigger id={`${formId}-lot-${index}`}>
                      <SelectValue placeholder={t("admin.balanceWriteOff.lotHint")} />
                    </SelectTrigger>
                    <SelectContent>
                      {lots.map((lot) => (
                        <SelectItem key={lot.batch_id} value={String(lot.batch_id)}>
                          {lot.number} · {lot.product}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </div>
              <Field label={t("admin.balanceWriteOff.amount")} htmlFor={`${formId}-lot-amount-${index}`}>
                <Input
                  id={`${formId}-lot-amount-${index}`}
                  inputMode="decimal"
                  className="num w-32 text-end"
                  value={row.amount}
                  onChange={(event) => setRow(index, { amount: event.target.value })}
                  autoComplete="off"
                />
              </Field>
              {rows.length > 1 && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setRows((current) => current.filter((_row, at) => at !== index))}
                  aria-label={t("admin.balanceWriteOff.removeLot")}
                >
                  ×
                </Button>
              )}
            </div>
          ))}
          {rows.length < lots.length && (
            <Button
              type="button"
              variant="ghost"
              className="self-start"
              onClick={() => setRows((current) => [...current, { batch: "", amount: "" }])}
            >
              {t("admin.balanceWriteOff.addLot")}
            </Button>
          )}
          <p className={spread === owedMillimes ? "text-ink-2" : "text-bad"}>
            {t("admin.balanceWriteOff.lotsTotal", { spread: formatMoney((spread / 1000).toFixed(3)), amount })}
          </p>
          {errors.lot_shares && (
            <p role="alert" className="text-bad">
              {errors.lot_shares}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setStep("reason")}>
              {t("admin.balanceWriteOff.back")}
            </Button>
            <Button type="submit" variant="danger" disabled={!lotsReady}>
              {t("admin.balanceWriteOff.continue")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    );
  }

  return (
    <DialogContent>
      <DialogTitle>
        {t(forInvoice ? "admin.balanceWriteOff.invoiceConfirmTitle" : "admin.balanceWriteOff.confirmTitle")}
      </DialogTitle>
      <DialogDescription>{t("admin.balanceWriteOff.typeAmount", { amount })}</DialogDescription>
      <form id={formId} onSubmit={(event) => void confirm(event)} noValidate className="flex flex-col gap-4">
        <Field label={t("admin.balanceWriteOff.amount")} htmlFor={`${formId}-amount`} error={errors.expected_amount}>
          <Input
            id={`${formId}-amount`}
            inputMode="decimal"
            className="num text-end"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            aria-invalid={errors.expected_amount ? true : undefined}
            autoComplete="off"
          />
        </Field>
        {(errors.lot_shares ?? errors.detail) && (
          <p role="alert" className="text-bad">
            {errors.lot_shares ?? errors.detail}
          </p>
        )}
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setStep(lots.length > 0 ? "lots" : "reason")}
            disabled={pending}
          >
            {t("admin.balanceWriteOff.back")}
          </Button>
          <Button type="submit" variant="danger" disabled={pending || !sameAmount(typed, owed)}>
            {t(forInvoice ? "admin.balanceWriteOff.invoiceSubmit" : "admin.balanceWriteOff.submit")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
