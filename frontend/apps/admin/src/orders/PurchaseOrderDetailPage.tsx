import { ApiError, cancelPurchaseOrder, closePurchaseOrder, useGetPurchaseOrder } from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  CardTitle,
  cn,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  EmptyState,
  Icon,
  PageHeader,
  Pill,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router";

import { AttachmentsCard } from "../lib/AttachmentsCard";
import { canRecordReceipts, todayInTunis } from "../receipts/shared";
import { ORDER_TONE, refreshOrders } from "./shared";

function Detail({ label, children, numeric = false }: { label: string; children: ReactNode; numeric?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[0.78rem] font-semibold text-ink-2">{label}</dt>
      <dd className={cn("break-words", numeric && "num")}>{children}</dd>
    </div>
  );
}

type Action = "close" | "cancel";

export function PurchaseOrderDetailPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canRecord = canRecordReceipts(session);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { orderId } = useParams();
  const id = Number(orderId);
  const validId = Number.isInteger(id) && id > 0;
  const order = useGetPurchaseOrder(id, { query: { enabled: validId, retry: false } });
  const [confirming, setConfirming] = useState<Action | null>(null);

  const act = useMutation({
    mutationFn: (action: Action) => (action === "close" ? closePurchaseOrder(id) : cancelPurchaseOrder(id)),
    onSuccess: async (saved, action) => {
      toast.success(
        t(action === "close" ? "admin.purchaseOrders.detail.closed" : "admin.purchaseOrders.detail.cancelled", {
          number: saved.number,
        }),
      );
      setConfirming(null);
      await refreshOrders(queryClient);
    },
    onError: () => {
      setConfirming(null);
      toast.error(t("admin.purchaseOrders.detail.failed"));
    },
  });

  const back = (
    <Link to="/achats/bons" className="text-[0.85rem] font-semibold text-sea hover:underline">
      {t("admin.purchaseOrders.back")}
    </Link>
  );

  if (validId && order.isPending) return <p className="text-ink-2">{t("common.loading")}</p>;
  if (!order.data) {
    const missing = !validId || (order.error instanceof ApiError && order.error.status === 404);
    return (
      <>
        {back}
        <EmptyState
          illustration="fish"
          title={missing ? t("admin.purchaseOrders.notFound") : t("common.serverUnreachable")}
        />
      </>
    );
  }

  const data = order.data;
  const none = t("admin.purchaseOrders.detail.none");
  const waiting = data.status === "open" || data.status === "partly_received";
  const late = waiting && data.expected_on !== null && data.expected_on < todayInTunis();

  return (
    <>
      {back}
      <PageHeader eyebrow={`${formatDate(data.ordered_on)} · ${data.supplier.name}`} title={data.number}>
        <Pill tone={ORDER_TONE[data.status]}>{t(`admin.purchaseOrders.status.${data.status}`)}</Pill>
        {canRecord && data.status === "open" && data.receipts.length === 0 && (
          <Button variant="ghost" onClick={() => setConfirming("cancel")}>
            <Icon name="trash" />
            {t("admin.purchaseOrders.detail.cancel")}
          </Button>
        )}
        {canRecord && data.status === "partly_received" && (
          <Button onClick={() => setConfirming("close")}>{t("admin.purchaseOrders.detail.close")}</Button>
        )}
        {canRecord && waiting && (
          <Button variant="primary" onClick={() => void navigate(`/achats/nouvelle?commande=${data.id}`)}>
            <Icon name="plus" />
            {t("admin.purchaseOrders.detail.receive")}
          </Button>
        )}
      </PageHeader>

      {late && data.expected_on && (
        <div role="note" className="flex items-start gap-3 rounded-card border border-line bg-warn-soft p-3">
          <span className="text-warn">
            <Icon name="alert" />
          </span>
          <span className="text-[0.9rem]">
            {t("admin.purchaseOrders.detail.late", { date: formatDate(data.expected_on) })}
          </span>
        </div>
      )}

      <Card>
        <CardTitle>{t("admin.purchaseOrders.detail.order")}</CardTitle>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-3">
          <Detail label={t("admin.purchaseOrders.detail.supplier")}>
            <Link to={`/fournisseurs/${data.supplier.id}`} className="font-semibold text-sea hover:underline">
              {data.supplier.name}
            </Link>
          </Detail>
          <Detail label={t("admin.purchaseOrders.detail.date")} numeric>
            {formatDate(data.ordered_on)}
          </Detail>
          <Detail label={t("admin.purchaseOrders.detail.expected")} numeric>
            {data.expected_on ? formatDate(data.expected_on) : none}
          </Detail>
          <Detail label={t("admin.purchaseOrders.detail.createdBy")}>{data.created_by || none}</Detail>
          {data.notes && (
            <div className="col-span-full">
              <Detail label={t("admin.purchaseOrders.detail.notes")}>
                <span className="whitespace-pre-line">{data.notes}</span>
              </Detail>
            </div>
          )}
        </dl>
      </Card>

      <Card className="p-2">
        <CardTitle className="px-2.5 pt-2">{t("admin.purchaseOrders.detail.lines")}</CardTitle>
        <Table>
          <thead>
            <tr>
              <Th>{t("admin.purchaseOrders.detail.product")}</Th>
              <Th numeric>{t("admin.purchaseOrders.detail.ordered")}</Th>
              <Th numeric>{t("admin.purchaseOrders.detail.received")}</Th>
              <Th numeric>{t("admin.purchaseOrders.detail.remaining")}</Th>
              <Th numeric className="max-[720px]:hidden">
                {t("admin.purchaseOrders.detail.cost")}
              </Th>
              <Th numeric className="max-[720px]:hidden">
                {t("admin.purchaseOrders.detail.amount")}
              </Th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((line) => {
              const remaining = line.remaining_quantity !== "0.000";
              return (
                <tr key={line.id}>
                  <Td>
                    <span className="font-semibold">{line.product.name}</span>
                    <div className="num text-[0.8rem] text-ink-2">{line.product.reference}</div>
                  </Td>
                  <Td numeric className="whitespace-nowrap">
                    {formatQuantity(line.ordered_quantity)}
                  </Td>
                  <Td numeric className="font-semibold whitespace-nowrap">
                    {formatQuantity(line.received_quantity)}
                  </Td>
                  <Td numeric className={cn("whitespace-nowrap", remaining && waiting && "font-semibold text-warn")}>
                    {remaining ? formatQuantity(line.remaining_quantity) : none}
                  </Td>
                  <Td numeric className="whitespace-nowrap max-[720px]:hidden">
                    {formatMoney(line.unit_cost)}
                  </Td>
                  <Td numeric className="whitespace-nowrap max-[720px]:hidden">
                    {formatMoney(line.ordered_amount)}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
        <dl className="flex flex-wrap justify-end gap-x-8 gap-y-2 border-t border-line px-2.5 py-3">
          <Detail label={t("admin.purchaseOrders.detail.total")} numeric>
            <b>{formatMoney(data.ordered_total)}</b>
          </Detail>
        </dl>
      </Card>

      <Card className="p-2">
        <CardTitle className="px-2.5 pt-2">{t("admin.purchaseOrders.detail.receipts")}</CardTitle>
        {data.receipts.length === 0 ? (
          <p className="px-2.5 pb-2 text-ink-2">{t("admin.purchaseOrders.detail.noReceipts")}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.purchaseOrders.detail.receipt")}</Th>
                <Th>{t("admin.purchaseOrders.detail.receivedOn")}</Th>
              </tr>
            </thead>
            <tbody>
              {data.receipts.map((receipt) => (
                <tr key={receipt.id}>
                  <Td className="num whitespace-nowrap">
                    <Link to={`/achats/${receipt.id}`} className="font-semibold text-sea hover:underline">
                      {receipt.number}
                    </Link>
                  </Td>
                  <Td className="num whitespace-nowrap">{formatDate(receipt.received_on)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <p className="text-[0.85rem] text-ink-2">{t("admin.purchaseOrders.detail.waitingNote")}</p>

      <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent>
          <DialogTitle>
            {t(
              confirming === "cancel"
                ? "admin.purchaseOrders.detail.cancelTitle"
                : "admin.purchaseOrders.detail.closeTitle",
              {
                number: data.number,
              },
            )}
          </DialogTitle>
          <DialogDescription>
            {t(
              confirming === "cancel"
                ? "admin.purchaseOrders.detail.cancelBody"
                : "admin.purchaseOrders.detail.closeBody",
            )}
          </DialogDescription>
          <DialogFooter>
            <DialogClose asChild>
              <Button>{t("admin.purchaseOrders.detail.keep")}</Button>
            </DialogClose>
            <Button
              variant="danger"
              disabled={act.isPending || confirming === null}
              onClick={() => confirming && act.mutate(confirming)}
            >
              {t(confirming === "cancel" ? "admin.purchaseOrders.detail.cancel" : "admin.purchaseOrders.detail.close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AttachmentsCard kind="purchase_order" objectId={data.id} canWrite={canRecord} />
    </>
  );
}
