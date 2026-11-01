import { addMyExpense, ApiError, useGetMyDaySummary, useListMyExpenses, useListRoadCategories } from "@frutti/api";
import { useSession } from "@frutti/auth";
import { formatMoney, parseDecimalInput, useTranslation } from "@frutti/i18n";
import { Button, Card, ConfirmButton, EmptyState, Input, MoneyInput, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { cashOffOn, PAID_WITH, type PaidWith, paidWithOn } from "./expensePaid";
import { sendOrKeep } from "./sendOrKeep";
import { sendWaiting } from "./sync";
import { newUuid } from "./uuid";

// "Dépense": what the driver paid on the road, in four taps and a photo of the receipt.
export function ExpensePage() {
  const { t } = useTranslation();
  const session = useSession();
  const queryClient = useQueryClient();
  const truck = session.data?.truck ?? null;
  const categories = useListRoadCategories();
  const expenses = useListMyExpenses();
  const day = useGetMyDaySummary({ query: { retry: false } });
  const [category, setCategory] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [paidWith, setPaidWith] = useState<PaidWith>("cash");
  const [photo, setPhoto] = useState<File | undefined>(undefined);
  const [uuid, setUuid] = useState(newUuid);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  if (truck === null) {
    return (
      <EmptyState illustration="truck" title={t("truck.day.noTruck")}>
        {t("truck.sale.needTruck")}
      </EmptyState>
    );
  }
  const amountValue = parseDecimalInput(amount.trim(), 3);
  const ready = category !== null && amountValue !== null && Number(amountValue) > 0;
  // The day's starting cash decides whether "La caisse" can pay (D-220); the server refuses it the same way.
  const cashOff = cashOffOn(day.data?.summary.opening_cash);
  const paid = paidWithOn(paidWith, cashOff);

  const save = async () => {
    if (category === null || amountValue === null) return;
    setSaving(true);
    setError("");
    const data = { category, amount: amountValue, description, receipt: photo, client_uuid: uuid, paid_with: paid };
    try {
      const outcome = await sendOrKeep(
        {
          kind: "expense",
          uuid,
          createdAt: new Date().toISOString(),
          label: (categories.data ?? []).find((item) => item.id === category)?.name ?? "",
          data,
          status: "pending",
          error: "",
        },
        () => addMyExpense(data),
      );
      toast.success(t(outcome.kept ? "truck.expense.kept" : "truck.expense.saved"));
      setCategory(null);
      setAmount("");
      setDescription("");
      setPaidWith("cash");
      setPhoto(undefined);
      setUuid(newUuid());
      void queryClient.invalidateQueries();
      void sendWaiting(queryClient);
    } catch (failure) {
      const body = failure instanceof ApiError ? JSON.stringify(failure.body ?? "") : "";
      setError(body === "" || body === '""' ? t("truck.expense.failed") : t("truck.expense.failedWith", { why: body }));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <h2>{t("truck.expense.what")}</h2>
        <div className="grid grid-cols-2 gap-3">
          {(categories.data ?? []).map((item) => (
            <Button
              key={item.id}
              size="lg"
              variant={category === item.id ? "primary" : "secondary"}
              className="py-4 text-lg"
              onClick={() => setCategory(item.id)}
            >
              {item.name}
            </Button>
          ))}
        </div>
        <div className="space-y-1">
          <label htmlFor="expense-amount" className="font-semibold">
            {t("truck.expense.amount")}
          </label>
          <MoneyInput
            id="expense-amount"
            inputMode="decimal"
            placeholder="0"
            className="text-2xl"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </div>
        <div role="group" aria-label={t("truck.expense.paidWith")} className="space-y-1">
          <p className="font-semibold">{t("truck.expense.paidWith")}</p>
          <div className="grid grid-cols-3 gap-2">
            {PAID_WITH.map((value) => (
              <Button
                key={value}
                variant={paid === value ? "primary" : "secondary"}
                className="py-3"
                aria-pressed={paid === value}
                disabled={value === "cash" && cashOff}
                onClick={() => setPaidWith(value)}
              >
                {t(`truck.expense.paid.${value}`)}
              </Button>
            ))}
          </div>
          {cashOff && !day.isLoading ? <p className="text-sm text-warn">{t("truck.expense.cashOff")}</p> : null}
          {paid === "pocket" ? <p className="text-sm text-ink-2">{t("truck.expense.pocketHint")}</p> : null}
        </div>
        <div className="space-y-1">
          <label htmlFor="expense-note" className="font-semibold">
            {t("truck.expense.note")}
          </label>
          <Input id="expense-note" value={description} onChange={(event) => setDescription(event.target.value)} />
        </div>
        <div className="space-y-1">
          <label htmlFor="expense-photo" className="font-semibold">
            {t("truck.expense.photo")}
          </label>
          <input
            id="expense-photo"
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(event) => setPhoto(event.target.files?.[0])}
          />
        </div>
        {error === "" ? null : <p className="text-bad">{error}</p>}
        <ConfirmButton
          size="lg"
          variant="primary"
          className="py-4 text-lg"
          disabled={!ready || saving}
          title={categories.data?.find((item) => item.id === category)?.name}
          rows={[
            [t("truck.expense.amount"), formatMoney(amountValue ?? "0")],
            [t("truck.expense.paidWith"), t(`truck.expense.paid.${paid}`)],
          ]}
          onConfirm={() => void save()}
        >
          {t("truck.expense.save")}
        </ConfirmButton>
      </Card>
      {(expenses.data ?? []).length === 0 ? null : (
        <Card>
          <h2 className="mb-3">{t("truck.expense.today")}</h2>
          <ul className="divide-y divide-line">
            {(expenses.data ?? []).map((expense) => (
              <li key={expense.id} className="py-3">
                <p className="flex items-baseline justify-between gap-3">
                  <span className="text-lg font-semibold">{expense.category_name}</span>
                  <span className="text-lg font-bold">{formatMoney(expense.amount)}</span>
                </p>
                <p className="text-sm text-ink-2">
                  {t(`truck.expense.status.${expense.status}`)}
                  {expense.status === "rejected" && expense.rejection_reason !== ""
                    ? ` : ${expense.rejection_reason}`
                    : ""}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
