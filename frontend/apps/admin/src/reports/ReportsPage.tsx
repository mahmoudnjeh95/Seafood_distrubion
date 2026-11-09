import { useGetLossesReport, useGetSalesReport, useGetSlowMovingReport, useGetStockValueReport } from "@frutti/api";
import { canAccess, type Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, cn, EmptyState, Field, Input, PageHeader, Table, Td, Th } from "@frutti/ui";
import { useId, useState } from "react";
import { useOutletContext } from "react-router";

import { FinancialReports } from "./FinancialReports";
import { PartnerReports } from "./PartnerReports";

const TABS = ["sales", "stockValue", "slow", "losses", "financial", "partners"] as const;
type Tab = (typeof TABS)[number];
const GROUPS = ["customer", "product", "truck", "driver", "day", "week", "month"] as const;
type Group = (typeof GROUPS)[number];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthStart(): string {
  return `${today().slice(0, 8)}01`;
}

/** The Excel file of a report: a plain download link, the session cookie goes with it. */
function ExportLink({ path, query }: { path: string; query: Record<string, string | number> }) {
  const { t } = useTranslation();
  const search = new URLSearchParams(Object.entries(query).map(([key, value]) => [key, String(value)]));
  return (
    <Button asChild>
      <a href={`/api/v1/reports/${path}/export?${search.toString()}`} download>
        {t("admin.reports.excel")}
      </a>
    </Button>
  );
}

function Period({
  from,
  to,
  onFrom,
  onTo,
}: {
  from: string;
  to: string;
  onFrom: (value: string) => void;
  onTo: (value: string) => void;
}) {
  const { t } = useTranslation();
  const fromId = useId();
  const toId = useId();
  return (
    <>
      <Field label={t("admin.reports.from")} htmlFor={fromId}>
        <Input id={fromId} type="date" value={from} max={to} onChange={(event) => onFrom(event.target.value)} />
      </Field>
      <Field label={t("admin.reports.to")} htmlFor={toId}>
        <Input id={toId} type="date" value={to} min={from} onChange={(event) => onTo(event.target.value)} />
      </Field>
    </>
  );
}

function Loading({ query }: { query: { isPending: boolean; isError: boolean } }) {
  const { t } = useTranslation();
  if (query.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (query.isError) {
    return (
      <p role="alert" className="text-bad">
        {t("common.serverUnreachable")}
      </p>
    );
  }
  return null;
}

function Empty() {
  const { t } = useTranslation();
  return (
    <EmptyState illustration="mussel" title={t("admin.reports.empty")}>
      {t("admin.reports.emptyBody")}
    </EmptyState>
  );
}

function SalesReport() {
  const { t } = useTranslation();
  const [group, setGroup] = useState<Group>("customer");
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const query = { group_by: group, date_from: from, date_to: to };
  const report = useGetSalesReport(query);
  const data = report.data;
  return (
    <>
      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <div
          role="group"
          aria-label={t("admin.reports.groupBy")}
          className="flex flex-wrap rounded-control bg-surface-2 p-1"
        >
          {GROUPS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={group === value}
              onClick={() => setGroup(value)}
              className={cn(
                "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
                group === value && "bg-surface text-ink shadow-card",
              )}
            >
              {t(`admin.reports.groups.${value}`)}
            </button>
          ))}
        </div>
        <Period from={from} to={to} onFrom={setFrom} onTo={setTo} />
        <ExportLink path="sales" query={query} />
      </Card>
      <Loading query={report} />
      {data &&
        (data.rows.length === 0 ? (
          <Empty />
        ) : (
          <Card className="p-2">
            <Table>
              <thead>
                <tr>
                  <Th>{t(`admin.reports.groups.${group}`)}</Th>
                  <Th className="text-end">{t("admin.reports.sales")}</Th>
                  <Th className="text-end">{t("admin.reports.kg")}</Th>
                  <Th className="text-end">{t("admin.reports.revenue")}</Th>
                  <Th className="text-end">{t("admin.reports.cogs")}</Th>
                  <Th className="text-end">{t("admin.reports.margin")}</Th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.key}>
                    <Td>{row.name}</Td>
                    <Td className="num text-end">{row.sales}</Td>
                    <Td className="num text-end">{formatQuantity(row.quantity)}</Td>
                    <Td className="num text-end">{formatMoney(row.revenue)}</Td>
                    <Td className="num text-end">{formatMoney(row.cogs)}</Td>
                    <Td className="num text-end">{formatMoney(row.margin)}</Td>
                  </tr>
                ))}
                <tr className="font-bold">
                  <Td>{t("admin.reports.total")}</Td>
                  <Td className="num text-end">{data.totals.sales}</Td>
                  <Td className="num text-end">{formatQuantity(data.totals.quantity)}</Td>
                  <Td className="num text-end">{formatMoney(data.totals.revenue)}</Td>
                  <Td className="num text-end">{formatMoney(data.totals.cogs)}</Td>
                  <Td className="num text-end">{formatMoney(data.totals.margin)}</Td>
                </tr>
              </tbody>
            </Table>
          </Card>
        ))}
      <p className="text-[0.85rem] text-ink-2">{t("admin.reports.salesNote")}</p>
    </>
  );
}

