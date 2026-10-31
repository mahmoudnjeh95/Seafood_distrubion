import {
  type ChangedFigure,
  type DayClosingRow,
  type DayProduct,
  type DayReopening,
  type DaySummary,
  useApproveDayClosing,
  useCountDayClosing,
  useGetDayClosing,
  useListDayClosings,
  useListSyncProblems,
  useResolveSyncProblem,
  useRequestDayJustification,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatQuantity,
  parseDecimalInput,
  useTranslation,
} from "@frutti/i18n";
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
  Input,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { useDebounced } from "../lib/useDebounced";
import { DaysOverview } from "./DaysOverview";

const STATUSES = ["submitted", "justification", "reopened", "approved"] as const;
const TONES = { submitted: "warn", justification: "bad", reopened: "sea", approved: "good" } as const;

/** The office's count, or a dash before the office counted (D-213). */
function countedOrDash(value: string | null): string {
  return value === null ? "—" : formatMoney(value);
}

function gapOrDash(value: string | null): string {
  return value === null ? "—" : signed(value);
}

function signed(value: string): string {
  return `${Number(value) > 0 ? "+" : ""}${formatMoney(value)}`;
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <p className="flex justify-between gap-3">
      <span className="text-ink-2">{label}</span>
      <span className="num font-semibold">{value}</span>
    </p>
  );
}

/** The opening stock and the gap of a product (D-130): a day sent before they existed has neither. */
function stockOf(product: DayProduct): { opening?: string; unexplained?: string } {
  const kept: Partial<Pick<DayProduct, "opening" | "unexplained">> = product;
  return { opening: kept.opening, unexplained: kept.unexplained };
}

const PRODUCT_FIGURES: ReadonlySet<ChangedFigure["figure"]> = new Set([
  "opening",
  "loaded",
  "sold",
  "lost",
  "returned",
  "remaining",
]);

function changedValue(change: ChangedFigure, value: string): string {
  if (change.figure === "sales_count") return String(Number(value));
  return PRODUCT_FIGURES.has(change.figure) ? formatQuantity(value) : formatMoney(value);
}

/** The cash counted at the sends a new load undid: it is with the office (D-134). A day sent before the figure
 * existed has none in its kept figures. */
function handedOverOf(summary: DaySummary): string | null {
  const kept: Partial<Pick<DaySummary, "handed_over">> = summary;
  return kept.handed_over !== undefined && Number(kept.handed_over) !== 0 ? kept.handed_over : null;
}

/** A day a new load opened again (D-134): the driver sells and will send it again, so the figures shown are
 * those of the send the load undid. Below, every send undone that day, as it was: its cash is with the office. */
