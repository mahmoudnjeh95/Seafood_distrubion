import type { Session } from "@frutti/auth";
import { useTranslation } from "@frutti/i18n";
import { PageHeader } from "@frutti/ui";
import { useOutletContext } from "react-router";

import { DayFundsPanel } from "./DayFundsPanel";
import { canEditLocations } from "./shared";
import { TruckDayPanel } from "./TruckDayPanel";

/** "Camions du jour": its own menu entry, who drives which truck on a date (D-046). */
export function TruckDayPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.truckDay.title")} />
      <TruckDayPanel canEdit={canEditLocations(session)} />
      <DayFundsPanel canEdit={canEditLocations(session)} />
    </>
  );
}
