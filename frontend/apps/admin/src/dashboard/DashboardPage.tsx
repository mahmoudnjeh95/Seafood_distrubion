import { useGetDashboard } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatPercent, formatQuantity, useTranslation } from "@frutti/i18n";
import { Card, CardTitle, EmptyState, PageHeader, Pill } from "@frutti/ui";
import { Link, useOutletContext } from "react-router";

import { monthLabel } from "../hr/shared";
import { DueAlertsCard } from "../treasury/DueAlertsCard";

function Kpi({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "good" | "bad" }) {
  // formatMoney ends with the currency after a no-break space: show it smaller next to the figure.
  const money = formatMoney(value);
  const cut = money.lastIndexOf("\u00a0");
  return (
    <Card className="flex flex-col gap-1.5 p-4">
      <span className="eyebrow">{label}</span>
      <span className="num font-display text-[1.55rem] font-bold leading-tight">
        {money.slice(0, cut)} <small className="text-[0.8rem] font-semibold text-ink-2">{money.slice(cut + 1)}</small>
      </span>
      {note && <span className={tone === "bad" ? "text-[0.85rem] text-bad" : "text-[0.85rem] text-ink-2"}>{note}</span>}
    </Card>
  );
}

/** The change from last month's sales, in percent; null when last month sold nothing. */
function change(now: string, before: string): string | null {
  const previous = Number(before);
  if (!(previous > 0)) return null;
  return (((Number(now) - previous) / previous) * 100).toFixed(1);
}

