import { formatMoney, useTranslation } from "@frutti/i18n";
import { Button, DialogContent, DialogDescription, DialogFooter, DialogTitle, Field, Input, toast } from "@frutti/ui";
import { type FormEvent, useId, useState } from "react";

import { fieldErrors } from "../lib/errors";

type Errors = Partial<Record<"reason" | "expected_amount" | "detail", string>>;

/** The typed amount is the balance as shown, to the millime: "10", "10,000" and "10.000" all match "10.000". */
function sameAmount(typed: string, owed: string): boolean {
  const normalized = typed.trim().replace(/\s/g, "").replace(",", ".");
  return /^\d+(\.\d{1,3})?$/.test(normalized) && Number(normalized) === Number(owed);
}

/** Clearing a balance to zero (D-252): the rest is given up, as a loss on a customer or a gain on a supplier. Two
 * steps so that nothing is cleared by a misclick: the reason, then the exact amount typed again. */
export function BalanceWriteOffDialog({
  kind,
  party,
  owed,
  onWrite,
  onDone,
}: {
  kind: "customer" | "supplier";
  party: string;
  // The balance as the server sends it ("10.000"): what the office types again.
  owed: string;
  onWrite: (body: { expected_amount: string; reason: string }) => Promise<unknown>;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const formId = useId();
  const [step, setStep] = useState<"reason" | "amount">("reason");
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [pending, setPending] = useState(false);
  const amount = formatMoney(owed);

  function next(event: FormEvent) {
    event.preventDefault();
    if (!reason.trim()) {
      setErrors({ reason: t("admin.balanceWriteOff.reasonRequired") });
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
      await onWrite({ expected_amount: typed.trim(), reason: reason.trim() });
      toast.success(t("admin.balanceWriteOff.done"));
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
        <DialogTitle>{t("admin.balanceWriteOff.title")}</DialogTitle>
        <DialogDescription>{t(`admin.balanceWriteOff.${kind}Hint`, { party, amount })}</DialogDescription>
        <form id={formId} onSubmit={next} noValidate className="flex flex-col gap-4">
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

  return (
    <DialogContent>
      <DialogTitle>{t("admin.balanceWriteOff.confirmTitle")}</DialogTitle>
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
        {errors.detail && (
          <p role="alert" className="text-bad">
            {errors.detail}
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => setStep("reason")} disabled={pending}>
            {t("admin.balanceWriteOff.back")}
          </Button>
          <Button type="submit" variant="danger" disabled={pending || !sameAmount(typed, owed)}>
            {t("admin.balanceWriteOff.submit")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
