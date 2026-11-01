import {
  type CustomerPayment,
  type CustomerPaymentMethodEnum,
  getExportCustomerPaymentsUrl,
  useGetCustomerPaymentTotals,
  useGetReceivablesAgeing,
  useGetWithholdingSummary,
  useListCustomerPayments,
  voidCustomerPayment,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
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
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { PdfButton } from "../lib/PdfButton";
import { useDebounced } from "../lib/useDebounced";
import { TresorerieRibbon } from "../treasury/TresorerieRibbon";
import { filterParams, isFiltered, type ListFilters, NO_FILTERS } from "./listFilters";
import { MeansChips, PaymentListFilters, PaymentTotalsCard } from "./ListParts";
import { PaymentDialog } from "./PaymentDialog";
import { canCollect, refreshAfterPayment } from "./shared";

const PAGE_SIZE = 50;
const METHODS: readonly CustomerPaymentMethodEnum[] = ["cash", "cheque", "bill", "transfer", "card", "mixed"];

function VoidDialog({ payment, onClose }: { payment: CustomerPayment; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => voidCustomerPayment(payment.id, { reason: reason.trim() }),
    onSuccess: async () => {
      toast.success(t("admin.payments.void.done", { number: payment.number }));
      await refreshAfterPayment(queryClient);
      onClose();
    },
    onError: (failure) => {
      const fromServer = fieldErrors(failure);
      if (fromServer.reason) setError(fromServer.reason);
      else toast.error(t("admin.payments.void.error"));
    },
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{t("admin.payments.void.title", { number: payment.number })}</DialogTitle>
        <DialogDescription>{t("admin.payments.void.body")}</DialogDescription>
        <Field label={t("admin.payments.void.reason")} htmlFor="void-reason" error={error}>
          <Input id="void-reason" value={reason} maxLength={255} onChange={(event) => setReason(event.target.value)} />
        </Field>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("admin.payments.dialog.cancel")}
          </Button>
          <Button variant="danger" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
            {t("admin.payments.void.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AgeingCard({ canWrite }: { canWrite: boolean }) {
  const { t } = useTranslation();
  const ageing = useGetReceivablesAgeing();
  const [paying, setPaying] = useState<{ id: number; name: string; owed: string } | null>(null);
  const data = ageing.data;
  return (
    <Card className="p-2">
      <CardTitle className="px-2 pt-2">{t("admin.payments.ageing.title")}</CardTitle>
      {!data ? (
        <p className="px-2 pb-2 text-ink-2">{t("common.loading")}</p>
      ) : data.rows.length === 0 ? (
        <p className="px-2 pb-2 text-ink-2">{t("admin.payments.ageing.empty")}</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.payments.ageing.customer")}</Th>
              <Th numeric>{t("admin.payments.ageing.d0_30")}</Th>
              <Th numeric>{t("admin.payments.ageing.d31_60")}</Th>
              <Th numeric>{t("admin.payments.ageing.d60_plus")}</Th>
              <Th numeric>{t("admin.payments.ageing.credit")}</Th>
              <Th numeric>{t("admin.payments.ageing.balance")}</Th>
              {canWrite && <Th>{null}</Th>}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.customer.id}>
                <Td>
                  <Link to={`/clients/${row.customer.id}`} className="font-semibold text-ink hover:underline">
                    {row.customer.name}
                  </Link>
                </Td>
                <Td numeric>{formatMoney(row.ageing.d0_30)}</Td>
                <Td numeric>{formatMoney(row.ageing.d31_60)}</Td>
                <Td numeric>{formatMoney(row.ageing.d60_plus)}</Td>
                <Td numeric>{formatMoney(row.credit)}</Td>
                <Td numeric className="font-semibold">
                  {formatMoney(row.balance)}
                </Td>
                {canWrite && (
                  <Td>
                    <Button
                      variant="ghost"
                      onClick={() => setPaying({ id: row.customer.id, name: row.customer.name, owed: row.balance })}
                    >
                      {t("admin.payments.ageing.collect")}
                    </Button>
                  </Td>
                )}
              </tr>
            ))}
            <tr className="font-semibold">
              <Td>{t("admin.payments.ageing.total")}</Td>
              <Td numeric>{formatMoney(data.totals.d0_30)}</Td>
              <Td numeric>{formatMoney(data.totals.d31_60)}</Td>
              <Td numeric>{formatMoney(data.totals.d60_plus)}</Td>
              <Td numeric>{formatMoney(data.total_credit)}</Td>
              <Td numeric>{formatMoney(data.total_balance)}</Td>
              {canWrite && <Td>{null}</Td>}
            </tr>
          </tbody>
        </Table>
      )}
      {paying && <PaymentDialog customer={paying} owed={paying.owed} onClose={() => setPaying(null)} />}
    </Card>
  );
}

