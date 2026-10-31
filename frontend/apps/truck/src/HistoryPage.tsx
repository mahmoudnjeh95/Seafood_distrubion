import { type MyDayRow, useCloseMyPastDay, useGetMyPastDay, useListMyDays } from "@frutti/api";
import { formatDate, formatMoney, useTranslation } from "@frutti/i18n";
import { Button, Card, EmptyState } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { DayReport } from "./DayReport";
import { sendError } from "./sendError";

const TONES = {
  submitted: "text-warn",
  justification: "text-bad",
  reopened: "text-warn",
  approved: "text-good",
} as const;

function DayStatus({ row }: { row: MyDayRow }) {
  const { t } = useTranslation();
  if (row.closing === null) {
    return (
      <span className="text-ink-2">{t(row.ended_at === null ? "truck.history.running" : "truck.history.notSent")}</span>
    );
  }
  return (
    <span className={`font-semibold ${TONES[row.closing.status]}`}>
      {t(`truck.history.statuses.${row.closing.status}`)}
    </span>
  );
}

// "Mes journées": the driver's days, newest first; one tap opens its figures (D-134).
export function HistoryPage() {
  const { t } = useTranslation();
  const days = useListMyDays({ query: { retry: false } });
  if (days.isLoading) return null;
  const rows = days.data ?? [];
  if (rows.length === 0) {
    return (
      <EmptyState illustration="truck" title={t("truck.history.empty")}>
        {t("truck.history.emptyBody")}
      </EmptyState>
    );
  }
  return (
    <div className="space-y-3">
      <h2>{t("truck.history.title")}</h2>
      {rows.map((row) => (
        <Link key={row.id} to={`/historique/${row.id}`} className="block">
          <Card className="space-y-1">
            <p className="flex items-baseline justify-between gap-3">
              <span className="text-lg font-bold">{formatDate(row.date)}</span>
              <DayStatus row={row} />
            </p>
            <p className="text-sm text-ink-2">{row.truck_name}</p>
            {row.closing === null ? null : (
              <p className="text-ink-2">
                {t("truck.history.expected", { amount: formatMoney(row.closing.expected_cash) })}
              </p>
            )}
          </Card>
        </Link>
      ))}
    </div>
  );
}

// One day of the history: its figures as sent, and the form when the day is to send: never sent, asked about by
// the office, reopened by a new load, or changed since the send.
export function HistoryDayPage() {
  const { t } = useTranslation();
  const { dayId } = useParams();
  const id = Number(dayId);
  const queryClient = useQueryClient();
  const day = useGetMyPastDay(id, { query: { retry: false, enabled: Number.isInteger(id) } });
  const days = useListMyDays({ query: { retry: false } });
  const [error, setError] = useState("");
  const send = useCloseMyPastDay({
    mutation: {
      onSuccess: () => {
        setError("");
        void queryClient.invalidateQueries();
      },
      onError: (failure) => setError(sendError(failure, t("truck.closing.failed"))),
    },
  });
  const row = days.data?.find((item) => item.id === id);
  return (
    <div className="space-y-4">
      <Button asChild className="self-start">
        <Link to="/historique">{t("truck.history.back")}</Link>
      </Button>
      {row === undefined ? null : (
        <div>
          <h2>{formatDate(row.date)}</h2>
          <p className="text-ink-2">{row.truck_name}</p>
        </div>
      )}
      {day.isLoading ? null : day.data === undefined ? (
        <p className="text-bad">{t("truck.history.failed")}</p>
      ) : (
        <DayReport
          data={day.data}
          sending={send.isPending}
          error={error}
          onSend={(note) => send.mutate({ dayId: id, data: { note } })}
        />
      )}
    </div>
  );
}
