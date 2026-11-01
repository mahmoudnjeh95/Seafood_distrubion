import type { PaymentMethodEnum } from "@frutti/api";
import { formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Field,
  Input,
  MoneyInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@frutti/ui";

import { blankPayLine, GIVEN_METHODS, hasPaper, type PaidMode, type PayLine } from "./purchasePay";

type Props = {
  mode: PaidMode;
  lines: PayLine[];
  total: string;
  paid: string;
  rest: string;
  overpaid: boolean;
  onMode: (mode: PaidMode) => void;
  onLines: (lines: PayLine[]) => void;
};

export function PaidNow({ mode, lines, total, paid, rest, overpaid, onMode, onLines }: Props) {
  const { t } = useTranslation();
  const change = (key: number, patch: Partial<PayLine>) =>
    onLines(lines.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  const choose = (next: PaidMode) => {
    if (next !== "none" && lines.length === 0) onLines([blankPayLine()]);
    onMode(next);
  };
  const shown = mode === "all" ? lines.slice(0, 1) : lines;

  return (
    <Card className="space-y-3">
      <h2>{t("truck.purchase.givenNow")}</h2>
      <div className="grid grid-cols-3 gap-2" role="group" aria-label={t("truck.purchase.givenNow")}>
        {(["none", "part", "all"] as const).map((choice) => (
          <Button
            key={choice}
            size="lg"
            variant={mode === choice ? "primary" : "secondary"}
            className="py-4 text-lg"
            aria-pressed={mode === choice}
            onClick={() => choose(choice)}
          >
            {t(`truck.purchase.choice.${choice}`)}
          </Button>
        ))}
      </div>
      {mode === "none" ? null : (
        <div className="space-y-3">
          {shown.map((line, index) => (
            <div key={line.key} className="space-y-3 rounded-card border border-line p-3">
              <Field label={t("truck.purchase.method")} htmlFor={`pay-method-${line.key}`}>
                <Select
                  value={line.method}
                  onValueChange={(value) => change(line.key, { method: value as PaymentMethodEnum })}
                >
                  <SelectTrigger id={`pay-method-${line.key}`} className="text-xl">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {GIVEN_METHODS.map((method) => (
                      <SelectItem key={method} value={method}>
                        {t(`truck.purchase.methods.${method}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              {mode === "all" ? (
                <p className="flex justify-between text-lg">
                  <span>{t("truck.purchase.amount")}</span>
                  <b>{formatMoney(total)}</b>
                </p>
              ) : (
                <Field label={t("truck.purchase.amount")} htmlFor={`pay-amount-${line.key}`}>
                  <MoneyInput
                    id={`pay-amount-${line.key}`}
                    inputMode="decimal"
                    className="text-xl"
                    value={line.amount}
                    onChange={(event) => change(line.key, { amount: event.target.value })}
                  />
                </Field>
              )}
              {hasPaper(line.method) ? (
                <div className="grid grid-cols-2 gap-3">
                  <Field label={t("truck.purchase.paperNumber")} htmlFor={`pay-ref-${line.key}`}>
                    <Input
                      id={`pay-ref-${line.key}`}
                      value={line.reference}
                      onChange={(event) => change(line.key, { reference: event.target.value })}
                    />
                  </Field>
                  <Field label={t("truck.purchase.chequeDate")} htmlFor={`pay-date-${line.key}`}>
                    <Input
                      id={`pay-date-${line.key}`}
                      type="date"
                      value={line.cashOn}
                      onChange={(event) => change(line.key, { cashOn: event.target.value })}
                    />
                  </Field>
                </div>
              ) : null}
              {mode === "part" && lines.length > 1 ? (
                <Button onClick={() => onLines(lines.filter((other) => other.key !== line.key))}>
                  {t("truck.purchase.removePayment", { number: index + 1 })}
                </Button>
              ) : null}
            </div>
          ))}
          {mode === "part" ? (
            <Button className="w-full" onClick={() => onLines([...lines, blankPayLine()])}>
              {t("truck.purchase.addPayment")}
            </Button>
          ) : null}
        </div>
      )}
      <div className="space-y-1 border-t border-line pt-3">
        <p className="flex justify-between text-lg">
          <span>{t("truck.purchase.total")}</span>
          <b>{formatMoney(total)}</b>
        </p>
        <p className="flex justify-between text-lg">
          <span>{t("truck.purchase.paid")}</span>
          <span>{formatMoney(paid)}</span>
        </p>
        <p className="flex justify-between text-xl font-bold">
          <span>{t("truck.purchase.rest")}</span>
          <span>{formatMoney(rest)}</span>
        </p>
        <p className="text-ink-2">{t("truck.purchase.restOffice")}</p>
        {overpaid ? <p className="font-semibold text-bad">{t("truck.purchase.overpaid")}</p> : null}
      </div>
    </Card>
  );
}
