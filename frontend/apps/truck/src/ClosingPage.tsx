import { useCloseMyDay, useGetMyDaySummary, useListMyDeliveries } from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { DayReport } from "./DayReport";
import { sendError } from "./sendError";

// "Clôture": the day in a few lines, what the driver should hold, and one button to send it to the office (the
// figures, the wait for the phone's unsent sales and the form are in DayReport, shared with the history). The office
// counts the cash when the driver is back (D-213). Sending closes the day; it opens again when the office loads the
// truck again that date (D-134).
export function ClosingPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const day = useGetMyDaySummary({ query: { retry: false } });
  // The BL of the load still to deliver become "not delivered" when the day is sent (D-178).
  const deliveries = useListMyDeliveries({ query: { retry: false } });
  const undelivered = deliveries.data?.length ?? 0;
  const [error, setError] = useState("");
  const send = useCloseMyDay({
    mutation: {
      onSuccess: () => {
        setError("");
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
  return (
    <div className="space-y-4">
      {undelivered > 0 && !closed ? (
        <p role="status" className="rounded-control bg-warn-soft px-3 py-2 font-semibold text-warn">
          {t("truck.deliveries.closingWarning", { count: undelivered })}
        </p>
      ) : null}
      <DayReport
        data={day.data}
        sending={send.isPending}
        error={error}
        onSend={(note) => send.mutate({ data: { note } })}
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
