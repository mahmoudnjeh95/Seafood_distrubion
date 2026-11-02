import { ApiError, archiveCustomer, type Customer, restoreCustomer, useGetCustomer } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, cn, Dialog, EmptyState, PageHeader, Pill, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { fieldErrors } from "../lib/errors";
import { StatementButton } from "../lib/StatementButton";
import { CustomerBoxesCard } from "../boxes/CustomerBoxesCard";
import { canCollect } from "../payments/shared";
import { BalanceCard } from "./BalanceCard";
import { CustomerDialog } from "./CustomerDialog";
import { canEditCustomers, refreshCustomers } from "./shared";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

export function CustomerDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canEdit = canEditCustomers(session);
  const { customerId } = useParams();
  const id = Number(customerId);
  const validId = Number.isInteger(id) && id > 0;
  const customer = useGetCustomer(id, { query: { enabled: validId, retry: false } });
  const [editing, setEditing] = useState(false);
  const queryClient = useQueryClient();

  const toggleActive = useMutation({
    mutationFn: (target: Customer) => (target.is_active ? archiveCustomer(target.id) : restoreCustomer(target.id)),
    onSuccess: async (saved) => {
      toast.success(t(saved.is_active ? "admin.customers.form.restoredDone" : "admin.customers.form.archivedDone"));
      await refreshCustomers(queryClient);
    },
    onError: (failure) => toast.error(fieldErrors(failure).detail ?? t("admin.customers.form.error")),
  });

  const back = (
    <Link to="/clients" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.customers.back")}
    </Link>
  );

  if (validId && customer.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!customer.data) {
    const missing = !validId || (customer.error instanceof ApiError && customer.error.status === 404);
    return (
      <>
        {back}
        <EmptyState
          illustration="shrimp"
          title={missing ? t("admin.customers.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }

  const data = customer.data;
  const empty = t("admin.customers.detail.empty");

  return (
    <>
      {back}
      <PageHeader eyebrow={data.reference} title={data.name}>
        {!data.is_active && <Pill tone="neutral">{t("admin.customers.archived")}</Pill>}
        <StatementButton side="customer" id={data.id} name={data.name} />
        {canEdit && (
          <>
            {!data.is_walk_in && (
              <Button variant="ghost" disabled={toggleActive.isPending} onClick={() => toggleActive.mutate(data)}>
                {t(data.is_active ? "admin.customers.form.archive" : "admin.customers.form.restore")}
              </Button>
            )}
            <Button variant="primary" onClick={() => setEditing(true)}>
              {t("admin.customers.detail.edit")}
            </Button>
          </>
        )}
      </PageHeader>

      {data.is_walk_in && <p className="text-ink-2">{t("admin.customers.detail.walkInNote")}</p>}

      <div className="grid items-start gap-4 min-[960px]:grid-cols-[3fr_2fr]">
        <Card>
          <CardTitle>{t("admin.customers.detail.identity")}</CardTitle>
          <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
            <Detail label={t("admin.customers.form.kind")}>{t(`admin.customers.kinds.${data.kind}`)}</Detail>
            <Detail label={t("admin.customers.form.taxId")} numeric>
              {data.tax_id || empty}
            </Detail>
            <Detail label={t("admin.customers.form.phone")} numeric>
              {data.phone ? <a href={`tel:${data.phone.replace(/\s/g, "")}`}>{data.phone}</a> : empty}
            </Detail>
            <Detail label={t("admin.customers.form.email")}>
              {data.email ? <a href={`mailto:${data.email}`}>{data.email}</a> : empty}
            </Detail>
            <Detail label={t("admin.customers.form.city")}>{data.city || empty}</Detail>
            <div className="col-span-full">
              <Detail label={t("admin.customers.form.address")}>{data.address || empty}</Detail>
            </div>
            {data.notes && (
              <div className="col-span-full">
                <Detail label={t("admin.customers.detail.notes")}>
                  <span className="whitespace-pre-line">{data.notes}</span>
                </Detail>
              </div>
            )}
          </dl>
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <CardTitle>{t("admin.customers.detail.credit")}</CardTitle>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
              <Detail label={t("admin.customers.form.creditLimit")} numeric>
                {Number(data.credit_limit) > 0 ? formatMoney(data.credit_limit) : t("admin.customers.noCredit")}
              </Detail>
              <Detail label={t("admin.customers.form.paymentTerms")}>
                {data.payment_terms_days === 0
                  ? t("admin.customers.paymentOnDelivery")
                  : t("admin.customers.paymentTermsValue", { count: data.payment_terms_days })}
              </Detail>
            </dl>
          </Card>

          <Card>
            <CardTitle>{t("admin.customers.detail.contacts")}</CardTitle>
            {data.contacts.length === 0 ? (
              <p className="text-ink-2">{t("admin.customers.detail.noContacts")}</p>
            ) : (
              <ul className="flex flex-col divide-y divide-line">
                {data.contacts.map((contact, index) => (
                  <li key={index} className="flex flex-col gap-0.5 py-2.5 first:pt-0 last:pb-0">
                    <span className="font-semibold">
                      {contact.name}
                      {contact.role && <span className="font-normal text-ink-2"> · {contact.role}</span>}
                    </span>
                    {contact.phone && (
                      <a className="num text-[0.9rem]" href={`tel:${contact.phone.replace(/\s/g, "")}`}>
                        {contact.phone}
                      </a>
                    )}
                    {contact.email && (
                      <a className="text-[0.9rem]" href={`mailto:${contact.email}`}>
                        {contact.email}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        {!data.is_walk_in && (
          <BalanceCard
            customer={{ id: data.id, name: data.name }}
            canCollect={canCollect(session)}
            canClear={session.role === "owner"}
          />
        )}
        {!data.is_walk_in && <CustomerBoxesCard customerName={data.name} />}
      </div>

      <Dialog open={editing} onOpenChange={setEditing}>
        {editing && <CustomerDialog key={data.updated_at} customer={data} onDone={() => setEditing(false)} />}
      </Dialog>
    </>
  );
}
