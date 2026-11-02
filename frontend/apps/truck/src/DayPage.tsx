import {
  type MyBoxDay,
  useAssignTruck,
  useGetMyBoxDay,
  useGetMyDay,
  useGetMyDayFund,
  useGetMyTruckDay,
  useListMyDays,
  useListMyStock,
  useListMyTruckChoices,
  useOpenMyDay,
} from "@frutti/api";
import { useSession } from "@frutti/auth";
import { formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import { Button, Card, cn, ConfirmButton, EmptyState, Icon, type IconName, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { formatBoxCount } from "./boxes";
import { FoldCard } from "./FoldCard";
import { TodayAtAGlance } from "./TodayAtAGlance";

// "Ma journée", three steps and nothing else: pick the truck, check the load, start the day.
export function DayPage() {
  const session = useSession();
  const truck = session.data?.truck ?? null;
  return truck === null ? <PickTruck /> : <TruckDay truck={truck} />;
}

function PickTruck() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const choices = useListMyTruckChoices();
  const assign = useAssignTruck({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries(),
      onError: () => toast.error(t("truck.day.pickFailed")),
    },
  });
  const trucks = choices.data ?? [];
  if (choices.isLoading) return null;
  if (trucks.length === 0) {
    return (
      <EmptyState illustration="truck" title={t("truck.day.noTruck")}>
        {t("truck.day.noTruckBody")}
      </EmptyState>
    );
  }
  return (
    <div className="space-y-3">
      <h2>{t("truck.day.pickTruck")}</h2>
      {trucks.map((truck) => (
        <Button
          key={truck.id}
          size="lg"
          variant={truck.taken ? "ghost" : "primary"}
          className="flex-col py-5 text-xl"
          disabled={truck.taken || assign.isPending}
          onClick={() => assign.mutate({ data: { truck: truck.id } })}
        >
          <span>{truck.name}</span>
          <span className="text-sm font-normal">{truck.taken ? t("truck.day.taken") : truck.plate}</span>
        </Button>
      ))}
    </div>
  );
}

// The boxes of today per box type: what came, what the clients kept, what came back, and what should be on the truck.
function BoxDayCard({ day }: { day: MyBoxDay }) {
  const { t } = useTranslation();
  const typeName = (box: string) => (box === "small" ? t("truck.boxes.small") : t("truck.boxes.big"));
  const summary = day.lines.map((line) => `${typeName(line.box_type)} ${formatBoxCount(line.expected)}`).join(" · ");
  return (
    <FoldCard title={t("truck.boxes.dayTitle")} summary={summary}>
      <ul className="divide-y divide-line">
        {day.lines.map((line) => (
          <li key={line.box_type} className="space-y-1 py-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-lg font-semibold">
                {line.box_type === "small" ? t("truck.boxes.small") : t("truck.boxes.big")}
              </span>
              <span className="font-bold">{t("truck.boxes.expected", { count: formatBoxCount(line.expected) })}</span>
            </div>
            <p className="text-sm text-ink-2">
              {t("truck.boxes.dayLine", {
                loaded: formatBoxCount(line.loaded),
                left: formatBoxCount(line.left),
                collected: formatBoxCount(line.collected),
              })}
            </p>
          </li>
        ))}
      </ul>
    </FoldCard>
  );
}

/** The money the office gave for purchases at the port, kept apart from the sales cash (D-158). Read only on the
 * phone: the driver approved it when starting the day, and only the office changes it (D-248). */
function PurchaseFloat({ amount }: { amount: string }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1">
      <p className="text-ink-2">{t("truck.purchase.floatIs", { amount: formatMoney(amount) })}</p>
      <p className="text-sm text-ink-2">{t("truck.purchase.floatOfficeOnly")}</p>
    </div>
  );
}

interface TileProps {
  to: string;
  icon: IconName;
  label: string;
  primary?: boolean;
}

