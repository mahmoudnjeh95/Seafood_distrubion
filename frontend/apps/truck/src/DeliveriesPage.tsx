import {
  ApiError,
  type Deliver,
  deliverMyDelivery,
  notDeliveredMyDelivery,
  type SaleDetail,
  useListMyDeliveries,
} from "@frutti/api";
import { formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, ConfirmButton, EmptyState, Input, MoneyInput, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { BoxCountInputs } from "./BoxCountInputs";
import { boxCountsOf, type BoxInputs, formatBoxCount } from "./boxes";
import { FoldCard } from "./FoldCard";
import { messagesOf } from "./messages";
import { type QueuedDelivery, type QueuedNotDelivered, useQueue } from "./queue";
import { sendOrKeep } from "./sendOrKeep";
import { newUuid } from "./uuid";

const millimes = (value: string) => Math.round(Number(value) * 1000);

// "Mes livraisons": the BL the office validated and printed with the truck's load, one per client (D-160, D-178).
// The driver delivers each one as written or changed at the client's door (less, more, a product taken off), or not
// at all; only what is delivered is sold, the rest stays on the truck. Each delivery opens on tap (D-171).
export function DeliveriesPage() {
  const { t } = useTranslation();
  const deliveries = useListMyDeliveries({ query: { retry: false } });
  const queue = useQueue();
  // A delivery kept on the phone (no network) is done for the driver: it is sent when the network comes back.
  const sent = new Set(
    queue.flatMap((item) => (item.kind === "delivery" || item.kind === "not_delivered" ? [item.saleId] : [])),
  );

  if (deliveries.isPending) return <Card className="h-24 animate-pulse" aria-busy="true" />;
  if (deliveries.isError) {
    return (
      <Card className="space-y-3">
        <p className="text-lg font-semibold">{t("truck.deliveries.failed")}</p>
        <Button size="lg" onClick={() => void deliveries.refetch()}>
          {t("truck.stock.retry")}
        </Button>
      </Card>
    );
  }
  const waiting = deliveries.data.filter((sale) => !sent.has(sale.id));
  if (waiting.length === 0) {
    return (
      <EmptyState illustration="truck" title={t("truck.deliveries.empty")}>
        {t("truck.deliveries.emptyBody")}
      </EmptyState>
    );
  }
  return (
    <div className="space-y-3">
      <h2>{t("truck.deliveries.title")}</h2>
      {waiting.map((sale) => (
        <Delivery key={sale.id} sale={sale} />
      ))}
    </div>
  );
}

function initialBoxes(sale: SaleDetail): BoxInputs {
  return { small: sale.boxes.small ? String(sale.boxes.small) : "", big: sale.boxes.big ? String(sale.boxes.big) : "" };
}

export function Delivery({ sale }: { sale: SaleDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const queue = useQueue();
  const [kilos, setKilos] = useState<Record<number, string>>(() =>
    Object.fromEntries(sale.lines.map((line) => [line.id, line.quantity])),
  );
  const [boxInputs, setBoxInputs] = useState<BoxInputs>(() => initialBoxes(sale));
  const [paid, setPaid] = useState("");
  const [note, setNote] = useState("");
  const [refusing, setRefusing] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const kept = queue.some(
    (item) => (item.kind === "delivery" || item.kind === "not_delivered") && item.saleId === sale.id,
  );

  const parsed = sale.lines.map((line) => ({ line, kg: parseDecimalInput((kilos[line.id] ?? "").trim(), 3) }));
  const invalid = parsed.some(({ kg }) => kg === null);
  const lineMillimes = (line: SaleDetail["lines"][number], kg: string | null) =>
    kg === null ? 0 : Math.round((Number(kg) * millimes(line.unit_price) * (100 - Number(line.discount_rate))) / 100);
  const totalMillimes = parsed.reduce((sum, { line, kg }) => sum + lineMillimes(line, kg), 0);
  const totalText = (totalMillimes / 1000).toFixed(3);
  const changed = parsed.some(({ line, kg }) => kg !== null && Number(kg) !== Number(line.quantity));
  const paidValue = paid.trim() === "" ? "0" : parseDecimalInput(paid.trim(), 3);
  const tooMuch = paidValue !== null && millimes(paidValue) > totalMillimes;
  const counts = boxCountsOf(boxInputs);

  const done = (keptOnPhone: boolean, message: string) => {
    toast.success(keptOnPhone ? t("truck.deliveries.kept") : message);
    void queryClient.invalidateQueries();
  };
  const failed = (failure: unknown) => {
    setError(
      (failure instanceof ApiError ? messagesOf(failure.body).join(" ") : "") || t("truck.deliveries.failedConfirm"),
    );
  };

  const deliver = async () => {
    if (invalid || counts === null || paidValue === null || tooMuch) return;
    setBusy(true);
    setError("");
    const uuid = newUuid();
    const data: Deliver = {
      lines: parsed.flatMap(({ line, kg }) =>
        kg !== null && Number(kg) !== Number(line.quantity) ? [{ line: line.id, quantity: kg }] : [],
      ),
      boxes: counts,
      note: note.trim(),
      amount_paid: paidValue === "0" ? null : paidValue,
      payment_method: paidValue === "0" ? "" : "cash",
      client_uuid: uuid,
    };
    const item: QueuedDelivery = {
      kind: "delivery",
      uuid,
      createdAt: new Date().toISOString(),
      label: sale.customer.name,
      status: "pending",
      error: "",
      saleId: sale.id,
      data,
      kilos: Object.fromEntries(parsed.map(({ line, kg }) => [line.product.id, Number(kg ?? "0")])),
    };
    try {
      const outcome = await sendOrKeep(item, () => deliverMyDelivery(sale.id, data));
      const status = outcome.result?.delivery_status;
      done(
        outcome.kept,
        t(status === "cancelled" ? "truck.deliveries.notDeliveredDone" : "truck.deliveries.done", {
          number: sale.number,
        }),
      );
    } catch (failure) {
      failed(failure);
    } finally {
      setBusy(false);
    }
  };

  const notDelivered = async () => {
    setBusy(true);
    setError("");
    const uuid = newUuid();
    const item: QueuedNotDelivered = {
      kind: "not_delivered",
      uuid,
      createdAt: new Date().toISOString(),
      label: sale.customer.name,
      status: "pending",
      error: "",
      saleId: sale.id,
      data: { note: note.trim(), client_uuid: uuid },
    };
    try {
      const outcome = await sendOrKeep(item, () => notDeliveredMyDelivery(sale.id, item.data));
      done(outcome.kept, t("truck.deliveries.notDeliveredDone", { number: sale.number }));
    } catch (failure) {
      failed(failure);
    } finally {
      setBusy(false);
    }
  };

  if (kept) {
    return (
      <Card>
        <p className="font-semibold">{t("truck.deliveries.kept")}</p>
      </Card>
    );
  }

  return (
    <FoldCard
      title={sale.customer.name}
      summary={t("truck.deliveries.summary", { count: sale.lines.length, total: formatMoney(sale.total) })}
    >
      <div className="space-y-3">
        <p className="text-sm text-ink-2">{t("truck.deliveries.bl", { number: sale.number, version: sale.version })}</p>
        {sale.delivery_address ? <p className="text-ink-2">{sale.delivery_address}</p> : null}
        <ul className="divide-y divide-line">
          {parsed.map(({ line, kg }) => (
            <li key={line.id} className="space-y-1 py-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-lg font-semibold">{line.product.name}</span>
                <span className="text-sm text-ink-2">{formatMoney(line.unit_price)} / kg</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <label htmlFor={`delivered-${line.id}`} className="text-ink-2">
                  {t("truck.deliveries.written", { kilos: formatQuantity(line.quantity) })}
                </label>
                <div className="flex items-center gap-2">
                  <Input
                    id={`delivered-${line.id}`}
                    inputMode="decimal"
                    className="w-28 text-right text-xl"
                    aria-invalid={kg === null}
                    value={kilos[line.id] ?? ""}
                    onChange={(event) => setKilos({ ...kilos, [line.id]: event.target.value })}
                  />
                  <span>kg</span>
                </div>
              </div>
              {kg !== null && Number(kg) === 0 ? (
                <p className="text-sm font-semibold text-warn">{t("truck.deliveries.takenOff")}</p>
              ) : null}
            </li>
          ))}
        </ul>
        <BoxCountInputs inputs={boxInputs} onChange={setBoxInputs} />
        {sale.boxes.small || sale.boxes.big ? (
          <p className="text-sm text-ink-2">
            {t("truck.deliveries.boxesWritten", {
              small: formatBoxCount(sale.boxes.small ?? 0),
              big: formatBoxCount(sale.boxes.big ?? 0),
            })}
          </p>
        ) : null}
        <p className="flex justify-between text-lg font-bold">
          <span>{t(changed ? "truck.deliveries.newTotal" : "truck.deliveries.total")}</span>
          <span>{formatMoney(totalText)}</span>
        </p>
        <div className="flex items-center justify-between gap-3">
          <label htmlFor={`paid-${sale.id}`} className="font-semibold">
            {t("truck.deliveries.paid")}
          </label>
          <MoneyInput
            id={`paid-${sale.id}`}
            inputMode="decimal"
            placeholder="0"
            className="w-32 text-right text-xl"
            aria-invalid={paidValue === null || tooMuch}
            value={paid}
            onChange={(event) => setPaid(event.target.value)}
          />
        </div>
        {tooMuch ? <p className="text-sm font-semibold text-bad">{t("truck.deliveries.paidTooMuch")}</p> : null}
        <label className="block space-y-1">
          <span className="font-semibold">{t("truck.deliveries.note")}</span>
          <textarea
            className="w-full rounded-control border border-line bg-surface px-3 py-2"
            rows={2}
            maxLength={255}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        {error ? (
          <p role="alert" className="font-semibold text-bad">
            {error}
          </p>
        ) : null}
        {refusing ? (
          <div className="space-y-2 rounded-control bg-warn-soft p-3">
            <p className="font-semibold">{t("truck.deliveries.notDeliveredAsk")}</p>
            <Button size="lg" variant="danger" className="w-full" disabled={busy} onClick={() => void notDelivered()}>
              {t("truck.deliveries.notDeliveredConfirm")}
            </Button>
            <Button size="lg" variant="ghost" className="w-full" onClick={() => setRefusing(false)}>
              {t("truck.deliveries.back")}
            </Button>
          </div>
        ) : (
          <>
            <ConfirmButton
              size="lg"
              variant="primary"
              className="w-full py-4 text-lg"
              disabled={busy || invalid || counts === null || paidValue === null || tooMuch}
              title={sale.customer.name}
              rows={[
                [t(changed ? "truck.deliveries.newTotal" : "truck.deliveries.total"), formatMoney(totalText)],
                [t("truck.deliveries.paid"), formatMoney(paidValue ?? "0")],
              ]}
              onConfirm={() => void deliver()}
            >
              {busy
                ? t("truck.deliveries.confirming")
                : t(changed ? "truck.deliveries.confirmChanged" : "truck.deliveries.confirm")}
            </ConfirmButton>
            <Button size="lg" variant="ghost" className="w-full" disabled={busy} onClick={() => setRefusing(true)}>
              {t("truck.deliveries.notDelivered")}
            </Button>
          </>
        )}
        {changed ? <p className="text-sm text-ink-2">{t("truck.deliveries.paperHint")}</p> : null}
      </div>
    </FoldCard>
  );
}