function StockValueReport() {
  const { t } = useTranslation();
  const report = useGetStockValueReport();
  const data = report.data;
  return (
    <>
      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <span className="text-ink-2">{t("admin.reports.stockValueNote")}</span>
        <span className="ms-auto">
          <ExportLink path="stock-value" query={{}} />
        </span>
      </Card>
      <Loading query={report} />
      {data &&
        (data.rows.length === 0 ? (
          <Empty />
        ) : (
          <Card className="p-2">
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.reports.place")}</Th>
                  <Th>{t("admin.reports.product")}</Th>
                  <Th className="text-end">{t("admin.reports.kg")}</Th>
                  <Th className="text-end">{t("admin.reports.value")}</Th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={`${row.location_id}-${row.product_id}`}>
                    <Td>{row.location_name}</Td>
                    <Td>{row.product_name}</Td>
                    <Td className="num text-end">{formatQuantity(row.quantity)}</Td>
                    <Td className="num text-end">{formatMoney(row.value)}</Td>
                  </tr>
                ))}
                <tr className="font-bold">
                  <Td>{t("admin.reports.total")}</Td>
                  <Td />
                  <Td className="num text-end">{formatQuantity(data.total_quantity)}</Td>
                  <Td className="num text-end">{formatMoney(data.total_value)}</Td>
                </tr>
              </tbody>
            </Table>
          </Card>
        ))}
    </>
  );
}

function SlowReport() {
  const { t } = useTranslation();
  const daysId = useId();
  const [days, setDays] = useState(30);
  const report = useGetSlowMovingReport({ days });
  const data = report.data;
  return (
    <>
      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <Field label={t("admin.reports.idleDays")} htmlFor={daysId}>
          <Input
            id={daysId}
            type="number"
            min={0}
            max={3650}
            className="num"
            value={days}
            onChange={(event) => setDays(Math.max(0, Math.min(3650, Number(event.target.value) || 0)))}
          />
        </Field>
        <ExportLink path="slow-moving" query={{ days }} />
      </Card>
      <Loading query={report} />
      {data &&
        (data.rows.length === 0 ? (
          <Empty />
        ) : (
          <Card className="p-2">
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.reports.lot")}</Th>
                  <Th>{t("admin.reports.product")}</Th>
                  <Th>{t("admin.reports.supplier")}</Th>
                  <Th>{t("admin.reports.received")}</Th>
                  <Th>{t("admin.reports.lastMovement")}</Th>
                  <Th className="text-end">{t("admin.reports.idle")}</Th>
                  <Th className="text-end">{t("admin.reports.kg")}</Th>
                  <Th className="text-end">{t("admin.reports.value")}</Th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.batch_id}>
                    <Td>{row.batch_number}</Td>
                    <Td>{row.product_name}</Td>
                    <Td>{row.supplier_name}</Td>
                    <Td>{formatDate(row.received_on)}</Td>
                    <Td>{formatDate(row.last_movement_on)}</Td>
                    <Td className="num text-end">{row.days_idle}</Td>
                    <Td className="num text-end">{formatQuantity(row.quantity)}</Td>
                    <Td className="num text-end">{formatMoney(row.value)}</Td>
                  </tr>
                ))}
                <tr className="font-bold">
                  <Td>{t("admin.reports.total")}</Td>
                  <Td colSpan={5} />
                  <Td className="num text-end">{formatQuantity(data.total_quantity)}</Td>
                  <Td className="num text-end">{formatMoney(data.total_value)}</Td>
                </tr>
              </tbody>
            </Table>
          </Card>
        ))}
    </>
  );
}

