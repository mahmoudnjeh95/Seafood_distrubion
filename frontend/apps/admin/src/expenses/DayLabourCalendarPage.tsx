import {
  approveExpense,
  createDayLabour,
  type DayLabourEntry,
  type DayLabourWrite,
  deleteDayLabour,
  useGetBatch,
  useListBatches,
  useListDayLabour,
  useListDayLabourers,
  type WorkTypeEnum,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Field,
  Icon,
  Input,
  MoneyInput,
  PageHeader,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@frutti/ui";
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router";

import { sum } from "../lib/decimal";
import { fieldErrors } from "../lib/errors";
import { pickable } from "../lib/pickable";
import { todayInTunis } from "../receipts/shared";
import { addMonths, type Month, monthBounds, monthLabel, monthOf, weekdayLabels, weeksOf } from "./calendar";
import { ExpensesTabs } from "./ExpensesTabs";
import { canWriteExpenses, EXPENSE_TONES, isOpen, refreshExpenses, WORK_TYPES } from "./shared";

const NO_LOT = "none";
const RECENT_LOTS = 100;
type Errors = Record<string, string>;

/** The form of the day's dialog: who worked, what they were paid, on which lot and doing what. */
function AddDay({ day, initialLot }: { day: string; initialLot?: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const formId = useId();
  // Archived ones leave the pickers unless this entry already uses them (pickable).
  const labourers = useListDayLabourers({ status: "all" });
  const lots = useListBatches({ limit: RECENT_LOTS });
  const given = useGetBatch(initialLot ?? 0, { query: { enabled: initialLot !== undefined } });
  const [labourer, setLabourer] = useState("");
  const [amount, setAmount] = useState("");
  const [lot, setLot] = useState(initialLot ? String(initialLot) : NO_LOT);
  const [workType, setWorkType] = useState<WorkTypeEnum>("other");
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const lotOptions = [...(lots.data?.results ?? [])].filter((one) => one.received_on <= day);
  if (given.data && !lotOptions.some((one) => one.id === given.data.id)) lotOptions.unshift(given.data);
  // A lot of an archived product stays out of the picker unless this entry is on it.
  const lotChoices = lotOptions.filter((one) => one.product.is_active || String(one.id) === lot);

  const add = useMutation({
    mutationFn: (payload: DayLabourWrite) => createDayLabour(payload),
    onSuccess: async (saved) => {
      toast.success(t("admin.dayLabour.added", { name: saved.labourer.name, amount: formatMoney(saved.amount) }));
      setLabourer("");
      setAmount("");
      setNotes("");
      setErrors({});
      await refreshExpenses(queryClient);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setErrors(Object.keys(fromServer).length > 0 ? fromServer : { detail: t("admin.expenses.actionError") });
    },
  });

  function submit(approve: boolean) {
    return (event?: FormEvent) => {
      event?.preventDefault();
      const found: Errors = {};
      const typed = amount.trim();
      const parsed = typed ? parseDecimalInput(typed, 3) : "";
      if (!labourer) found.labourer = t("admin.expenses.form.required");
      if (parsed === null || (parsed && (parsed.startsWith("-") || /^0+(\.0+)?$/.test(parsed)))) {
        found.amount = t("admin.expenses.form.amountInvalid");
      }
      setErrors(found);
      if (Object.keys(found).length > 0 || parsed === null) return;
      add.mutate({
        labourer: Number(labourer),
        worked_on: day,
        amount: parsed || null,
        batch: lot === NO_LOT ? null : Number(lot),
        work_type: workType,
        notes: notes.trim(),
        approve_now: approve,
      });
    };
  }

  const id = (name: string) => `${formId}-${name}`;
  const usual = labourers.data?.find((one) => String(one.id) === labourer)?.usual_daily_pay;
  return (
    <form
      noValidate
      onSubmit={submit(false)}
      className="grid grid-cols-2 gap-3 border-t border-line pt-4 max-[640px]:grid-cols-1"
    >
      <Field label={t("admin.dayLabour.form.labourer")} htmlFor={id("labourer")} error={errors.labourer}>
        <Select
          value={labourer}
          onValueChange={(value) => {
            setLabourer(value);
            const pay = labourers.data?.find((one) => String(one.id) === value)?.usual_daily_pay;
            setAmount(pay ? pay.replace(".", ",") : "");
          }}
        >
          <SelectTrigger id={id("labourer")} aria-invalid={errors.labourer ? true : undefined}>
            <SelectValue placeholder={t("admin.expenses.form.choose")} />
          </SelectTrigger>
          <SelectContent>
            {pickable(labourers.data ?? [], [labourer]).map((one) => (
              <SelectItem key={one.id} value={String(one.id)}>
                {one.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label={t("admin.dayLabour.form.amount")} htmlFor={id("amount")} error={errors.amount}>
        <MoneyInput
          id={id("amount")}
          inputMode="decimal"
          className="num"
          value={amount}
          placeholder={usual ? undefined : t("admin.dayLabour.form.amountHint")}
          onChange={(event) => setAmount(event.target.value)}
          aria-invalid={errors.amount ? true : undefined}
          autoComplete="off"
        />
      </Field>
      <Field label={t("admin.dayLabour.form.lot")} htmlFor={id("batch")} error={errors.batch}>
        <Select value={lot} onValueChange={setLot}>
          <SelectTrigger id={id("batch")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_LOT}>{t("admin.dayLabour.form.noLot")}</SelectItem>
            {lotChoices.map((one) => (
              <SelectItem key={one.id} value={String(one.id)}>
                {`${one.number} · ${one.product.name}`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field label={t("admin.dayLabour.form.workType")} htmlFor={id("work_type")} error={errors.work_type}>
        <Select value={workType} onValueChange={(value) => setWorkType(value as WorkTypeEnum)}>
          <SelectTrigger id={id("work_type")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {WORK_TYPES.map((value) => (
              <SelectItem key={value} value={value}>
                {t(`admin.dayLabour.workTypes.${value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <div className="col-span-full">
        <Field label={t("admin.dayLabour.form.notes")} htmlFor={id("notes")} error={errors.notes}>
          <Input id={id("notes")} value={notes} onChange={(event) => setNotes(event.target.value)} autoComplete="off" />
        </Field>
      </div>
      {(errors.detail || errors.worked_on || errors.category) && (
        <p
          role="alert"
          className="col-span-full rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad"
        >
          {errors.detail || errors.worked_on || errors.category}
        </p>
      )}
      <div className="col-span-full flex flex-wrap justify-end gap-2">
        <Button type="submit" disabled={add.isPending}>
          <Icon name="plus" />
          {t("admin.dayLabour.form.add")}
        </Button>
        <Button variant="primary" disabled={add.isPending} onClick={() => submit(true)()}>
          {t("admin.dayLabour.form.addApprove")}
        </Button>
      </div>
    </form>
  );
}

/** One day worked in the day's dialog, with its lot and status, approved or deleted from here. */
function DayEntry({ entry, canWrite }: { entry: DayLabourEntry; canWrite: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const failed = (failure: unknown) =>
    toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.expenses.actionError"));
  const approve = useMutation({
    mutationFn: () => approveExpense(entry.expense_id),
    onSuccess: () => refreshExpenses(queryClient),
    onError: failed,
  });
  const remove = useMutation({
    mutationFn: () => deleteDayLabour(entry.id),
    onSuccess: () => refreshExpenses(queryClient),
    onError: failed,
  });
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-control border border-line p-2.5">
      <span className="font-semibold">{entry.labourer.name}</span>
      <span className="text-[0.85rem] text-ink-2">{t(`admin.dayLabour.workTypes.${entry.work_type}`)}</span>
      {entry.batch ? (
        <Link
          to={`/stock/lots/${entry.batch.id}`}
          className="num text-[0.85rem] font-semibold text-sea hover:underline"
        >
          {t("admin.dayLabour.onLot", { number: entry.batch.number, product: entry.batch.product_name })}
        </Link>
      ) : (
        <span className="text-[0.85rem] text-ink-2">{t("admin.dayLabour.general")}</span>
      )}
      <Pill tone={EXPENSE_TONES[entry.status]}>{t(`admin.expenses.statuses.${entry.status}`)}</Pill>
      <b className="num ms-auto">{formatMoney(entry.amount)}</b>
      <Link to={`/charges/${entry.expense_id}`} className="num text-[0.8rem] text-ink-2 hover:underline">
        {entry.number}
      </Link>
      {canWrite && isOpen(entry.status) && (
        <span className="flex gap-1">
          <Button
            variant="ghost"
            disabled={approve.isPending}
            aria-label={t("admin.dayLabour.approveOf", { name: entry.labourer.name })}
            onClick={() => approve.mutate()}
          >
            <Icon name="check" />
          </Button>
          {entry.status === "draft" && (
            <Button
              variant="ghost"
              disabled={remove.isPending}
              aria-label={t("admin.dayLabour.deleteOf", { name: entry.labourer.name })}
              onClick={() => remove.mutate()}
            >
              <Icon name="trash" />
            </Button>
          )}
        </span>
      )}
      {entry.notes && <p className="w-full text-[0.85rem] text-ink-2">{entry.notes}</p>}
    </li>
  );
}

/** "Calendrier journaliers": a month of days worked; a day opens who worked, on what, and what they were paid. */
export function DayLabourCalendarPage() {
  const { t, i18n } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canWriteExpenses(session);
  const [params] = useSearchParams();
  const today = todayInTunis();
  const askedDay = params.get("jour");
  const askedLot = Number(params.get("lot"));
  const initialLot = Number.isInteger(askedLot) && askedLot > 0 ? askedLot : undefined;
  const [month, setMonth] = useState<Month>(monthOf(askedDay ?? today));
  const [openDay, setOpenDay] = useState<string | null>(askedDay ?? (initialLot ? today : null));
  const bounds = monthBounds(month);
  const entries = useListDayLabour(
    { date_from: bounds.first, date_to: bounds.last },
    { query: { placeholderData: keepPreviousData } },
  );

  const byDay = new Map<string, DayLabourEntry[]>();
  for (const entry of entries.data ?? []) {
    byDay.set(entry.worked_on, [...(byDay.get(entry.worked_on) ?? []), entry]);
  }
  const counted = (entries.data ?? []).filter((entry) => entry.status !== "rejected");
  const monthTotal = sum(counted.map((entry) => entry.amount));
  const dayEntries = openDay ? (byDay.get(openDay) ?? []) : [];
  const weekdays = weekdayLabels(i18n.language);

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.dayLabour.title")} />
      <ExpensesTabs />
      <p className="text-ink-2">{t("admin.dayLabour.intro")}</p>

      <Card className="filter-bar flex flex-wrap items-center gap-2 p-3">
        <Button onClick={() => setMonth(addMonths(month, -1))} aria-label={t("admin.dayLabour.previousMonth")}>
          ‹
        </Button>
        <h2 className="min-w-44 text-center text-[1.05rem] font-bold capitalize" aria-live="polite">
          {monthLabel(month, i18n.language)}
        </h2>
        <Button onClick={() => setMonth(addMonths(month, 1))} aria-label={t("admin.dayLabour.nextMonth")}>
          ›
        </Button>
        <Button variant="ghost" onClick={() => setMonth(monthOf(today))}>
          {t("admin.dayLabour.thisMonth")}
        </Button>
        <span className="ms-auto text-ink-2">
          {t("admin.dayLabour.monthTotal", { count: counted.length })}{" "}
          <b className="num text-ink">{formatMoney(monthTotal)}</b>
        </span>
      </Card>

      {entries.isError && (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      )}

      <Card className="overflow-x-auto p-2">
        <table className="w-full min-w-[640px] table-fixed border-separate border-spacing-1">
          <thead>
            <tr>
              {weekdays.map((name) => (
                <th key={name} scope="col" className="text-[0.78rem] font-semibold text-ink-2 capitalize">
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {weeksOf(month).map((week) => (
              <tr key={week.find(Boolean) ?? "empty"}>
                {week.map((day, index) => {
                  if (day === null) return <td key={`blank-${index}`} />;
                  const list = byDay.get(day) ?? [];
                  const total = sum(list.filter((entry) => entry.status !== "rejected").map((entry) => entry.amount));
                  const lots = [...new Set(list.flatMap((entry) => (entry.batch ? [entry.batch.number] : [])))];
                  return (
                    <td key={day} className="align-top">
                      <button
                        type="button"
                        onClick={() => setOpenDay(day)}
                        aria-label={
                          list.length > 0
                            ? t("admin.dayLabour.dayLabel", {
                                date: formatDate(day),
                                count: list.length,
                                amount: formatMoney(total),
                              })
                            : formatDate(day)
                        }
                        className={cn(
                          "flex h-24 w-full flex-col items-start gap-0.5 rounded-control border border-line p-1.5 text-start hover:bg-surface-2",
                          day === today && "border-coral",
                          list.length > 0 && "bg-surface-2",
                        )}
                      >
                        <span className="num text-[0.8rem] font-semibold">{Number(day.slice(8))}</span>
                        {list.length > 0 && (
                          <>
                            <span className="text-[0.75rem] text-ink-2">
                              {t("admin.dayLabour.people", { count: list.length })}
                            </span>
                            <span className="num text-[0.8rem] font-semibold">{formatMoney(total)}</span>
                            {lots.length > 0 && (
                              <span className="num truncate text-[0.72rem] text-sea">{lots.join(" · ")}</span>
                            )}
                          </>
                        )}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Dialog open={openDay !== null} onOpenChange={(open) => !open && setOpenDay(null)}>
        {openDay && (
          <DialogContent className="max-h-[90vh] overflow-y-auto">
            <DialogTitle>{t("admin.dayLabour.dayTitle", { date: formatDate(openDay) })}</DialogTitle>
            <DialogDescription>{t("admin.dayLabour.dayBody")}</DialogDescription>
            {dayEntries.length === 0 ? (
              <p className="text-ink-2">{t("admin.dayLabour.nobody")}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {dayEntries.map((entry) => (
                  <DayEntry key={entry.id} entry={entry} canWrite={canWrite} />
                ))}
              </ul>
            )}
            {canWrite && openDay <= today && <AddDay key={openDay} day={openDay} initialLot={initialLot} />}
            {openDay > today && <p className="text-[0.85rem] text-ink-2">{t("admin.dayLabour.future")}</p>}
            <DialogFooter>
              <Button onClick={() => setOpenDay(null)}>{t("admin.dayLabour.close")}</Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}
