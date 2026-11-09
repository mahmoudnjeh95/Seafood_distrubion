import { ApiError, recordMyTruckTemperature } from "@frutti/api";
import { formatTemperature, useTranslation } from "@frutti/i18n";
import { Button, Card, Input, toast } from "@frutti/ui";
import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { newUuid } from "./uuid";

/** The driver notes the temperature of the truck's box (D-303); outside its range the office is told. Needs the
 * network: without it, the driver tries again later. */
export function TruckTemperatureCard() {
  const { t } = useTranslation();
  const [celsius, setCelsius] = useState("");
  const [requestId, setRequestId] = useState(newUuid);
  const save = useMutation({
    mutationFn: () => recordMyTruckTemperature({ celsius: celsius.trim(), client_uuid: requestId }),
    onSuccess: (reading) => {
      if (reading.out_of_range)
        toast.error(t("truck.temperature.alert", { celsius: formatTemperature(reading.celsius) }));
      else toast.success(t("truck.temperature.saved"));
      setCelsius("");
      setRequestId(newUuid());
    },
    onError: (failure) =>
      toast.error(failure instanceof ApiError ? t("truck.temperature.refused") : t("truck.temperature.offline")),
  });
  return (
    <Card>
      <h2 className="mb-2">{t("truck.temperature.title")}</h2>
      <form
        className="flex items-center gap-2"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <Input
          aria-label={t("truck.temperature.title")}
          placeholder="°C"
          inputMode="decimal"
          value={celsius}
          onChange={(event) => setCelsius(event.target.value)}
          className="w-28 text-lg"
        />
        <Button type="submit" size="lg" disabled={save.isPending || celsius.trim() === ""}>
          {t("truck.temperature.save")}
        </Button>
      </form>
    </Card>
  );
}
