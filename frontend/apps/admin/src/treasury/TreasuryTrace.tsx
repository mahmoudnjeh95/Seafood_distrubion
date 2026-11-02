import { useListMovementsOf } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Card, CardTitle } from "@frutti/ui";
import { Link } from "react-router";

/** Where the money of a record went (P9-T09c, D-251): each treasury movement it wrote, with the account it went
 * through, linked to that account's journal. Shows nothing when the record moved no money. */
export function TreasuryTrace({ source, ids }: { source: string; ids: readonly number[] }) {
  const { t } = useTranslation();
  const movements = useListMovementsOf({ source, source_ids: ids.join(",") }, { query: { enabled: ids.length > 0 } });
  const rows = movements.data ?? [];
  if (rows.length === 0) return null;

  return (
    <Card className="p-3">
      <CardTitle>{t("admin.treasury.trace.title")}</CardTitle>
      <ul className="flex flex-col divide-y divide-line">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-[0.9rem]">
            <span>
              {row.account.kind === "driver" ? (
                <span className="font-semibold">{row.account.name}</span>
              ) : (
                <Link
                  to={`/tresorerie/journal/${row.account.kind === "bank" ? "banques" : "caisses"}?compte=${row.account.id}`}
                  className="font-semibold text-sea hover:underline"
                >
                  {row.account.name}
                </Link>
              )}
              <span className="text-ink-2"> · {formatDate(row.day)}</span>
            </span>
            <span className="num font-semibold">{formatMoney(row.amount)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
