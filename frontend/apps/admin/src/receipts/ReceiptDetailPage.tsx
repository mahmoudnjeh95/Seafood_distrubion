import { ApiError, type ReceiptLine, useGetReceipt } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatDateTime, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, CardTitle, cn, Dialog, EmptyState, Icon, PageHeader, Pill, Table, Td, Th } from "@frutti/ui";
import type { ReactNode } from "react";
import { useState } from "react";
import { Link, useOutletContext, useParams } from "react-router";

import { AttachmentsCard } from "../lib/AttachmentsCard";
import { subtract } from "../lib/decimal";
import { canRecordReceipts } from "./shared";
import { ReceiptDisputeDialog } from "./ReceiptDisputeDialog";
import { ReceiptEditDialog } from "./ReceiptEditDialog";
import { ReceiptHistory } from "./ReceiptHistory";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

/** "−2,000 kg" in warning colour, or nothing when the two weights agree. */
function Gap({ accepted, other }: { accepted: string; other: string }) {
  const gap = subtract(accepted, other);
  if (/^-?0\.000$/.test(gap)) return null;
  return <span className="font-semibold text-warn">{formatQuantity(gap)}</span>;
}

export function ReceiptDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const { receiptId } = useParams();
  const id = Number(receiptId);
  const validId = Number.isInteger(id) && id > 0;
  const receipt = useGetReceipt(id, { query: { enabled: validId, retry: false } });
  const [editing, setEditing] = useState(false);
  const [disputing, setDisputing] = useState<"dispute" | "resolve" | null>(null);

  const back = (
    <Link to="/achats" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.receipts.back")}
    </Link>
  );

  if (validId && receipt.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!receipt.data) {
    const missing = !validId || (receipt.error instanceof ApiError && receipt.error.status === 404);
    return (
      <>
        {back}
        <EmptyState
          illustration="fish"
          title={missing ? t("admin.receipts.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }

  const data = receipt.data;
  // Changed by the owner or the manager while no invoice carries it; the server refuses the rest (D-269).
  const canEdit = data.editable && canRecordReceipts(session);
  // Contested while no invoice carries it, lifted when settled (D-285); the server refuses the rest.
  const disputed = data.dispute_status === "open";
  const canDispute = canRecordReceipts(session) && !data.invoice && !disputed;
  const canResolve = canRecordReceipts(session) && disputed;
  const none = t("admin.receipts.detail.none");
  const differing = data.lines.filter((line) => line.has_difference);
  // The ordered weight is optional: a receipt where none was typed (or against a purchase order) has no such column.
  const hasOrdered = data.lines.some((line) => line.ordered_quantity);
  const describe = (line: ReceiptLine) =>
    line.accepted_quantity !== line.invoiced_quantity
      ? t("admin.receipts.detail.differenceLine", {
          product: line.product.name,
          batch: line.batch.number,
          accepted: formatQuantity(line.accepted_quantity),
          invoiced: formatQuantity(line.invoiced_quantity),
        })
      : t("admin.receipts.detail.orderedLine", {
          product: line.product.name,
          batch: line.batch.number,
          accepted: formatQuantity(line.accepted_quantity),
          ordered: formatQuantity(line.ordered_quantity ?? line.accepted_quantity),
        });

  return (
    <>
      {back}
      <PageHeader eyebrow={`${formatDate(data.received_on)} · ${data.supplier.name}`} title={data.number}>
        {data.has_differences && <Pill tone="warn">{t("admin.receipts.difference")}</Pill>}
        {disputed && <Pill tone="bad">{t("admin.receipts.dispute.pill")}</Pill>}
      </PageHeader>
      {(canEdit || canDispute || canResolve) && (
        <div className="flex flex-wrap gap-2">
          {canEdit && <Button onClick={() => setEditing(true)}>{t("admin.receipts.edit.open")}</Button>}
          {canDispute && <Button onClick={() => setDisputing("dispute")}>{t("admin.receipts.dispute.open")}</Button>}
          {canResolve && <Button onClick={() => setDisputing("resolve")}>{t("admin.receipts.dispute.lift")}</Button>}
        </div>
      )}
      <Dialog open={editing} onOpenChange={setEditing}>
        {editing && <ReceiptEditDialog receipt={data} onDone={() => setEditing(false)} />}
      </Dialog>
      <Dialog open={disputing !== null} onOpenChange={(open) => !open && setDisputing(null)}>
        {disputing && <ReceiptDisputeDialog receipt={data} mode={disputing} onDone={() => setDisputing(null)} />}
      </Dialog>

      {data.dispute_status !== "" && (
        <div
          role="note"
          className={cn(
            "flex items-start gap-3 rounded-card border border-line p-3",
            disputed ? "bg-bad-soft" : "bg-surface-2",
          )}
        >
          <div className="flex flex-col gap-0.5 text-[0.9rem]">
            <b>{t(disputed ? "admin.receipts.dispute.openTitle" : "admin.receipts.dispute.resolvedTitle")}</b>
            <span>
              {t("admin.receipts.dispute.reasonLine", {
                reason: data.dispute_reason,
                name: data.disputed_by || "—",
                at: data.disputed_at ? formatDateTime(data.disputed_at) : "—",
              })}
            </span>
            {!disputed && (
              <span>
                {t("admin.receipts.dispute.resolutionLine", {
                  resolution: data.dispute_resolution,
                  name: data.dispute_resolved_by || "—",
                  at: data.dispute_resolved_at ? formatDateTime(data.dispute_resolved_at) : "—",
                })}
              </span>
            )}
            {disputed && <span className="text-ink-2">{t("admin.receipts.dispute.blocked")}</span>}
          </div>
        </div>
      )}

      {differing.length > 0 && (
        <div role="note" className="flex items-start gap-3 rounded-card border border-line bg-warn-soft p-3">
          <span className="text-warn">
            <Icon name="scale" />
          </span>
          <div className="flex flex-col gap-0.5">
            <b>{t("admin.receipts.detail.differenceTitle")}</b>
            {differing.map((line) => (
              <span key={line.id} className="text-[0.9rem]">
                {describe(line)}
              </span>
            ))}
          </div>
        </div>
      )}

      <Card>
        <CardTitle>{t("admin.receipts.detail.receipt")}</CardTitle>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
          <Detail label={t("admin.receipts.detail.supplier")}>
            <Link to={`/fournisseurs/${data.supplier.id}`} className="font-semibold text-sea hover:underline">
              {data.supplier.name}
            </Link>
          </Detail>
          <Detail label={t("admin.receipts.detail.location")}>{data.location.name}</Detail>
          <Detail label={t("admin.receipts.detail.date")} numeric>
            {formatDate(data.received_on)}
          </Detail>
          <Detail label={t("admin.receipts.detail.supplierReference")} numeric>
            {data.supplier_reference || none}
          </Detail>
          <Detail label={t("admin.receipts.detail.createdBy")}>{data.created_by || none}</Detail>
          <Detail label={t("admin.receipts.detail.purchaseOrder")} numeric>
            {data.purchase_order ? (
              <Link to={`/achats/bons/${data.purchase_order.id}`} className="font-semibold text-sea hover:underline">
                {data.purchase_order.number}
              </Link>
            ) : (
              t("admin.receipts.detail.noPurchaseOrder")
            )}
          </Detail>
          <Detail label={t("admin.receipts.detail.invoice")} numeric>
            {data.invoice ? (
              <Link to={`/achats/factures/${data.invoice.id}`} className="font-semibold text-sea hover:underline">
                {data.invoice.number}
              </Link>
            ) : (
              <span className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
                {t("admin.receipts.detail.notInvoiced")}
                <Link
                  to={`/achats/factures/nouvelle?fournisseur=${data.supplier.id}&reception=${data.id}`}
                  className="font-semibold text-sea hover:underline"
                >
                  {t("admin.receipts.detail.createInvoice")}
                </Link>
              </span>
            )}
          </Detail>
          {data.notes && (
            <div className="col-span-full">
              <Detail label={t("admin.receipts.detail.notes")}>
                <span className="whitespace-pre-line">{data.notes}</span>
              </Detail>
            </div>
          )}
        </dl>
      </Card>

      <Card className="p-2">
        <CardTitle className="px-2.5 pt-2">{t("admin.receipts.detail.lines")}</CardTitle>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.receipts.detail.product")}</Th>
              <Th>{t("admin.receipts.detail.batch")}</Th>
              {hasOrdered && <Th numeric>{t("admin.receipts.detail.ordered")}</Th>}
              <Th numeric>{t("admin.receipts.detail.invoiced")}</Th>
              <Th numeric>{t("admin.receipts.detail.accepted")}</Th>
              <Th numeric>{t("admin.receipts.detail.gap")}</Th>
              <Th numeric>{t("admin.receipts.detail.cost")}</Th>
              <Th numeric>{t("admin.receipts.detail.amount")}</Th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((line) => (
              <tr key={line.id}>
                <Td>
                  <span className="font-semibold">{line.product.name}</span>
                  <div className="num text-[0.8rem] text-ink-2">{line.product.reference}</div>
                </Td>
                <Td className="num whitespace-nowrap">
                  {line.batch.number}
                  <Link
                    to={`/fournisseurs/${data.supplier.id}`}
                    className="flex items-center gap-1 font-sans text-[0.8rem] font-semibold text-sea hover:underline"
                  >
                    <Icon name="anchor" />
                    {data.supplier.name}
                  </Link>
                  {line.batch.use_by && <div className="text-[0.8rem] text-ink-2">{formatDate(line.batch.use_by)}</div>}
                </Td>
                {hasOrdered && (
                  <Td numeric className="whitespace-nowrap">
                    {line.ordered_quantity ? formatQuantity(line.ordered_quantity) : none}
                  </Td>
                )}
                <Td numeric className="whitespace-nowrap">
                  {formatQuantity(line.invoiced_quantity)}
                </Td>
                <Td numeric className="font-semibold whitespace-nowrap">
                  {formatQuantity(line.accepted_quantity)}
                </Td>
                <Td numeric className="whitespace-nowrap">
                  <Gap accepted={line.accepted_quantity} other={line.invoiced_quantity} />
                </Td>
                <Td numeric className="whitespace-nowrap">
                  {formatMoney(line.unit_cost)}
                </Td>
                <Td numeric className="whitespace-nowrap">
                  {formatMoney(line.invoiced_amount)}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <dl className="flex flex-wrap justify-end gap-x-8 gap-y-2 border-t border-line px-2.5 py-3">
          <Detail label={t("admin.receipts.detail.invoicedTotal")} numeric>
            <b>{formatMoney(data.invoiced_total)}</b>
          </Detail>
          <Detail label={t("admin.receipts.detail.acceptedTotal")} numeric>
            {formatMoney(data.accepted_total)}
          </Detail>
          {data.invoiced_total !== data.accepted_total && (
            <Detail label={t("admin.receipts.detail.gapTotal")} numeric>
              <span className="font-semibold text-warn">
                {formatMoney(subtract(data.invoiced_total, data.accepted_total))}
              </span>
            </Detail>
          )}
        </dl>
      </Card>

      <ReceiptHistory receipt={data} />

      <p className="text-[0.85rem] text-ink-2">
        {t(data.editable ? "admin.receipts.detail.changeable" : "admin.receipts.detail.locked")}
      </p>
      <AttachmentsCard kind="goods_receipt" objectId={data.id} canWrite={canRecordReceipts(session)} />
    </>
  );
}
