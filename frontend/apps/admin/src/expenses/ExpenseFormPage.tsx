import {
  addExpenseReceipt,
  ApiError,
  createExpense,
  type ExpenseDetail,
  type ExpenseWrite,
  type PaymentMethodEnum,
  updateExpense,
  useGetBatch,
  useGetExpense,
  useListBatches,
  useListExpenseCategories,
  useListTrucks,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  cn,
  EmptyState,
  Field,
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
import { type FormEvent, useId, useState } from "react";
import { Link, Navigate, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router";

import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
import { todayInTunis } from "../receipts/shared";
import { canWriteExpenses, isOpen, PAYMENT_METHODS, refreshExpenses } from "./shared";

type Errors = Record<string, string>;
type Target = "general" | "lot" | "truck";
const TARGETS: Target[] = ["general", "lot", "truck"];
const DAY_LABOUR = "day_labour";
const RECENT_LOTS = 100;

/** "Nouvelle dépense" and "Modifier": what was paid, how, and what it is charged to. */
function ExpenseForm({ expense, initialLot }: { expense?: ExpenseDetail; initialLot?: number }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const formId = useId();

  // Archived ones leave the pickers unless this expense already uses them (pickable).
  const categories = useListExpenseCategories({ status: "all" });
  const trucks = useListTrucks({ status: "all" });
  const lots = useListBatches({ limit: RECENT_LOTS });

  const startLot = expense?.batch?.id ?? initialLot;
  const [spentOn, setSpentOn] = useState(expense?.spent_on ?? todayInTunis());
  const [category, setCategory] = useState(expense ? String(expense.category.id) : "");
  const [amount, setAmount] = useState(expense ? expense.amount.replace(".", ",") : "");
  const [method, setMethod] = useState<PaymentMethodEnum>(expense?.payment_method ?? "cash");
  const [description, setDescription] = useState(expense?.description ?? "");
  const [payee, setPayee] = useState(expense?.payee ?? "");
  const [notes, setNotes] = useState(expense?.notes ?? "");
  const [target, setTarget] = useState<Target>(startLot ? "lot" : expense?.truck ? "truck" : "general");
  const [lot, setLot] = useState(startLot ? String(startLot) : "");
  const [truck, setTruck] = useState(expense?.truck ? String(expense.truck.id) : "");
  const [receipt, setReceipt] = useState<File | null>(null);
  const [errors, setErrors] = useState<Errors>({});

  // The lot given in the address (from a lot's page) may be older than the recent ones listed.
  const given = useGetBatch(startLot ?? 0, { query: { enabled: startLot !== undefined } });
  const lotOptions = [...(lots.data?.results ?? [])];
  if (given.data && !lotOptions.some((one) => one.id === given.data.id)) lotOptions.unshift(given.data);
  // A lot of an archived product stays out of the picker unless this expense is on it.
  const lotChoices = lotOptions.filter((one) => one.product.is_active || String(one.id) === lot);

  const save = useMutation({
    mutationFn: async (payload: ExpenseWrite) => {
      const saved = expense ? await updateExpense(expense.id, payload) : await createExpense(payload);
      if (!receipt) return { saved, receiptFailed: false };
      try {
        return { saved: await addExpenseReceipt(saved.id, { receipt }), receiptFailed: false };
      } catch {
        return { saved, receiptFailed: true };
      }
    },
    onSuccess: async ({ saved, receiptFailed }) => {
      toast.success(
        t(saved.status === "approved" ? "admin.expenses.form.approved" : "admin.expenses.form.saved", {
          number: saved.number,
        }),
      );
      if (receiptFailed) toast.error(t("admin.expenses.form.receiptFailed"));
      await refreshExpenses(queryClient);
      void navigate(`/charges/${saved.id}`);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.expenses.form.error") });
    },
  });

  function submit(approve: boolean) {
    return (event?: FormEvent) => {
      event?.preventDefault();
      const found: Errors = {};
      const parsed = parseDecimalInput(amount.trim(), 3);
      if (!spentOn) found.spent_on = t("admin.expenses.form.required");
      if (!category) found.category = t("admin.expenses.form.required");
      if (parsed === null || parsed.startsWith("-") || /^0+(\.0+)?$/.test(parsed)) {
        found.amount = t("admin.expenses.form.amountInvalid");
      }
      if (target === "lot" && !lot) found.batch = t("admin.expenses.form.required");
      if (target === "truck" && !truck) found.truck = t("admin.expenses.form.required");
      setErrors(found);
      if (Object.keys(found).length > 0 || parsed === null) return;
      save.mutate({
        spent_on: spentOn,
        category: Number(category),
        amount: parsed,
        payment_method: method,
        description: description.trim(),
        payee: payee.trim(),
        notes: notes.trim(),
        batch: target === "lot" ? Number(lot) : null,
        truck: target === "truck" ? Number(truck) : null,
        approve_now: approve,
      });
    };
  }

  const id = (name: string) => `${formId}-${name}`;
  const select = (
    name: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    options: { value: string; label: string }[],
  ) => (
    <Field label={label} htmlFor={id(name)} error={errors[name]}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id(name)} aria-invalid={errors[name] ? true : undefined}>
          <SelectValue placeholder={t("admin.expenses.form.choose")} />
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
  const text = (name: string, label: string, value: string, onChange: (value: string) => void) => (
    <Field label={label} htmlFor={id(name)} error={errors[name]}>
      <Input id={id(name)} value={value} onChange={(event) => onChange(event.target.value)} autoComplete="off" />
    </Field>
  );

  const back = expense ? `/charges/${expense.id}` : "/charges";
  return (
    <>
      <Link to={back} className="text-[0.85rem] font-semibold text-sea hover:underline">
        {t("admin.expenses.back")}
      </Link>
      <PageHeader
        eyebrow={t("admin.expenses.title")}
        title={
          expense ? t("admin.expenses.form.editTitle", { number: expense.number }) : t("admin.expenses.form.title")
        }
      />

      <form onSubmit={submit(false)} noValidate className="flex flex-col gap-4">
        <Card className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <Field label={t("admin.expenses.form.date")} htmlFor={id("spent_on")} error={errors.spent_on}>
            <Input
              id={id("spent_on")}
              type="date"
              max={todayInTunis()}
              value={spentOn}
              onChange={(event) => setSpentOn(event.target.value)}
              aria-invalid={errors.spent_on ? true : undefined}
            />
          </Field>
          {select(
            "category",
            t("admin.expenses.form.category"),
            category,
            setCategory,
            pickable(categories.data ?? [], [category])
              .filter((one) => one.code !== DAY_LABOUR)
              .map((one) => ({ value: String(one.id), label: one.name })),
          )}
          <Field label={t("admin.expenses.form.amount")} htmlFor={id("amount")} error={errors.amount}>
            <MoneyInput
              id={id("amount")}
              inputMode="decimal"
              className="num"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              aria-invalid={errors.amount ? true : undefined}
              autoComplete="off"
            />
          </Field>
          {select(
            "payment_method",
            t("admin.expenses.form.method"),
            method,
            (value) => setMethod(value as PaymentMethodEnum),
            PAYMENT_METHODS.map((value) => ({ value, label: t(`admin.expenses.methods.${value}`) })),
          )}
          {text("description", t("admin.expenses.form.description"), description, setDescription)}
          {text("payee", t("admin.expenses.form.payee"), payee, setPayee)}
          <p className="col-span-full text-[0.85rem] text-ink-2">{t("admin.expenses.form.dayLabourHint")}</p>
        </Card>

        <Card className="flex flex-col gap-4">
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-2 text-[0.78rem] font-semibold text-ink-2">{t("admin.expenses.form.target")}</legend>
            <div className="flex flex-wrap gap-4">
              {TARGETS.map((value) => (
                <label key={value} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={id("target")}
                    value={value}
                    checked={target === value}
                    onChange={() => setTarget(value)}
                  />
                  {t(`admin.expenses.form.targets.${value}`)}
                </label>
              ))}
            </div>
            <p className="text-[0.85rem] text-ink-2">{t(`admin.expenses.form.targetHints.${target}`)}</p>
          </fieldset>
          <div className={cn("grid grid-cols-2 gap-4 max-[640px]:grid-cols-1", target === "general" && "hidden")}>
            {target === "lot" &&
              select(
                "batch",
                t("admin.expenses.form.lot"),
                lot,
                setLot,
                lotChoices.map((one) => ({
                  value: String(one.id),
                  label: `${one.number} · ${one.product.name} · ${formatDate(one.received_on)}`,
                })),
              )}
            {target === "truck" &&
              select(
                "truck",
                t("admin.expenses.form.truck"),
                truck,
                setTruck,
                (trucks.data ?? [])
                  .filter((one) => one.is_active || String(one.id) === truck)
                  .map((one) => ({ value: String(one.id), label: `${one.name} · ${one.plate}` })),
              )}
          </div>
        </Card>

        <Card className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <Field label={t("admin.expenses.form.receipt")} htmlFor={id("receipt")} error={errors.receipt}>
            <input
              id={id("receipt")}
              type="file"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              onChange={(event) => setReceipt(event.target.files?.[0] ?? null)}
              className="rounded-control border border-line bg-surface px-3 py-2 text-[0.9rem] text-ink"
            />
          </Field>
          <div className="col-span-full">
            <Field label={t("admin.expenses.form.notes")} htmlFor={id("notes")} error={errors.notes}>
              <textarea
                id={id("notes")}
                rows={2}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                className="w-full rounded-control border border-line bg-surface px-3 py-2.5 text-ink"
              />
            </Field>
          </div>
        </Card>

        {(errors.detail || errors.non_field_errors) && (
          <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
            {errors.detail || errors.non_field_errors}
          </p>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={() => void navigate(back)}>{t("admin.expenses.form.cancel")}</Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? t("admin.expenses.form.saving") : t("admin.expenses.form.save")}
          </Button>
          <Button variant="primary" disabled={save.isPending} onClick={() => submit(true)()}>
            {t("admin.expenses.form.saveApprove")}
          </Button>
        </div>
      </form>
    </>
  );
}

export function ExpenseFormPage() {
  const session = useOutletContext<Session>();
  const [params] = useSearchParams();
  const lot = Number(params.get("lot"));
  if (!canWriteExpenses(session)) return <Navigate to="/charges" replace />;
  return <ExpenseForm initialLot={Number.isInteger(lot) && lot > 0 ? lot : undefined} />;
}

export function ExpenseEditPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const id = Number(useParams().expenseId);
  const validId = Number.isInteger(id) && id > 0;
  const expense = useGetExpense(id, { query: { enabled: validId, retry: false } });
  if (!canWriteExpenses(session)) return <Navigate to="/charges" replace />;
  if (validId && expense.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!expense.data) {
    const missing = !validId || (expense.error instanceof ApiError && expense.error.status === 404);
    return (
      <EmptyState illustration="mix" title={missing ? t("admin.expenses.notFound") : t("common.serverUnreachable")} />
    );
  }
  if (expense.data.day_labour_id !== null) return <Navigate to="/charges/calendrier" replace />;
  if (!isOpen(expense.data.status)) return <Navigate to={`/charges/${id}`} replace />;
  return <ExpenseForm expense={expense.data} />;
}
