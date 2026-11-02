import { getExportSupplierInvoicesUrl, type ListSupplierInvoicesStatus, useGetSupplier, useListSupplierInvoices } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  cn,
  EmptyState,
  Icon,
  Input,
  PageHeader,
  Pager,
  Pill,
  SortTh,
  Table,
  Td,
  Th,
  useServerTable,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useNavigate, useOutletContext, useSearchParams } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { canRecordReceipts } from "../receipts/shared";
import { PurchasingTabs } from "./PurchasingTabs";
import { idFrom, STATUS_TONE } from "./shared";
import { ExportButton } from "../lib/ExportButton";

const FILTERS = ["open", "draft", "paid", "all"] as const;
type Filter = (typeof FILTERS)[number];

export function SupplierInvoicesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordReceipts(session);
  const overdueId = useId();
  const [params, setParams] = useSearchParams();
  // `?fournisseur=3` (from the supplier page) shows one supplier's invoices.
  const supplierId = idFrom(params.get("fournisseur"));
  const supplier = useGetSupplier(supplierId ?? 0, { query: { enabled: supplierId !== null } });
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [onlyOverdue, setOnlyOverdue] = useState(false);
  const table = useServerTable();
  const query = useDebounced(search.trim());

  const status: ListSupplierInvoicesStatus | undefined = filter === "all" ? undefined : filter;
  const filters = {
    overdue: onlyOverdue,
    ...(status ? { status } : {}),
    ...(query ? { search: query } : {}),
    ...(supplierId ? { supplier: supplierId } : {}),
  };
  const invoices = useListSupplierInvoices(
    { ...table.params, ...filters },
    { query: { placeholderData: keepPreviousData } },
  );
  const page = invoices.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || filter !== "all" || onlyOverdue || supplierId !== null;

  return (
    <>
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.supplierInvoices.title")}>
        {canRecord && (
          <Button
            variant="primary"
            onClick={() => void navigate(`/achats/factures/nouvelle${supplierId ? `?fournisseur=${supplierId}` : ""}`)}
          >
            <Icon name="plus" />
            {t("admin.supplierInvoices.add")}
          </Button>
        )}
        <ExportButton href={getExportSupplierInvoicesUrl({ ...table.ordering, ...filters })} />
      </PageHeader>

      <PurchasingTabs />

      {!canRecord && <p className="text-ink-2">{t("admin.supplierInvoices.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.supplierInvoices.search")}
          placeholder={t("admin.supplierInvoices.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div
          role="group"
          aria-label={t("admin.supplierInvoices.show")}
          className="flex rounded-control bg-surface-2 p-1"
        >
          {FILTERS.map((choice) => (
            <button
              key={choice}
              type="button"
              aria-pressed={filter === choice}
              onClick={() => {
                setFilter(choice);
                table.backToFirstPage();
              }}
              className={cn(
                "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
                filter === choice && "bg-surface text-ink shadow-card",
              )}
            >
              {t(`admin.supplierInvoices.filter.${choice}`)}
            </button>
          ))}
        </div>
        <label htmlFor={overdueId} className="flex items-center gap-2 text-[0.9rem]">
          <input
            id={overdueId}
            type="checkbox"
            checked={onlyOverdue}
            onChange={(event) => {
              setOnlyOverdue(event.target.checked);
              table.backToFirstPage();
            }}
            className="size-4 accent-coral"
          />
          {t("admin.supplierInvoices.onlyOverdue")}
        </label>
        {supplierId !== null && (
          <span className="flex items-center gap-2 text-[0.9rem]">
            <Pill tone="sea">{t("admin.supplierInvoices.supplierFilter", { name: supplier.data?.name ?? "…" })}</Pill>
            <button
              type="button"
              className="font-semibold text-sea hover:underline"
              onClick={() => {
                setParams({});
                table.backToFirstPage();
              }}
            >
              {t("admin.supplierInvoices.clearSupplier")}
            </button>
          </span>
        )}
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.supplierInvoices.count", { count: page.count })}
        </span>
      </Card>

      {invoices.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : invoices.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.supplierInvoices.noMatch")}</p>
        ) : (
          <EmptyState illustration="fish" title={t("admin.supplierInvoices.empty")}>
            {t("admin.supplierInvoices.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.supplierInvoices.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.supplierInvoices.columns.date")}
                </SortTh>
                <SortTh sortKey="supplier" {...table.sorting}>
                  {t("admin.supplierInvoices.columns.supplier")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.supplierInvoices.columns.due")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.supplierInvoices.columns.total")}
                </Th>
                <Th numeric>{t("admin.supplierInvoices.columns.outstanding")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((invoice) => (
                // The number is the link; a click anywhere on the row opens the same page.
                <tr
                  key={invoice.id}
                  onClick={() => void navigate(`/achats/factures/${invoice.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/achats/factures/${invoice.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {invoice.number}
                    </Link>
                    <Pill className="ms-2" tone={STATUS_TONE[invoice.status]}>
                      {t(`admin.supplierInvoices.status.${invoice.status}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(invoice.invoice_date)}</Td>
                  <Td>
                    <span className="font-semibold">{invoice.supplier.name}</span>
                    {invoice.supplier_reference && (
                      <div className="num text-[0.8rem] text-ink-2">{invoice.supplier_reference}</div>
                    )}
                  </Td>
                  <Td className="num whitespace-nowrap max-[720px]:hidden">
                    <span className={cn(invoice.is_overdue && "font-semibold text-bad")}>
                      {formatDate(invoice.due_date)}
                    </span>
                    {invoice.is_overdue && (
                      <Pill className="ms-2" tone="bad">
                        {t("admin.supplierInvoices.overdue")}
                      </Pill>
                    )}
                  </Td>
                  <Td numeric className="whitespace-nowrap max-[720px]:hidden">
                    {formatMoney(invoice.total)}
                  </Td>
                  <Td numeric className="font-semibold whitespace-nowrap">
                    {invoice.status === "draft" ? "—" : formatMoney(invoice.outstanding)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      )}
    </>
  );
}
