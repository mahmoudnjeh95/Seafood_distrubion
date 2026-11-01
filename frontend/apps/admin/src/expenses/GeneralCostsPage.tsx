import {
  approveExpense,
  createGeneralCost,
  createRecurringCost,
  deleteGeneralCost,
  type GeneralCost,
  generateRecurringCosts,
  type PaymentMethodEnum,
  type RecurringCost,
  updateRecurringCost,
  useListExpenseCategories,
  useListGeneralCosts,
  useListRecurringCosts,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  EmptyState,
  Field,
  Icon,
  Input,
  MoneyInput,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { useOutletContext } from "react-router";

import { currentMonth, monthLabel, shiftMonth } from "../hr/shared";
import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
import { todayInTunis } from "../receipts/shared";
import { CostSelect } from "./CostSelect";
import { ExpensesTabs } from "./ExpensesTabs";
import { canManageCategories, canWriteExpenses, EXPENSE_TONES, PAYMENT_METHODS, refreshExpenses } from "./shared";

type Errors = Record<string, string>;

/** "2026-10" from a month input → "2026-10-01" (the API wants the first day of the month). */
const toFirstDay = (month: string) => (month ? `${month}-01` : "");

/** Parse a typed amount: a positive DT amount with at most 3 decimals, or null. */
function positiveAmount(typed: string): string | null {
  const parsed = parseDecimalInput(typed.trim(), 3);
  if (!parsed || parsed.startsWith("-") || /^0+(\.0+)?$/.test(parsed)) return null;
  return parsed;
}

/** Add or change a monthly cost (owner): the template that generates each month's expense. */
function RecurringDialog({ cost, onDone }: { cost?: RecurringCost; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  // Archived ones leave the pickers unless this cost already uses them (pickable).
  const categories = useListExpenseCategories({ status: "all" });
  const [name, setName] = useState(cost?.name ?? "");
  const [category, setCategory] = useState(cost ? String(cost.category.id) : "");
  const [amount, setAmount] = useState(cost?.monthly_amount.replace(".", ",") ?? "");
  const [method, setMethod] = useState<PaymentMethodEnum>(cost?.payment_method ?? "transfer");
  const [payee, setPayee] = useState(cost?.payee ?? "");
  const [start, setStart] = useState(cost?.start_month.slice(0, 7) ?? currentMonth().slice(0, 7));
  const [end, setEnd] = useState(cost?.end_month?.slice(0, 7) ?? "");
  const [stopped, setStopped] = useState(cost ? !cost.is_active : false);
  const [errors, setErrors] = useState<Errors>({});
  const save = useMutation({
    mutationFn: (payload: Parameters<typeof createRecurringCost>[0]) =>
      cost ? updateRecurringCost(cost.id, payload) : createRecurringCost(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.generalCosts.dialog.saved", { name: saved.name }));
      await refreshExpenses(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.generalCosts.generate.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    const parsed = positiveAmount(amount);
    if (!name.trim()) found.name = t("admin.generalCosts.dialog.required");
    if (!category) found.category = t("admin.generalCosts.dialog.required");
    if (parsed === null) found.monthly_amount = t("admin.generalCosts.dialog.amountInvalid");
    if (!start) found.start_month = t("admin.generalCosts.dialog.required");
    setErrors(found);
    if (Object.keys(found).length > 0 || parsed === null) return;
    save.mutate({
      name: name.trim(),
      category: Number(category),
      monthly_amount: parsed,
      payment_method: method,
      payee: payee.trim(),
      start_month: toFirstDay(start),
      end_month: end ? toFirstDay(end) : null,
      is_active: !stopped,
    });
  }

  const id = (field: string) => `${formId}-${field}`;
  return (
    <DialogContent>
      <DialogTitle>
        {cost ? t("admin.generalCosts.dialog.editTitle") : t("admin.generalCosts.dialog.addTitle")}
      </DialogTitle>
      <DialogDescription>{t("admin.generalCosts.dialog.body")}</DialogDescription>
      <form noValidate onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t("admin.generalCosts.dialog.name")} htmlFor={id("name")} error={errors.name}>
          <Input id={id("name")} value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" />
        </Field>
        <CostSelect
          id={id("category")}
          label={t("admin.generalCosts.dialog.category")}
          value={category}
          onChange={setCategory}
          options={pickable(categories.data ?? [], [category])
            .filter((one) => one.code !== "day_labour")
            .map((one) => ({ value: String(one.id), label: one.name }))}
          placeholder={t("admin.generalCosts.dialog.choose")}
          error={errors.category}
        />
        <Field label={t("admin.generalCosts.dialog.amount")} htmlFor={id("amount")} error={errors.monthly_amount}>
          <MoneyInput
            id={id("amount")}
            inputMode="decimal"
            className="num"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <CostSelect
          id={id("method")}
          label={t("admin.generalCosts.dialog.method")}
          value={method}
          onChange={(value) => setMethod(value as PaymentMethodEnum)}
          options={PAYMENT_METHODS.map((value) => ({ value, label: t(`admin.expenses.methods.${value}`) }))}
          placeholder={t("admin.generalCosts.dialog.choose")}
          error={errors.payment_method}
        />
        <Field label={t("admin.generalCosts.dialog.payee")} htmlFor={id("payee")} error={errors.payee}>
          <Input id={id("payee")} value={payee} onChange={(event) => setPayee(event.target.value)} autoComplete="off" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("admin.generalCosts.dialog.start")} htmlFor={id("start")} error={errors.start_month}>
            <Input id={id("start")} type="month" value={start} onChange={(event) => setStart(event.target.value)} />
          </Field>
          <Field label={t("admin.generalCosts.dialog.end")} htmlFor={id("end")} error={errors.end_month}>
            <Input id={id("end")} type="month" value={end} onChange={(event) => setEnd(event.target.value)} />
          </Field>
        </div>
        {cost && (
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={stopped} onChange={(event) => setStopped(event.target.checked)} />
            {t("admin.generalCosts.dialog.stopped")}
          </label>
        )}
        {errors.detail && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail}
          </p>
        )}
        <DialogFooter>
          <Button onClick={onDone}>{t("admin.generalCosts.dialog.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.generalCosts.dialog.save")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

/** A bill covering several months (an insurance for a year), spread equally over them. */
function MultiMonthDialog({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  // Archived ones leave the pickers unless this cost already uses them (pickable).
  const categories = useListExpenseCategories({ status: "all" });
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethodEnum>("transfer");
  const [payee, setPayee] = useState("");
  const [date, setDate] = useState(todayInTunis());
  const [first, setFirst] = useState(currentMonth().slice(0, 7));
  const [months, setMonths] = useState("12");
  const [approve, setApprove] = useState(true);
  const [errors, setErrors] = useState<Errors>({});
  const save = useMutation({
    mutationFn: (payload: Parameters<typeof createGeneralCost>[0]) => createGeneralCost(payload),
    onSuccess: async () => {
      toast.success(t("admin.generalCosts.multi.saved"));
      await refreshExpenses(queryClient);
      onDone();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.generalCosts.generate.error") });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const found: Errors = {};
    const parsed = positiveAmount(amount);
    const count = Number(months);
    if (!description.trim()) found.description = t("admin.generalCosts.dialog.required");
    if (!category) found.category = t("admin.generalCosts.dialog.required");
    if (parsed === null) found.amount = t("admin.generalCosts.dialog.amountInvalid");
    if (!Number.isInteger(count) || count < 1 || count > 60) found.months = t("admin.generalCosts.multi.invalid");
    setErrors(found);
    if (Object.keys(found).length > 0 || parsed === null) return;
    save.mutate({
      spent_on: date,
      category: Number(category),
      amount: parsed,
      first_month: toFirstDay(first),
      months: count,
      payment_method: method,
      description: description.trim(),
      payee: payee.trim(),
      approve_now: approve,
    });
  }

  const id = (field: string) => `${formId}-${field}`;
  return (
    <DialogContent>
      <DialogTitle>{t("admin.generalCosts.multi.title")}</DialogTitle>
      <DialogDescription>{t("admin.generalCosts.multi.body")}</DialogDescription>
      <form noValidate onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t("admin.generalCosts.multi.description")} htmlFor={id("description")} error={errors.description}>
          <Input
            id={id("description")}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <CostSelect
          id={id("category")}
          label={t("admin.generalCosts.multi.category")}
          value={category}
          onChange={setCategory}
          options={pickable(categories.data ?? [], [category])
            .filter((one) => one.code !== "day_labour")
            .map((one) => ({ value: String(one.id), label: one.name }))}
          placeholder={t("admin.generalCosts.dialog.choose")}
          error={errors.category}
        />
        <Field label={t("admin.generalCosts.multi.amount")} htmlFor={id("amount")} error={errors.amount}>
          <MoneyInput
            id={id("amount")}
            inputMode="decimal"
            className="num"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            autoComplete="off"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("admin.generalCosts.multi.firstMonth")} htmlFor={id("first")} error={errors.first_month}>
            <Input id={id("first")} type="month" value={first} onChange={(event) => setFirst(event.target.value)} />
          </Field>
          <Field label={t("admin.generalCosts.multi.months")} htmlFor={id("months")} error={errors.months}>
            <Input
              id={id("months")}
              inputMode="numeric"
              className="num"
              value={months}
              onChange={(event) => setMonths(event.target.value)}
            />
          </Field>
          <Field label={t("admin.generalCosts.multi.date")} htmlFor={id("date")} error={errors.spent_on}>
            <Input
              id={id("date")}
              type="date"
              max={todayInTunis()}
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
          </Field>
          <CostSelect
            id={id("method")}
            label={t("admin.generalCosts.multi.method")}
            value={method}
            onChange={(value) => setMethod(value as PaymentMethodEnum)}
            options={PAYMENT_METHODS.map((value) => ({ value, label: t(`admin.expenses.methods.${value}`) }))}
            placeholder={t("admin.generalCosts.dialog.choose")}
          />
        </div>
        <Field label={t("admin.generalCosts.multi.payee")} htmlFor={id("payee")} error={errors.payee}>
          <Input id={id("payee")} value={payee} onChange={(event) => setPayee(event.target.value)} autoComplete="off" />
        </Field>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={approve} onChange={(event) => setApprove(event.target.checked)} />
          {t("admin.generalCosts.multi.approveNow")}
        </label>
        {errors.detail && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail}
          </p>
        )}
        <DialogFooter>
          <Button onClick={onDone}>{t("admin.generalCosts.dialog.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t("admin.generalCosts.multi.save")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

/** "Frais généraux": monthly costs (rent, accountant, insurance) as templates, the month's generated
 * expenses, and bills over several months. Each is charged to lots like a salary (P5-T05, D-059). */
export function GeneralCostsPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const session = useOutletContext<Session>();
  const canWrite = canWriteExpenses(session);
  const isOwner = canManageCategories(session);
  const [month, setMonth] = useState(currentMonth);
  const [editing, setEditing] = useState<RecurringCost | "new" | null>(null);
  const [multi, setMulti] = useState(false);
  const costs = useListRecurringCosts();
  const periods = useListGeneralCosts({ month });
  const label = monthLabel(month, i18n.language);

  const generate = useMutation({
    mutationFn: (approve: boolean) => generateRecurringCosts({ month, approve_now: approve }),
    onSuccess: async (created) => {
      toast.success(
        created.length > 0
          ? t("admin.generalCosts.generate.done", { count: created.length })
          : t("admin.generalCosts.generate.nothing"),
      );
      await refreshExpenses(queryClient);
    },
    onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.generalCosts.generate.error")),
  });
  const approve = useMutation({
    mutationFn: (period: GeneralCost) => approveExpense(period.expense_id),
    onSuccess: async () => {
      toast.success(t("admin.generalCosts.month.approved"));
      await refreshExpenses(queryClient);
    },
    onError: () => toast.error(t("admin.generalCosts.generate.error")),
  });
  const remove = useMutation({
    mutationFn: (period: GeneralCost) => deleteGeneralCost(period.id),
    onSuccess: async () => {
      toast.success(t("admin.generalCosts.month.deleted"));
      await refreshExpenses(queryClient);
    },
    onError: () => toast.error(t("admin.generalCosts.generate.error")),
  });
  const list = costs.data ?? [];
  const rows = periods.data ?? [];
  const busy = generate.isPending || approve.isPending || remove.isPending;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.generalCosts.title")}>
        {canWrite && (
          <Button onClick={() => setMulti(true)}>
            <Icon name="plus" />
            {t("admin.generalCosts.multi.button")}
          </Button>
        )}
      </PageHeader>
      <ExpensesTabs />
      <p className="text-ink-2">{t("admin.generalCosts.intro")}</p>
      {!isOwner && <p className="text-[0.88rem] text-ink-2">{t("admin.generalCosts.readOnly")}</p>}

      <section aria-labelledby="recurring" className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="recurring" className="me-auto">
            {t("admin.generalCosts.recurring.title")}
          </h2>
          {isOwner && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              <Icon name="plus" />
              {t("admin.generalCosts.recurring.add")}
            </Button>
          )}
        </div>
        {costs.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : costs.isError ? (
          <p role="alert" className="text-bad">
            {t("common.serverUnreachable")}
          </p>
        ) : list.length === 0 ? (
          <EmptyState illustration="mix" title={t("admin.generalCosts.recurring.empty")}>
            {t("admin.generalCosts.recurring.emptyBody")}
          </EmptyState>
        ) : (
          <Card className="p-2">
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.generalCosts.recurring.name")}</Th>
                  <Th>{t("admin.generalCosts.recurring.category")}</Th>
                  <Th numeric>{t("admin.generalCosts.recurring.amount")}</Th>
                  <Th>{t("admin.generalCosts.recurring.period")}</Th>
                  {isOwner && <Th className="w-0" />}
                </tr>
              </thead>
              <tbody>
                {list.map((cost) => (
                  <tr key={cost.id}>
                    <Td>
                      <span className="font-semibold">{cost.name}</span>
                      {!cost.is_active && (
                        <Pill className="ms-2" tone="neutral">
                          {t("admin.generalCosts.recurring.stopped")}
                        </Pill>
                      )}
                    </Td>
                    <Td>{cost.category.name}</Td>
                    <Td numeric className="whitespace-nowrap">
                      {formatMoney(cost.monthly_amount)}
                    </Td>
                    <Td className="text-[0.88rem] text-ink-2">
                      {cost.end_month
                        ? t("admin.generalCosts.recurring.fromTo", {
                            from: monthLabel(cost.start_month, i18n.language),
                            to: monthLabel(cost.end_month, i18n.language),
                          })
                        : t("admin.generalCosts.recurring.from", {
                            month: monthLabel(cost.start_month, i18n.language),
                          })}
                    </Td>
                    {isOwner && (
                      <Td>
                        <Button
                          variant="ghost"
                          aria-label={t("admin.generalCosts.recurring.editOf", { name: cost.name })}
                          onClick={() => setEditing(cost)}
                        >
                          {t("admin.generalCosts.recurring.edit")}
                        </Button>
                      </Td>
                    )}
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        )}
      </section>

      <section aria-labelledby="month-costs" className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="month-costs" className="me-auto capitalize">
            {t("admin.generalCosts.generate.title", { month: label })}
          </h2>
          <Button
            variant="ghost"
            aria-label={t("admin.coldCost.previous")}
            onClick={() => setMonth(shiftMonth(month, -1))}
          >
            ‹
          </Button>
          <Button variant="ghost" aria-label={t("admin.coldCost.next")} onClick={() => setMonth(shiftMonth(month, 1))}>
            ›
          </Button>
          {canWrite && month <= currentMonth() && (
            <>
              <Button disabled={busy} onClick={() => generate.mutate(false)}>
                {t("admin.generalCosts.generate.button")}
              </Button>
              <Button variant="primary" disabled={busy} onClick={() => generate.mutate(true)}>
                {t("admin.generalCosts.generate.buttonApprove")}
              </Button>
            </>
          )}
        </div>
        {rows.length === 0 ? (
          <p className="text-ink-2">{t("admin.generalCosts.month.empty")}</p>
        ) : (
          <Card className="p-2">
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.generalCosts.month.label")}</Th>
                  <Th numeric>{t("admin.generalCosts.month.amount")}</Th>
                  <Th>{t("admin.generalCosts.month.covers")}</Th>
                  <Th>{t("admin.generalCosts.month.status")}</Th>
                  {canWrite && <Th className="w-0" />}
                </tr>
              </thead>
              <tbody>
                {rows.map((period) => (
                  <tr key={period.id}>
                    <Td>
                      <span className="font-semibold">{period.description || period.category.name}</span>
                      <div className="text-[0.8rem] text-ink-2">{period.expense_number}</div>
                    </Td>
                    <Td numeric className="whitespace-nowrap">
                      {formatMoney(period.amount)}
                    </Td>
                    <Td>{t("admin.generalCosts.month.months", { count: period.months })}</Td>
                    <Td>
                      <Pill tone={EXPENSE_TONES[period.status]}>{t(`admin.expenses.statuses.${period.status}`)}</Pill>
                    </Td>
                    {canWrite && (
                      <Td className="whitespace-nowrap">
                        {period.status === "draft" && (
                          <>
                            <Button variant="ghost" disabled={busy} onClick={() => approve.mutate(period)}>
                              {t("admin.generalCosts.month.approve")}
                            </Button>
                            <Button variant="ghost" disabled={busy} onClick={() => remove.mutate(period)}>
                              {t("admin.generalCosts.month.delete")}
                            </Button>
                          </>
                        )}
                      </Td>
                    )}
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        )}
      </section>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        {editing !== null && (
          <RecurringDialog cost={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />
        )}
      </Dialog>
      <Dialog open={multi} onOpenChange={setMulti}>
        {multi && <MultiMonthDialog onDone={() => setMulti(false)} />}
      </Dialog>
    </>
  );
}
