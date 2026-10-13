import {
  type ExpenseCategory,
  type ExpenseStatusEnum,
  createExpenseCategory,
  updateExpenseCategory,
  useGetExpenseTotals,
  useListExpenseCategories,
  useListExpenses,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  EmptyState,
  Field,
  Icon,
  Input,
  PageHeader,
  Pill,
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
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useNavigate, useOutletContext, useSearchParams } from "react-router";

import { fieldErrors } from "../lib/errors";
import { useDebounced } from "../lib/useDebounced";
import { ExpensesTabs } from "./ExpensesTabs";
import { canManageCategories, canWriteExpenses, EXPENSE_STATUSES, EXPENSE_TONES, refreshExpenses } from "./shared";

const PAGE_SIZE = 50;
const ALL = "all";

/** One category of the owner's dialog: rename it, archive or restore it (a default one is never archived). */
function CategoryRow({ category }: { category: ExpenseCategory }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const inputId = useId();
  const [name, setName] = useState(category.name);
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: (body: { name?: string; is_active?: boolean }) => updateExpenseCategory(category.id, body),
    onSuccess: async () => {
      setError("");
      toast.success(t("admin.expenses.categories.saved"));
      await refreshExpenses(queryClient);
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      setError(fromServer.name ?? fromServer.is_active ?? t("admin.expenses.actionError"));
    },
  });
  return (
    <li className="flex flex-wrap items-end gap-2">
      <Field
        label={t("admin.expenses.categories.nameOf", { name: category.name })}
        htmlFor={inputId}
        error={error}
        className="min-w-48 flex-1"
      >
        <Input
          id={inputId}
          value={name}
          onChange={(event) => setName(event.target.value)}
          className={cn(!category.is_active && "text-ink-2")}
        />
      </Field>
      <Button
        disabled={save.isPending || name.trim() === category.name}
        onClick={() => save.mutate({ name: name.trim() })}
      >
        {t("admin.expenses.categories.rename")}
      </Button>
      {!category.code && (
        <Button disabled={save.isPending} onClick={() => save.mutate({ is_active: !category.is_active })}>
          {category.is_active ? t("admin.expenses.categories.archive") : t("admin.expenses.categories.restore")}
        </Button>
      )}
    </li>
  );
}

