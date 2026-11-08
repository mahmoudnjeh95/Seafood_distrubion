import { type Alert, useListMyAlerts } from "@frutti/api";
import { formatDate, useTranslation } from "@frutti/i18n";
import { Card, cn } from "@frutti/ui";

/** What is due on the driver's truck and on his own papers (P10-T05, D-295): red first, then orange. Nothing when
 * all is in order, or while the phone is offline. */
export function MyAlertsCard() {
  const { t } = useTranslation();
  const alerts = useListMyAlerts({ query: { retry: false } });
  const list = alerts.data ?? [];
  if (list.length === 0) return null;
  const late = list.some((alert) => alert.state === "late");
  return (
    <Card className={cn("space-y-2 border-2", late ? "border-bad" : "border-warn")}>
      <p className="text-lg font-semibold">{t("truck.alerts.title")}</p>
      <ul className="space-y-1">
        {list.map((alert) => (
          <li key={`${alert.what}-${alert.object_id}`} className={alert.state === "late" ? "text-bad" : "text-warn"}>
            <span className="font-semibold">{alert.title}</span> · {alert.subject} · <When alert={alert} />
          </li>
        ))}
      </ul>
      <p className="text-sm text-ink-2">{t("truck.alerts.hint")}</p>
    </Card>
  );
}

function When({ alert }: { alert: Alert }) {
  const { t } = useTranslation();
  if (alert.state === "late") return <>{t("truck.alerts.late")}</>;
  if (alert.km_left !== null) return <>{t("truck.alerts.kmLeft", { km: alert.km_left })}</>;
  if (alert.due_on !== null) return <>{t("truck.alerts.before", { date: formatDate(alert.due_on) })}</>;
  return <>{t("truck.alerts.soon")}</>;
}
