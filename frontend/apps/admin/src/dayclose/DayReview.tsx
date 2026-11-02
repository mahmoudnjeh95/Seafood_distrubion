import {
  useDecideDayOverviewExpense,
  useGetDayOverview,
  useReturnDayOverviewToStock,
  useValidateDayOverviewPurchase,
} from "@frutti/api";
import { formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Input, Pill, Table, Td, Th, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fieldErrors } from "../lib/errors";

const K = "admin.dayReview";
const EXPENSE_TONES: Record<string, "warn" | "good" | "bad"> = {
  draft: "warn",
  pending: "warn",
  approved: "good",
  rejected: "bad",
};
const PURCHASE_TONES: Record<string, "warn" | "good" | "bad"> = {
  submitted: "warn",
  validated: "good",
  refused: "bad",
};

/**
 * The office's check of one driver's day (D-239): the expenses to approve or refuse, the purchases to validate, and
 * what the truck still holds (kilos and boxes), which goes back to the cold room. Used by the closing window and by
 * the drivers' days, so the office can act whether or not the driver sent the day.
 */
export function DayReview({ dayId, canDecide }: { dayId: number; canDecide: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const day = useGetDayOverview(dayId);
  // The expense being refused, and why (a refusal needs its reason).
  const [refusing, setRefusing] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const refresh = () => {
    void queryClient.invalidateQueries();
  };
  const failed = (failure: unknown) => toast.error(Object.values(fieldErrors(failure))[0] ?? t(`${K}.error`));
  const decide = useDecideDayOverviewExpense({
    mutation: {
      onSuccess: () => {
        toast.success(t(`${K}.done`));
        setRefusing(null);
        setReason("");
        refresh();
      },
      onError: failed,
    },
  });
  const validate = useValidateDayOverviewPurchase({
    mutation: {
      onSuccess: () => {
        toast.success(t(`${K}.done`));
        refresh();
      },
      onError: failed,
    },
  });
  const back = useReturnDayOverviewToStock({
    mutation: {
      onSuccess: () => {
        toast.success(t(`${K}.done`));
        refresh();
      },
      onError: failed,
    },
  });
  const data = day.data;
  if (data === undefined) return null;
  const stockLeft = data.stock.some((row) => Number(row.on_truck) > 0) || data.boxes.some((row) => row.on_truck > 0);

  return (
    <fieldset className="flex flex-col gap-3 rounded-card border border-line p-3">
      <legend className="px-1 font-semibold">{t(`${K}.title`)}</legend>
      <p className="text-[0.85rem] text-ink-2">{t(`${K}.hint`)}</p>
      {data.review_blockers.length === 0 ? (
        <p className="font-semibold text-good">{t(`${K}.ready`)}</p>
      ) : (
        <div>
          <p className="font-semibold text-bad">{t(`${K}.blockedHeader`)}</p>
          <ul className="list-disc ps-5 text-bad">
            {data.review_blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}

      <section className="space-y-2">
        <p className="font-semibold">{t(`${K}.expenses.title`)}</p>
        {data.expenses.length === 0 ? (
          <p className="text-[0.85rem] text-ink-2">{t(`${K}.expenses.none`)}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t(`${K}.expenses.columns.item`)}</Th>
                <Th className="text-end">{t(`${K}.expenses.columns.amount`)}</Th>
                <Th>{t(`${K}.expenses.columns.paidWith`)}</Th>
                <Th>{t(`${K}.expenses.columns.status`)}</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {data.expenses.map((expense) => {
                const open = expense.status === "draft" || expense.status === "pending";
                const paidWith = expense.paid_by_driver
                  ? "pocket"
                  : expense.payment_method === "cash"
                    ? "cash"
                    : "other";
                return (
                  <tr key={expense.id}>
                    <Td>
                      {expense.category_name}
                      {expense.description ? ` · ${expense.description}` : ""}
                    </Td>
                    <Td className="num text-end">{formatMoney(expense.amount)}</Td>
                    <Td>{t(`${K}.expenses.paidWith.${paidWith}`)}</Td>
                    <Td>
                      <Pill tone={EXPENSE_TONES[expense.status] ?? "warn"}>
                        {t(`${K}.expenses.statuses.${expense.status}`)}
                      </Pill>
                      {expense.rejection_reason !== "" && (
                        <span className="ms-2 text-[0.85rem] text-ink-2">{expense.rejection_reason}</span>
                      )}
                    </Td>
                    <Td>
                      {canDecide &&
                        open &&
                        (refusing === expense.id ? (
                          <div className="flex flex-wrap gap-2">
                            <Input
                              aria-label={t(`${K}.expenses.reason`)}
                              placeholder={t(`${K}.expenses.reason`)}
                              value={reason}
                              onChange={(event) => setReason(event.target.value)}
                            />
                            <Button
                              variant="primary"
                              disabled={decide.isPending || reason.trim() === ""}
                              onClick={() =>
                                decide.mutate({
                                  dayId,
                                  expenseId: expense.id,
                                  data: { decision: "reject", reason: reason.trim() },
                                })
                              }
                            >
                              {t(`${K}.expenses.confirmRefuse`)}
                            </Button>
                            <Button onClick={() => setRefusing(null)}>{t("admin.dayClosings.correct.cancel")}</Button>
                          </div>
                        ) : (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="primary"
                              disabled={decide.isPending}
                              onClick={() =>
                                decide.mutate({
                                  dayId,
                                  expenseId: expense.id,
                                  data: { decision: "approve", reason: "" },
                                })
                              }
                            >
                              {t(`${K}.expenses.approve`)}
                            </Button>
                            <Button
                              onClick={() => {
                                setRefusing(expense.id);
                                setReason("");
                              }}
                            >
                              {t(`${K}.expenses.refuse`)}
                            </Button>
                          </div>
                        ))}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </section>

      <section className="space-y-2">
        <p className="font-semibold">{t(`${K}.purchases.title`)}</p>
        {data.purchases.length === 0 ? (
          <p className="text-[0.85rem] text-ink-2">{t(`${K}.purchases.none`)}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t(`${K}.purchases.columns.number`)}</Th>
                <Th>{t(`${K}.purchases.columns.supplier`)}</Th>
                <Th className="text-end">{t(`${K}.purchases.columns.total`)}</Th>
                <Th className="text-end">{t(`${K}.purchases.columns.cash`)}</Th>
                <Th>{t(`${K}.purchases.columns.status`)}</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {data.purchases.map((purchase) => (
                <tr key={purchase.id}>
                  <Td className="num">{purchase.number}</Td>
                  <Td>{purchase.supplier_name}</Td>
                  <Td className="num text-end">{formatMoney(purchase.total)}</Td>
                  <Td className="num text-end">{formatMoney(purchase.cash)}</Td>
                  <Td>
                    <Pill tone={PURCHASE_TONES[purchase.status] ?? "warn"}>
                      {t(`${K}.purchases.statuses.${purchase.status}`)}
                    </Pill>
                  </Td>
                  <Td>
                    {canDecide && purchase.status === "submitted" && (
                      <Button
                        variant="primary"
                        disabled={validate.isPending}
                        onClick={() => validate.mutate({ dayId, purchaseId: purchase.id })}
                      >
                        {t(`${K}.purchases.validate`)}
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>

      {data.owns_truck ? (
        <>
          <section className="space-y-2">
            <p className="font-semibold">{t(`${K}.stock.title`)}</p>
            {data.stock.length === 0 ? (
              <p className="text-[0.85rem] text-ink-2">{t(`${K}.stock.empty`)}</p>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>{t(`${K}.stock.product`)}</Th>
                    <Th className="text-end">{t(`${K}.stock.onTruck`)}</Th>
                    <Th className="text-end">{t(`${K}.stock.pending`)}</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.stock.map((row) => (
                    <tr key={row.product_id}>
                      <Td>{row.product_name}</Td>
                      <Td className="num text-end">{formatQuantity(row.on_truck)}</Td>
                      <Td className="num text-end">{formatQuantity(row.purchased_pending)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </section>

          <section className="space-y-2">
            <p className="font-semibold">{t(`${K}.boxes.title`)}</p>
            <Table>
              <thead>
                <tr>
                  <Th>{t(`${K}.stock.product`)}</Th>
                  <Th className="text-end">{t(`${K}.boxes.onTruck`)}</Th>
                  <Th className="text-end">{t(`${K}.boxes.leftAtClients`)}</Th>
                  <Th className="text-end">{t(`${K}.boxes.collected`)}</Th>
                  <Th className="text-end">{t(`${K}.boxes.fromSuppliers`)}</Th>
                </tr>
              </thead>
              <tbody>
                {data.boxes.map((row) => (
                  <tr key={row.box_type}>
                    <Td>{t(`${K}.boxes.types.${row.box_type}`)}</Td>
                    <Td className="num text-end">{row.on_truck}</Td>
                    <Td className="num text-end">{row.left_at_clients}</Td>
                    <Td className="num text-end">{row.collected}</Td>
                    <Td className="num text-end">{row.from_suppliers}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </section>

          {canDecide && (
            <div className="flex flex-col gap-1">
              <p className="text-[0.85rem] text-ink-2">{t(`${K}.returnHint`)}</p>
              <Button
                className="self-start"
                variant="primary"
                disabled={back.isPending || !stockLeft}
                onClick={() => back.mutate({ dayId })}
              >
                {t(`${K}.returnAll`)}
              </Button>
            </div>
          )}
        </>
      ) : (
        <p className="text-[0.85rem] text-ink-2">{t(`${K}.notLatest`)}</p>
      )}
    </fieldset>
  );
}
