import { useListDueAlerts } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Card, CardTitle, Pill } from "@frutti/ui";
import { Link } from "react-router";

import { todayInput } from "../payments/shared";

/** The cheques and traites that need someone today (P9-T09e, D-254): ours to cash from their due day, ours to pay
 * from the day before (a cheque) or 15 days before (a traite). Shows nothing when there is none. */
export function DueAlertsCard() {
  const { t } = useTranslation();
  const alerts = useListDueAlerts();
  const today = todayInput();
  const rows = alerts.data ?? [];
  if (rows.length === 0) return null;

  return (
    <Card className="p-4">
      <CardTitle>{t("admin.treasury.dueAlerts.title")}</CardTitle>
      <ul className="flex flex-col gap-2 pt-2">
        {rows.map((row) => {
          const received = row.direction === "received";
          const party = row.customer?.name ?? row.supplier?.name ?? row.drawer;
          return (
            <li key={row.id} className="flex flex-wrap items-center justify-between gap-3">
              <Link
                to={received ? "/tresorerie/portefeuille" : "/tresorerie/portefeuille?onglet=issued"}
                className="hover:underline"
              >
                {t(received ? "admin.treasury.dueAlerts.toCash" : "admin.treasury.dueAlerts.toPay", {
                  kind: t(`admin.treasury.bordereau.kinds.${row.kind}`),
                  number: row.number,
                  party,
                })}
              </Link>
              <span className="flex items-center gap-2">
                <span className="num font-semibold">{formatMoney(row.amount)}</span>
                <Pill tone={row.due_on < today ? "bad" : "warn"}>{formatDate(row.due_on)}</Pill>
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