function Reopenings({ reopened, sends }: { reopened: boolean; sends: readonly DayReopening[] }) {
  const { t } = useTranslation();
  if (!reopened && sends.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {reopened && (
        <div role="status" className="flex flex-col gap-1 rounded-control bg-sea-soft px-3 py-2">
          <p className="font-semibold text-sea">{t("admin.dayClosings.reopened.title")}</p>
          <p className="text-[0.88rem]">{t("admin.dayClosings.reopened.body")}</p>
        </div>
      )}
      {sends.length > 0 && (
        <>
          <p className="font-semibold">{t("admin.dayClosings.reopened.earlier")}</p>
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.dayClosings.reopened.sentAt")}</Th>
                <Th>{t("admin.dayClosings.reopened.was")}</Th>
                <Th className="text-end">{t("admin.dayClosings.expected")}</Th>
                <Th className="text-end">{t("admin.dayClosings.officeCounted")}</Th>
                <Th className="text-end">{t("admin.dayClosings.difference")}</Th>
                <Th>{t("admin.dayClosings.reopened.load")}</Th>
              </tr>
            </thead>
            <tbody>
              {sends.map((send) => (
                <tr key={send.reopened_at}>
                  <Td>{formatDateTime(send.submitted_at)}</Td>
                  <Td>
                    {send.status === "approved" && send.reviewed_by_name !== ""
                      ? t("admin.dayClosings.reopened.approvedBy", { name: send.reviewed_by_name })
                      : t(`admin.dayClosings.statuses.${send.status}`)}
                  </Td>
                  <Td className="num text-end">{formatMoney(send.expected_cash)}</Td>
                  <Td className="num text-end font-semibold">{countedOrDash(send.counted_cash)}</Td>
                  <Td className="num text-end">{gapOrDash(send.difference)}</Td>
                  <Td>
                    {send.load_number} · {formatDateTime(send.reopened_at)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}
    </div>
  );
}

/** What the records say now against what the driver sent (D-132, D-134): a sale received after the send, or a
 * correction by the office. The office cannot approve until the driver sends the day again. */
function ChangesSinceSent({ changes }: { changes: readonly ChangedFigure[] }) {
  const { t } = useTranslation();
  if (changes.length === 0) return null;
  return (
    <div role="status" className="flex flex-col gap-2 rounded-control bg-warn-soft px-3 py-2">
      <p className="font-semibold text-warn">{t("admin.dayClosings.changed.title")}</p>
      <p className="text-[0.88rem]">{t("admin.dayClosings.changed.body")}</p>
      <Table>
        <thead>
          <tr>
            <Th>{t("admin.dayClosings.changed.figure")}</Th>
            <Th className="text-end">{t("admin.dayClosings.changed.sent")}</Th>
            <Th className="text-end">{t("admin.dayClosings.changed.live")}</Th>
          </tr>
        </thead>
        <tbody>
          {changes.map((change) => (
            <tr key={`${change.figure}-${change.product_name}`}>
              <Td>
                {t(`admin.dayClosings.changed.figures.${change.figure}`)}
                {change.product_name === "" ? "" : ` · ${change.product_name}`}
              </Td>
              <Td className="num text-end">{changedValue(change, change.sent)}</Td>
              <Td className="num text-end font-semibold">{changedValue(change, change.live)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

function ClosingDialog({ id, canDecide, onDone }: { id: number; canDecide: boolean; onDone: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const closing = useGetDayClosing(id);
  const [reason, setReason] = useState("");
  const [asking, setAsking] = useState(false);
  // The cash the office counts when the driver hands it over (D-213), and why it differs, if it does.
  const [officeCash, setOfficeCash] = useState("");
  const [officePurchase, setOfficePurchase] = useState("");
  const [gapNote, setGapNote] = useState("");
  const refresh = () => {
    void queryClient.invalidateQueries();
  };
  const approve = useApproveDayClosing({
    mutation: {
      onSuccess: () => {
        toast.success(t("admin.dayClosings.approved"));
        refresh();
        onDone();
      },
      onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.dayClosings.error")),
    },
  });
  const count = useCountDayClosing({
    mutation: {
      onSuccess: () => {
        toast.success(t("admin.dayClosings.countSaved"));
        refresh();
      },
      onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.dayClosings.error")),
    },
  });
  const ask = useRequestDayJustification({
    mutation: {
      onSuccess: () => {
        toast.success(t("admin.dayClosings.asked"));
        refresh();
        onDone();
      },
      onError: () => toast.error(t("admin.dayClosings.error")),
    },
  });
  const data = closing.data;
  const handedOver = data ? handedOverOf(data.summary) : null;
  const hasPurchases =
    data !== undefined && (data.summary.purchases_count > 0 || Number(data.summary.purchase_float) !== 0);
  const officeCashValue = parseDecimalInput(officeCash.trim(), 3);
  const officePurchaseValue = hasPurchases ? parseDecimalInput(officePurchase.trim() || "0", 3) : null;
  // What the office counted: the figures typed now, else the ones already saved by the count.
  const cashCounted = officeCashValue ?? data?.office_counted_cash ?? null;
  const purchaseCounted = hasPurchases ? (officePurchaseValue ?? data?.office_counted_purchase_cash ?? null) : null;
  // Office count - what the driver should hold, in millimes so no float adds up money.
  const gapOf = (office: string | null, expected: string | undefined) =>
    office === null || expected === undefined
      ? 0
      : Math.round(Number(office) * 1000) - Math.round(Number(expected) * 1000);
  const officeGap = gapOf(cashCounted, data?.expected_cash);
  const officePurchaseGap = gapOf(purchaseCounted, data?.expected_purchase_cash);
  const gapToExplain = officeGap !== 0 || officePurchaseGap !== 0;
  const readyToApprove = cashCounted !== null && (!gapToExplain || gapNote.trim() !== "");
  return (
    <DialogContent className="w-[min(1100px,calc(100vw-2rem))] max-w-none">
      <DialogTitle>{data ? `${data.truck_name} · ${formatDate(data.date)}` : t("common.loading")}</DialogTitle>
      <DialogDescription>{data?.driver_name ?? ""}</DialogDescription>
      {data && (
        <div className="flex flex-col gap-4">
          <Reopenings reopened={data.status === "reopened"} sends={data.reopenings} />
          <div className="space-y-1">
            <Line
              label={t("admin.dayClosings.sales", { count: data.summary.sales_count })}
              value={formatMoney(data.summary.sales_total)}
            />
            <Line label={t("admin.dayClosings.cash")} value={formatMoney(data.summary.cash_received)} />
            <Line label={t("admin.dayClosings.payments")} value={formatMoney(data.summary.payments_cash ?? "0.000")} />
            <Line label={t("admin.dayClosings.other")} value={formatMoney(data.summary.other_payments)} />
            <Line label={t("admin.dayClosings.credit")} value={formatMoney(data.summary.on_credit)} />
            <Line label={t("admin.dayClosings.expenses")} value={formatMoney(data.summary.expenses_total)} />
            {/* Not taken from the cash (D-205): paid out of the driver's pocket (owed back), or by card. */}
            {Number(data.summary.expenses_pocket ?? "0") !== 0 && (
              <Line
                label={t("admin.dayClosings.expensesPocket")}
                value={formatMoney(data.summary.expenses_pocket ?? "0")}
              />
            )}
            {Number(data.summary.expenses_other ?? "0") !== 0 && (
              <Line
                label={t("admin.dayClosings.expensesOther")}
                value={formatMoney(data.summary.expenses_other ?? "0")}
              />
            )}
            <Line label={t("admin.dayClosings.opening")} value={formatMoney(data.summary.opening_cash)} />
            {handedOver !== null && <Line label={t("admin.dayClosings.handedOver")} value={formatMoney(handedOver)} />}
            <Line label={t("admin.dayClosings.expected")} value={formatMoney(data.expected_cash)} />
            {data.office_counted_cash !== null && (
              <>
                <Line label={t("admin.dayClosings.officeCounted")} value={formatMoney(data.office_counted_cash)} />
                <Line label={t("admin.dayClosings.officeGap")} value={signed(data.office_difference)} />
              </>
            )}
          </div>
          {/* Purchases at the port and their money, counted apart (D-158); a day without them shows nothing. */}
          {(data.summary.purchases_count > 0 || Number(data.summary.purchase_float) !== 0) && (
            <div className="space-y-1">
              <p className="font-semibold">{t("admin.dayClosings.purchases.title")}</p>
              <Line
                label={t("admin.dayClosings.purchases.count", { count: data.summary.purchases_count })}
                value={formatMoney(data.summary.purchases_total)}
              />
              <Line label={t("admin.dayClosings.purchases.float")} value={formatMoney(data.summary.purchase_float)} />
              <Line label={t("admin.dayClosings.purchases.cash")} value={formatMoney(data.summary.purchases_cash)} />
              <Line label={t("admin.dayClosings.purchases.other")} value={formatMoney(data.summary.purchases_other)} />
              {Number(data.summary.purchases_from_sales) !== 0 && (
                <Line
                  label={t("admin.dayClosings.purchases.fromSales")}
                  value={formatMoney(data.summary.purchases_from_sales)}
                />
              )}
              {Number(data.summary.owed_to_driver) > 0 && (
                <Line label={t("admin.dayClosings.purchases.owed")} value={formatMoney(data.summary.owed_to_driver)} />
              )}
              <Line
                label={t("admin.dayClosings.purchases.expected")}
                value={formatMoney(data.expected_purchase_cash)}
              />
              <Line
                label={t("admin.dayClosings.purchases.counted")}
                value={countedOrDash(data.office_counted_purchase_cash)}
              />
              <Line
                label={t("admin.dayClosings.purchases.difference")}
                value={signed(data.office_purchase_difference)}
              />
            </div>
          )}
          <ChangesSinceSent changes={data.changes_since_sent} />
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.dayClosings.product")}</Th>
                <Th className="text-end">{t("admin.dayClosings.stockOpening")}</Th>
                <Th className="text-end">{t("admin.dayClosings.loaded")}</Th>
                <Th className="text-end">{t("admin.dayClosings.sold")}</Th>
                <Th className="text-end">{t("admin.dayClosings.lost")}</Th>
                <Th className="text-end">{t("admin.dayClosings.returned")}</Th>
                <Th className="text-end">{t("admin.dayClosings.left")}</Th>
                <Th className="text-end">{t("admin.dayClosings.unexplained")}</Th>
              </tr>
            </thead>
            <tbody>
              {data.summary.products.map((product) => {
                // The truck's stock when the day started and the gap the records do not explain (D-130), as sent.
                const { opening, unexplained } = stockOf(product);
                return (
                  <tr key={product.product_id}>
                    <Td>{product.product_name}</Td>
                    <Td className="num text-end">{opening === undefined ? "" : formatQuantity(opening)}</Td>
                    <Td className="num text-end">{formatQuantity(product.loaded)}</Td>
                    <Td className="num text-end">{formatQuantity(product.sold)}</Td>
                    <Td className="num text-end">{formatQuantity(product.lost)}</Td>
                    <Td className="num text-end">{formatQuantity(product.returned)}</Td>
                    <Td className="num text-end">{formatQuantity(product.remaining)}</Td>
                    <Td className={cn("num text-end", Number(unexplained ?? 0) !== 0 && "font-semibold text-bad")}>
                      {unexplained === undefined ? "" : formatQuantity(unexplained)}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          {data.driver_note !== "" && (
            <p>
              <span className="text-ink-2">{t("admin.dayClosings.driverNote")} : </span>
              {data.driver_note}
            </p>
          )}
          {data.review_note !== "" && (
            <p>
              <span className="text-ink-2">{t("admin.dayClosings.reviewNote")} : </span>
              {data.review_note}
            </p>
          )}
          {canDecide && data.status === "submitted" && !asking && (
            <fieldset className="flex flex-col gap-2 rounded-card border border-line p-3">
              <legend className="px-1 font-semibold">{t("admin.dayClosings.officeCount")}</legend>
              <p className="text-[0.85rem] text-ink-2">{t("admin.dayClosings.officeCountHint")}</p>
              <div className="flex flex-wrap items-end gap-4">
                <label className="flex flex-col gap-1">
                  <span className="text-[0.85rem] font-semibold">{t("admin.dayClosings.officeCash")}</span>
                  <Input
                    inputMode="decimal"
                    className="num max-w-40"
                    value={officeCash}
                    onChange={(event) => setOfficeCash(event.target.value)}
                  />
                </label>
                {hasPurchases && (
                  <label className="flex flex-col gap-1">
                    <span className="text-[0.85rem] font-semibold">{t("admin.dayClosings.officePurchase")}</span>
                    <Input
                      inputMode="decimal"
                      className="num max-w-40"
                      value={officePurchase}
                      onChange={(event) => setOfficePurchase(event.target.value)}
                    />
                  </label>
                )}
              </div>
              {officeCashValue !== null && (
                <p className={cn("font-semibold", officeGap === 0 ? "text-good" : "text-bad")}>
                  {t("admin.dayClosings.officeGapLive", {
                    office: formatMoney(officeCashValue),
                    expected: formatMoney(data.expected_cash),
                    gap: signed((officeGap / 1000).toFixed(3)),
                  })}
                </p>
              )}
              {hasPurchases && officePurchaseValue !== null && officePurchaseGap !== 0 && (
                <p className="font-semibold text-bad">
                  {t("admin.dayClosings.officePurchaseGapLive", {
                    gap: signed((officePurchaseGap / 1000).toFixed(3)),
                  })}
                </p>
              )}
              {gapToExplain && (
                <Input
                  aria-label={t("admin.dayClosings.gapNote")}
                  placeholder={t("admin.dayClosings.gapNote")}
                  value={gapNote}
                  onChange={(event) => setGapNote(event.target.value)}
                />
              )}
            </fieldset>
          )}
          {canDecide && data.status === "submitted" && asking && (
            <Input
              aria-label={t("admin.dayClosings.reason")}
              placeholder={t("admin.dayClosings.reason")}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </div>
      )}
      <DialogFooter>
        <Button onClick={onDone}>{t("admin.dayClosings.close")}</Button>
        {canDecide && data?.status === "submitted" && (
          <>
            {asking ? (
              <Button
                disabled={reason.trim() === "" || ask.isPending}
                onClick={() => ask.mutate({ closingId: id, data: { reason } })}
              >
                {t("admin.dayClosings.sendQuestion")}
              </Button>
            ) : (
              <Button onClick={() => setAsking(true)}>{t("admin.dayClosings.askWhy")}</Button>
            )}
            <Button
              disabled={count.isPending || data.changed_since_sent || officeCashValue === null}
              onClick={() => {
                if (officeCashValue === null) return;
                count.mutate({
                  closingId: id,
                  data: {
                    office_counted_cash: officeCashValue,
                    office_counted_purchase_cash: hasPurchases ? officePurchaseValue : null,
                  },
                });
              }}
            >
              {t("admin.dayClosings.saveCount")}
            </Button>
            <Button
              variant="primary"
              disabled={approve.isPending || data.changed_since_sent || !readyToApprove}
              onClick={() =>
                approve.mutate({
                  closingId: id,
                  data: {
                    office_counted_cash: officeCashValue,
                    office_counted_purchase_cash: hasPurchases ? officePurchaseValue : null,
                    note: gapNote.trim(),
                  },
                })
              }
            >
              {t("admin.dayClosings.approve")}
            </Button>
          </>
        )}
      </DialogFooter>
    </DialogContent>
  );
}

function SyncProblems({ canDecide }: { canDecide: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const problems = useListSyncProblems();
  const resolve = useResolveSyncProblem({
    mutation: {
      onSuccess: () => {
        toast.success(t("admin.dayClosings.problems.handled"));
        void queryClient.invalidateQueries();
      },
      onError: () => toast.error(t("admin.dayClosings.error")),
    },
  });
  const list = problems.data ?? [];
  if (list.length === 0) return null;
  return (
    <Card className="p-2">
      <h2 className="px-3 pt-2">{t("admin.dayClosings.problems.title")}</h2>
      <p className="px-3 pb-2 text-ink-2">{t("admin.dayClosings.problems.body")}</p>
      <Table>
        <thead>
          <tr>
            <Th>{t("admin.dayClosings.date")}</Th>
            <Th>{t("admin.dayClosings.problems.driver")}</Th>
            <Th>{t("admin.dayClosings.problems.what")}</Th>
            <Th>{t("admin.dayClosings.problems.reason")}</Th>
            {canDecide && <Th />}
          </tr>
        </thead>
        <tbody>
          {list.map((problem) => (
            <tr key={problem.id}>
              <Td>{formatDate(problem.created_at)}</Td>
              <Td>{problem.driver_name}</Td>
              <Td>
                {t(
                  `admin.dayClosings.problems.kinds.${problem.kind as "sale" | "expense" | "loss" | "payment" | "pickup" | "purchase" | "delivery" | "not_delivered"}`,
                )}{" "}
                · {problem.label}
              </Td>
              <Td>{problem.reason}</Td>
              {canDecide && (
                <Td>
                  <Button disabled={resolve.isPending} onClick={() => resolve.mutate({ problemId: problem.id })}>
                    {t("admin.dayClosings.problems.done")}
                  </Button>
                </Td>
              )}
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

/** "Journées des chauffeurs": what each driver is doing now, and the days they sent, to check and approve. */
export function DayClosingsPage() {
  const { t } = useTranslation();
  const [view, setView] = useState<"overview" | "closings">("overview");
  const tab = (value: typeof view, label: string) => (
    <button
      key={value}
      type="button"
      aria-pressed={view === value}
      onClick={() => setView(value)}
      className={cn(
        "rounded-[7px] px-4 py-1.5 text-[0.9rem] font-semibold text-ink-2",
        view === value && "bg-surface text-ink shadow-card",
      )}
    >
      {label}
    </button>
  );
  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.dayClosings.title")} />
      <div className="mb-4 flex w-fit rounded-control bg-surface-2 p-1">
        {tab("overview", t("admin.dayOverview.tabs.overview"))}
        {tab("closings", t("admin.dayOverview.tabs.closings"))}
      </div>
      {view === "overview" ? <DaysOverview /> : <ClosingsList />}
    </>
  );
}

/** The days drivers sent, to check and approve (P3-T06), and their history (D-134). */
function ClosingsList() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canDecide = session.role === "owner" || session.role === "manager";
  const [status, setStatus] = useState<(typeof STATUSES)[number] | "">("submitted");
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const query = useDebounced(search.trim());
  // "Toutes" with a driver and dates is the history of the drivers' days (D-134).
  const closings = useListDayClosings({
    ...(status ? { status } : {}),
    ...(query ? { search: query } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  });
  const list: readonly DayClosingRow[] = closings.data ?? [];

  const statusButton = (value: (typeof STATUSES)[number] | "", label: string) => (
    <button
      key={value || "all"}
      type="button"
      aria-pressed={status === value}
      onClick={() => setStatus(value)}
      className={cn(
        "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
        status === value && "bg-surface text-ink shadow-card",
      )}
    >
      {label}
    </button>
  );

  return (
    <>
      <SyncProblems canDecide={canDecide} />
      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <div
          role="group"
          aria-label={t("admin.dayClosings.statusFilter")}
          className="flex rounded-control bg-surface-2 p-1"
        >
          {STATUSES.map((value) => statusButton(value, t(`admin.dayClosings.statuses.${value}`)))}
          {statusButton("", t("admin.dayClosings.all"))}
        </div>
        <Input
          type="search"
          aria-label={t("admin.dayClosings.search")}
          placeholder={t("admin.dayClosings.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <Input
          type="date"
          aria-label={t("admin.dayClosings.dateFrom")}
          value={dateFrom}
          onChange={(event) => setDateFrom(event.target.value)}
          className="w-40"
        />
        <Input
          type="date"
          aria-label={t("admin.dayClosings.dateTo")}
          value={dateTo}
          onChange={(event) => setDateTo(event.target.value)}
          className="w-40"
        />
      </Card>
      {closings.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : closings.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        <EmptyState illustration="truck" title={t("admin.dayClosings.empty")}>
          {t("admin.dayClosings.emptyBody")}
        </EmptyState>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.dayClosings.date")}</Th>
                <Th>{t("admin.dayClosings.truck")}</Th>
                <Th>{t("admin.dayClosings.driver")}</Th>
                <Th className="text-end">{t("admin.dayClosings.expected")}</Th>
                <Th className="text-end">{t("admin.dayClosings.officeCounted")}</Th>
                <Th className="text-end">{t("admin.dayClosings.difference")}</Th>
                <Th>{t("admin.dayClosings.status")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((row) => (
                <tr key={row.id} className="cursor-pointer hover:bg-surface-2" onClick={() => setOpen(row.id)}>
                  <Td>
                    <button type="button" className="font-semibold" onClick={() => setOpen(row.id)}>
                      {formatDate(row.date)}
                    </button>
                  </Td>
                  <Td>{row.truck_name}</Td>
                  <Td>{row.driver_name}</Td>
                  <Td className="num text-end">{formatMoney(row.expected_cash)}</Td>
                  <Td className="num text-end">{countedOrDash(row.office_counted_cash)}</Td>
                  <Td className="num text-end">{gapOrDash(row.office_difference)}</Td>
                  <Td>
                    <Pill tone={TONES[row.status]}>{t(`admin.dayClosings.statuses.${row.status}`)}</Pill>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
      <Dialog open={open !== null} onOpenChange={(value) => !value && setOpen(null)}>
        {open !== null && <ClosingDialog id={open} canDecide={canDecide} onDone={() => setOpen(null)} />}
      </Dialog>
    </>
  );
}
