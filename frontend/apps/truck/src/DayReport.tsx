import type { DayProduct, DaySummary, MyDaySummary } from "@frutti/api";
import { formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, ConfirmButton, Input } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { closingGate } from "./closingGate";
import { useOnline } from "./offline";
import { useQueue } from "./queue";
import { StickyAction } from "./StickyAction";
import { sendWaiting, useSyncProblem } from "./sync";

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <p className={`flex items-baseline justify-between gap-3 ${strong ? "text-xl font-bold" : ""}`}>
      <span>{label}</span>
      <span>{value}</span>
    </p>
  );
}

/** The opening stock and the gap of a product (D-130). A day sent before they existed is shown as it was sent,
 * without them: its kept figures do not have them. */
function stockOf(product: DayProduct): { opening?: string; unexplained?: string } {
  const kept: Partial<Pick<DayProduct, "opening" | "unexplained">> = product;
  return { opening: kept.opening, unexplained: kept.unexplained };
}

/** The cash counted at the sends a new load undid: it is with the office (D-134). A day sent before the figure
 * existed has none in its kept figures. */
function handedOverOf(summary: DaySummary): string | null {
  const kept: Partial<Pick<DaySummary, "handed_over">> = summary;
  return kept.handed_over !== undefined && Number(kept.handed_over) !== 0 ? kept.handed_over : null;
}

/** The purchases at the port of the day and their money, kept apart from the sales cash (D-158); null for a day
 * without purchase money nor purchases (and for a day kept on the phone before these figures existed). */
function purchasesOf(summary: DaySummary) {
  const kept: Partial<DaySummary> = summary;
  const count = kept.purchases_count ?? 0;
  const float = kept.purchase_float ?? "0.000";
  if (count === 0 && Number(float) === 0) return null;
  return {
    count,
    float,
    total: kept.purchases_total ?? "0.000",
    cash: kept.purchases_cash ?? "0.000",
    other: kept.purchases_other ?? "0.000",
    fromSales: kept.purchases_from_sales ?? "0.000",
    owed: kept.owed_to_driver ?? "0.000",
    expected: kept.expected_purchase_cash ?? "0.000",
  };
}

function PurchaseFigures({ summary }: { summary: DaySummary }) {
  const { t } = useTranslation();
  const purchases = purchasesOf(summary);
  if (purchases === null) return null;
  return (
    <Card className="space-y-2">
      <h2>{t("truck.purchase.closingTitle")}</h2>
      <p>{t("truck.purchase.closingCount", { count: purchases.count, amount: formatMoney(purchases.total) })}</p>
      <Row label={t("truck.purchase.closingFloat")} value={formatMoney(purchases.float)} />
      <Row label={t("truck.purchase.closingCash")} value={formatMoney(purchases.cash)} />
      <Row label={t("truck.purchase.closingOther")} value={formatMoney(purchases.other)} />
      {Number(purchases.fromSales) === 0 ? null : (
        <Row label={t("truck.purchase.closingFromSales")} value={formatMoney(purchases.fromSales)} />
      )}
      {Number(purchases.owed) === 0 ? null : (
        <Row label={t("truck.purchase.closingOwed")} value={formatMoney(purchases.owed)} />
      )}
      <Row label={t("truck.purchase.closingExpected")} value={formatMoney(purchases.expected)} strong />
    </Card>
  );
}

