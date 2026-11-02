import {
  type DayOverviewRow,
  type DayOverviewSale,
  useGetDayOverview,
  useListDayOverview,
  useListDayOverviewDrivers,
  useListTrucks,
} from "@frutti/api";
import { formatDate, formatDateTime, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Card,
  cn,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  EmptyState,
  Input,
  Pill,
  Table,
  Td,
  Th,
} from "@frutti/ui";
import { type ReactNode, useState } from "react";
import { Link } from "react-router";

import { ROUTE_MAP_ENABLED, RouteMap } from "./RouteMap";

const SELECT_CLASSES = "rounded-control border border-line bg-surface px-3 py-2 text-ink";
const PHASE_TONES = {
  running: "sea",
  submitted: "warn",
  justification: "bad",
  reopened: "sea",
  approved: "good",
} as const;
const PURCHASE_TONES = {
  submitted: "warn",
  validated: "good",
  refused: "bad",
} as const;

/** Millimes of a decimal string, so sums stay exact (never a float, ARCHITECTURE §4.1). */
function millimes(value: string): bigint {
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = value.replace("-", "").split(".");
  const total = BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, "0").slice(0, 3));
  return negative ? -total : total;
}

function fromMillimes(value: bigint): string {
  const negative = value < 0n;
  const abs = negative ? -value : value;
  return `${negative ? "-" : ""}${abs / 1000n}.${(abs % 1000n).toString().padStart(3, "0")}`;
}

function sum(values: readonly string[]): string {
  return fromMillimes(values.reduce((total, value) => total + millimes(value), 0n));
}

function isoDay(date: Date): string {
  return date.toLocaleDateString("sv-SE");
}

function daysAgo(count: number): string {
  const date = new Date();
  date.setDate(date.getDate() - count);
  return isoDay(date);
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[0.75rem] font-semibold text-ink-2">{label}</p>
      <p className="num text-[1.05rem] font-bold">{value}</p>
      {hint && <p className="text-[0.75rem] text-ink-2">{hint}</p>}
    </div>
  );
}

function Delivery({ done, todo }: { done: number; todo: number }) {
  const { t } = useTranslation();
  const total = done + todo;
  if (total === 0) return <p className="text-[0.85rem] text-ink-2">{t("admin.dayOverview.deliveriesNone")}</p>;
  return (
    <div>
      <p className="text-[0.85rem] font-semibold">{t("admin.dayOverview.deliveriesOf", { done, total })}</p>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        <div className="h-full bg-good" style={{ width: `${(done / total) * 100}%` }} />
      </div>
    </div>
  );
}

function DayCard({ row, onOpen }: { row: DayOverviewRow; onOpen: () => void }) {
  const { t } = useTranslation();
  return (
    <button type="button" onClick={onOpen} className="text-start" aria-label={`${row.driver_name} ${row.truck_name}`}>
      <Card className="h-full p-4 transition hover:shadow-card">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-[1.05rem] font-bold">{row.driver_name}</p>
            <p className="truncate text-[0.85rem] text-ink-2">
              {row.truck_name} · {formatDate(row.date)}
            </p>
          </div>
          <Pill tone={PHASE_TONES[row.phase]}>{t(`admin.dayOverview.phases.${row.phase}`)}</Pill>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
          <Stat
            label={t("admin.dayOverview.salesLabel")}
            value={formatMoney(row.sales_total)}
            hint={
              Number(row.on_credit) > 0
                ? `${t("admin.dayClosings.sales", { count: row.sales_count })} · ${formatMoney(row.on_credit)} ${t("admin.dayOverview.credit")}`
                : t("admin.dayClosings.sales", { count: row.sales_count })
            }
          />
          <Stat
            label={t(row.phase === "approved" ? "admin.dayOverview.cashReceivedLabel" : "admin.dayOverview.cashLabel")}
            value={formatMoney(row.expected_cash)}
          />
          <Stat label={t("admin.dayOverview.expensesLabel")} value={formatMoney(row.expenses_total)} />
          {row.purchases_count > 0 && (
            <Stat
              label={t("admin.dayOverview.purchasesLabel")}
              value={formatMoney(row.purchases_total)}
              hint={t("admin.dayOverview.purchasesCount", { count: row.purchases_count })}
            />
          )}
          <div>
            <p className="text-[0.75rem] font-semibold text-ink-2">{t("admin.dayOverview.deliveriesLabel")}</p>
            <Delivery done={row.deliveries_done} todo={row.deliveries_todo} />
          </div>
        </div>
      </Card>
    </button>
  );
}