function LossesReport() {
  const { t } = useTranslation();
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const query = { date_from: from, date_to: to };
  const report = useGetLossesReport(query);
  const data = report.data;
  return (
    <>
      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <Period from={from} to={to} onFrom={setFrom} onTo={setTo} />
        <ExportLink path="losses" query={query} />
      </Card>
      <Loading query={report} />
      {data &&
        (data.rows.length === 0 ? (
          <Empty />
        ) : (
          <Card className="p-2">
            <Table>
              <thead>
                <tr>
                  <Th>{t("admin.reports.product")}</Th>
                  <Th className="text-end">{t("admin.reports.lostKg")}</Th>
                  <Th className="text-end">{t("admin.reports.lostValue")}</Th>
                  <Th className="text-end">{t("admin.reports.diffKg")}</Th>
                  <Th className="text-end">{t("admin.reports.diffValue")}</Th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.product_id}>
                    <Td>{row.product_name}</Td>
                    <Td className="num text-end">{formatQuantity(row.lost_quantity)}</Td>
                    <Td className="num text-end">{formatMoney(row.lost_value)}</Td>
                    <Td className="num text-end">{formatQuantity(row.difference_quantity)}</Td>
                    <Td className="num text-end">{formatMoney(row.difference_value)}</Td>
                  </tr>
                ))}
                <tr className="font-bold">
                  <Td>{t("admin.reports.total")}</Td>
                  <Td className="num text-end">{formatQuantity(data.total_lost_quantity)}</Td>
                  <Td className="num text-end">{formatMoney(data.total_lost_value)}</Td>
                  <Td />
                  <Td />
                </tr>
              </tbody>
            </Table>
          </Card>
        ))}
    </>
  );
}

/** "Rapports": commercial and stock reports, with an Excel file for each (P7-T02, P7-T03, D-113). */
export function ReportsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  // The company's money is for the owner and the accountant (the server refuses the others too).
  const tabs = TABS.filter(
    (value) =>
      (value !== "financial" && value !== "partners") ||
      (session.role !== "manager" && canAccess(session, "reports", "read")),
  );
  const [tab, setTab] = useState<Tab>("sales");
  return (
    <>
      <PageHeader eyebrow={t("admin.groups.steering")} title={t("admin.reports.title")} />
      <div
        role="tablist"
        aria-label={t("admin.reports.title")}
        className="flex flex-wrap gap-1 rounded-control bg-surface-2 p-1 self-start"
      >
        {tabs.map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={cn(
              "rounded-[7px] px-3 py-1.5 text-[0.9rem] font-semibold text-ink-2",
              tab === value && "bg-surface text-ink shadow-card",
            )}
          >
            {t(`admin.reports.tabs.${value}`)}
          </button>
        ))}
      </div>
      {tab === "sales" && <SalesReport />}
      {tab === "stockValue" && <StockValueReport />}
      {tab === "slow" && <SlowReport />}
      {tab === "losses" && <LossesReport />}
      {tab === "financial" && <FinancialReports />}
      {tab === "partners" && <PartnerReports />}
    </>
  );
}