function Figures({ summary }: { summary: DaySummary }) {
  const { t } = useTranslation();
  const handedOver = handedOverOf(summary);
  return (
    <>
      <Card className="space-y-2">
        <h2>{t("truck.closing.title")}</h2>
        <Row
          label={t("truck.closing.sales", { count: summary.sales_count })}
          value={formatMoney(summary.sales_total)}
          strong
        />
        <Row label={t("truck.closing.cash")} value={formatMoney(summary.cash_received)} />
        <Row label={t("truck.closing.payments")} value={formatMoney(summary.payments_cash ?? "0.000")} />
        <Row label={t("truck.closing.other")} value={formatMoney(summary.other_payments)} />
        <Row label={t("truck.closing.credit")} value={formatMoney(summary.on_credit)} />
        <Row label={t("truck.closing.expenses")} value={formatMoney(summary.expenses_total)} />
        <Row label={t("truck.closing.opening")} value={formatMoney(summary.opening_cash)} />
        {handedOver === null ? null : <Row label={t("truck.closing.handedOver")} value={formatMoney(handedOver)} />}
        <Row label={t("truck.closing.expected")} value={formatMoney(summary.expected_cash)} strong />
      </Card>
      <PurchaseFigures summary={summary} />
      {summary.products.length === 0 ? null : (
        <Card>
          <h2 className="mb-3">{t("truck.closing.stock")}</h2>
          <ul className="divide-y divide-line">
            {summary.products.map((product) => {
              const { opening, unexplained } = stockOf(product);
              return (
                <li key={product.product_id} className="space-y-1 py-3">
                  <p className="text-lg font-semibold">{product.product_name}</p>
                  <p className="text-sm text-ink-2">
                    {opening === undefined ? null : `${t("truck.closing.stockOpening")} ${formatQuantity(opening)} · `}
                    {t("truck.closing.loaded")} {formatQuantity(product.loaded)} · {t("truck.closing.sold")}{" "}
                    {formatQuantity(product.sold)} · {t("truck.closing.lost")} {formatQuantity(product.lost)} ·{" "}
                    {t("truck.closing.returned")} {formatQuantity(product.returned)}
                  </p>
                  <p className="font-semibold">
                    {t("truck.closing.left")} {formatQuantity(product.remaining)}
                  </p>
                  {unexplained === undefined || Number(unexplained) === 0 ? null : (
                    <p className="font-semibold text-bad">
                      {t("truck.closing.unexplained", { kg: formatQuantity(unexplained) })}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </>
  );
}

/** A driver's day in a few lines, its closing state, and the button to send it while it can be sent: the "Clôture"
 * screen for the day of now, the history for an earlier one (D-134). The driver is not asked to count the cash: the
 * office counts it when they are back, and they see only what they should hold (D-213). Both screens wait for what
 * the phone still has to send, say why it waits and let the driver retry (D-129). A sent day is sent again when the
 * office asked, when a new load reopened it, or when its records changed since the send (D-132). */
export function DayReport({
  data,
  sending,
  error,
  onSend,
}: {
  data: MyDaySummary;
  sending: boolean;
  error: string;
  /** `note`: what the driver wants the office to know with the day; may be empty. */
  onSend: (note: string) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const queue = useQueue();
  const online = useOnline();
  const problem = useSyncProblem();
  const [retrying, setRetrying] = useState(false);
  const [note, setNote] = useState("");
  // Waiting sales are sent as soon as the day's figures open, not only on the half-minute timer (D-090).
  useEffect(() => {
    void sendWaiting(queryClient);
  }, [queryClient]);
  const retry = async () => {
    setRetrying(true);
    try {
      await sendWaiting(queryClient);
    } finally {
      setRetrying(false);
    }
  };
  const { summary, closing } = data;
  const changed = closing?.status === "submitted" && closing.changed_since_sent;
  const locked = closing?.status === "approved" || (closing?.status === "submitted" && !changed);
  const handedOver = handedOverOf(summary);
  const gate = closingGate({ queue, online, busy: sending });
  const waiting = gate.waiting;
  // The purchase money is shown only on a day with purchase money or purchases (D-158).
  const purchases = purchasesOf(summary);
  // Why the sale has not gone yet: the phone's own connection first, then what the last send ran into.
  const waitReason = !online
    ? t("truck.closing.waitOffline")
    : problem === "session"
      ? t("truck.closing.waitSession")
      : problem === "server"
        ? t("truck.closing.waitServerBusy")
        : problem === "offline"
          ? t("truck.closing.waitNoAnswer")
          : t("truck.closing.waitRetrying");

  return (
    <div className="space-y-4">
      <Figures summary={summary} />
      {closing?.status === "approved" ? (
        <Card>
          <p className="text-xl font-bold">{t("truck.closing.approved")}</p>
        </Card>
      ) : closing?.status === "submitted" && !changed ? (
        <Card>
          <p className="text-xl font-bold">{t("truck.closing.sent")}</p>
        </Card>
      ) : null}
      {locked ? null : (
        <Card className="space-y-4">
          {closing?.status === "reopened" ? (
            <p className="font-semibold text-warn">{t("truck.closing.reopened")}</p>
          ) : null}
          {changed ? <p className="font-semibold text-warn">{t("truck.closing.changed")}</p> : null}
          {closing !== null && closing.status !== "submitted" && closing.review_note !== "" ? (
            <p className="font-semibold text-bad">{t("truck.closing.asked", { reason: closing.review_note })}</p>
          ) : null}
          {handedOver === null ? null : (
            <p className="text-ink-2">{t("truck.closing.handedOverHint", { amount: formatMoney(handedOver) })}</p>
          )}
          <div className="space-y-1">
            <label htmlFor="closing-note" className="font-semibold">
              {t("truck.closing.note")}
            </label>
            <Input id="closing-note" value={note} onChange={(event) => setNote(event.target.value)} />
          </div>
          {error === "" ? null : <p className="text-bad">{error}</p>}
          {waiting > 0 ? (
            <div className="space-y-2">
              <p className="font-semibold text-warn">{t("truck.closing.waitingSales", { count: waiting })}</p>
              <p className="text-ink-2">{waitReason}</p>
              <Button disabled={!online || retrying} onClick={() => void retry()}>
                {t("truck.closing.retrySend")}
              </Button>
            </div>
          ) : !online ? (
            <p className="text-warn">{t("truck.closing.needNetwork")}</p>
          ) : null}
        </Card>
      )}
      {locked ? null : (
        <StickyAction>
          <ConfirmButton
            size="lg"
            variant="primary"
            className="py-4 text-lg"
            disabled={!gate.canSend}
            rows={[
              [t("truck.closing.expected"), formatMoney(summary.expected_cash)],
              ...(purchases === null
                ? []
                : [[t("truck.purchase.closingExpected"), formatMoney(purchases.expected)] as [string, string]]),
            ]}
            onConfirm={() => onSend(note)}
          >
            {t("truck.closing.send")}
          </ConfirmButton>
        </StickyAction>
      )}
    </div>
  );
}
