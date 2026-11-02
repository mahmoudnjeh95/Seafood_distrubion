import { CustomerKindEnum, useListCustomers } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  Icon,
  Input,
  PageHeader,
  Pager,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SortTh,
  Table,
  Td,
  useTableView,
  useUrlState,
} from "@frutti/ui";
import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router";

import { type Status, StatusFilter } from "../lib/StatusFilter";
import { useDebounced } from "../lib/useDebounced";
import { CustomerDialog } from "./CustomerDialog";
import { canEditCustomers } from "./shared";

const ALL_KINDS = "all";

export function CustomersPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const navigate = useNavigate();
  const canEdit = canEditCustomers(session);
  const [search, setSearch] = useUrlState("q");
  const [status, setStatus] = useState<Status>("active");
  const [kind, setKind] = useState(ALL_KINDS);
  const [creating, setCreating] = useState(false);
  const query = useDebounced(search.trim());

  const customers = useListCustomers(
    {
      status,
      ...(query ? { search: query } : {}),
      ...(kind !== ALL_KINDS ? { kind: kind as CustomerKindEnum } : {}),
    },
    { query: { placeholderData: keepPreviousData } },
  );
  const list = customers.data ?? [];
  const filtering = query !== "" || status !== "active" || kind !== ALL_KINDS;

  const view = useTableView(list, {
    reference: (customer) => customer.reference,
    name: (customer) => customer.name,
    kind: (customer) => customer.kind,
    phone: (customer) => customer.phone,
    creditLimit: (customer) => Number(customer.credit_limit),
    paymentTerms: (customer) => customer.payment_terms_days,
  });
  const sorting = { sort: view.sort, onSort: view.toggleSort };

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.sales")} title={t("admin.customers.title")}>
        {canEdit && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Icon name="plus" />
            {t("admin.customers.add")}
          </Button>
        )}
      </PageHeader>

      {!canEdit && <p className="text-ink-2">{t("admin.customers.readOnly")}</p>}

      <Card className="filter-bar flex flex-wrap items-center gap-3 p-3">
        <Input
          type="search"
          aria-label={t("admin.customers.search")}
          placeholder={t("admin.customers.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="min-w-52 flex-[2_1_14rem]"
        />
        <div className="min-w-44 flex-[1_1_10rem]">
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger aria-label={t("admin.customers.kindFilter")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_KINDS}>{t("admin.customers.allKinds")}</SelectItem>
              {Object.values(CustomerKindEnum).map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`admin.customers.kinds.${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <StatusFilter
          value={status}
          onChange={setStatus}
          label={t("admin.customers.show")}
          labels={{
            active: t("admin.customers.status.active"),
            archived: t("admin.customers.status.archived"),
            all: t("admin.customers.status.all"),
          }}
        />
        <span className="ms-auto text-[0.85rem] text-ink-2" aria-live="polite">
          {customers.data && t("admin.customers.count", { count: list.length })}
        </span>
      </Card>

      {customers.isPending ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : customers.isError ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : list.length === 0 ? (
        filtering ? (
          <p className="text-ink-2">{t("admin.customers.noMatch")}</p>
        ) : (
          <EmptyState illustration="shrimp" title={t("admin.customers.empty")}>
            {t("admin.customers.emptyBody")}
          </EmptyState>
        )
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <SortTh sortKey="reference" {...sorting}>
                  {t("admin.customers.columns.reference")}
                </SortTh>
                <SortTh sortKey="name" {...sorting}>
                  {t("admin.customers.columns.name")}
                </SortTh>
                <SortTh sortKey="kind" {...sorting} className="max-[720px]:hidden">
                  {t("admin.customers.columns.kind")}
                </SortTh>
                <SortTh sortKey="phone" {...sorting} className="max-[720px]:hidden">
                  {t("admin.customers.columns.phone")}
                </SortTh>
                <SortTh numeric sortKey="creditLimit" {...sorting}>
                  {t("admin.customers.columns.creditLimit")}
                </SortTh>
                <SortTh sortKey="paymentTerms" {...sorting} className="max-[720px]:hidden">
                  {t("admin.customers.columns.paymentTerms")}
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((customer) => (
                // The name is the link; a click anywhere on the row opens the same page.
                <tr
                  key={customer.id}
                  onClick={() => void navigate(`/clients/${customer.id}`)}
                  className="cursor-pointer hover:bg-surface-2"
                >
                  <Td className="num whitespace-nowrap text-ink-2">{customer.reference}</Td>
                  <Td>
                    <Link
                      to={`/clients/${customer.id}`}
                      className="font-semibold text-ink hover:underline"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {customer.name}
                    </Link>
                    {!customer.is_active && (
                      <Pill className="ms-2" tone="neutral">
                        {t("admin.customers.archived")}
                      </Pill>
                    )}
                    {customer.city && <div className="text-[0.8rem] text-ink-2">{customer.city}</div>}
                  </Td>
                  <Td className="whitespace-nowrap max-[720px]:hidden">
                    {t(`admin.customers.kinds.${customer.kind}`)}
                  </Td>
                  <Td className="num whitespace-nowrap max-[720px]:hidden">{customer.phone}</Td>
                  <Td className="num whitespace-nowrap text-end">
                    {Number(customer.credit_limit) > 0 ? (
                      formatMoney(customer.credit_limit)
                    ) : (
                      <span className="text-ink-2">{t("admin.customers.noCredit")}</span>
                    )}
                  </Td>
                  <Td className="whitespace-nowrap max-[720px]:hidden">
                    {customer.payment_terms_days === 0
                      ? t("admin.customers.paymentOnDelivery")
                      : t("admin.customers.paymentTermsValue", { count: customer.payment_terms_days })}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Pager {...view.pager} />
        </Card>
      )}

      <Dialog open={creating} onOpenChange={setCreating}>
        {creating && (
          <CustomerDialog
            onDone={(created) => {
              setCreating(false);
              if (created) void navigate(`/clients/${created.id}`);
            }}
          />
        )}
      </Dialog>
    </>
  );
}