// One road task as a tile, two to a row: the day's menu takes one screen, not a scroll (D-171).
function DayTile({ to, icon, label, primary = false }: TileProps) {
  return (
    <Link
      to={to}
      className={cn(
        "flex min-h-[84px] flex-col items-center justify-center gap-2 rounded-card border p-3 text-center font-semibold",
        primary ? "border-sea bg-sea text-white" : "border-line bg-surface text-ink",
      )}
    >
      <Icon name={icon} className="size-6" />
      <span>{label}</span>
    </Link>
  );
}

/**
 * The cash the office set for today (D-203): the driver checks it and accepts it, which starts the day with it.
 * Nothing set yet: the driver asks the office and refreshes.
 */
function AcceptFund({
  canBuy,
  starting,
  onAccept,
  onRefresh,
}: {
  canBuy: boolean;
  starting: boolean;
  onAccept: () => void;
  onRefresh: () => void;
}) {
  const { t } = useTranslation();
  const fund = useGetMyDayFund({ query: { retry: false } });
  if (fund.isLoading) return null;
  if (!fund.data) {
    return (
      <Card className="space-y-3">
        <p className="text-lg font-semibold">{t("truck.day.fundWaiting")}</p>
        <p className="text-ink-2">{t("truck.day.fundWaitingBody")}</p>
        <Button size="lg" className="py-4 text-lg" onClick={onRefresh}>
          {t("truck.history.refresh")}
        </Button>
      </Card>
    );
  }
  const rows: [string, string][] = [[t("truck.day.cashLabel"), formatMoney(fund.data.opening_cash)]];
  if (canBuy || Number(fund.data.purchase_float) > 0) {
    rows.push([t("truck.purchase.float"), formatMoney(fund.data.purchase_float)]);
  }
  return (
    <Card className="space-y-3">
      <p className="text-lg font-semibold">{t("truck.day.fundTitle")}</p>
      <dl className="space-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3">
            <dt className="text-ink-2">{label}</dt>
            <dd className="num text-xl font-bold">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-sm text-ink-2">{t("truck.day.fundHint")}</p>
      <ConfirmButton
        size="lg"
        variant="primary"
        className="py-4 text-lg"
        disabled={starting}
        title={t("truck.day.fundConfirm")}
        rows={rows}
        onConfirm={onAccept}
      >
        {t("truck.day.fundAccept")}
      </ConfirmButton>
    </Card>
  );
}

