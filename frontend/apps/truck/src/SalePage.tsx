import {
  ApiError,
  type CustomerChoice,
  type MyStockLine,
  type SaleDetail,
  createSale,
  useListMyCustomers,
  useListMyDeliveries,
} from "@frutti/api";
import { useSession } from "@frutti/auth";
import { formatDateTime, formatMoney, formatQuantity, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, ConfirmButton, EmptyState, Input } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { BoxCountInputs } from "./BoxCountInputs";
import { boxCountsOf, type BoxInputs, NO_BOXES } from "./boxes";
import { Delivery } from "./DeliveriesPage";
import { messagesOf } from "./messages";
import { NewCustomerForm } from "./NewCustomerForm";
import { useOnline } from "./offline";
import { truckIsEmpty, useTruckStock } from "./myStock";
import { PricesAsOf } from "./PriceNotice";
import { enqueue, madeAtOf, pendingKilos, type QueuedSale, useQueue } from "./queue";
import { ProductPhoto } from "./ProductPhoto";
import { recentCustomerIds, rememberCustomer } from "./recentCustomers";
import { StickyAction } from "./StickyAction";
import { sendWaiting } from "./sync";
import { newUuid } from "./uuid";

// Millimes, so sums of prices stay exact.
const millimes = (value: string) => Math.round(Number(value) * 1000);

