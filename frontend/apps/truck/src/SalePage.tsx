import {
  ApiError,
  type CustomerChoice,
  type MyStockLine,
  type SaleDetail,
  createSale,
  useListMyCustomers,
  useListMyStock,
} from "@frutti/api";
import { useSession } from "@frutti/auth";
import { formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState, Input } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { enqueue, pendingKilos, type QueuedSale, useQueue } from "./queue";
import { sendWaiting } from "./sync";
import { newUuid } from "./uuid";

// Every text the server put in an error answer, so the driver reads why a sale was refused.
function messagesOf(body: unknown): string[] {
  if (typeof body === "string") return [body];
  if (Array.isArray(body)) return body.flatMap(messagesOf);
  if (typeof body === "object" && body !== null) return Object.values(body).flatMap(messagesOf);
  return [];
}

// Millimes, so sums of prices stay exact.
const millimes = (value: string) => Math.round(Number(value) * 1000);

// "Vente": customer, then goods, then payment, then the receipt. One question per screen.
export function SalePage() {
  const { t } = useTranslation();
  const session = useSession();
  const queryClient = useQueryClient();
  const truck = session.data?.truck ?? null;
  const stock = useListMyStock({ query: { enabled: truck !== null, retry: false } });
  const [customer, setCustomer] = useState<CustomerChoice | null>(null);
  const [kilos, setKilos] = useState<Record<number, string>>({});
  const [paid, setPaid] = useState<string | null>(null);
  const [step, setStep] = useState<"goods" | "pay">("goods");
  const queue = useQueue();
  const [receipt, setReceipt] = useState<SaleDetail | QueuedSale | null>(null);
  const [sending, setSending] = useState(false);
  const [uuid, setUuid] = useState(newUuid);
  const [error, setError] = useState("");
  const startNew = () => {
    setReceipt(null);
    setCustomer(null);
    setKilos({});
    setPaid(null);
    setStep("goods");
    setError("");
    setUuid(newUuid());
  };

  if (truck === null) {
    return (
      <EmptyState illustration="truck" title={t("truck.day.noTruck")}>
        {t("truck.sale.needTruck")}
      </EmptyState>
    );
  }
  if (receipt !== null) {
    if ("uuid" in receipt) return <QueuedReceipt sale={receipt} onNew={startNew} />;
    return <Receipt sale={receipt} onNew={startNew} />;
  }
  if (customer === null) return <PickCustomer onPick={setCustomer} />;

  // What the truck holds, less the sales still waiting to be sent: those kilos are already promised.
  const promised = pendingKilos(queue);
  const available = (line: MyStockLine) => Math.max(Number(line.quantity) - (promised[line.product_id] ?? 0), 0);
  const lines = (stock.data ?? []).filter((line) => Number(kilos[line.product_id] ?? 0) > 0);
  const overstock = lines.some((line) => Number(kilos[line.product_id] ?? 0) > available(line) + 0.0005);
  const lineMillimes = (line: MyStockLine) =>
    Math.round(Number(kilos[line.product_id] ?? 0) * millimes(line.unit_price ?? "0"));
  const totalMillimes = lines.reduce((sum, line) => sum + lineMillimes(line), 0);
  const totalText = (totalMillimes / 1000).toFixed(3);
  const paidText = paid ?? totalText;
  const paidValue = parseDecimalInput(paidText.trim(), 3);
  const tooMuch = paidValue !== null && millimes(paidValue) > totalMillimes;
  const owedMillimes = paidValue === null ? 0 : Math.max(totalMillimes - millimes(paidValue), 0);

  const confirm = async () => {
    if (paidValue === null || tooMuch || overstock) return;
    setError("");
    const data = {
      customer: customer.is_walk_in ? null : customer.id,
      location: truck.location_id,
      confirm_now: true,
      client_uuid: uuid,
      amount_paid: paidValue,
      payment_method: "cash" as const,
      lines: lines.map((line) => ({ product: line.product_id, quantity: kilos[line.product_id] ?? "" })),
    };
    const waiting = (): QueuedSale => ({
      kind: "sale",
      uuid,
      createdAt: new Date().toISOString(),
      label: customer.name,
      data,
      estimate: {
        lines: lines.map((line) => ({
          name: line.product_name,
          kilos: kilos[line.product_id] ?? "",
          amount: (lineMillimes(line) / 1000).toFixed(3),
        })),
        total: totalText,
        paid: paidValue,
      },
      status: "pending",
      error: "",
    });
    setSending(true);
    try {
      if (!navigator.onLine) throw new TypeError("offline");
      const sale = await createSale(data);
      setReceipt(sale);
      void queryClient.invalidateQueries();
      void sendWaiting(queryClient);
    } catch (failure) {
      if (failure instanceof ApiError) {
        setError(messagesOf(failure.body).join(" ") || t("truck.sale.failed"));
      } else {
        // No connection: keep the sale on the phone, it is sent as soon as the network is back.
        const kept = waiting();
        try {
          await enqueue(kept);
          setReceipt(kept);
        } catch {
          setError(t("truck.sale.failed"));
        }
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm text-ink-2">{t("truck.sale.customer")}</p>
          <p className="text-xl font-bold">{customer.name}</p>
        </div>
        <Button onClick={() => setCustomer(null)}>{t("truck.sale.change")}</Button>
      </Card>
      {step === "goods" ? (
        <>
          {stock.isLoading ? null : (stock.data ?? []).length === 0 ? (
            <EmptyState illustration="fridge" title={t("truck.sale.emptyTruck")}>
              {t("truck.sale.emptyTruckBody")}
            </EmptyState>
          ) : (
            <Card>
              <h2 className="mb-3">{t("truck.sale.howMuch")}</h2>
              <ul className="divide-y divide-line">
                {(stock.data ?? []).map((line) => (
                  <li key={line.product_id} className="space-y-2 py-3">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-lg font-semibold">{line.product_name}</span>
                      <span className="text-sm text-ink-2">
                        {t("truck.sale.left", { kg: formatQuantity(available(line).toFixed(3)) })}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <Input
                        inputMode="decimal"
                        aria-label={line.product_name}
                        placeholder="0"
                        className="text-xl"
                        value={kilos[line.product_id] ?? ""}
                        onChange={(event) => setKilos({ ...kilos, [line.product_id]: event.target.value })}
                      />
                      <span className="shrink-0 text-lg font-semibold">kg</span>
                    </div>
                    {line.unit_price === null ? null : (
                      <p className="text-sm text-ink-2">{formatMoney(line.unit_price)} / kg</p>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Card className="space-y-3">
            <p className="flex items-baseline justify-between">
              <span>{t("truck.sale.total")}</span>
              <span className="text-2xl font-bold">{formatMoney(totalText)}</span>
            </p>
            <Button
              size="lg"
              variant="primary"
              className="py-4 text-lg"
              disabled={lines.length === 0 || overstock}
              onClick={() => setStep("pay")}
            >
              {t("truck.sale.next")}
            </Button>
            {overstock ? <p className="text-bad">{t("truck.sale.notEnough")}</p> : null}
          </Card>
        </>
      ) : (
        <Card className="space-y-4">
          <p className="flex items-baseline justify-between">
            <span>{t("truck.sale.total")}</span>
            <span className="text-2xl font-bold">{formatMoney(totalText)}</span>
          </p>
          <div className="space-y-1">
            <label htmlFor="paid" className="font-semibold">
              {t("truck.sale.paid")}
            </label>
            <Input
              id="paid"
              inputMode="decimal"
              className="text-2xl"
              value={paidText}
              aria-invalid={paidValue === null || tooMuch}
              onChange={(event) => setPaid(event.target.value)}
            />
          </div>
          {tooMuch ? <p className="text-bad">{t("truck.sale.tooMuch")}</p> : null}
          {owedMillimes > 0 && !tooMuch ? (
            <p className="text-lg font-semibold">
              {t("truck.sale.onCredit", { amount: formatMoney((owedMillimes / 1000).toFixed(3)) })}
            </p>
          ) : null}
          {error === "" ? null : <p className="text-bad">{error}</p>}
          <Button
            size="lg"
            variant="primary"
            className="py-4 text-lg"
            disabled={paidValue === null || tooMuch || sending}
            onClick={() => void confirm()}
          >
            {t("truck.sale.confirm")}
          </Button>
          <Button size="lg" onClick={() => setStep("goods")}>
            {t("truck.sale.back")}
          </Button>
        </Card>
      )}
    </div>
  );
}

function PickCustomer({ onPick }: { onPick: (customer: CustomerChoice) => void }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const customers = useListMyCustomers({ search: search.trim() });
  return (
    <div className="space-y-3">
      <h2>{t("truck.sale.whoFor")}</h2>
      <Input
        type="search"
        aria-label={t("truck.sale.search")}
        placeholder={t("truck.sale.search")}
        className="text-lg"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {(customers.data ?? []).map((customer) => (
        <Button
          key={customer.id}
          size="lg"
          variant={customer.is_walk_in ? "secondary" : "primary"}
          className="flex-col py-4 text-xl"
          onClick={() => onPick(customer)}
        >
          <span>{customer.name}</span>
          {customer.city === "" ? null : <span className="text-sm font-normal">{customer.city}</span>}
        </Button>
      ))}
    </div>
  );
}

function Receipt({ sale, onNew }: { sale: SaleDetail; onNew: () => void }) {
  const { t } = useTranslation();
  const text = [
    `${sale.number} · ${sale.customer.name}`,
    ...sale.lines.map(
      (line) =>
        `${line.product.name}: ${formatQuantity(line.quantity)} × ${formatMoney(line.unit_price)} = ${formatMoney(line.amount)}`,
    ),
    `${t("truck.sale.total")}: ${formatMoney(sale.total)}`,
    `${t("truck.sale.paid")}: ${formatMoney(sale.amount_paid)}`,
    ...(Number(sale.amount_due) > 0 ? [`${t("truck.sale.stillOwed")}: ${formatMoney(sale.amount_due)}`] : []),
  ].join("\n");
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <p className="text-xl font-bold">{t("truck.sale.done", { number: sale.number })}</p>
        <p className="text-ink-2">{sale.customer.name}</p>
        <ul className="divide-y divide-line">
          {sale.lines.map((line) => (
            <li key={line.id} className="flex items-baseline justify-between gap-3 py-2">
              <span>
                {line.product.name} · {formatQuantity(line.quantity)}
              </span>
              <span className="font-semibold">{formatMoney(line.amount)}</span>
            </li>
          ))}
        </ul>
        <p className="flex justify-between text-xl font-bold">
          <span>{t("truck.sale.total")}</span>
          <span>{formatMoney(sale.total)}</span>
        </p>
        <p className="flex justify-between">
          <span>{t("truck.sale.paid")}</span>
          <span>{formatMoney(sale.amount_paid)}</span>
        </p>
        {Number(sale.amount_due) > 0 ? (
          <p className="flex justify-between font-semibold">
            <span>{t("truck.sale.stillOwed")}</span>
            <span>{formatMoney(sale.amount_due)}</span>
          </p>
        ) : null}
      </Card>
      {typeof navigator.share === "function" ? (
        <Button size="lg" className="py-4 text-lg" onClick={() => void navigator.share({ title: sale.number, text })}>
          {t("truck.sale.share")}
        </Button>
      ) : null}
      <Button size="lg" variant="primary" className="py-4 text-lg" onClick={onNew}>
        {t("truck.sale.newSale")}
      </Button>
    </div>
  );
}

function QueuedReceipt({ sale, onNew }: { sale: QueuedSale; onNew: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <p className="text-xl font-bold">{t("truck.sale.keptOnPhone")}</p>
        <p className="text-ink-2">{t("truck.sale.keptOnPhoneBody")}</p>
        <p className="text-ink-2">{sale.label}</p>
        <ul className="divide-y divide-line">
          {sale.estimate.lines.map((line) => (
            <li key={line.name} className="flex items-baseline justify-between gap-3 py-2">
              <span>
                {line.name} · {formatQuantity(line.kilos)}
              </span>
              <span className="font-semibold">{formatMoney(line.amount)}</span>
            </li>
          ))}
        </ul>
        <p className="flex justify-between text-xl font-bold">
          <span>{t("truck.sale.total")}</span>
          <span>{formatMoney(sale.estimate.total)}</span>
        </p>
        <p className="flex justify-between">
          <span>{t("truck.sale.paid")}</span>
          <span>{formatMoney(sale.estimate.paid)}</span>
        </p>
      </Card>
      <Button size="lg" variant="primary" className="py-4 text-lg" onClick={onNew}>
        {t("truck.sale.newSale")}
      </Button>
    </div>
  );
}
