import { ApiError, archiveSupplier, restoreSupplier, type Supplier, useGetSupplier } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, cn, Dialog, EmptyState, PageHeader, Pill, toast } from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { fieldErrors } from "../lib/errors";
import { StatementButton } from "../lib/StatementButton";
import { usePartnerSuppliers } from "../partnerships/usePartnerSuppliers";
import { SupplierBalanceCard } from "../purchasing/SupplierBalanceCard";
import { canEditSuppliers, refreshSuppliers } from "./shared";
import { SupplierDialog } from "./SupplierDialog";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

export function SupplierDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canEdit = canEditSuppliers(session);
  const { supplierId } = useParams();
  const id = Number(supplierId);
  const validId = Number.isInteger(id) && id > 0;
  const supplier = useGetSupplier(id, { query: { enabled: validId, retry: false } });
  const partnerLots = usePartnerSuppliers(session);
  const [editing, setEditing] = useState(false);
  const queryClient = useQueryClient();

  const toggleActive = useMutation({
    mutationFn: (target: Supplier) => (target.is_active ? archiveSupplier(target.id) : restoreSupplier(target.id)),
    onSuccess: async (saved) => {
      toast.success(t(saved.is_active ? "admin.suppliers.form.restoredDone" : "admin.suppliers.form.archivedDone"));
      await refreshSuppliers(queryClient);
    },
    onError: (failure) => toast.error(fieldErrors(failure).detail ?? t("admin.suppliers.form.error")),
  });

  const back = (
    <Link to="/fournisseurs" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.suppliers.back")}
    </Link>
  );

  if (validId && supplier.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!supplier.data) {
    const missing = !validId || (supplier.error instanceof ApiError && supplier.error.status === 404);
    return (
      <>
        {back}
        <EmptyState
          illustration="shrimp"
          title={missing ? t("admin.suppliers.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }

  const data = supplier.data;
  const empty = t("admin.suppliers.detail.empty");

  return (
    <>
      {back}
      <PageHeader eyebrow={data.reference} title={data.name}>
        {partnerLots?.has(data.id) && (
          <Pill tone="good">
            {t("admin.suppliers.partner")} · {t("admin.suppliers.partnerLots", { count: partnerLots.get(data.id) })}
          </Pill>
        )}
        {partnerLots && !partnerLots.has(data.id) && <Pill tone="neutral">{t("admin.suppliers.notPartnerShort")}</Pill>}
        {!data.is_active && <Pill tone="neutral">{t("admin.suppliers.archived")}</Pill>}
        <StatementButton side="supplier" id={data.id} name={data.name} />
        {canEdit && (
          <>
            <Button variant="ghost" disabled={toggleActive.isPending} onClick={() => toggleActive.mutate(data)}>
              {t(data.is_active ? "admin.suppliers.form.archive" : "admin.suppliers.form.restore")}
            </Button>
            <Button variant="primary" onClick={() => setEditing(true)}>
              {t("admin.suppliers.detail.edit")}
            </Button>
          </>
        )}
      </PageHeader>

      <div className="grid items-start gap-4 min-[960px]:grid-cols-[3fr_2fr]">
        <Card>
          <CardTitle>{t("admin.suppliers.detail.identity")}</CardTitle>
          <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
            <Detail label={t("admin.suppliers.form.taxId")} numeric>
              {data.tax_id || empty}
            </Detail>
            <Detail label={t("admin.suppliers.form.phone")} numeric>
              {data.phone ? <a href={`tel:${data.phone.replace(/\s/g, "")}`}>{data.phone}</a> : empty}
            </Detail>
            <Detail label={t("admin.suppliers.form.email")}>
              {data.email ? <a href={`mailto:${data.email}`}>{data.email}</a> : empty}
            </Detail>
            <Detail label={t("admin.suppliers.form.city")}>{data.city || empty}</Detail>
            <div className="col-span-full">
              <Detail label={t("admin.suppliers.form.address")}>{data.address || empty}</Detail>
            </div>
            {data.notes && (
              <div className="col-span-full">
                <Detail label={t("admin.suppliers.detail.notes")}>
                  <span className="whitespace-pre-line">{data.notes}</span>
                </Detail>
              </div>
            )}
          </dl>
        </Card>

        <Card>
          <CardTitle>{t("admin.suppliers.detail.contacts")}</CardTitle>
          {data.contacts.length === 0 ? (
            <p className="text-ink-2">{t("admin.suppliers.detail.noContacts")}</p>
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

        <SupplierBalanceCard
          supplierId={data.id}
          supplierName={data.name}
          canRecord={canEdit}
          canClear={session.role === "owner"}
        />
      </div>

      <Dialog open={editing} onOpenChange={setEditing}>
        {editing && <SupplierDialog key={data.updated_at} supplier={data} onDone={() => setEditing(false)} />}
      </Dialog>
    </>
  );
}