function WithholdingCard() {
  const { t } = useTranslation();
  const summary = useGetWithholdingSummary();
  const data = summary.data;
  if (!data || (data.count === 0 && data.awaiting.length === 0)) return null;
  return (
    <Card className="p-2">
      <CardTitle className="px-2 pt-2">{t("admin.payments.withholding.title")}</CardTitle>
      <p className="px-2 pb-2 text-[0.9rem] text-ink-2">
        {t("admin.payments.withholding.summary", {
          count: data.count,
          total: formatMoney(data.total),
          awaiting: data.awaiting.length,
          awaitingTotal: formatMoney(data.awaiting_total),
        })}
      </p>
      <Table>
        <thead>
          <tr>
            <Th>{t("admin.payments.withholding.month")}</Th>
            <Th numeric>{t("admin.payments.withholding.count")}</Th>
            <Th numeric>{t("admin.payments.withholding.amount")}</Th>
          </tr>
        </thead>
        <tbody>
          {data.by_month.map((row) => (
            <tr key={row.month}>
              <Td className="num">{row.month}</Td>
              <Td numeric>{row.count}</Td>
              <Td numeric>{formatMoney(row.amount)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

/** "Règlements": what customers owe by age, withholding totals for the accountant, and every payment. */
export function PaymentsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canWrite = canCollect(session);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [voiding, setVoiding] = useState<CustomerPayment | null>(null);
  const [filters, setFilters] = useState<ListFilters<CustomerPaymentMethodEnum>>(NO_FILTERS);
  const query = useDebounced(search.trim());
  const shared = { ...filterParams(filters), ...(query ? { search: query } : {}) };
  const payments = useListCustomerPayments(
    { limit: PAGE_SIZE, offset, ...shared },
    { query: { placeholderData: keepPreviousData } },
  );
  const totals = useGetCustomerPaymentTotals(shared, { query: { placeholderData: keepPreviousData } });
  const methodLabel = (method: string) => t(`admin.sales.methods.${method as CustomerPaymentMethodEnum}`);
  const page = payments.data;
  const list = page?.results ?? [];

  return (
    <>
      <TresorerieRibbon active="encaissement" />
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.payments.title")}>
        {canWrite && (
          <Button variant="primary" asChild>
            <Link to="/reglements/nouveau">{t("admin.treasury.form.new")}</Link>
          </Button>
        )}
      </PageHeader>
      <p className="text-ink-2">{t("admin.payments.intro")}</p>
      <AgeingCard canWrite={canWrite} />
      <WithholdingCard />
      <Card className="filter-bar flex flex-wrap items-end gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.payments.search")}
          placeholder={t("admin.payments.search")}
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
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {page && t("admin.payments.count", { count: page.count })}
        </span>
      </Card>
      <PaymentTotalsCard
        totals={totals.data}
        methodLabel={methodLabel}
        restLabel={t("admin.treasury.form.credit")}
        exportUrl={getExportCustomerPaymentsUrl(shared)}
      />
      {payments.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : list.length === 0 ? (
        query || isFiltered(filters) ? (
          <p className="text-ink-2">{t("admin.treasury.list.noMatch")}</p>
        ) : (
          <EmptyState illustration="mix" title={t("admin.payments.empty")}>
            {t("admin.payments.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.payments.columns.number")}</Th>
                <Th>{t("admin.payments.columns.date")}</Th>
                <Th>{t("admin.payments.columns.customer")}</Th>
                <Th className="max-[720px]:hidden">{t("admin.payments.columns.reason")}</Th>
                <Th>{t("admin.payments.columns.method")}</Th>
                <Th numeric>{t("admin.payments.columns.amount")}</Th>
                <Th numeric>{t("admin.payments.columns.remaining")}</Th>
                <Th numeric>{t("admin.payments.columns.credit")}</Th>
                <Th>{null}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((payment) => (
                <tr key={payment.id}>
                  <Td className="num whitespace-nowrap font-semibold">
                    <Link to={`/reglements/${payment.id}`} className="text-sea hover:underline">
                      {payment.number}
                    </Link>
                    {payment.is_voided && (
                      <Pill tone="bad" className="ms-2">
                        {t("admin.payments.voided")}
                      </Pill>
                    )}
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(payment.received_on)}</Td>
                  <Td>
                    <Link to={`/clients/${payment.customer.id}`} className="hover:underline">
                      {payment.customer.name}
                    </Link>
                  </Td>
                  <Td className="max-[720px]:hidden">{payment.reason}</Td>
                  <Td>
                    <MeansChips lines={payment.lines} methodLabel={methodLabel} />
                  </Td>
                  <Td numeric>{formatMoney(payment.amount)}</Td>
                  <Td numeric>{formatMoney(payment.remaining)}</Td>
                  <Td numeric>{formatMoney(payment.unallocated)}</Td>
                  <Td>
                    <div className="flex items-center justify-end gap-1">
                      <PdfButton kind="receipt" id={payment.id} variant="ghost" />
                      {canWrite && !payment.is_voided && (
                        <Button variant="ghost" onClick={() => setVoiding(payment)}>
                          {t("admin.payments.void.action")}
                        </Button>
                      )}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {page && page.count > PAGE_SIZE && (
            <div className="flex items-center justify-between p-3">
              <Button
                variant="ghost"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                {t("admin.payments.previous")}
              </Button>
              <Button variant="ghost" disabled={!page.next} onClick={() => setOffset(offset + PAGE_SIZE)}>
                {t("admin.payments.next")}
              </Button>
            </div>
          )}
        </Card>
      )}
      {voiding && <VoidDialog payment={voiding} onClose={() => setVoiding(null)} />}
    </>
  );
}