/** "Tableau de bord": this month's profit and cash side by side but never mixed, then what needs a look. */
export function DashboardPage() {
  const { t, i18n } = useTranslation();
  const session = useOutletContext<Session>();
  const dashboard = useGetDashboard();
  const header = <PageHeader eyebrow={session.organization.name} title={t("admin.nav.dashboard")} />;

  // The figures are for the owner and the accountant: a manager only gets the welcome.
  if (dashboard.isError) {
    return (
      <>
        {header}
        <EmptyState
          illustration="fridge"
          title={t("admin.dashboard.hello", { name: session.user.first_name || session.user.username })}
        >
          {t("admin.dashboard.body")}
        </EmptyState>
      </>
    );
  }
  const data = dashboard.data;
  if (!data) {
    return (
      <>
        {header}
        <p className="text-ink-2">{t("common.loading")}</p>
      </>
    );
  }

  const month = monthLabel(data.month, i18n.language);
  const delta = change(data.sales, data.previous_sales);
  const alerts =
    data.overdue_customer_count +
    data.days_waiting +
    data.expenses_waiting +
    data.field_purchases_waiting +
    data.settlements_undefined_late +
    data.low_stock_count +
    data.expiring_count +
    data.cash_difference_count +
    data.pending_terms_count;

  return (
    <>
      {header}
      <p className="text-ink-2">{t("admin.dashboard.period", { month })}</p>

      <section aria-labelledby="dash-profit" className="flex flex-col gap-3">
        <h2 id="dash-profit" className="text-[1.05rem] font-semibold">
          {t("admin.dashboard.profit.title")}
        </h2>
        <p className="text-[0.9rem] text-ink-2">{t("admin.dashboard.profit.hint")}</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Kpi
            label={t("admin.dashboard.profit.sales")}
            value={data.sales}
            {...(delta !== null && { note: t("admin.dashboard.profit.vsLast", { percent: formatPercent(delta) }) })}
          />
          <Kpi label={t("admin.dashboard.profit.margin")} value={data.gross_margin} />
          <Kpi
            label={t("admin.dashboard.profit.net")}
            value={data.net_result}
            note={t("admin.dashboard.profit.netHint")}
            {...(Number(data.net_result) < 0 && { tone: "bad" as const })}
          />
        </div>
      </section>

      <section aria-labelledby="dash-cash" className="flex flex-col gap-3">
        <h2 id="dash-cash" className="text-[1.05rem] font-semibold">
          {t("admin.dashboard.cash.title")}
        </h2>
        <p className="text-[0.9rem] text-ink-2">{t("admin.dashboard.cash.hint")}</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Kpi label={t("admin.dashboard.cash.collected")} value={data.cash_collected} />
          <Kpi
            label={t("admin.dashboard.cash.receivables")}
            value={data.receivables}
            {...(Number(data.receivables_overdue) > 0 && {
              note: t("admin.dashboard.cash.overdue", { amount: formatMoney(data.receivables_overdue) }),
              tone: "bad" as const,
            })}
          />
          <Kpi
            label={t("admin.dashboard.cash.stock")}
            value={data.stock_value}
            note={t("admin.dashboard.cash.stockHint")}
          />
        </div>
      </section>

      <DueAlertsCard />

      <Card className="p-4">
        <CardTitle>{t("admin.dashboard.alerts.title")}</CardTitle>
        {alerts === 0 ? (
          <p className="pt-2 text-ink-2">{t("admin.dashboard.alerts.none")}</p>
        ) : (
          <ul className="flex flex-col gap-2 pt-2">
            {data.overdue_customers.map((row) => (
              <li key={row.customer_id} className="flex items-center justify-between gap-3">
                <Link to={`/clients/${row.customer_id}`} className="hover:underline">
                  {t("admin.dashboard.alerts.overdue", { name: row.name })}
                </Link>
                <Pill tone="bad">{formatMoney(row.overdue)}</Pill>
              </li>
            ))}
            {data.overdue_customer_count > data.overdue_customers.length && (
              <li>
                <Link to="/reglements" className="text-ink-2 hover:underline">
                  {t("admin.dashboard.alerts.moreOverdue", {
                    count: data.overdue_customer_count - data.overdue_customers.length,
                  })}
                </Link>
              </li>
            )}
            {data.days_waiting > 0 && (
              <li className="flex items-center justify-between gap-3">
                <Link to="/journees" className="hover:underline">
                  {t("admin.dashboard.alerts.days", { count: data.days_waiting })}
                </Link>
                <Pill tone="warn">{data.days_waiting}</Pill>
              </li>
            )}
            {data.cash_differences.map((row) => (
              <li key={row.closing_id} className="flex items-center justify-between gap-3">
                <Link to="/journees" className="hover:underline">
                  {t("admin.dashboard.alerts.cashDifference", { driver: row.driver_name, day: formatDate(row.day) })}
                </Link>
                <Pill tone="bad">{formatMoney(row.difference)}</Pill>
              </li>
            ))}
            {data.cash_difference_count > data.cash_differences.length && (
              <li>
                <Link to="/journees" className="text-ink-2 hover:underline">
                  {t("admin.dashboard.alerts.moreCashDifferences", {
                    count: data.cash_difference_count - data.cash_differences.length,
                  })}
                </Link>
              </li>
            )}
            {data.low_stock.map((row) => (
              <li key={row.product_id} className="flex items-center justify-between gap-3">
                <Link to="/stock" className="hover:underline">
                  {t("admin.dashboard.alerts.lowStock", { name: row.name, min: formatQuantity(row.min_stock) })}
                </Link>
                <Pill tone="warn">{formatQuantity(row.quantity)}</Pill>
              </li>
            ))}
            {data.low_stock_count > data.low_stock.length && (
              <li>
                <Link to="/stock" className="text-ink-2 hover:underline">
                  {t("admin.dashboard.alerts.moreLowStock", { count: data.low_stock_count - data.low_stock.length })}
                </Link>
              </li>
            )}
            {data.expiring.map((row) => (
              <li key={row.batch_id} className="flex items-center justify-between gap-3">
                <Link to="/stock" className="hover:underline">
                  {t("admin.dashboard.alerts.expiring", {
                    name: row.product_name,
                    batch: row.batch_number,
                    date: formatDate(row.use_by),
                  })}
                </Link>
                <Pill tone="warn">{formatQuantity(row.quantity)}</Pill>
              </li>
            ))}
            {data.expiring_count > data.expiring.length && (
              <li>
                <Link to="/stock" className="text-ink-2 hover:underline">
                  {t("admin.dashboard.alerts.moreExpiring", { count: data.expiring_count - data.expiring.length })}
                </Link>
              </li>
            )}
            {data.pending_terms.map((row) => (
              <li key={row.partnership_id} className="flex items-center justify-between gap-3">
                <Link to={`/stock/lots/${row.batch_id}`} className="hover:underline">
                  {t("admin.dashboard.alerts.pendingTerms", { batch: row.batch_number, partner: row.partner_name })}
                </Link>
                <Pill tone="warn">{t("admin.partnerships.section.pending")}</Pill>
              </li>
            ))}
            {data.pending_terms_count > data.pending_terms.length && (
              <li>
                <Link to="/partenariats" className="text-ink-2 hover:underline">
                  {t("admin.dashboard.alerts.morePendingTerms", {
                    count: data.pending_terms_count - data.pending_terms.length,
                  })}
                </Link>
              </li>
            )}
            {data.field_purchases_waiting > 0 && (
              <li className="flex items-center justify-between gap-3">
                <Link to="/achats/terrain" className="hover:underline">
                  {t("admin.dashboard.alerts.fieldPurchases", { count: data.field_purchases_waiting })}
                  {data.field_purchases_late > 0 && (
                    <span className="ms-2 font-semibold text-bad">
                      {t("admin.dashboard.alerts.fieldPurchasesLate", { count: data.field_purchases_late })}
                    </span>
                  )}
                </Link>
                <Pill tone={data.field_purchases_late > 0 ? "bad" : "warn"}>{data.field_purchases_waiting}</Pill>
              </li>
            )}
            {data.settlements_undefined_late > 0 && (
              <li className="flex items-center justify-between gap-3">
                <Link to="/achats/reglements?etat=undefined" className="hover:underline">
                  {t("admin.dashboard.alerts.settlementsUndefined", { count: data.settlements_undefined_late })}
                </Link>
                <Pill tone="bad">{data.settlements_undefined_late}</Pill>
              </li>
            )}
            {data.expenses_waiting > 0 && (
              <li className="flex items-center justify-between gap-3">
                <Link to="/charges" className="hover:underline">
                  {t("admin.dashboard.alerts.expenses", { count: data.expenses_waiting })}
                </Link>
                <Pill tone="warn">{data.expenses_waiting}</Pill>
              </li>
            )}
          </ul>
        )}
      </Card>
    </>
  );
}
