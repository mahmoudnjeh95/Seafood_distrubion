import { ApiError, type FieldPurchase, useGetFieldPurchase } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Card, CardTitle, cn, EmptyState, PageHeader, Pill, Table, Td, Th } from "@frutti/ui";
import type { ReactNode } from "react";
import { Link, Navigate, useOutletContext, useParams } from "react-router";

import { subtract } from "../lib/decimal";
import { canRecordReceipts } from "../receipts/shared";
import { FieldPurchaseForm } from "./FieldPurchaseForm";
import { FieldPurchaseHistory } from "./FieldPurchaseHistory";
import { STATUS_TONE } from "./shared";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

function BackLink() {
  const { t } = useTranslation();
  return (
    <Link to="/achats/terrain" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.fieldPurchases.back")}
    </Link>
  );
}

/** The deal as one line: "Comptant", "À 15 jours", "Fin de mois + 10 jours". */
function useTermsLabel() {
  const { t } = useTranslation();
  return (purchase: Pick<FieldPurchase, "terms" | "due_days">) => {
    if (purchase.terms === "days") return t("admin.fieldPurchases.terms.days", { count: purchase.due_days });
    if (purchase.terms === "month_end" && purchase.due_days > 0)
      return t("admin.fieldPurchases.terms.month_end_plus", { count: purchase.due_days });
    return t(`admin.fieldPurchases.terms.${purchase.terms}`);
  };
}

