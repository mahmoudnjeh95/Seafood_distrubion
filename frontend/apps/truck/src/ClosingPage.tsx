import {
  ApiError,
  getGetMyOdometerQueryKey,
  recordMyOdometer,
  useCloseMyDay,
  useGetMyDaySummary,
  useGetMyOdometer,
  useListMyDeliveries,
} from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DayReport } from "./DayReport";
import { formatKm, parseOdometer } from "./odometer";
import { OdometerCard } from "./OdometerCard";
import { sendError } from "./sendError";

// "Clôture": the day in a few lines, what the driver should hold, and one button to send it to the office (the
// figures, the wait for the phone's unsent sales and the form are in DayReport, shared with the history). The office
// counts the cash when the driver is back (D-213). Sending closes the day; it opens again when the office loads the
// truck again that date (D-134). The compteur of the day is asked first, once a day, and recorded just before the
// send (P10-T01, D-295).
export function ClosingPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const day = useGetMyDaySummary({ query: { retry: false } });
  const odometer = useGetMyOdometer({ query: { retry: false } });
  // The BL of the load still to deliver become "not delivered" when the day is sent (D-178).
  const deliveries = useListMyDeliveries({ query: { retry: false } });
  const undelivered = deliveries.data?.length ?? 0;
  const [error, setError] = useState("");
  const [km, setKm] = useState("");
  const [photo, setPhoto] = useState<File | undefined>(undefined);
  const [recording, setRecording] = useState(false);
  const send = useCloseMyDay({
    mutation: {
      onSuccess: () => {
        setError("");
        setKm("");
        setPhoto(undefined);
        void queryClient.invalidateQueries();
      },
      onError: (failure) => setError(sendError(failure, t("truck.closing.failed"))),
    },
  });

  if (day.isLoading) return null;
  if (day.data === undefined) {
    return (
      <EmptyState illustration="fridge" title={t("truck.closing.notStarted")}>
        {t("truck.closing.notStartedBody")}
      </EmptyState>
    );
  }
  const { closing } = day.data;
  // Sent and nothing to send again: the day is closed until a new load.
  const closed =
    closing !== null &&
    (closing.status === "approved" || (closing.status === "submitted" && !closing.changed_since_sent));
  // Asked once a day: a day sent again (a justification) keeps the compteur already typed. A new load that reopened
  // the day asks it again, since the truck drove since.
  const asksOdometer =
    odometer.data !== undefined && (odometer.data.today_km === null || closing?.status === "reopened");
  const typed = parseOdometer(km);
  const odometerReady = !asksOdometer || typed !== null;

  const sendDay = async (note: string) => {
    setError("");
    if (asksOdometer && typed !== null) {
      setRecording(true);
      try {
        await recordMyOdometer({ km: typed, ...(photo === undefined ? {} : { photo }) });
        await queryClient.invalidateQueries({ queryKey: getGetMyOdometerQueryKey() });
      } catch (failure) {
        setError(odometerError(failure, t("truck.odometer.failed")));
        return;
      } finally {
        setRecording(false);
      }
    }
    send.mutate({ data: { note } });
  };

  return (
    <div className="space-y-4">
      {undelivered > 0 && !closed ? (
        <p role="status" className="rounded-control bg-warn-soft px-3 py-2 font-semibold text-warn">
          {t("truck.deliveries.closingWarning", { count: undelivered })}
        </p>
      ) : null}
      <DayReport
        data={day.data}
        sending={send.isPending || recording}
        error={error}
        onSend={(note) => void sendDay(note)}
        sendReady={odometerReady}
        confirmRows={asksOdometer && typed !== null ? [[t("truck.odometer.label"), formatKm(typed)]] : []}
        beforeSend={
          asksOdometer && odometer.data !== undefined ? (
            <OdometerCard odometer={odometer.data} km={km} onKm={setKm} photo={photo} onPhoto={setPhoto} />
          ) : null
        }
      />
      {closed ? (
        <Card>
          <p className="text-ink-2">{t("truck.closing.closedBody")}</p>
        </Card>
      ) : null}
      <Button asChild size="lg" className="py-4 text-lg">
        <Link to="/historique">{t("truck.history.open")}</Link>
      </Button>
    </div>
  );
}

/** The server's reason for refusing the compteur (below the last reading, a day already sent), or the fallback. */
function odometerError(failure: unknown, fallback: string): string {
  if (!(failure instanceof ApiError) || typeof failure.body !== "object" || failure.body === null) return fallback;
  const first = Object.values(failure.body as Record<string, unknown>).flat()[0];
  return typeof first === "string" ? first : fallback;
}
