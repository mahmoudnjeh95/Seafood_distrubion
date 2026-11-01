import { ApiError, collectMyPayment, type CustomerChoice, useListMyCustomers, useListMyPayments } from "@frutti/api";
import { useSession } from "@frutti/auth";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, ConfirmButton, EmptyState, Input, MoneyInput, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { sendOrKeep } from "./sendOrKeep";
import { sendWaiting } from "./sync";
import { newUuid } from "./uuid";

// Every text the server put in an error answer, so the driver reads why it was refused.
function messagesOf(body: unknown): string[] {
  if (typeof body === "string") return [body];
  if (Array.isArray(body)) return body.flatMap(messagesOf);
  if (typeof body === "object" && body !== null) return Object.values(body).flatMap(messagesOf);
  return [];
}

// "Encaisser": money a customer hands over for what they already owe. Cash only, in two taps.
export function PaymentPage() {
  const { t } = useTranslation();
  const session = useSession();
  const queryClient = useQueryClient();
  const hasTruck = session.data?.truck != null;
  const [search, setSearch] = useState("");
  const customers = useListMyCustomers({ search: search.trim() });
  const today = useListMyPayments();
  const [customer, setCustomer] = useState<CustomerChoice | null>(null);
  const [amount, setAmount] = useState("");
  const [uuid, setUuid] = useState(newUuid);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  if (!hasTruck) {
    return (
      <EmptyState illustration="truck" title={t("truck.day.noTruck")}>
        {t("truck.sale.needTruck")}
      </EmptyState>
    );
  }
  const amountValue = parseDecimalInput(amount.trim(), 3);
  const ready = customer !== null && amountValue !== null && Number(amountValue) > 0;

  const save = async () => {
    if (customer === null || amountValue === null) return;
    setSaving(true);
    setError("");
    const data = { customer: customer.id, amount: amountValue, method: "cash" as const, client_uuid: uuid };
    try {
      const outcome = await sendOrKeep(
        {
          kind: "payment",
          uuid,
          createdAt: new Date().toISOString(),
          label: customer.name,
          data,
          status: "pending",
          error: "",
        },
        () => collectMyPayment(data),
      );
      toast.success(t(outcome.kept ? "truck.payment.kept" : "truck.payment.saved"));
      setCustomer(null);
      setAmount("");
      setUuid(newUuid());
      void queryClient.invalidateQueries();
      void sendWaiting(queryClient);
    } catch (failure) {
      setError((failure instanceof ApiError ? messagesOf(failure.body).join(" ") : "") || t("truck.payment.failed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {customer === null ? (
        <div className="space-y-3">
          <h2>{t("truck.payment.who")}</h2>
          <Input
            type="search"
            aria-label={t("truck.sale.search")}
            placeholder={t("truck.sale.search")}
            className="text-lg"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {(customers.data ?? [])
            .filter((item) => !item.is_walk_in)
            .map((item) => (
              // What a customer owes is never shown on the phone (D-207): the driver types what was handed over.
              <Button
                key={item.id}
                size="lg"
                variant="secondary"
                className="flex-col py-4 text-xl"
                onClick={() => {
                  setCustomer(item);
                  setAmount("");
                }}
              >
                <span>{item.name}</span>
                {item.city ? <span className="text-sm font-normal">{item.city}</span> : null}
              </Button>
            ))}
        </div>
      ) : (
        <Card className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-ink-2">{t("truck.sale.customer")}</p>
              <p className="text-xl font-bold">{customer.name}</p>
            </div>
            <Button onClick={() => setCustomer(null)}>{t("truck.sale.change")}</Button>
          </div>
          <div className="space-y-1">
            <label htmlFor="payment-amount" className="font-semibold">
              {t("truck.payment.amount")}
            </label>
            <MoneyInput
              id="payment-amount"
              inputMode="decimal"
              placeholder="0"
              className="text-2xl"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </div>
          {error === "" ? null : <p className="text-bad">{error}</p>}
          <ConfirmButton
            size="lg"
            variant="primary"
            className="py-4 text-lg"
            disabled={!ready || saving}
            title={customer?.name}
            rows={[[t("truck.payment.amount"), formatMoney(amountValue ?? "0")]]}
            onConfirm={() => void save()}
          >
            {t("truck.payment.save")}
          </ConfirmButton>
        </Card>
      )}
      {(today.data ?? []).length === 0 ? null : (
        <Card>
          <h2 className="mb-3">{t("truck.payment.today")}</h2>
          <ul className="divide-y divide-line">
            {(today.data ?? []).map((payment) => (
              <li key={payment.id} className="flex items-baseline justify-between gap-3 py-3">
                <span className="text-lg font-semibold">{payment.customer_name}</span>
                <span className="text-lg font-bold">{formatMoney(payment.amount)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
