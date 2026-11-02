import {
  type InvoiceStatusEnum,
  type ListInvoicesPaymentState,
  useListCreditNotes,
  useListInvoices,
} from "@frutti/api";
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
  TotalsRow,
  useServerTable,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { useDebounced } from "../lib/useDebounced";
import { totalOf } from "../lib/totals";
import { canInvoice, INVOICE_STATUSES, isZero, STATUS_TONES } from "./shared";

type Tab = "invoices" | "creditNotes";

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap rounded-control bg-surface-2 p-1">
      {options.map((option) => (
        <button
          key={option.value || "all"}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-[7px] px-3 py-1.5 text-[0.85rem] font-semibold text-ink-2",
            value === option.value && "bg-surface text-ink shadow-card",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** "Factures": every customer invoice (drafts first) and, on the second tab, every credit note. */
export function InvoicesPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("invoices");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<InvoiceStatusEnum | "">("");
  const [paymentState, setPaymentState] = useState<ListInvoicesPaymentState | "">("");
  const table = useServerTable();
  const query = useDebounced(search.trim());

  const invoices = useListInvoices(
    {
      ...table.params,
      ...(status ? { status } : {}),
      ...(paymentState ? { payment_state: paymentState } : {}),
      ...(query ? { search: query } : {}),
    },
    { query: { placeholderData: keepPreviousData, enabled: tab === "invoices" } },
  );
  const creditNotes = useListCreditNotes(
    { ...table.params, ...(query ? { search: query } : {}) },
    { query: { placeholderData: keepPreviousData, enabled: tab === "creditNotes" } },
  );
  const current = tab === "invoices" ? invoices : creditNotes;
  const filtering = query !== "" || (tab === "invoices" && (status !== "" || paymentState !== ""));

  let body: ReactNode;
  if (current.isPending) body = <p className="text-ink-2">{t("common.loading")}</p>;
  else if (current.isError)
    body = (
      <p role="alert" className="text-bad">
        {t("common.serverUnreachable")}
      </p>
    );
  else if (tab === "invoices") {
    const page = invoices.data;
    const list = page?.results ?? [];
    body =
      list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.invoices.noMatch")}</p>
        ) : (
          <EmptyState illustration="mix" title={t("admin.invoices.empty")}>
            {t("admin.invoices.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.invoices.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.invoices.columns.date")}
                </SortTh>
                <SortTh sortKey="customer" {...table.sorting}>
                  {t("admin.invoices.columns.customer")}
                </SortTh>
                <Th className="max-[720px]:hidden">{t("admin.invoices.columns.sale")}</Th>
                <Th numeric>{t("admin.invoices.columns.total")}</Th>
                <Th numeric className="max-[720px]:hidden">
                  {t("admin.invoices.columns.toCollect")}
                </Th>
              </tr>
            </thead>
            <tbody>
              {list.map((invoice) => (
                <tr
                  key={invoice.id}
                  onClick={() => void navigate(`/factures/${invoice.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap">
                    <Link
                      to={`/factures/${invoice.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {invoice.number || t("admin.invoices.draftNumber")}
                    </Link>
                    <Pill className="ms-2" tone={STATUS_TONES[invoice.status]}>
                      {t(`admin.invoices.statuses.${invoice.status}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{invoice.issued_on ? formatDate(invoice.issued_on) : "—"}</Td>
                  <Td>
                    <span className="font-semibold">{invoice.customer.name}</span>
                    <div className="num text-[0.8rem] text-ink-2">{invoice.customer.reference}</div>
                  </Td>
                  <Td className="num max-[720px]:hidden">{invoice.sales.map((sale) => sale.number).join(", ")}</Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(invoice.total_incl_tax)}
                  </Td>
                  <Td
                    numeric
                    className={cn(
                      "whitespace-nowrap max-[720px]:hidden",
                      invoice.status === "issued" && !isZero(invoice.remaining_to_pay) && "font-semibold",
                    )}
                  >
                    {invoice.status === "issued" ? formatMoney(invoice.remaining_to_pay) : "—"}
                    {invoice.payment_state === "partial" && (
                      <Pill className="ms-2" tone="warn">
                        {t("admin.invoices.paymentStates.partial")}
                      </Pill>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
            <TotalsRow
              span={4}
              cells={[
                {
                  value: totalOf(
                    list.filter((i) => i.status !== "cancelled"),
                    (i) => i.total_incl_tax,
                  ),
                },
                {
                  value: totalOf(
                    list.filter((i) => i.status === "issued"),
                    (i) => i.remaining_to_pay,
                  ),
                  phoneHidden: true,
                },
              ]}
            />
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      );
  } else {
    const page = creditNotes.data;
    const list = page?.results ?? [];
    body =
      list.length === 0 ? (
        <p className="text-ink-2">{filtering ? t("admin.invoices.noMatch") : t("admin.invoices.noCreditNotes")}</p>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="number" {...table.sorting}>
                  {t("admin.invoices.columns.number")}
                </SortTh>
                <SortTh sortKey="date" {...table.sorting}>
                  {t("admin.invoices.columns.date")}
                </SortTh>
                <SortTh sortKey="invoice" {...table.sorting}>
                  {t("admin.invoices.columns.invoice")}
                </SortTh>
                <SortTh sortKey="reason" {...table.sorting}>
                  {t("admin.invoices.columns.reason")}
                </SortTh>
                <Th numeric>{t("admin.invoices.columns.creditAmount")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((note) => (
                <tr key={note.id}>
                  <Td className="num font-semibold whitespace-nowrap">
                    {note.number}
                    <Pill className="ms-2" tone="sea">
                      {t(`admin.invoices.creditKinds.${note.kind}`)}
                    </Pill>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(note.issued_on)}</Td>
                  <Td>
                    <Link to={`/factures/${note.invoice.id}`} className="num font-semibold text-sea hover:underline">
                      {note.invoice.number}
                    </Link>
                    <div className="text-[0.8rem] text-ink-2">{note.invoice.customer_name}</div>
                  </Td>
                  <Td>{note.reason}</Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(note.net_amount)}
                  </Td>
                </tr>
              ))}
            </tbody>
            <TotalsRow span={4} cells={[{ value: totalOf(list, (n) => n.net_amount) }]} />
          </Table>
          {page && <Pager {...table.pager(page.count)} />}
        </Card>
      );
  }

  const count = tab === "invoices" ? invoices.data?.count : creditNotes.data?.count;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.invoices.title")}>
        {canInvoice(session) && (
          <Button variant="primary" onClick={() => void navigate("/factures/nouvelle")}>
            <Icon name="plus" />
            {t("admin.invoiceBuilder.title")}
          </Button>
        )}
        {(session.role === "owner" || session.role === "manager" || session.role === "accountant") && (
          <Button onClick={() => void navigate("/factures/parametres")}>
            <Icon name="percent" />
            {t("admin.financeSettings.title")}
          </Button>
        )}
      </PageHeader>
      <p className="text-ink-2">{t("admin.invoices.intro")}</p>

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Segmented
          label={t("admin.invoices.tabsLabel")}
          value={tab}
          options={[
            { value: "invoices", label: t("admin.invoices.tabs.invoices") },
            { value: "creditNotes", label: t("admin.invoices.tabs.creditNotes") },
          ]}
          onChange={(value) => {
            setTab(value);
            table.backToFirstPage();
          }}
        />
        <Input
          type="search"
          aria-label={t("admin.invoices.search")}
          placeholder={t("admin.invoices.search")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            table.backToFirstPage();
          }}
          className="min-w-52 flex-[2_1_14rem]"
        />
        {tab === "invoices" && (
          <Segmented
            label={t("admin.invoices.statusFilter")}
            value={status}
            options={[
              { value: "" as const, label: t("admin.invoices.allStatuses") },
              ...INVOICE_STATUSES.map((value) => ({ value, label: t(`admin.invoices.statuses.${value}`) })),
            ]}
            onChange={(value) => {
              setStatus(value);
              table.backToFirstPage();
            }}
          />
        )}
        {tab === "invoices" && (
          <Segmented
            label={t("admin.invoices.paymentFilter")}
            value={paymentState}
            options={[
              { value: "" as const, label: t("admin.invoices.allPayments") },
              ...(["unpaid", "partial", "paid"] as const).map((value) => ({
                value,
                label: t(`admin.invoices.paymentStates.${value}`),
              })),
            ]}
            onChange={(value) => {
              setPaymentState(value);
              table.backToFirstPage();
            }}
          />
        )}
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {count !== undefined &&
            (tab === "invoices" ? t("admin.invoices.count", { count }) : t("admin.invoices.creditCount", { count }))}
        </span>
      </Card>

      {body}
    </>
  );
}