function CategoriesDialog({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const categories = useListExpenseCategories({ status: "all" });
  const newId = useId();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const add = useMutation({
    mutationFn: (value: string) => createExpenseCategory({ name: value }),
    onSuccess: async (created) => {
      setName("");
      setError("");
      toast.success(t("admin.expenses.categories.added", { name: created.name }));
      await refreshExpenses(queryClient);
    },
    onError: (failure) => setError(fieldErrors(failure).name ?? t("admin.expenses.actionError")),
  });
  return (
    <DialogContent className="max-h-[90vh] overflow-y-auto">
      <DialogTitle>{t("admin.expenses.categories.title")}</DialogTitle>
      <DialogDescription>{t("admin.expenses.categories.body")}</DialogDescription>
      <ul className="flex flex-col gap-3">
        {(categories.data ?? []).map((category) => (
          <CategoryRow key={category.id} category={category} />
        ))}
      </ul>
      <form
        noValidate
        className="flex flex-wrap items-end gap-2 border-t border-line pt-4"
        onSubmit={(event) => {
          event.preventDefault();
          add.mutate(name.trim());
        }}
      >
        <Field label={t("admin.expenses.categories.new")} htmlFor={newId} error={error} className="min-w-48 flex-1">
          <Input id={newId} value={name} onChange={(event) => setName(event.target.value)} />
        </Field>
        <Button type="submit" variant="primary" disabled={add.isPending}>
          <Icon name="plus" />
          {t("admin.expenses.categories.add")}
        </Button>
      </form>
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.expenses.categories.close")}</Button>
      </DialogFooter>
    </DialogContent>
  );
}

/** "Dépenses": every expense with its status, filters, totals, and the way to record and approve them. */
export function ExpensesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canWrite = canWriteExpenses(session);
  // The month closing's cost lines link here with a category and a date range pre-set (D-122).
  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ExpenseStatusEnum | "">("");
  const [category, setCategory] = useState(searchParams.get("category") ?? ALL);
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") ?? "");
  const [dateTo, setDateTo] = useState(searchParams.get("date_to") ?? "");
  const [offset, setOffset] = useState(0);
  const [managing, setManaging] = useState(false);
  const query = useDebounced(search.trim());

  const categories = useListExpenseCategories({ status: "all" });
  const filters = {
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(category !== ALL ? { category: Number(category) } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    ...(query ? { search: query } : {}),
  };
  const expenses = useListExpenses(
    { limit: PAGE_SIZE, offset, ...filters },
    { query: { placeholderData: keepPreviousData } },
  );
  const totals = useGetExpenseTotals(filters, { query: { placeholderData: keepPreviousData } });
  const page = expenses.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || statusFilter !== "" || category !== ALL || dateFrom !== "" || dateTo !== "";

  const statusButton = (value: ExpenseStatusEnum | "", label: string) => (
    <button
      key={value || "all"}
      type="button"
      aria-pressed={statusFilter === value}
      onClick={() => {
        setStatusFilter(value);
        setOffset(0);
      }}
      className={cn(
        "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
        statusFilter === value && "bg-surface text-ink shadow-card",
      )}
    >
      {label}
    </button>
  );

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.finance")} title={t("admin.expenses.title")}>
        {canManageCategories(session) && (
          <Button onClick={() => setManaging(true)}>{t("admin.expenses.categories.manage")}</Button>
        )}
        {canWrite && (
          <Button variant="primary" onClick={() => void navigate("/charges/nouvelle")}>
            <Icon name="plus" />
            {t("admin.expenses.add")}
          </Button>
        )}
      </PageHeader>
      <ExpensesTabs />

      {!canWrite && <p className="text-ink-2">{t("admin.expenses.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.expenses.search")}
          placeholder={t("admin.expenses.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div
          role="group"
          aria-label={t("admin.expenses.statusFilter")}
          className="flex rounded-control bg-surface-2 p-1"
        >
          {statusButton("", t("admin.expenses.allStatuses"))}
          {EXPENSE_STATUSES.map((value) => statusButton(value, t(`admin.expenses.statuses.${value}`)))}
        </div>
        <Select
          value={category}
          onValueChange={(value) => {
            setCategory(value);
            setOffset(0);
          }}
        >
          <SelectTrigger aria-label={t("admin.expenses.categoryFilter")} className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t("admin.expenses.allCategories")}</SelectItem>
            {(categories.data ?? []).map((one) => (
              <SelectItem key={one.id} value={String(one.id)}>
                {one.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          type="date"
          aria-label={t("admin.expenses.dateFrom")}
          value={dateFrom}
          onChange={(event) => {
            setDateFrom(event.target.value);
            setOffset(0);
          }}
          className="w-40"
        />
        <Input
          type="date"
          aria-label={t("admin.expenses.dateTo")}
          value={dateTo}
          onChange={(event) => {
            setDateTo(event.target.value);
            setOffset(0);
          }}
          className="w-40"
        />
      </Card>

      {totals.data && (
        <p className="flex flex-wrap gap-x-6 gap-y-1 text-ink-2" aria-live="polite">
          <span>{t("admin.expenses.count", { count: totals.data.count })}</span>
          <span>
            {t("admin.expenses.approvedTotal")} <b className="num text-ink">{formatMoney(totals.data.approved)}</b>
          </span>
          <span>
            {t("admin.expenses.waitingTotal")} <b className="num text-ink">{formatMoney(totals.data.waiting)}</b>
          </span>
        </p>
      )}

      {expenses.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : expenses.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.expenses.noMatch")}</p>
        ) : (
          <EmptyState illustration="mix" title={t("admin.expenses.empty")}>
            {t("admin.expenses.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.expenses.columns.number")}</Th>
                <Th>{t("admin.expenses.columns.date")}</Th>
                <Th>{t("admin.expenses.columns.category")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.expenses.columns.charged")}</Th>
                <Th numeric>{t("admin.expenses.columns.amount")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((expense) => (
                <tr
                  key={expense.id}
                  onClick={() => void navigate(`/charges/${expense.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="whitespace-nowrap">
                    <Link
                      to={`/charges/${expense.id}`}
                      className="num font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {expense.number}
                    </Link>
                    <Pill className="ms-2" tone={EXPENSE_TONES[expense.status]}>
                      {t(`admin.expenses.statuses.${expense.status}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(expense.spent_on)}</Td>
                  <Td>
                    <span className="font-semibold">{expense.category.name}</span>
                    {(expense.description || expense.payee) && (
                      <div className="text-[0.8rem] text-ink-2">{expense.description || expense.payee}</div>
                    )}
                  </Td>
                  <Td className="max-[720px]:hidden">
                    {expense.batch
                      ? t("admin.expenses.onLot", { number: expense.batch.number, product: expense.batch.product_name })
                      : expense.truck
                        ? t("admin.expenses.onTruck", { name: expense.truck.name })
                        : t("admin.expenses.general")}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(expense.amount)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {page && page.count > PAGE_SIZE && (
            <div className="flex items-center justify-end gap-2 p-2">
              <span className="me-auto text-[0.85rem] text-ink-2">
                {t("admin.expenses.page", {
                  from: offset + 1,
                  to: Math.min(offset + PAGE_SIZE, page.count),
                  count: page.count,
                })}
              </span>
              <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                {t("admin.expenses.previous")}
              </Button>
              <Button disabled={!page.next} onClick={() => setOffset(offset + PAGE_SIZE)}>
                {t("admin.expenses.next")}
              </Button>
            </div>
          )}
        </Card>
      )}

      <Dialog open={managing} onOpenChange={setManaging}>
        {managing && <CategoriesDialog onDone={() => setManaging(false)} />}
      </Dialog>
    </>
  );
}
