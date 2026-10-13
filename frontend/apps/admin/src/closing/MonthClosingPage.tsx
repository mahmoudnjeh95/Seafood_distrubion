import {
  approveMonth,
  getGetMonthQueryKey,
  getListMonthsQueryKey,
  type MonthRow,
  type MonthStateEnum,
  type MonthView,
  reopenMonth,
  reviewMonth,
  useGetMonth,
  useListMonths,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useState } from "react";
import { Link, useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { canReadResults, canWriteResults } from "../partnerships/shared";
import { monthKey, monthLabel, monthRange } from "./month";

type CheckCode =
  | "expenses_approved"
  | "payroll_approved"
  | "losses_decided"
  | "sales_confirmed"
  | "cogs_matches_ledger"
  | "cash_differences"
  | "driver_days_closed";
type LedgerKind =
  "receipt" | "customer_return" | "supplier_return" | "sale" | "loss" | "count_correction" | "adjustment";

const STATE_TONE: Record<MonthStateEnum, "neutral" | "good" | "warn"> = {
  open: "neutral",
  reviewed: "warn",
  approved: "good",
};

function Line({
  label,
  amount,
  strong,
  sign,
  to,
}: {
  label: ReactNode;
  amount: string;
  strong?: boolean;
  sign?: string;
  // Where this figure comes from: the line becomes a link to it (D-122).
  to?: string;
}) {
  return (
    <div className={cn("flex items-baseline gap-3 px-2.5 py-1.5", strong && "border-t border-line font-semibold")}>
      <span className="me-auto">
        {sign && <span className="me-2 inline-block w-3 text-ink-2">{sign}</span>}
        {to ? (
          <Link to={to} className="text-sea hover:underline">
            {label}
          </Link>
        ) : (
          label
        )}
      </span>
      <span className="num">{formatMoney(amount)}</span>
    </div>
  );
}

function Checks({ view }: { view: MonthView }) {
  const { t } = useTranslation();
  return (
    <Card className="flex flex-col gap-1 p-4">
      <CardTitle>{t("admin.monthClosing.checks.title")}</CardTitle>
      <ul className="flex flex-col gap-1">
        {view.report.checks.map((check) => {
          const tracked = check.code !== "cash_differences" && check.code !== "driver_days_closed";
          return (
            <li key={check.code} className="flex flex-wrap items-baseline gap-2">
              <Pill tone={!tracked ? "neutral" : check.ok ? "good" : check.blocking ? "bad" : "warn"}>
                {!tracked
                  ? t("admin.monthClosing.checks.notTracked")
                  : check.ok
                    ? t("admin.monthClosing.checks.ok")
                    : check.blocking
                      ? t("admin.monthClosing.checks.blocking")
                      : t("admin.monthClosing.checks.warning")}
              </Pill>
              <span>{t(`admin.monthClosing.checks.codes.${check.code as CheckCode}`)}</span>
              {!check.ok && check.count !== null && check.count > 0 && (
                <span className="num text-ink-2">
                  {check.count}
                  {check.amount && Number(check.amount) !== 0 ? ` · ${formatMoney(check.amount)}` : ""}
                </span>
              )}
              {!check.ok && check.code === "cogs_matches_ledger" && check.amount && (
                <span className="num text-ink-2">{formatMoney(check.amount)}</span>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function ResultCard({ view }: { view: MonthView }) {
  const { t } = useTranslation();
  const report = view.report;
  const range = monthRange(report.month);
  return (
    <Card className="flex flex-col p-4">
      <CardTitle>{t("admin.monthClosing.result.title")}</CardTitle>
      <p className="px-2.5 pb-2 text-[0.88rem] text-ink-2">{t("admin.monthClosing.result.hint")}</p>
      <Line
        label={t("admin.monthClosing.result.sales", {
          count: report.sales.count,
          quantity: formatQuantity(report.sales.quantity),
        })}
        amount={report.sales.revenue}
        to="/ventes"
      />
      <Line label={t("admin.monthClosing.result.cogs")} amount={report.cogs} sign="−" />
      <Line label={t("admin.monthClosing.result.grossMargin")} amount={report.gross_margin} strong />
      <Line
        label={t("admin.monthClosing.result.spoilage", { quantity: formatQuantity(report.spoilage.quantity) })}
        amount={report.spoilage.value}
        sign="−"
        to="/stock/pertes"
      />
      <Line label={t("admin.monthClosing.result.expenses")} amount={report.expenses.total} sign="−" to="/charges" />
      <Line
        label={t("admin.monthClosing.result.personnel")}
        amount={report.personnel}
        sign="−"
        to="/salaires/employes"
      />
      <Line label={t("admin.monthClosing.result.net")} amount={report.net_result} strong />
      {report.expenses.categories.length > 0 && (
        <div className="mt-3 flex flex-col">
          <h3 className="px-2.5 pb-1 text-[0.85rem] font-semibold text-ink-2">
            {t("admin.monthClosing.result.byCategory")}
          </h3>
          {report.expenses.categories.map((category) => (
            <Line
              key={category.category_id}
              label={`${category.name} (${category.count})`}
              amount={category.total}
              to={`/charges?category=${category.category_id}&date_from=${range.from}&date_to=${range.to}`}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

/** Each partner's part of the month's shared costs: rent, electricity, fuel, salaries and the lot's other
 * costs are split over the lots in stock (D-041), including partnership lots, exactly like an own-stock
 * lot. This is the raw cost their lots carried, by category — not weighted by their profit or loss % — so
 * it answers "where did this charge go" (owner request, 2026-10-13, D-122). */
function PartnerCostsCard({ view }: { view: MonthView }) {
  const { t } = useTranslation();
  const shares = view.report.partner_costs;
  const range = monthRange(view.report.month);
  if (shares.length === 0) return null;
  return (
    <Card className="flex flex-col p-4">
      <CardTitle>{t("admin.monthClosing.partnerCosts.title")}</CardTitle>
      <p className="px-2.5 pb-2 text-[0.88rem] text-ink-2">{t("admin.monthClosing.partnerCosts.hint")}</p>
      <div className="flex flex-col gap-3">
        {shares.map((share) => (
          <div key={share.partner_id} className="flex flex-col">
            <div className="flex items-baseline gap-3 px-2.5 py-1">
              <Link to={`/fournisseurs/${share.partner_id}`} className="me-auto font-semibold text-sea hover:underline">
                {share.partner_name}
              </Link>
              <span className="num font-semibold">{formatMoney(share.total)}</span>
            </div>
            <div className="flex flex-col ps-3">
              {share.categories.map((category) => (
                <Line
                  key={category.key}
                  label={`${category.is_employee ? t("admin.monthClosing.partnerCosts.salaries") : category.name} (${category.count})`}
                  amount={category.amount}
                  to={
                    category.is_employee
                      ? "/salaires/employes"
                      : category.category_id !== null
                        ? `/charges?category=${category.category_id}&date_from=${range.from}&date_to=${range.to}`
                        : undefined
                  }
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function StockCard({ view }: { view: MonthView }) {
  const { t } = useTranslation();
  const stock = view.report.stock;
  return (
    <Card className="flex flex-col p-4">
      <CardTitle>{t("admin.monthClosing.stock.title")}</CardTitle>
      <p className="px-2.5 pb-2 text-[0.88rem] text-ink-2">{t("admin.monthClosing.stock.hint")}</p>
      <Line label={t("admin.monthClosing.stock.opening")} amount={stock.opening_value} />
      {stock.ledger.map((row) => (
        <Line
          key={row.kind}
          sign={Number(row.value) < 0 ? "−" : "+"}
          label={`${t(`admin.monthClosing.stock.kinds.${row.kind as LedgerKind}`)} (${formatQuantity(row.quantity.replace("-", ""))})`}
          amount={row.value.replace("-", "")}
        />
      ))}
      <Line label={t("admin.monthClosing.stock.closing")} amount={stock.closing_value} strong />
      {Number(stock.rounding_difference) !== 0 && (
        <p className="px-2.5 pt-1 text-[0.82rem] text-ink-2">
          {t("admin.monthClosing.stock.rounding", { amount: formatMoney(stock.rounding_difference) })}
        </p>
      )}
      {stock.rows.length > 0 && (
        <div className="mt-3">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.monthClosing.stock.columns.lot")}</Th>
                <Th>{t("admin.monthClosing.stock.columns.product")}</Th>
                <Th numeric>{t("admin.monthClosing.stock.columns.quantity")}</Th>
                <Th numeric>{t("admin.monthClosing.stock.columns.cost")}</Th>
                <Th numeric>{t("admin.monthClosing.stock.columns.value")}</Th>
              </tr>
            </thead>
            <tbody>
              {stock.rows.map((row) => (
                <tr key={row.batch_id}>
                  <Td className="num whitespace-nowrap">
                    <Link to={`/stock/lots/${row.batch_id}`} className="text-sea hover:underline">
                      {row.batch_number}
                    </Link>
                  </Td>
                  <Td>
                    {row.product_name}
                    <span className="block text-[0.8rem] text-ink-2">{row.supplier_name}</span>
                  </Td>
                  <Td numeric>{formatQuantity(row.quantity)}</Td>
                  <Td numeric>{formatMoney(row.unit_cost)}</Td>
                  <Td numeric>{formatMoney(row.value)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
    </Card>
  );
}

function ReopenDialog({ month, onClose }: { month: string; onClose: () => void }) {
  const { t } = useTranslation();
  const formId = useId();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => reopenMonth(month, { reason: reason.trim() }),
    onSuccess: async () => {
      toast.success(t("admin.monthClosing.reopen.done"));
      await queryClient.invalidateQueries({ queryKey: getGetMonthQueryKey(month) });
      await queryClient.invalidateQueries({ queryKey: getListMonthsQueryKey() });
      onClose();
    },
    onError: (failure) => setError(fieldErrors(failure).reason ?? t("admin.monthClosing.reopen.error")),
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{t("admin.monthClosing.reopen.title")}</DialogTitle>
        <DialogDescription>{t("admin.monthClosing.reopen.body")}</DialogDescription>
        <Field label={t("admin.monthClosing.reopen.reason")} htmlFor={`${formId}-reason`} error={error}>
          <Input
            id={`${formId}-reason`}
            value={reason}
            maxLength={300}
            onChange={(event) => setReason(event.target.value)}
            aria-invalid={error ? true : undefined}
          />
        </Field>
        <DialogFooter>
          <Button onClick={onClose}>{t("admin.monthClosing.reopen.keep")}</Button>
          <Button variant="danger" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
            {t("admin.monthClosing.reopen.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MonthDetail({ month, session }: { month: string; session: Session }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const view = useGetMonth(month);
  const [reopening, setReopening] = useState(false);
  const owner = canWriteResults(session);
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: getGetMonthQueryKey(month) });
    await queryClient.invalidateQueries({ queryKey: getListMonthsQueryKey() });
  };
  const failed = (failure: unknown) => {
    const found = fieldErrors(failure);
    const first = Object.values(found)[0];
    toast.error(first ?? t("admin.monthClosing.actionError"));
  };
  const review = useMutation({
    mutationFn: () => reviewMonth(month, {}),
    onSuccess: async () => {
      toast.success(t("admin.monthClosing.reviewed"));
      await refresh();
    },
    onError: failed,
  });
  const approve = useMutation({
    mutationFn: () => approveMonth(month),
    onSuccess: async () => {
      toast.success(t("admin.monthClosing.approved"));
      await refresh();
    },
    onError: failed,
  });

  if (view.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (view.isError || !view.data) {
    return (
      <p role="alert" className="text-bad">
        {t("admin.monthClosing.loadError")}
      </p>
    );
  }
  const data = view.data;
  const closing = data.closing;
  const drift = data.live_net_result !== null && data.live_net_result !== data.report.net_result;
  return (
    <section aria-labelledby="month-title" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="month-title" className="me-auto capitalize">
          {monthLabel(data.month)}
        </h2>
        <Pill tone={STATE_TONE[data.state]}>{t(`admin.monthClosing.states.${data.state}`)}</Pill>
        {data.can_review && (
          <Button disabled={review.isPending} onClick={() => review.mutate()}>
            {data.state === "reviewed" ? t("admin.monthClosing.reviewAgain") : t("admin.monthClosing.review")}
          </Button>
        )}
        {owner && data.can_approve && (
          <Button variant="primary" disabled={approve.isPending} onClick={() => approve.mutate()}>
            {t("admin.monthClosing.approve")}
          </Button>
        )}
        {owner && closing && (
          <Button variant="danger" onClick={() => setReopening(true)}>
            {t("admin.monthClosing.reopenAction")}
          </Button>
        )}
      </div>

      {!data.is_over && <p className="text-ink-2">{t("admin.monthClosing.notOver")}</p>}
      {data.state === "reviewed" && closing && (
        <p>
          {t("admin.monthClosing.reviewedBy", {
            name: closing.reviewed_by_name,
            date: formatDate(closing.reviewed_at),
          })}
          {!owner && ` ${t("admin.monthClosing.waitsOwner")}`}
          {owner && !data.can_approve && ` ${t("admin.monthClosing.reviewStale")}`}
        </p>
      )}
      {data.state === "approved" && closing?.approved_at && (
        <p>
          {t("admin.monthClosing.approvedBy", {
            name: closing.approved_by_name,
            date: formatDate(closing.approved_at),
          })}
        </p>
      )}
      {drift && data.live_net_result !== null && (
        <p role="status" className="rounded-control bg-warn-soft px-3 py-2 text-warn">
          {t("admin.monthClosing.drift", {
            frozen: formatMoney(data.report.net_result),
            now: formatMoney(data.live_net_result),
          })}
        </p>
      )}

      <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] items-start gap-4 max-[1000px]:grid-cols-1">
        <div className="flex flex-col gap-4">
          <ResultCard view={data} />
          <PartnerCostsCard view={data} />
          <StockCard view={data} />
        </div>
        <div className="flex flex-col gap-4">
          <Checks view={data} />
          {data.history.length > 0 && (
            <Card className="flex flex-col gap-1 p-4">
              <CardTitle>{t("admin.monthClosing.history")}</CardTitle>
              {data.history.map((row) => (
                <p key={row.id} className="text-[0.88rem]">
                  {t("admin.monthClosing.historyLine", {
                    name: row.reopened_by_name,
                    date: row.reopened_at ? formatDate(row.reopened_at) : "",
                    reason: row.reopen_reason,
                  })}
                </p>
              ))}
            </Card>
          )}
        </div>
      </div>
      {reopening && <ReopenDialog month={month} onClose={() => setReopening(false)} />}
    </section>
  );
}

/** "Clôture mensuelle" (P6-T06, D-074): the accountant checks a finished month, the owner approves it and it
 * is frozen. The figures are the month's sales, cost of goods sold (never purchases), spoilage, expenses,
 * payroll and the stock valued at month-end (P6-T05, D-073). */
export function MonthClosingPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const allowed = canReadResults(session);
  const months = useListMonths({ query: { enabled: allowed } });
  const [chosen, setChosen] = useState<string | null>(null);

  if (!allowed) {
    return (
      <>
        <PageHeader eyebrow={t("admin.monthClosing.eyebrow")} title={t("admin.monthClosing.title")} />
        <EmptyState illustration="mix" title={t("admin.monthClosing.restricted")} />
      </>
    );
  }
  const rows: readonly MonthRow[] = months.data ?? [];
  // The latest month that is over, unless the person chose another.
  const selected = chosen ?? monthKey((rows.find((row) => row.is_over) ?? rows[0])?.month ?? "");
  return (
    <>
      <PageHeader eyebrow={t("admin.monthClosing.eyebrow")} title={t("admin.monthClosing.title")} />
      <p className="text-ink-2">{t("admin.monthClosing.intro")}</p>
      <div role="group" aria-label={t("admin.monthClosing.months")} className="flex flex-wrap gap-2">
        {rows.map((row) => {
          const key = monthKey(row.month);
          return (
            <button
              key={key}
              type="button"
              aria-pressed={selected === key}
              onClick={() => setChosen(key)}
              className={cn(
                "flex flex-col rounded-control border border-line bg-surface px-3 py-2 text-start",
                selected === key && "border-sea shadow-card",
              )}
            >
              <span className="font-semibold capitalize">{monthLabel(row.month)}</span>
              <span className="mt-0.5 flex items-center gap-2 text-[0.8rem]">
                <Pill tone={STATE_TONE[row.state]}>{t(`admin.monthClosing.states.${row.state}`)}</Pill>
                {row.net_result !== null && <span className="num text-ink-2">{formatMoney(row.net_result)}</span>}
              </span>
            </button>
          );
        })}
      </div>
      {selected && <MonthDetail key={selected} month={selected} session={session} />}
    </>
  );
}