function SaleList({ sales, empty }: { sales: readonly DayOverviewSale[]; empty: string }) {
  const { t } = useTranslation();
  if (sales.length === 0) return <p className="text-ink-2">{empty}</p>;
  return (
    <Table>
      <thead>
        <tr>
          <Th>{t("admin.dayOverview.detail.client")}</Th>
          <Th className="text-end">{t("admin.dayOverview.detail.total")}</Th>
          <Th className="text-end">{t("admin.dayOverview.detail.paid")}</Th>
          <Th className="text-end">{t("admin.dayOverview.detail.due")}</Th>
          <Th />
        </tr>
      </thead>
      <tbody>
        {sales.map((sale) => (
          <tr key={sale.id}>
            <Td>
              <p className="font-semibold">{sale.customer_name}</p>
              <p className="text-[0.78rem] text-ink-2">
                {sale.products}
                {sale.delivery_address && ` · ${sale.delivery_address}`}
              </p>
            </Td>
            <Td className="num text-end">{formatMoney(sale.total)}</Td>
            <Td className="num text-end">{formatMoney(sale.amount_paid)}</Td>
            <Td className="num text-end">{formatMoney(sale.amount_due)}</Td>
            <Td>
              {sale.from_load && (
                <Pill tone={sale.status === "confirmed" ? "good" : "warn"}>
                  {sale.status === "confirmed"
                    ? t("admin.dayOverview.detail.delivered")
                    : t("admin.dayOverview.detail.toDeliver")}
                </Pill>
              )}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="mb-2 text-[0.95rem] font-bold">{title}</h3>
      {children}
    </section>
  );
}

function MoneyLine({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <p className={cn("flex justify-between gap-3", strong && "border-t border-line pt-2 font-bold")}>
      <span className={strong ? undefined : "text-ink-2"}>{label}</span>
      <span className="num font-semibold">{value}</span>
    </p>
  );
}

function DayDialog({ id }: { id: number }) {
  const { t } = useTranslation();
  const day = useGetDayOverview(id);
  const d = day.data;
  const k = "admin.dayOverview.detail";
  return (
    <DialogContent className="max-h-[96dvh] w-[min(1400px,calc(100vw-1.5rem))] max-w-none overflow-y-auto p-5">
      {d === undefined ? (
        <>
          <DialogTitle>{t("admin.dayClosings.title")}</DialogTitle>
          <DialogDescription>{day.isError ? t("common.serverUnreachable") : t("common.loading")}</DialogDescription>
        </>
      ) : (
        <>
          <DialogTitle>
            {d.driver_name} · {d.truck_name}
          </DialogTitle>
          <DialogDescription>
            {formatDate(d.date)} · <Pill tone={PHASE_TONES[d.phase]}>{t(`admin.dayOverview.phases.${d.phase}`)}</Pill>
          </DialogDescription>

          {ROUTE_MAP_ENABLED && (
            <Section title={t(`${k}.route.title`)}>
              <RouteMap dayId={id} running={d.phase === "running" || d.phase === "reopened"} />
            </Section>
          )}

          <Section title={t(`${k}.money`)}>
            <Card className="space-y-1.5 p-4">
              <MoneyLine label={t(`${k}.opening`)} value={formatMoney(d.opening_cash)} />
              <MoneyLine label={t(`${k}.cashSales`)} value={`+ ${formatMoney(d.cash_received)}`} />
              <MoneyLine label={t(`${k}.payments`)} value={`+ ${formatMoney(d.payments_cash)}`} />
              <MoneyLine label={t(`${k}.expenses`)} value={`− ${formatMoney(d.expenses_total)}`} />
              {Number(d.purchases_from_sales) > 0 && (
                <MoneyLine label={t(`${k}.purchases`)} value={`− ${formatMoney(d.purchases_from_sales)}`} />
              )}
              {Number(d.handed_over) > 0 && (
                <MoneyLine label={t(`${k}.handedOver`)} value={`− ${formatMoney(d.handed_over)}`} />
              )}
              <MoneyLine strong label={t(`${k}.expected`)} value={formatMoney(d.expected_cash)} />
              {/* Paid out of pocket at the port: owed by the office, not in the cash the driver holds (D-182). */}
              {Number(d.owed_to_driver) > 0 && (
                <MoneyLine label={t(`${k}.owed`)} value={formatMoney(d.owed_to_driver)} />
              )}
              {d.closing && (
                <>
                  <MoneyLine
                    label={t(`${k}.officeCounted`)}
                    value={d.closing.office_counted_cash === null ? "—" : formatMoney(d.closing.office_counted_cash)}
                  />
                  {d.closing.office_counted_cash === null ? null : (
                    <MoneyLine label={t(`${k}.officeGap`)} value={formatMoney(d.closing.office_difference)} />
                  )}
                  {d.closing.driver_note && (
                    <p className="pt-1 text-[0.85rem] text-ink-2">
                      {t(`${k}.driverNote`)} : {d.closing.driver_note}
                    </p>
                  )}
                  <p className="pt-1 text-[0.8rem] text-ink-2">{t(`${k}.closingHint`)}</p>
                </>
              )}
            </Card>
          </Section>

          <Section title={`${t(`${k}.deliveries`)} (${d.deliveries_done}/${d.deliveries_done + d.deliveries_todo})`}>
            <SaleList sales={d.deliveries} empty={t(`${k}.deliveriesEmpty`)} />
          </Section>

          <Section title={`${t(`${k}.sales`)} (${d.sales.length})`}>
            <SaleList sales={d.sales} empty={t(`${k}.salesEmpty`)} />
          </Section>

          {d.payments.length > 0 && (
            <Section title={t(`${k}.paymentsTitle`)}>
              <Table>
                <tbody>
                  {d.payments.map((p) => (
                    <tr key={p.id}>
                      <Td className="font-semibold">{p.customer_name}</Td>
                      <Td>{t(`${k}.methods.${p.method}`, { defaultValue: p.method })}</Td>
                      <Td className="text-ink-2">{formatDateTime(p.made_at)}</Td>
                      <Td className="num text-end">{formatMoney(p.amount)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Section>
          )}

          <Section title={`${t(`${k}.expensesTitle`)} (${formatMoney(d.expenses_total)})`}>
            {d.expenses.length === 0 ? (
              <p className="text-ink-2">{t(`${k}.expensesEmpty`)}</p>
            ) : (
              <Table>
                <tbody>
                  {d.expenses.map((e) => (
                    <tr key={e.id}>
                      <Td>
                        <p className="font-semibold">{e.category_name}</p>
                        {e.description && <p className="text-[0.78rem] text-ink-2">{e.description}</p>}
                      </Td>
                      <Td className="text-ink-2">{formatDateTime(e.made_at)}</Td>
                      <Td>
                        <Pill tone={e.status === "rejected" ? "bad" : e.status === "approved" ? "good" : "warn"}>
                          {t(
                            `${k}.${e.status === "rejected" ? "rejected" : e.status === "approved" ? "approved" : "pending"}`,
                          )}
                        </Pill>
                      </Td>
                      <Td className="num text-end">{formatMoney(e.amount)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Section>

          <Section title={`${t(`${k}.purchasesTitle`)} (${d.purchases.length})`}>
            {d.purchases.length === 0 ? (
              <p className="text-ink-2">{t(`${k}.purchasesEmpty`)}</p>
            ) : (
              <Table>
                <tbody>
                  {d.purchases.map((p) => (
                    <tr key={p.id}>
                      <Td>
                        <Link className="font-semibold underline" to={`/achats/terrain/${p.id}`}>
                          {p.number}
                        </Link>
                        <p className="text-[0.78rem] text-ink-2">{p.supplier_name}</p>
                      </Td>
                      <Td className="text-ink-2">{formatDateTime(p.made_at)}</Td>
                      <Td>
                        <Pill tone={PURCHASE_TONES[p.status]}>{t(`${k}.purchaseStatus.${p.status}`)}</Pill>
                      </Td>
                      <Td className="num text-end">{formatMoney(p.total)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Section>

          {d.products.length > 0 && (
            <Section title={t(`${k}.stock`)}>
              <Table>
                <thead>
                  <tr>
                    <Th>{t("admin.dayClosings.product")}</Th>
                    <Th className="text-end">{t("admin.dayClosings.loaded")}</Th>
                    <Th className="text-end">{t("admin.dayClosings.sold")}</Th>
                    <Th className="text-end">{t("admin.dayClosings.returned")}</Th>
                    <Th className="text-end">{t("admin.dayClosings.left")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.products.map((p) => (
                    <tr key={p.product_id}>
                      <Td className="font-semibold">{p.product_name}</Td>
                      <Td className="num text-end">{formatQuantity(p.loaded)}</Td>
                      <Td className="num text-end">{formatQuantity(p.sold)}</Td>
                      <Td className="num text-end">{formatQuantity(p.returned)}</Td>
                      <Td className="num text-end">{formatQuantity(p.remaining)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Section>
          )}
        </>
      )}
    </DialogContent>
  );
}

/** What each driver is doing: their money, sales, deliveries and expenses per day, filtered by driver, truck and day. */
export function DaysOverview() {
  const { t } = useTranslation();
  const [dateFrom, setDateFrom] = useState(() => daysAgo(0));
  const [dateTo, setDateTo] = useState(() => daysAgo(0));
  const [driver, setDriver] = useState("");
  const [truck, setTruck] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const drivers = useListDayOverviewDrivers();
  const trucks = useListTrucks({ status: "all" });
  const days = useListDayOverview({
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    ...(driver ? { driver_id: Number(driver) } : {}),
    ...(truck ? { truck_id: Number(truck) } : {}),
  });
  const rows: readonly DayOverviewRow[] = days.data ?? [];

  const range = (from: string, to: string) => {
    setDateFrom(from);
    setDateTo(to);
  };
  const preset = (label: string, from: string, to: string) => (
    <button
      type="button"
      aria-pressed={dateFrom === from && dateTo === to}
      onClick={() => range(from, to)}
      className={cn(
        "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
        dateFrom === from && dateTo === to && "bg-surface text-ink shadow-card",
      )}
    >
      {label}
    </button>
  );

  const done = rows.reduce((total, row) => total + row.deliveries_done, 0);
  const planned = rows.reduce((total, row) => total + row.deliveries_done + row.deliveries_todo, 0);

  return (
    <>
      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <div className="flex rounded-control bg-surface-2 p-1">
          {preset(t("admin.dayOverview.today"), daysAgo(0), daysAgo(0))}
          {preset(t("admin.dayOverview.yesterday"), daysAgo(1), daysAgo(1))}
          {preset(t("admin.dayOverview.last7"), daysAgo(6), daysAgo(0))}
        </div>
        <label className="flex flex-col gap-1 text-[0.78rem] font-semibold text-ink-2">
          {t("admin.dayOverview.from")}
          <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="w-40" />
        </label>
        <label className="flex flex-col gap-1 text-[0.78rem] font-semibold text-ink-2">
          {t("admin.dayOverview.to")}
          <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="w-40" />
        </label>
        <label className="flex flex-col gap-1 text-[0.78rem] font-semibold text-ink-2">
          {t("admin.dayOverview.driver")}
          <select className={SELECT_CLASSES} value={driver} onChange={(event) => setDriver(event.target.value)}>
            <option value="">{t("admin.dayOverview.allDrivers")}</option>
            {(drivers.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[0.78rem] font-semibold text-ink-2">
          {t("admin.dayOverview.truck")}
          <select className={SELECT_CLASSES} value={truck} onChange={(event) => setTruck(event.target.value)}>
            <option value="">{t("admin.dayOverview.allTrucks")}</option>
            {(trucks.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      </Card>

      {days.isPending ? (
        <p className="mt-4 text-ink-2">{t("common.loading")}</p>
      ) : days.isError ? (
        <p role="alert" className="mt-4 text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : rows.length === 0 ? (
        <EmptyState illustration="truck" title={t("admin.dayOverview.empty")}>
          {t("admin.dayOverview.emptyBody")}
        </EmptyState>
      ) : (
        <>
          <Card className="mt-4 grid grid-cols-2 gap-4 p-4 md:grid-cols-5">
            <Stat label={t("admin.dayOverview.totals.days")} value={String(rows.length)} />
            <Stat
              label={t("admin.dayOverview.totals.sales")}
              value={formatMoney(sum(rows.map((r) => r.sales_total)))}
            />
            <Stat
              label={t("admin.dayOverview.totals.cash")}
              value={formatMoney(sum(rows.map((r) => r.expected_cash)))}
            />
            <Stat
              label={t("admin.dayOverview.totals.expenses")}
              value={formatMoney(sum(rows.map((r) => r.expenses_total)))}
            />
            <Stat label={t("admin.dayOverview.totals.deliveries")} value={`${done} / ${planned}`} />
          </Card>
          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((row) => (
              <DayCard key={row.id} row={row} onOpen={() => setOpen(row.id)} />
            ))}
          </div>
        </>
      )}
      <Dialog open={open !== null} onOpenChange={(value) => !value && setOpen(null)}>
        {open !== null && <DayDialog id={open} />}
      </Dialog>
    </>
  );
}