// "Vente": customer, then goods, then payment, then the receipt. One question per screen.
export function SalePage() {
  const { t } = useTranslation();
  const session = useSession();
  const queryClient = useQueryClient();
  const truck = session.data?.truck ?? null;
  const [customer, setCustomer] = useState<CustomerChoice | null>(null);
  // The prices the customer pays: their own list shows here, as the server will charge them (D-150, D-049).
  const stock = useTruckStock(truck !== null, customer?.id);
  const [kilos, setKilos] = useState<Record<number, string>>({});
  const [paid, setPaid] = useState<string | null>(null);
  const [step, setStep] = useState<"goods" | "pay">("goods");
  const queue = useQueue();
  const [receipt, setReceipt] = useState<SaleDetail | QueuedSale | null>(null);
  const [sending, setSending] = useState(false);
  const [uuid, setUuid] = useState(newUuid);
  const [error, setError] = useState("");
  // Returnable boxes the client keeps after this sale (P1-T14d). They go with the sale, queued with it when offline.
  const [boxInputs, setBoxInputs] = useState<BoxInputs>(NO_BOXES);
  const startNew = () => {
    setReceipt(null);
    setCustomer(null);
    setKilos({});
    setBoxInputs(NO_BOXES);
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
  // What the truck holds, less the sales still waiting to be sent: those kilos are already promised.
  const promised = pendingKilos(queue);
  if (customer === null) {
    // An empty truck shows no clients, only that there is nothing to sell (D-184). Without the stock (offline, never
    // loaded) the list still shows, so a sale is never blocked by a missing answer.
    if (stock.isLoading) return null;
    if (stock.data !== undefined && truckIsEmpty(stock.data, promised)) {
      return (
        <EmptyState illustration="fridge" title={t("truck.sale.emptyTruck")}>
          {t("truck.sale.emptyTruckBody")}
        </EmptyState>
      );
    }
    return <PickCustomer onPick={setCustomer} delivers />;
  }

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
  const boxCounts = boxCountsOf(boxInputs);

  const confirm = async () => {
    if (paidValue === null || tooMuch || overstock || boxCounts === null) return;
    setError("");
    // The moment of the sale by the phone's clock (D-133). It goes with the sale, sent now or kept for later, so a
    // sale made without connection keeps its own date and price; the server checks it.
    const madeAt = new Date().toISOString();
    const data = {
      customer: customer.is_walk_in ? null : customer.id,
      location: truck.location_id,
      sold_at: madeAt,
      confirm_now: true,
      client_uuid: uuid,
      amount_paid: paidValue,
      payment_method: "cash" as const,
      // The price each line showed goes with the sale: the server checks it was a real price (P3-T02, D-148).
      lines: lines.map((line) => ({
        product: line.product_id,
        quantity: kilos[line.product_id] ?? "",
        unit_price: line.unit_price,
      })),
      boxes: boxCounts,
    };
    const waiting = (): QueuedSale => ({
      kind: "sale",
      uuid,
      createdAt: madeAt,
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
        // No connection: keep the sale on the phone, boxes included, and send it as soon as the network is back.
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
              <PricesAsOf updatedAt={stock.dataUpdatedAt} />
              <ul className="divide-y divide-line">
                {(stock.data ?? []).map((line) => (
                  <li key={line.product_id} className="flex items-center gap-3 py-2.5">
                    <ProductPhoto url={line.photo_url} name={line.product_name} />
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-lg font-semibold leading-tight">{line.product_name}</span>
                      <span className="block text-sm text-ink-2">
                        {t("truck.sale.left", { kg: formatQuantity(available(line).toFixed(3)) })}
                        {line.unit_price === null ? null : ` · ${formatMoney(line.unit_price)} / kg`}
                      </span>
                    </span>
                    <Input
                      inputMode="decimal"
                      aria-label={line.product_name}
                      placeholder="0"
                      className="w-24 text-end text-xl"
                      value={kilos[line.product_id] ?? ""}
                      onChange={(event) => setKilos({ ...kilos, [line.product_id]: event.target.value })}
                    />
                    <span className="w-6 flex-none text-lg font-semibold">kg</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Card className="space-y-3">
            <h2>{t("truck.boxes.leftTitle")}</h2>
            <p className="text-sm text-ink-2">{t("truck.boxes.leftHint")}</p>
            <BoxCountInputs inputs={boxInputs} onChange={setBoxInputs} />
            {boxCounts === null ? <p className="text-bad">{t("truck.boxes.invalidCount")}</p> : null}
          </Card>
          <StickyAction>
            {overstock ? <p className="text-bad">{t("truck.sale.notEnough")}</p> : null}
            <div className="flex items-center justify-between gap-3">
              <p className="flex flex-col">
                <span className="text-sm text-ink-2">{t("truck.sale.total")}</span>
                <span className="text-2xl font-bold">{formatMoney(totalText)}</span>
              </p>
              <Button
                size="lg"
                variant="primary"
                className="w-auto flex-none px-6 py-3 text-lg"
                disabled={lines.length === 0 || overstock || boxCounts === null}
                onClick={() => setStep("pay")}
              >
                {t("truck.sale.next")}
              </Button>
            </div>
          </StickyAction>
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
          <ConfirmButton
            size="lg"
            variant="primary"
            className="py-4 text-lg"
            disabled={paidValue === null || tooMuch || sending}
            title={customer.name}
            rows={[
              [t("truck.sale.total"), formatMoney(totalText)],
              [t("truck.sale.paid"), formatMoney(paidValue ?? "0")],
            ]}
            onConfirm={() => void confirm()}
          >
            {t("truck.sale.confirm")}
          </ConfirmButton>
          <Button size="lg" onClick={() => setStep("goods")}>
            {t("truck.sale.back")}
          </Button>
        </Card>
      )}
    </div>
  );
}

// `delivers`: a client with a BL from the load opens it (Vente); the box pickup only picks the client.
export function PickCustomer({
  onPick,
  delivers = false,
}: {
  onPick: (customer: CustomerChoice) => void;
  delivers?: boolean;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const online = useOnline();
  const customers = useListMyCustomers({ search: search.trim() });
  // The BL the office prepared with the load (D-160): a client who has one is delivered first (D-174).
  const deliveries = useListMyDeliveries({ query: { enabled: delivers, retry: false } });
  const [delivering, setDelivering] = useState<CustomerChoice | null>(null);
  const toDeliver = (customer: CustomerChoice) =>
    delivers ? deliveries.data?.find((sale) => sale.customer.id === customer.id) : undefined;
  // A customer picked goes to the top of the recent list (D-171).
  const pick = (customer: CustomerChoice) => {
    rememberCustomer(customer.id);
    if (toDeliver(customer)) setDelivering(customer);
    else onPick(customer);
  };
  if (delivering !== null) {
    const sale = toDeliver(delivering);
    return (
      <div className="space-y-3">
        <h2>{delivering.name}</h2>
        {sale ? (
          <Delivery sale={sale} />
        ) : (
          <Card>
            <p className="text-lg font-semibold">{t("truck.sale.deliveredDone")}</p>
          </Card>
        )}
        <Button size="lg" className="w-full py-4 text-lg" onClick={() => onPick(delivering)}>
          {t("truck.sale.sellMore")}
        </Button>
        <Button size="lg" variant="ghost" className="w-full" onClick={() => setDelivering(null)}>
          {t("truck.sale.change")}
        </Button>
      </div>
    );
  }
  if (adding) return <NewCustomerForm onAdded={pick} onCancel={() => setAdding(false)} />;
  const all = customers.data ?? [];
  // Today's load names its clients: the server lists only them and the walk-in customer (D-174).
  const loaded = all.some((customer) => customer.on_load);
  // While nothing is typed, the customers sold to most recently come first.
  const recent =
    search.trim() === "" && !loaded ? recentCustomerIds().flatMap((id) => all.filter((one) => one.id === id)) : [];
  const others = all.filter((customer) => !recent.includes(customer));
  const badge = (customer: CustomerChoice) =>
    delivers && customer.on_load ? t(toDeliver(customer) ? "truck.sale.toDeliver" : "truck.sale.delivered") : undefined;
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
      {loaded ? <p className="text-sm font-semibold text-ink-2">{t("truck.sale.loadClients")}</p> : null}
      {recent.length > 0 ? <p className="text-sm font-semibold text-ink-2">{t("truck.sale.recent")}</p> : null}
      {recent.map((customer) => (
        <CustomerButton key={customer.id} customer={customer} onPick={pick} />
      ))}
      {recent.length > 0 && others.length > 0 ? (
        <p className="text-sm font-semibold text-ink-2">{t("truck.sale.others")}</p>
      ) : null}
      {others.map((customer) => (
        <CustomerButton key={customer.id} customer={customer} onPick={pick} badge={badge(customer)} />
      ))}
      {loaded ? null : (
        <>
          <Button size="lg" className="py-4 text-lg" disabled={!online} onClick={() => setAdding(true)}>
            {t("truck.newCustomer.button")}
          </Button>
          {online ? null : <p className="text-sm text-ink-2">{t("truck.newCustomer.needNetwork")}</p>}
        </>
      )}
    </div>
  );
}

// One customer on one line: the name, and the city when there is one (or what is left to deliver to them).
function CustomerButton({
  customer,
  onPick,
  badge,
}: {
  customer: CustomerChoice;
  onPick: (customer: CustomerChoice) => void;
  badge?: string;
}) {
  return (
    <Button
      size="lg"
      variant={customer.is_walk_in ? "secondary" : "primary"}
      className="justify-between py-3 text-lg"
      onClick={() => onPick(customer)}
    >
      <span className="min-w-0 truncate">{customer.name}</span>
      {badge !== undefined ? (
        <span className="flex-none text-sm font-semibold">{badge}</span>
      ) : customer.city === "" ? null : (
        <span className="flex-none text-sm font-normal">{customer.city}</span>
      )}
    </Button>
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
        <p className="text-ink-2">{t("truck.lateSale.madeAt", { when: formatDateTime(madeAtOf(sale)) })}</p>
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
