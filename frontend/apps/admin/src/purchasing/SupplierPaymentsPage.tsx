import {
  getExportSupplierPaymentsUrl,
  type SupplierPayment,
  type SupplierPaymentMethodEnum,
  useGetSupplier,
  useGetSupplierPaymentTotals,
  useListSupplierPayments,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, Dialog, EmptyState, Icon, Input, PageHeader, Pill, Table, Td, Th } from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useOutletContext, useSearchParams } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { filterParams, isFiltered, type ListFilters, NO_FILTERS } from "../payments/listFilters";
import { MeansChips, PaymentListFilters, PaymentTotalsCard } from "../payments/ListParts";
import { canRecordReceipts } from "../receipts/shared";
import { TresorerieRibbon } from "../treasury/TresorerieRibbon";
import { AllocateDialog } from "./AllocateDialog";
import { compare } from "./allocation";
import { PurchasingTabs } from "./PurchasingTabs";
import { idFrom } from "./shared";

const PAGE_SIZE = 50;
const METHODS: readonly SupplierPaymentMethodEnum[] = ["cash", "cheque", "bill", "transfer", "other", "mixed"];

/** "Paiements fournisseurs": every règlement, filtered by days, means and state, with the totals of the filter and
 * its Excel file (P9-T03b). A row opens the règlement. */
