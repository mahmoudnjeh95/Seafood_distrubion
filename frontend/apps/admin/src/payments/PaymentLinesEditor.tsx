import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Field,
  Icon,
  Input,
  MoneyInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@frutti/ui";
import { useState } from "react";

import { isPaper, newLine, type PaymentLine, splitIntoEffets } from "./lines";

type Bank = { id: number; code: string; name: string };

/** The means of one règlement, line by line (D-197, D-208): each one its method and amount; a cheque or a traite
 * also its number, bank and échéance (and, received from a customer, its drawer). "Répartir" adds N effets of
 * equal amounts a month apart. Shared by the customer and the supplier forms. */
export function PaymentLinesEditor<M extends string>({
  idPrefix,
  lines,
  onChange,
  methods,
  methodLabel,
  banks,
  errors,
  withDrawer = false,
  drawerPlaceholder = "",
  issuedOn,
}: {
  idPrefix: string;
  lines: readonly PaymentLine<M>[];
  onChange: (lines: PaymentLine<M>[]) => void;
  methods: readonly M[];
  methodLabel: (method: M) => string;
  banks: readonly Bank[];
  /** Messages by line index and field (`method`, `amount`, `number`, `bank`, `due_on`, `drawer`, `reference`). */
  errors: Record<number, Record<string, string>>;
  /** Received effets have a drawer (the customer by default); ours do not. */
  withDrawer?: boolean;
  drawerPlaceholder?: string;
  /** The règlement's day: the first échéance proposed by "Répartir". */
  issuedOn: string;
}) {
  const { t } = useTranslation();
  const [splitting, setSplitting] = useState(false);
  const change = (key: number, patch: Partial<PaymentLine<M>>) =>
    onChange(lines.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  const paperMethods = methods.filter(isPaper);

  return (
    <div className="flex flex-col gap-3">
      <ol className="flex flex-col gap-3">
        {lines.map((line, index) => {
          const n = index + 1;
          const id = (field: string) => `${idPrefix}-line-${line.key}-${field}`;
          const lineErrors = errors[index] ?? {};
          const paper = isPaper(line.method);
          return (
            <li
              key={line.key}
              aria-label={t("admin.treasury.lines.line", { n })}
              className="grid grid-cols-[2rem_repeat(6,minmax(0,1fr))_auto] items-start gap-3 rounded-control border border-line bg-surface p-3 max-[900px]:grid-cols-2"
            >
              <span className="num pt-8 font-bold text-ink-2 max-[900px]:hidden">{n}</span>
              <Field
                label={t("admin.treasury.lines.method")}
                htmlFor={id("method")}
                error={lineErrors.method}
                className="col-span-1"
              >
                <Select value={line.method} onValueChange={(value) => change(line.key, { method: value as M })}>
                  <SelectTrigger
                    id={id("method")}
                    aria-label={t("admin.treasury.lines.aria", { field: t("admin.treasury.lines.method"), n })}
                    aria-invalid={lineErrors.method ? true : undefined}
                  >
                    <SelectValue placeholder={t("admin.treasury.lines.choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {methods.map((method) => (
                      <SelectItem key={method} value={method}>
                        {methodLabel(method)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label={t("admin.treasury.lines.amount")} htmlFor={id("amount")} error={lineErrors.amount}>
                <MoneyInput
                  id={id("amount")}
                  inputMode="decimal"
                  aria-label={t("admin.treasury.lines.aria", { field: t("admin.treasury.lines.amount"), n })}
                  value={line.amount}
                  onChange={(event) => change(line.key, { amount: event.target.value })}
                  aria-invalid={lineErrors.amount ? true : undefined}
                  autoComplete="off"
                  className="num text-end"
                />
              </Field>
              {paper ? (
                <>
                  <Field label={t("admin.treasury.lines.number")} htmlFor={id("number")} error={lineErrors.number}>
                    <Input
                      id={id("number")}
                      aria-label={t("admin.treasury.lines.aria", { field: t("admin.treasury.lines.number"), n })}
                      value={line.number}
                      maxLength={50}
                      onChange={(event) => change(line.key, { number: event.target.value })}
                      aria-invalid={lineErrors.number ? true : undefined}
                      autoComplete="off"
                      className="num"
                    />
                  </Field>
                  <Field label={t("admin.treasury.lines.bank")} htmlFor={id("bank")} error={lineErrors.bank}>
                    <BankSelect
                      id={id("bank")}
                      label={t("admin.treasury.lines.aria", { field: t("admin.treasury.lines.bank"), n })}
                      banks={banks}
                      value={line.bank}
                      invalid={Boolean(lineErrors.bank)}
                      onChange={(bank) => change(line.key, { bank })}
                    />
                  </Field>
                  <Field label={t("admin.treasury.lines.dueOn")} htmlFor={id("due")} error={lineErrors.due_on}>
                    <Input
                      id={id("due")}
                      type="date"
                      aria-label={t("admin.treasury.lines.aria", { field: t("admin.treasury.lines.dueOn"), n })}
                      value={line.dueOn}
                      onChange={(event) => change(line.key, { dueOn: event.target.value })}
                      aria-invalid={lineErrors.due_on ? true : undefined}
                    />
                  </Field>
                  {withDrawer ? (
                    <Field label={t("admin.treasury.lines.drawer")} htmlFor={id("drawer")} error={lineErrors.drawer}>
                      <Input
                        id={id("drawer")}
                        aria-label={t("admin.treasury.lines.aria", { field: t("admin.treasury.lines.drawer"), n })}
                        value={line.drawer}
                        maxLength={150}
                        placeholder={drawerPlaceholder}
                        onChange={(event) => change(line.key, { drawer: event.target.value })}
                        autoComplete="off"
                      />
                    </Field>
                  ) : (
                    <span className="max-[900px]:hidden" />
                  )}
                </>
              ) : (
                <Field
                  label={t("admin.treasury.lines.reference")}
                  htmlFor={id("reference")}
                  error={lineErrors.reference}
                  className="col-span-4 max-[900px]:col-span-2"
                >
                  <Input
                    id={id("reference")}
                    aria-label={t("admin.treasury.lines.aria", { field: t("admin.treasury.lines.reference"), n })}
                    value={line.reference}
                    maxLength={50}
                    onChange={(event) => change(line.key, { reference: event.target.value })}
                    autoComplete="off"
                  />
                </Field>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="mt-6 max-[900px]:mt-0"
                aria-label={t("admin.treasury.lines.remove", { n })}
                disabled={lines.length === 1}
                onClick={() => onChange(lines.filter((one) => one.key !== line.key))}
              >
                <Icon name="trash" />
              </Button>
            </li>
          );
        })}
      </ol>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.85rem] font-semibold text-ink-2">{t("admin.treasury.lines.add")}</span>
        {methods.map((method) => (
          <Button key={method} onClick={() => onChange([...lines, newLine<M>(method)])}>
            <Icon name="plus" />
            {methodLabel(method)}
          </Button>
        ))}
        {paperMethods.length > 0 && (
          <Button variant="secondary" className="ms-auto" onClick={() => setSplitting((open) => !open)}>
            {t("admin.treasury.split.open")}
          </Button>
        )}
      </div>

      {splitting && (
        <SplitPanel
          idPrefix={idPrefix}
          methods={paperMethods}
          methodLabel={methodLabel}
          banks={banks}
          issuedOn={issuedOn}
          onCancel={() => setSplitting(false)}
          onAdd={(added) => {
            // An empty first line (the form's start) gives way to the effets.
            const kept = lines.filter((line) => line.method !== "" || line.amount.trim() !== "");
            onChange([...kept, ...added]);
            setSplitting(false);
          }}
        />
      )}
    </div>
  );
}

function BankSelect({
  id,
  label,
  banks,
  value,
  invalid,
  onChange,
}: {
  id: string;
  label: string;
  banks: readonly Bank[];
  value: string;
  invalid: boolean;
  onChange: (bank: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} aria-label={label} aria-invalid={invalid ? true : undefined}>
        <SelectValue placeholder={t("admin.treasury.lines.bankPlaceholder")} />
      </SelectTrigger>
      <SelectContent>
        {banks.map((bank) => (
          <SelectItem key={bank.id} value={String(bank.id)}>
            {bank.code} · {bank.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** "Répartir": N cheques or traites of equal amounts, a month (or more) apart, numbered on from the first. */
function SplitPanel<M extends string>({
  idPrefix,
  methods,
  methodLabel,
  banks,
  issuedOn,
  onCancel,
  onAdd,
}: {
  idPrefix: string;
  methods: readonly M[];
  methodLabel: (method: M) => string;
  banks: readonly Bank[];
  issuedOn: string;
  onCancel: () => void;
  onAdd: (lines: PaymentLine<M>[]) => void;
}) {
  const { t } = useTranslation();
  const [method, setMethod] = useState<M | "">(methods.find((one) => one === "bill") ?? methods[0] ?? "");
  const [total, setTotal] = useState("");
  const [count, setCount] = useState("3");
  const [firstDue, setFirstDue] = useState(issuedOn);
  const [every, setEvery] = useState("1");
  const [firstNumber, setFirstNumber] = useState("");
  const [bank, setBank] = useState("");
  const id = (field: string) => `${idPrefix}-split-${field}`;

  const amount = parseDecimalInput(total.trim(), 3);
  const times = Number.parseInt(count, 10);
  const months = Number.parseInt(every, 10);
  const valid =
    method !== "" &&
    amount !== null &&
    !amount.startsWith("-") &&
    Number.isInteger(times) &&
    times >= 1 &&
    times <= 24 &&
    Number.isInteger(months) &&
    months >= 1 &&
    months <= 12 &&
    firstDue !== "";
  const preview = valid
    ? splitIntoEffets({ total: amount, count: times, firstDue, everyMonths: months, firstNumber })
    : [];

  return (
    <section
      aria-label={t("admin.treasury.split.title")}
      className="flex flex-col gap-3 rounded-control border border-dashed border-line bg-surface-2 p-3"
    >
      <h3 className="font-semibold">{t("admin.treasury.split.title")}</h3>
      <div className="grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
        <Field label={t("admin.treasury.split.kind")} htmlFor={id("kind")}>
          <Select value={method} onValueChange={(value) => setMethod(value as M)}>
            <SelectTrigger id={id("kind")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {methods.map((one) => (
                <SelectItem key={one} value={one}>
                  {methodLabel(one)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("admin.treasury.split.total")} htmlFor={id("total")}>
          <MoneyInput
            id={id("total")}
            inputMode="decimal"
            value={total}
            onChange={(event) => setTotal(event.target.value)}
            autoComplete="off"
            className="num text-end"
          />
        </Field>
        <Field label={t("admin.treasury.split.count")} htmlFor={id("count")}>
          <Input
            id={id("count")}
            type="number"
            min={1}
            max={24}
            value={count}
            onChange={(event) => setCount(event.target.value)}
            className="num"
          />
        </Field>
        <Field label={t("admin.treasury.split.every")} htmlFor={id("every")}>
          <Input
            id={id("every")}
            type="number"
            min={1}
            max={12}
            value={every}
            onChange={(event) => setEvery(event.target.value)}
            className="num"
          />
        </Field>
        <Field label={t("admin.treasury.split.firstDue")} htmlFor={id("due")}>
          <Input id={id("due")} type="date" value={firstDue} onChange={(event) => setFirstDue(event.target.value)} />
        </Field>
        <Field label={t("admin.treasury.split.firstNumber")} htmlFor={id("number")}>
          <Input
            id={id("number")}
            value={firstNumber}
            maxLength={50}
            onChange={(event) => setFirstNumber(event.target.value)}
            autoComplete="off"
            className="num"
          />
        </Field>
        <Field label={t("admin.treasury.lines.bank")} htmlFor={id("bank")} className="col-span-2">
          <BankSelect
            id={id("bank")}
            label={t("admin.treasury.lines.bank")}
            banks={banks}
            value={bank}
            invalid={false}
            onChange={setBank}
          />
        </Field>
      </div>
      {preview.length > 0 && (
        <p className="text-[0.85rem] text-ink-2">
          {t("admin.treasury.split.preview", {
            count: preview.length,
            amount: formatMoney(preview[0]?.amount ?? "0"),
            last: formatMoney(preview[preview.length - 1]?.amount ?? "0"),
          })}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          {t("admin.treasury.split.cancel")}
        </Button>
        <Button
          variant="primary"
          disabled={preview.length === 0}
          onClick={() =>
            onAdd(
              preview.map((split) => ({
                ...newLine<M>(method, split.amount.replace(".", ",")),
                number: split.number,
                dueOn: split.dueOn,
                bank,
              })),
            )
          }
        >
          {t("admin.treasury.split.apply")}
        </Button>
      </div>
    </section>
  );
}
