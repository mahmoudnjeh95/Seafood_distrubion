import { createInvoice, useListCustomers, useListSales, useListUninvoicedCounts } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  Combobox,
  type ComboboxOption,
  EmptyState,
  PageHeader,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { canInvoice } from "./shared";

// Sum of decimal strings in millimes, so no float ever adds up money.
const millimes = (value: string) => Math.round(Number(value) * 1000);

/**
 * "Nouvelle facture" (D-200): pick a customer, tick one or several of their BL still to invoice, generate. Each
 * customer shows how many BL they have to invoice ("— 3 BL"). A generated invoice opens at once (D-283); on a
 * failure the page stays as it was, the BL still ticked.
 */
export function InvoiceBuilderPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const queryClient = useQueryClient();
  const [customer, setCustomer] = useState("");
  const navigate = useNavigate();
  const [chosen, setChosen] = useState<Set<number>>(new Set());

  const customers = useListCustomers({ status: "active" });
  const counts = useListUninvoicedCounts();
  const options = useMemo<ComboboxOption[]>(() => {
    const toInvoice = new Map((counts.data ?? []).map((row) => [row.customer, row.count]));
    return (customers.data ?? [])
      .filter((row) => !row.is_walk_in)
      .map((row) => {
        const count = toInvoice.get(row.id) ?? 0;
        return {
          value: String(row.id),
          label: count > 0 ? t("admin.invoiceBuilder.customerWithCount", { name: row.name, count }) : row.name,
          keywords: [row.reference, row.city].filter(Boolean),
        };
      });
  }, [customers.data, counts.data, t]);
  const sales = useListSales(
    { customer: Number(customer), uninvoiced: true, limit: 200 },
    { query: { enabled: customer !== "" } },
  );
  const open = sales.data?.results ?? [];
  const picked = open.filter((sale) => chosen.has(sale.id));
  const total = picked.reduce((sum, sale) => sum + millimes(sale.total), 0);

  const generate = useMutation({
    mutationFn: (issue: boolean) => createInvoice({ sales: picked.map((sale) => sale.id), issue_now: issue }),
    onSuccess: async (invoice) => {
      toast.success(
        t("admin.invoiceBuilder.made", {
          count: picked.length,
          number: invoice.number || t("admin.invoices.draftNumber"),
        }),
      );
      await queryClient.invalidateQueries();
      void navigate(`/factures/${invoice.id}`);
    },
    onError: (failure) => toast.error(Object.values(fieldErrors(failure))[0] ?? t("admin.invoiceBuilder.failed")),
  });

  if (!canInvoice(session)) return <Navigate to="/factures" replace />;

  const toggle = (id: number) =>
    setChosen((now) => {
      const next = new Set(now);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allChosen = open.length > 0 && picked.length === open.length;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.invoiceBuilder.title")} />
      <p className="text-ink-2">{t("admin.invoiceBuilder.intro")}</p>

      <Card className="flex flex-col gap-3">
        <label htmlFor="builder-customer" className="font-semibold">
          {t("admin.invoiceBuilder.customer")}
        </label>
        <Combobox
          id="builder-customer"
          className="max-w-md"
          value={customer}
          onValueChange={(value) => {
            setCustomer(value);
            setChosen(new Set());
          }}
          options={options}
          empty={t("admin.invoiceBuilder.noCustomer")}
          placeholder={t("admin.invoiceBuilder.customerPlaceholder")}
        />
      </Card>

      {customer !== "" && (
        <Card className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <CardTitle className="mb-0">{t("admin.invoiceBuilder.toInvoice")}</CardTitle>
            <span className="text-ink-2">{t("admin.invoiceBuilder.hint")}</span>
          </div>
          {sales.isPending ? (
            <p className="text-ink-2">{t("common.loading")}</p>
          ) : open.length === 0 ? (
            <EmptyState illustration="mix" title={t("admin.invoiceBuilder.nothing")} />
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th className="w-10">
                      <input
                        type="checkbox"
                        aria-label={t("admin.invoiceBuilder.all")}
                        checked={allChosen}
                        onChange={() => setChosen(allChosen ? new Set() : new Set(open.map((sale) => sale.id)))}
                      />
                    </Th>
                    <Th>{t("admin.invoiceBuilder.number")}</Th>
                    <Th>{t("admin.invoiceBuilder.date")}</Th>
                    <Th numeric>{t("admin.invoiceBuilder.lines")}</Th>
                    <Th numeric>{t("admin.invoiceBuilder.amount")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {open.map((sale) => (
                    <tr key={sale.id} className="cursor-pointer" onClick={() => toggle(sale.id)}>
                      <Td>
                        <input
                          type="checkbox"
                          aria-label={sale.number}
                          checked={chosen.has(sale.id)}
                          onChange={() => toggle(sale.id)}
                          onClick={(event) => event.stopPropagation()}
                        />
                      </Td>
                      <Td>
                        <Link
                          to={`/ventes/${sale.id}`}
                          className="font-semibold text-sea hover:underline"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {sale.number}
                        </Link>
                      </Td>
                      <Td>{formatDate(sale.sold_at)}</Td>
                      <Td numeric>{sale.line_count}</Td>
                      <Td numeric>{formatMoney(sale.total)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <div className="flex flex-wrap items-center justify-end gap-3">
                <span className="me-auto">
                  {t("admin.invoiceBuilder.chosen", { count: picked.length })} ·{" "}
                  <b className="num">{formatMoney((total / 1000).toFixed(3))}</b>
                </span>
                <Button disabled={picked.length === 0 || generate.isPending} onClick={() => generate.mutate(false)}>
                  {t("admin.invoiceBuilder.draft")}
                </Button>
                <Button
                  variant="primary"
                  disabled={picked.length === 0 || generate.isPending}
                  onClick={() => generate.mutate(true)}
                >
                  {t("admin.invoiceBuilder.issue")}
                </Button>
              </div>
            </>
          )}
        </Card>
      )}
    </>
  );
}
