import { useListMyFieldPurchases } from "@frutti/api";
import { useSession } from "@frutti/auth";
import { formatDate, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState, Pill } from "@frutti/ui";
import { Link } from "react-router";

import { useOnline } from "./offline";
import { PrintButton } from "./printing/PrintButton";
import { useQueue } from "./queue";

const TONE = { submitted: "warn", validated: "good", refused: "bad" } as const;

/** "Mes achats": the purchases of the last 30 days, what the office decided and said, and the ones still on the
 * phone. One not decided yet can be changed (with network). */
export function MyPurchasesPage() {
  const { t } = useTranslation();
  const session = useSession();
  const online = useOnline();
  const canBuy = session.data?.can_buy === true;
  const purchases = useListMyFieldPurchases({ query: { retry: false } });
  const waiting = useQueue().filter((item) => item.kind === "purchase");
  const rows = purchases.data ?? [];

  return (
    <div className="space-y-4">
      <h2>{t("truck.purchase.mine")}</h2>
      {canBuy ? (
        <Button asChild size="lg" variant="primary" className="py-4 text-lg">
          <Link to="/achat">{t("truck.purchase.add")}</Link>
        </Button>
      ) : null}
      {waiting.map((item) => (
        <Card key={item.uuid} className="space-y-1">
          <p className="flex items-center justify-between gap-3">
            <span className="text-lg font-semibold">{item.label}</span>
            <Pill tone={item.status === "refused" ? "bad" : "neutral"}>{t("truck.purchase.waiting")}</Pill>
          </p>
          {item.error === "" ? null : <p className="text-bad">{item.error}</p>}
        </Card>
      ))}
      {purchases.isLoading ? null : rows.length === 0 && waiting.length === 0 ? (
        <EmptyState illustration="fish" title={t("truck.purchase.empty")} />
      ) : (
        rows.map((purchase) => (
          <Card key={purchase.id} className="space-y-2">
            <p className="flex items-center justify-between gap-3">
              <span className="text-lg font-semibold">{purchase.supplier?.name ?? purchase.proposed_supplier}</span>
              <Pill tone={TONE[purchase.status]}>{t(`truck.purchase.status.${purchase.status}`)}</Pill>
            </p>
            <p className="text-sm text-ink-2">
              {purchase.number} · {formatDate(purchase.bought_on)}
              {purchase.has_paper ? ` · ${t("truck.purchase.paperJoined")}` : ""}
            </p>
            <ul className="text-sm">
              {purchase.lines.map((line) => (
                <li key={line.id}>
                  {line.product?.name ?? line.proposed_product} · {formatQuantity(line.declared_quantity)} ×{" "}
                  {formatMoney(line.unit_cost)}
                  {line.received_quantity !== null && line.received_quantity !== line.declared_quantity ? (
                    <span className="font-semibold text-warn">
                      {" "}
                      · {t("truck.purchase.received", { kilos: formatQuantity(line.received_quantity) })}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
            <p className="flex justify-between">
              <span>{t("truck.purchase.total")}</span>
              <b>{formatMoney(purchase.total)}</b>
            </p>
            <p className="flex justify-between">
              <span>{t("truck.purchase.rest")}</span>
              <b>{formatMoney(purchase.rest)}</b>
            </p>
            {purchase.office_note ? (
              <p className="font-semibold">{t("truck.purchase.officeNote", { note: purchase.office_note })}</p>
            ) : null}
            <PrintButton
              receipt={{
                kind: "purchase",
                company: session.data?.organization.name ?? "",
                number: purchase.number,
                date: purchase.created_at,
                partyName: purchase.supplier?.name ?? purchase.proposed_supplier,
                by: session.data?.user.first_name,
                lines: purchase.lines.map((line) => ({
                  name: line.product?.name ?? line.proposed_product,
                  quantity: line.received_quantity ?? line.declared_quantity,
                  unitPrice: line.unit_cost,
                  amount: line.amount,
                })),
                total: purchase.total,
                paid: purchase.paid,
                rest: purchase.rest,
              }}
            />
            {purchase.status === "submitted" && canBuy ? (
              <Button asChild disabled={!online}>
                <Link to={`/achats/${purchase.id}`}>{t("truck.purchase.edit")}</Link>
              </Button>
            ) : null}
          </Card>
        ))
      )}
    </div>
  );
}