/** A purchase already validated or refused, or one the person may only read. */
function FieldPurchaseView({ purchase }: { purchase: FieldPurchase }) {
  const { t } = useTranslation();
  const termsLabel = useTermsLabel();
  const none = t("admin.fieldPurchases.detail.none");
  const boxes = Object.entries(purchase.boxes).filter(([, count]) => count > 0);

  return (
    <>
      {purchase.status !== "submitted" && (
        <p role="note" className="rounded-card border border-line bg-surface-2 p-3 text-[0.9rem]">
          {t(
            purchase.status === "validated"
              ? "admin.fieldPurchases.detail.validatedNote"
              : "admin.fieldPurchases.detail.refusedNote",
          )}
        </p>
      )}
      <Card>
        <CardTitle>{t("admin.fieldPurchases.detail.purchase")}</CardTitle>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
          <Detail label={t("admin.fieldPurchases.detail.supplier")}>
            {purchase.supplier ? (
              <Link to={`/fournisseurs/${purchase.supplier.id}`} className="font-semibold text-sea hover:underline">
                {purchase.supplier.name}
              </Link>
            ) : (
              <>
                {purchase.proposed_supplier} <Pill tone="warn">{t("admin.fieldPurchases.newName")}</Pill>
              </>
            )}
          </Detail>
          <Detail label={t("admin.fieldPurchases.detail.buyer")}>{purchase.buyer || none}</Detail>
          <Detail label={t("admin.fieldPurchases.detail.date")} numeric>
            {formatDate(purchase.bought_on)}
          </Detail>
          <Detail label={t("admin.fieldPurchases.detail.terms")}>{termsLabel(purchase)}</Detail>
          <Detail label={t("admin.fieldPurchases.detail.due")} numeric>
            {formatDate(purchase.due_date)}
          </Detail>
          <Detail label={t("admin.fieldPurchases.detail.supplierReference")} numeric>
            {purchase.supplier_reference || none}
          </Detail>
          <Detail label={t("admin.fieldPurchases.detail.location")}>{purchase.location?.name ?? none}</Detail>
          {purchase.receipt && (
            <Detail label={t("admin.fieldPurchases.detail.receipt")} numeric>
              <Link to={`/achats/${purchase.receipt.id}`} className="font-semibold text-sea hover:underline">
                {purchase.receipt.number}
              </Link>
            </Detail>
          )}
          {purchase.invoice ? (
            <Detail label={t("admin.fieldPurchases.detail.invoice")} numeric>
              <Link to={`/achats/factures/${purchase.invoice.id}`} className="font-semibold text-sea hover:underline">
                {purchase.invoice.number}
              </Link>
            </Detail>
          ) : (
            purchase.receipt &&
            purchase.supplier && (
              // Validating makes no invoice (D-200): the office makes it here, with other receipts if it wants.
              <Detail label={t("admin.fieldPurchases.detail.invoice")}>
                <Link
                  to={`/achats/factures/nouvelle?fournisseur=${purchase.supplier.id}&reception=${purchase.receipt.id}`}
                  className="font-semibold text-sea hover:underline"
                >
                  {t("admin.fieldPurchases.detail.makeInvoice")}
                </Link>
              </Detail>
            )
          )}
          {purchase.decided_by && (
            <Detail label={t("admin.fieldPurchases.detail.decided")}>{purchase.decided_by}</Detail>
          )}
          {boxes.length > 0 && (
            <Detail label={t("admin.fieldPurchases.detail.boxes")}>
              {boxes
                .map(([type, count]) => `${count} × ${t(`admin.boxes.types.${type as "small" | "big"}`)}`)
                .join(", ")}
            </Detail>
          )}
          {purchase.notes && (
            <div className="col-span-full">
              <Detail label={t("admin.fieldPurchases.detail.driverNote")}>
                <span className="whitespace-pre-line">{purchase.notes}</span>
              </Detail>
            </div>
          )}
          {purchase.office_note && (
            <div className="col-span-full">
              <Detail label={t("admin.fieldPurchases.detail.officeNote")}>
                <span className="whitespace-pre-line">{purchase.office_note}</span>
              </Detail>
            </div>
          )}
        </dl>
      </Card>

      <Card className="p-2">
        <CardTitle className="px-2.5 pt-2">{t("admin.fieldPurchases.detail.lines")}</CardTitle>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.fieldPurchases.form.product")}</Th>
              <Th numeric>{t("admin.fieldPurchases.form.declared")}</Th>
              <Th numeric>{t("admin.fieldPurchases.form.received")}</Th>
              <Th numeric>{t("admin.fieldPurchases.form.gap")}</Th>
              <Th numeric>{t("admin.fieldPurchases.form.cost")}</Th>
              <Th numeric>{t("admin.fieldPurchases.form.amount")}</Th>
            </tr>
          </thead>
          <tbody>
            {purchase.lines.map((line) => {
              const gap = subtract(line.owed_quantity, line.declared_quantity);
              return (
                <tr key={line.id}>
                  <Td>
                    <span className="font-semibold">{line.product?.name ?? line.proposed_product}</span>
                    {!line.product && (
                      <Pill className="ms-2" tone="warn">
                        {t("admin.fieldPurchases.newName")}
                      </Pill>
                    )}
                    {line.partner && (
                      <div className="text-[0.8rem] text-ink-2">
                        {t("admin.fieldPurchases.form.partner")} : {line.partner.name}
                      </div>
                    )}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatQuantity(line.declared_quantity)}
                  </Td>
                  <Td numeric className="font-semibold whitespace-nowrap">
                    {line.received_quantity ? formatQuantity(line.received_quantity) : none}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {/^-?0\.000$/.test(gap) ? (
                      ""
                    ) : (
                      <span className="font-semibold text-warn">{formatQuantity(gap)}</span>
                    )}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(line.unit_cost)}
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(line.amount)}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
        <dl className="flex flex-wrap justify-end gap-x-8 gap-y-2 border-t border-line px-2.5 py-3">
          {purchase.declared_total !== purchase.total && (
            <Detail label={t("admin.fieldPurchases.form.totalDeclared")} numeric>
              {formatMoney(purchase.declared_total)}
            </Detail>
          )}
          <Detail label={t("admin.fieldPurchases.form.total")} numeric>
            <b>{formatMoney(purchase.total)}</b>
          </Detail>
          <Detail label={t("admin.fieldPurchases.form.paid")} numeric>
            {formatMoney(purchase.paid)}
          </Detail>
          <Detail label={t("admin.fieldPurchases.form.rest")} numeric>
            <b>{formatMoney(purchase.rest)}</b>
          </Detail>
        </dl>
      </Card>

      {purchase.payments.length > 0 && (
        <Card className="p-2">
          <CardTitle className="px-2.5 pt-2">{t("admin.fieldPurchases.detail.payments")}</CardTitle>
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.fieldPurchases.form.method")}</Th>
                <Th>{t("admin.fieldPurchases.form.reference")}</Th>
                <Th>{t("admin.fieldPurchases.form.cashOn")}</Th>
                <Th>{t("admin.fieldPurchases.detail.paymentDoc")}</Th>
                <Th numeric>{t("admin.fieldPurchases.form.paymentAmount")}</Th>
              </tr>
            </thead>
            <tbody>
              {purchase.payments.map((payment) => (
                <tr key={payment.id}>
                  <Td>{t(`admin.supplierPayments.method.${payment.method}`)}</Td>
                  <Td className="num">{payment.reference || none}</Td>
                  <Td className="num">{payment.cash_on ? formatDate(payment.cash_on) : none}</Td>
                  <Td className="num">{payment.supplier_payment?.number ?? none}</Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatMoney(payment.amount)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </>
  );
}

/** One purchase at the port: the office's check form while it waits, else what it says; and its history. */
export function FieldPurchasePage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { purchaseId } = useParams();
  const id = Number(purchaseId);
  const validId = Number.isInteger(id) && id > 0;
  const purchase = useGetFieldPurchase(id, { query: { enabled: validId, retry: false } });

  if (validId && purchase.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!purchase.data) {
    const missing = !validId || (purchase.error instanceof ApiError && purchase.error.status === 404);
    return (
      <>
        <BackLink />
        <EmptyState
          illustration="fish"
          title={missing ? t("admin.fieldPurchases.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }

  const data = purchase.data;
  const editable = data.status === "submitted" && canRecordReceipts(session);
  return (
    <>
      <BackLink />
      <PageHeader
        eyebrow={`${formatDate(data.bought_on)} · ${data.supplier?.name ?? data.proposed_supplier}`}
        title={editable ? t("admin.fieldPurchases.form.editTitle", { number: data.number }) : data.number}
      >
        <Pill tone={STATUS_TONE[data.status]}>{t(`admin.fieldPurchases.status.${data.status}`)}</Pill>
        {data.is_late && <Pill tone="bad">{t("admin.fieldPurchases.late")}</Pill>}
      </PageHeader>
      {data.paper_url && (
        // The photo of the supplier's paper the driver took (D-159), to check the kilos and prices against.
        <Card className="flex flex-col gap-2">
          <CardTitle className="mb-0">{t("admin.fieldPurchases.detail.paper")}</CardTitle>
          <a href={data.paper_url} target="_blank" rel="noreferrer" className="w-fit">
            <img
              src={data.paper_url}
              alt={t("admin.fieldPurchases.detail.paper")}
              className="max-h-80 rounded-control border border-line object-contain"
            />
          </a>
          <p className="text-[0.85rem] text-ink-2">{t("admin.fieldPurchases.detail.paperHint")}</p>
        </Card>
      )}
      {editable ? (
        // Keyed by revision: after someone else's save, a reload starts the form from what is saved now.
        <FieldPurchaseForm
          key={data.revision}
          purchase={data}
          session={session}
          onReload={() => void purchase.refetch()}
        />
      ) : (
        <FieldPurchaseView purchase={data} />
      )}
      <FieldPurchaseHistory revisions={data.revisions} />
    </>
  );
}

/** Type a purchase phoned in by a driver. Owners and managers only; the server checks it too. */
export function FieldPurchaseNewPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  if (!canRecordReceipts(session)) return <Navigate to="/achats/terrain" replace />;
  return (
    <>
      <BackLink />
      <PageHeader eyebrow={t("admin.nav.purchases")} title={t("admin.fieldPurchases.form.newTitle")} />
      <FieldPurchaseForm session={session} />
    </>
  );
}
