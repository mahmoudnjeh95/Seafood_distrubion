import {
  getListMyNotificationsQueryKey,
  type Notification,
  useListMyNotifications,
  useMarkMyNotificationsRead,
} from "@frutti/api";
import { formatDate, formatDateTime, formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { isSoundOn, NotificationBell, playChime, setSoundOn, toast, unlockSound } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";

// The messages the server writes (backend apps/notifications/rules.py); another one shows a plain "new notification".
const KINDS = [
  "day_started",
  "day_sent",
  "day_resent",
  "sale_confirmed",
  "credit_requested",
  "payment_recorded",
  "expense_created",
  "loss_recorded",
  "loss_waiting",
  "purchase_sent",
  "purchase_edited",
  "customer_created",
  "sync_problem",
  "truck_returned",
  "load_validated",
  "day_approved",
  "day_justification",
  "day_reopened",
  "purchase_validated",
  "purchase_refused",
  "purchase_changed",
  "loss_approved",
  "loss_rejected",
  "expense_approved",
  "expense_rejected",
  "truck_assigned",
  "sync_resolved",
  "delivery_done",
  "delivery_partial",
  "delivery_cancelled",
  "bl_changed",
  "bl_cancelled",
  "web_quote",
  "web_order",
  "effet_unpaid",
] as const;
type Kind = (typeof KINDS)[number];

const MONEY = new Set(["amount", "total", "difference"]);
// Both apps ask every 20 seconds, also from a tab in the background, so the tone comes soon after the action.
const POLL_MS = 20_000;
const SHOWN_AS_TOASTS = 3;

function isKind(kind: string): kind is Kind {
  return (KINDS as readonly string[]).includes(kind);
}

/** A value as the reader expects it: amounts in DT, weights in kg, dates as dates. */
function shown(name: string, value: string): string {
  try {
    if (MONEY.has(name)) return formatMoney(value);
    if (name === "quantity") return formatQuantity(value);
    if (name === "date") return formatDate(value);
  } catch {
    // Not the expected shape: shown as it came.
  }
  return value;
}

function useNotificationText(): (notification: Notification) => string {
  const { t } = useTranslation();
  return useCallback(
    (notification: Notification) => {
      if (!isKind(notification.kind)) return t("notifications.unknown");
      const values = Object.fromEntries(
        Object.entries(notification.params).map(([name, value]) => [name, shown(name, value)]),
      );
      // The values come from the server as a plain map; the typed `t` wants each message's own names, so the key is
      // checked (`isKind`) and the values are passed untyped.
      const translate = t as unknown as (key: string, values: Record<string, string>) => string;
      return translate(`notifications.kinds.${notification.kind}`, values);
    },
    [t],
  );
}

// The newest notification this person was already told about on this device, so a reload does not ring again.
function seenKey(userId: number): string {
  return `frutti-notifications-seen-${userId}`;
}

function readSeen(userId: number): number | null {
  try {
    const value = localStorage.getItem(seenKey(userId));
    return value === null ? null : Number(value);
  } catch {
    return null;
  }
}

function writeSeen(userId: number, id: number): void {
  try {
    localStorage.setItem(seenKey(userId), String(id));
  } catch {
    // Not kept: the same notifications may ring once more after a reload.
  }
}

/**
 * The bell of the header, in both apps (D-175). It asks the server every few seconds; a notification that came since
 * the last look plays the tone and shows as a toast. A click marks it read and opens where it says.
 */
export function NotificationCenter({ userId, tone }: { userId: number; tone?: "light" | "dark" }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const text = useNotificationText();
  const [soundOn, setSound] = useState(isSoundOn);
  const list = useListMyNotifications({
    query: { refetchInterval: POLL_MS, refetchIntervalInBackground: true, retry: false },
  });
  const markRead = useMarkMyNotificationsRead({
    mutation: {
      onSuccess: () => void queryClient.invalidateQueries({ queryKey: getListMyNotificationsQueryKey() }),
    },
  });
  const results = list.data?.results;

  useEffect(() => unlockSound(), []);

  useEffect(() => {
    if (!results) return;
    const newest = results[0]?.id ?? 0;
    const seen = readSeen(userId);
    // First time on this device: what came before is in the list, without a tone.
    if (seen === null || newest > seen) writeSeen(userId, newest);
    if (seen === null) return;
    const fresh = results.filter((notification) => notification.id > seen && !notification.read);
    if (fresh.length === 0) return;
    playChime();
    for (const notification of fresh.slice(0, SHOWN_AS_TOASTS)) toast(text(notification));
    if (fresh.length > SHOWN_AS_TOASTS) toast(t("notifications.more", { count: fresh.length - SHOWN_AS_TOASTS }));
  }, [results, userId, text, t]);

  const open = (id: number) => {
    const notification = results?.find((row) => row.id === id);
    if (!notification) return;
    if (!notification.read) markRead.mutate({ data: { ids: [id] } });
    if (notification.link) void navigate(notification.link);
  };

  return (
    <NotificationBell
      tone={tone}
      unread={list.data?.unread ?? 0}
      items={(results ?? []).map((notification) => ({
        id: notification.id,
        text: text(notification),
        time: formatDateTime(notification.created_at),
        read: notification.read,
      }))}
      onOpen={open}
      onReadAll={() => markRead.mutate({ data: { all: true } })}
      soundOn={soundOn}
      onToggleSound={() => {
        setSoundOn(!soundOn);
        setSound(!soundOn);
        if (!soundOn) playChime();
      }}
    />
  );
}