function TruckDay({ truck }: { truck: { name: string; plate: string } }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const session = useSession();
  const canBuy = session.data?.can_buy === true;
  const day = useGetMyDay({ query: { retry: false } });
  const load = useGetMyTruckDay({ query: { retry: false } });
  const open = useOpenMyDay({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries(),
      onError: () => toast.error(t("truck.day.startFailed")),
    },
  });
  // Kilos left on the truck from an earlier day are not in today's load: show them as "in the truck".
  const stock = useListMyStock(undefined, { query: { retry: false } });
  // Returnable boxes of the truck today (P1-T14d): read only, nothing is posted at closing.
  const boxes = useGetMyBoxDay({ query: { retry: false } });
  const loadedToday = load.data?.lines.filter((line) => Number(line.loaded) > 0) ?? [];
  const lines =
    loadedToday.length > 0
      ? loadedToday.map((line) => ({ ...line, quantity: line.loaded }))
      : (stock.data ?? []).filter((line) => Number(line.quantity) > 0);
  // Millimes, as the other sums of kilos in this app.
  const loadMillimes = lines.reduce((sum, line) => sum + Math.round(Number(line.quantity) * 1000), 0);
  const running = day.data !== undefined && day.data.ended_at === null;
  // The day's closing was sent: it is closed until the office loads the truck again (D-134).
  const ended = day.data !== undefined && day.data.ended_at !== null;
  // A day the office asked about waits in the history for the driver's answer.
  const days = useListMyDays({ query: { retry: false } });
  const asked = days.data?.find((row) => row.closing?.status === "justification");
  const reopened = days.data?.find((row) => row.id === day.data?.id)?.closing?.status === "reopened";

  return (
    <div className="space-y-4">
      {asked === undefined ? null : (
        <Link to={`/historique/${asked.id}`} className="block">
          <Card className="space-y-1">
            <p className="font-semibold text-bad">{t("truck.history.askedTitle")}</p>
            <p>{t("truck.closing.asked", { reason: asked.closing?.review_note ?? "" })}</p>
          </Card>
        </Link>
      )}
      <Card className="p-4">
        <p className="text-sm text-ink-2">{t("truck.day.yourTruck")}</p>
        <p className="text-2xl font-bold">{truck.name}</p>
        <p className="text-ink-2">{truck.plate}</p>
      </Card>
      {/* Until the day starts, the cash form is the first thing here, not at the bottom (D-171). */}
      {day.isLoading ? null : running ? (
        <Card>
          <p className="text-lg font-semibold">{t(reopened ? "truck.history.reopened" : "truck.day.started")}</p>
          <p className="text-ink-2">{t("truck.day.cashAtStart", { amount: formatMoney(day.data.opening_cash) })}</p>
          {canBuy ? <PurchaseFloat amount={day.data.purchase_float} /> : null}
        </Card>
      ) : ended ? (
        <Card className="space-y-3">
          <div>
            <p className="text-lg font-semibold">{t("truck.history.ended")}</p>
            <p className="text-ink-2">{t("truck.history.endedBody")}</p>
          </div>
          <Button size="lg" className="py-4 text-lg" onClick={() => void queryClient.invalidateQueries()}>
            {t("truck.history.refresh")}
          </Button>
        </Card>
      ) : (
        <AcceptFund
          canBuy={canBuy}
          starting={open.isPending}
          onAccept={() => open.mutate()}
          onRefresh={() => void queryClient.invalidateQueries()}
        />
      )}
      <TodayAtAGlance enabled={running} />
      {load.isLoading || stock.isLoading ? null : lines.length === 0 ? (
        <EmptyState illustration="fridge" title={t("truck.day.nothingLoaded")}>
          {t("truck.day.nothingLoadedBody")}
        </EmptyState>
      ) : (
        <FoldCard
          defaultOpen
          title={t(loadedToday.length > 0 ? "truck.day.loaded" : "truck.day.inTruck")}
          summary={t("truck.day.loadSummary", {
            count: lines.length,
            kg: formatQuantity((loadMillimes / 1000).toFixed(3)),
          })}
        >
          <ul className="divide-y divide-line">
            {lines.map((line) => (
              <li key={line.product_id} className="flex items-center justify-between gap-3 py-3">
                <span className="text-lg font-semibold">{line.product_name}</span>
                <span className="text-end">
                  <span className="block text-xl font-bold">{formatQuantity(line.quantity)}</span>
                  {line.unit_price === null ? null : (
                    <span className="text-sm text-ink-2">{formatMoney(line.unit_price)} / kg</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </FoldCard>
      )}
      {boxes.data === undefined ? null : <BoxDayCard day={boxes.data} />}
      <div className="grid grid-cols-2 gap-2.5">
        {canBuy ? (
          <>
            <DayTile to="/achat" icon="cart" label={t("truck.purchase.add")} primary />
            <DayTile to="/achats" icon="receipt" label={t("truck.purchase.mine")} />
          </>
        ) : null}
        <DayTile to="/livraisons" icon="truck" label={t("truck.deliveries.open")} primary />
        <DayTile to="/reprise" icon="box" label={t("truck.boxes.pickupAdd")} />
        <DayTile to="/depense" icon="wallet" label={t("truck.expense.add")} />
        <DayTile to="/encaissement" icon="cash" label={t("truck.payment.add")} />
        <DayTile to="/perte" icon="trash" label={t("truck.loss.add")} />
        <DayTile to="/historique" icon="calcheck" label={t("truck.history.open")} />
      </div>
    </div>
  );
}
