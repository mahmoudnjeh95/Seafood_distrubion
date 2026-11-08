import type { MyOdometer } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Input } from "@frutti/ui";

import { formatKm, parseOdometer } from "./odometer";
import { PaperPhotoInput } from "./PaperPhotoInput";

/** The compteur typed when the day is sent (P10-T01, D-295): what the dashboard shows, in km, and an optional photo
 * of it. The truck's last reading is shown so a typo stands out; the server refuses a lower number. */
export function OdometerCard({
  odometer,
  km,
  onKm,
  photo,
  onPhoto,
}: {
  odometer: MyOdometer;
  km: string;
  onKm: (km: string) => void;
  photo: File | undefined;
  onPhoto: (photo: File | undefined) => void;
}) {
  const { t } = useTranslation();
  const typed = parseOdometer(km);
  const below = typed !== null && odometer.last_km !== null && typed < odometer.last_km;
  return (
    <div className="space-y-3 rounded-control border border-line p-3">
      <div className="space-y-1">
        <label htmlFor="closing-odometer" className="font-semibold">
          {t("truck.odometer.label")}
        </label>
        <Input
          id="closing-odometer"
          inputMode="numeric"
          autoComplete="off"
          value={km}
          onChange={(event) => onKm(event.target.value.replace(/\D/g, "").slice(0, 7))}
          className="text-xl"
        />
        {odometer.last_km === null ? null : (
          <p className="text-sm text-ink-2">{t("truck.odometer.last", { km: formatKm(odometer.last_km) })}</p>
        )}
        {below ? <p className="text-bad">{t("truck.odometer.below")}</p> : null}
      </div>
      <PaperPhotoInput value={photo} onChange={onPhoto} alreadyJoined={false} title={t("truck.odometer.photo")} />
    </div>
  );
}