export function SupplierPaymentsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canRecord = canRecordReceipts(session);
  const [params, setParams] = useSearchParams();
  // `?fournisseur=3` (from the supplier page) shows one supplier's payments.
  const supplierId = idFrom(params.get("fournisseur"));
  const supplier = useGetSupplier(supplierId ?? 0, { query: { enabled: supplierId !== null } });
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<ListFilters<SupplierPaymentMethodEnum>>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const [allocating, setAllocating] = useState<SupplierPayment | null>(null);
  const query = useDebounced(search.trim());
  const methodLabel = (method: string) => t(`admin.supplierPayments.method.${method as SupplierPaymentMethodEnum}`);

  const shared = {
    ...filterParams(filters),
    ...(query ? { search: query } : {}),
    ...(supplierId ? { supplier: supplierId } : {}),
  };
  const payments = useListSupplierPayments(
    { limit: PAGE_SIZE, offset, ...shared },
    { query: { placeholderData: keepPreviousData } },
  );
  const totals = useGetSupplierPaymentTotals(shared, { query: { placeholderData: keepPreviousData } });
  const page = payments.data;
  const list = page?.results ?? [];
  const filtering = query !== "" || isFiltered(filters) || supplierId !== null;

  return (
    <>
      <TresorerieRibbon active="decaissement" />
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.supplierPayments.title")}>
        {canRecord && (
          <Button
            variant="primary"
            onClick={() => void navigate(`/achats/paiements/nouveau${supplierId ? `?fournisseur=${supplierId}` : ""}`)}
          >
            <Icon name="plus" />
            {t("admin.supplierPayments.add")}
          </Button>
        )}
      </PageHeader>

      <PurchasingTabs />

      {!canRecord && <p className="text-ink-2">{t("admin.supplierInvoices.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.supplierPayments.search")}
          placeholder={t("admin.supplierPayments.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <PaymentListFilters
          filters={filters}
          onChange={(next) => {
            setFilters(next);
            setOffset(0);
          }}
          methods={METHODS}
          methodLabel={methodLabel}
        />
        {supplierId !== null && (
          <span className="flex items-center gap-2 text-[0.9rem]">
            <Pill tone="sea">{t("admin.supplierInvoices.supplierFilter", { name: supplier.data?.name ?? "…" })}</Pill>
            <button
              type="button"
              className="font-semibold text-sea hover:underline"
              onClick={() => {
                setParams({});
                setOffset(0);
              }}
            >
              {t("admin.supplierInvoices.clearSupplier")}
            </button>
          </span>
        )}
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.supplierPayments.count", { count: page.count })}
        </span>
      </Card>

      <PaymentTotalsCard
        totals={totals.data}
        methodLabel={methodLabel}
        restLabel={t("admin.treasury.list.advances")}
        exportUrl={getExportSupplierPaymentsUrl(shared)}
      />

      {payments.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : payments.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.supplierPayments.noMatch")}</p>
        ) : (
          <EmptyState illustration="fish" title={t("admin.supplierPayments.empty")}>
            {t("admin.supplierPayments.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.supplierPayments.columns.number")}</Th>
                <Th>{t("admin.supplierPayments.columns.date")}</Th>
                <Th>{t("admin.supplierPayments.columns.supplier")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.supplierPayments.columns.reason")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.treasury.list.means")}</Th>
                <Th numeric>{t("admin.supplierPayments.columns.amount")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.supplierPayments.columns.invoices")}</Th>
                <Th numeric>{t("admin.supplierPayments.columns.unallocated")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((payment) => {
                const hasAdvance = compare(payment.unallocated_amount, "0") > 0;
                return (
                  <tr key={payment.id} className={payment.is_voided ? "opacity-60" : undefined}>
                    <Td className="num font-semibold whitespace-nowrap">
                      <Link to={`/achats/paiements/${payment.id}`} className="text-sea hover:underline">
                        {payment.number}
                      </Link>
                      {payment.is_voided && (
                        <Pill tone="bad" className="ms-2">
                          {t("admin.payments.voided")}
                        </Pill>
                      )}
                    </Td>
                    <Td className="num whitespace-nowrap">{formatDate(payment.paid_on)}</Td>
                    <Td>
                      <Link to={`/fournisseurs/${payment.supplier.id}`} className="font-semibold hover:underline">
                        {payment.supplier.name}
                      </Link>
                    </Td>
                    <Td className="max-[720px]:hidden">{payment.reason}</Td>
                    <Td className="max-[720px]:hidden">
                      <MeansChips lines={payment.lines} methodLabel={methodLabel} />
                    </Td>
                    <Td numeric className="font-semibold whitespace-nowrap">
                      {formatMoney(payment.amount)}
                    </Td>
                    <Td className="max-[720px]:hidden">
                      <ul className="flex flex-col gap-0.5">
                        {payment.allocations.map((allocation) => (
                          <li key={allocation.id} className="num text-[0.85rem] whitespace-nowrap">
                            <Link
                              to={`/achats/factures/${allocation.invoice.id}`}
                              className="font-semibold text-sea hover:underline"
                            >
                              {allocation.invoice.number}
                            </Link>{" "}
                            · {formatMoney(allocation.amount)}
                          </li>
                        ))}
                      </ul>
                    </Td>
                    <Td numeric className="whitespace-nowrap">
                      {hasAdvance ? (
                        <span className="flex flex-col items-end gap-1">
                          <span>
                            <Pill tone="warn" className="me-2">
                              {t("admin.supplierPayments.advance")}
                            </Pill>
                            {formatMoney(payment.unallocated_amount)}
                          </span>
                          {canRecord && (
                            <Button onClick={() => setAllocating(payment)}>
                              {t("admin.supplierPayments.allocate")}
                            </Button>
                          )}
                        </span>
                      ) : (
                        "—"
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          {page && page.count > PAGE_SIZE && (
            <div className="flex items-center justify-end gap-2 p-2">
              <span className="me-auto text-[0.85rem] text-ink-2">
                {t("admin.supplierPayments.page", {
                  from: offset + 1,
                  to: Math.min(offset + PAGE_SIZE, page.count),
                  count: page.count,
                })}
              </span>
              <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                {t("admin.supplierPayments.previous")}
              </Button>
              <Button disabled={!page.next} onClick={() => setOffset(offset + PAGE_SIZE)}>
                {t("admin.supplierPayments.next")}
              </Button>
            </div>
          )}
        </Card>
      )}

      <Dialog open={allocating !== null} onOpenChange={(open) => !open && setAllocating(null)}>
        {allocating && <AllocateDialog key={allocating.id} payment={allocating} onDone={() => setAllocating(null)} />}
      </Dialog>
    </>
  );
}
