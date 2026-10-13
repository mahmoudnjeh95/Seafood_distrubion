import {
  archiveLocation,
  archiveTruck,
  restoreLocation,
  restoreTruck,
  useGetStockOverview,
  useListLocations,
  useListTrucks,
} from "@frutti/api";
import type { Session } from "@frutti/auth";
import { formatMoney, formatQuantity, useTranslation } from "@frutti/i18n";
import {
  Button,
  Card,
  cn,
  Dialog,
  Icon,
  Illustration,
  type IllustrationName,
  PageHeader,
  Pill,
  toast,
} from "@frutti/ui";
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { useOutletContext } from "react-router";

import { fieldErrors } from "../lib/errors";
import { type Status, StatusFilter } from "../lib/StatusFilter";
import { StockTabs } from "../lib/StockTabs";
import { StockProductCard } from "../stock/StockProductCard";
import { LocationDialog } from "./LocationDialog";
import { canEditLocations, refreshLocations } from "./shared";
import { TruckDialog } from "./TruckDialog";

type Open = { kind: "room" | "truck"; id: number | "new" } | null;

/** A location card like the prototype's: drawing, name, a line below and status labels. */
function PlaceCard({
  illustration,
  title,
  subtitle,
  stock = null,
  pills,
  numeric = false,
  onOpen,
  action,
}: {
  illustration: IllustrationName;
  title: string;
  subtitle: ReactNode;
  // Kilos and cost held, once the stock is loaded.
  stock?: string | null;
  pills: ReactNode;
  // The subtitle is a plate or another code: fixed-width digits.
  numeric?: boolean;
  onOpen?: () => void;
  // A button under the card, outside the clickable area (archive or restore).
  action?: ReactNode;
}) {
  const body = (
    <>
      <div className="grid h-20 w-[104px] flex-none place-items-center rounded-[10px] bg-surface-2">
        <Illustration name={illustration} className="h-[70px] w-24" />
      </div>
      <div className="flex min-w-0 flex-col items-start gap-1 text-start">
        <h3 className="max-w-full break-words" title={title}>
          {title}
        </h3>
        <span className={cn("text-[0.9rem] text-ink-2", numeric && "num")}>{subtitle}</span>
        {stock && <span className="num text-base font-semibold">{stock}</span>}
        <span className="flex flex-wrap gap-1.5">{pills}</span>
      </div>
    </>
  );
  return (
    <Card className="p-0" role="article" aria-label={title}>
      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          className="flex w-full items-center gap-4 rounded-card p-5 hover:bg-surface-2/60"
        >
          {body}
        </button>
      ) : (
        <div className="flex items-center gap-4 p-5">{body}</div>
      )}
      {action && <div className="flex justify-end border-t border-line px-5 py-2.5">{action}</div>}
    </Card>
  );
}

/** Archive or restore a place from its card. A place still holding stock is refused by the server. */
function ArchiveButton({ active, toggle }: { active: boolean; toggle: () => Promise<{ is_active: boolean }> }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: toggle,
    onSuccess: async (saved) => {
      toast.success(t(saved.is_active ? "admin.locations.form.restoredDone" : "admin.locations.form.archivedDone"));
      await refreshLocations(queryClient);
    },
    onError: (failure) => toast.error(fieldErrors(failure).detail ?? t("admin.locations.form.error")),
  });
  return (
    <Button variant="ghost" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
      {t(active ? "admin.locations.form.archive" : "admin.locations.form.restore")}
    </Button>
  );
}

export function LocationsPage() {
  const { t } = useTranslation();
  const session = useOutletContext<Session>();
  const canEdit = canEditLocations(session);
  const [status, setStatus] = useState<Status>("active");
  const [open, setOpen] = useState<Open>(null);

  const locations = useListLocations({ status }, { query: { placeholderData: keepPreviousData } });
  const trucks = useListTrucks({ status }, { query: { placeholderData: keepPreviousData } });
  const rooms = (locations.data ?? []).filter((location) => location.kind !== "truck");
  const truckList = trucks.data ?? [];
  const editingRoom = open?.kind === "room" ? rooms.find((room) => room.id === open.id) : undefined;
  const editingTruck = open?.kind === "truck" ? truckList.find((truck) => truck.id === open.id) : undefined;
  // Kilos and cost held per place, and the products with their stock (P1-T11).
  const overview = useGetStockOverview();
  const totals = overview.data?.locations ?? [];
  const stockLine = (locationId: number) => {
    const total = totals.find((row) => row.id === locationId);
    return total
      ? t("admin.stock.locationLine", {
          quantity: formatQuantity(total.quantity),
          value: formatMoney(total.value),
        })
      : null;
  };
  const failed = locations.isError || trucks.isError;
  const loading = locations.isPending || trucks.isPending;

  const archivedPill = (active: boolean) => !active && <Pill tone="neutral">{t("admin.locations.archived")}</Pill>;

  return (
    <>
      <PageHeader eyebrow={t("admin.groups.goods")} title={t("admin.locations.title")}>
        {canEdit && (
          <>
            <Button onClick={() => setOpen({ kind: "room", id: "new" })}>
              <Icon name="snow" />
              {t("admin.locations.addRoom")}
            </Button>
            <Button onClick={() => setOpen({ kind: "truck", id: "new" })}>
              <Icon name="truck" />
              {t("admin.locations.addTruck")}
            </Button>
          </>
        )}
      </PageHeader>
      <StockTabs />

      <p className="text-ink-2">{t(canEdit ? "admin.locations.intro" : "admin.locations.readOnly")}</p>

      <div className="flex">
        <StatusFilter
          value={status}
          onChange={setStatus}
          label={t("admin.locations.show")}
          labels={{
            active: t("admin.locations.status.active"),
            archived: t("admin.locations.status.archived"),
            all: t("admin.locations.status.all"),
          }}
        />
      </div>

      {loading ? (
        <p className="text-ink-2">{t("common.loading")}</p>
      ) : failed ? (
        <p role="alert" className="text-bad">
          {t("common.serverUnreachable")}
        </p>
      ) : (
        <>
          <section aria-labelledby="rooms-title" className="flex flex-col gap-3">
            <h2 id="rooms-title">{t("admin.locations.rooms")}</h2>
            {rooms.length === 0 ? (
              <p className="text-ink-2">{t("admin.locations.noRooms")}</p>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
                {rooms.map((room) => (
                  <PlaceCard
                    key={room.id}
                    illustration="fridge"
                    title={room.name}
                    subtitle={t(`admin.locations.kinds.${room.kind}`)}
                    stock={stockLine(room.id)}
                    pills={
                      <>
                        {room.counter_sales && <Pill tone="sea">{t("admin.locations.counterSales")}</Pill>}
                        {archivedPill(room.is_active)}
                      </>
                    }
                    onOpen={canEdit ? () => setOpen({ kind: "room", id: room.id }) : undefined}
                    action={
                      canEdit && (
                        <ArchiveButton
                          active={room.is_active}
                          toggle={() => (room.is_active ? archiveLocation(room.id) : restoreLocation(room.id))}
                        />
                      )
                    }
                  />
                ))}
              </div>
            )}
          </section>

          <section aria-labelledby="trucks-title" className="flex flex-col gap-3">
            <h2 id="trucks-title">{t("admin.locations.trucks")}</h2>
            {truckList.length === 0 ? (
              <p className="text-ink-2">{t("admin.locations.noTrucks")}</p>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
                {truckList.map((truck) => (
                  <PlaceCard
                    key={truck.id}
                    illustration="truck"
                    title={truck.driver ? `${truck.name} · ${truck.driver.name}` : truck.name}
                    subtitle={truck.plate}
                    stock={stockLine(truck.location_id)}
                    numeric
                    pills={
                      <>
                        {!truck.driver && truck.is_active && <Pill tone="warn">{t("admin.locations.noDriver")}</Pill>}
                        {archivedPill(truck.is_active)}
                      </>
                    }
                    onOpen={canEdit ? () => setOpen({ kind: "truck", id: truck.id }) : undefined}
                    action={
                      canEdit && (
                        <ArchiveButton
                          active={truck.is_active}
                          toggle={() => (truck.is_active ? archiveTruck(truck.id) : restoreTruck(truck.id))}
                        />
                      )
                    }
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <section aria-labelledby="stock-products-title" className="flex flex-col gap-3">
        <h2 id="stock-products-title">{t("admin.stock.productsTitle")}</h2>
        <p className="text-ink-2">{t("admin.stock.productsIntro")}</p>
        {overview.isPending ? (
          <p className="text-ink-2">{t("common.loading")}</p>
        ) : overview.isError ? (
          <p role="alert" className="text-bad">
            {t("admin.stock.loadError")}
          </p>
        ) : overview.data.products.length === 0 ? (
          <p className="text-ink-2">{t("admin.stock.noProducts")}</p>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">
            {overview.data.products.map((stock) => (
              <StockProductCard key={stock.id} stock={stock} places={totals} />
            ))}
          </div>
        )}
      </section>

      <Dialog open={open !== null} onOpenChange={(isOpen) => !isOpen && setOpen(null)}>
        {open?.kind === "room" && open.id === "new" && <LocationDialog onDone={() => setOpen(null)} />}
        {editingRoom && <LocationDialog key={editingRoom.id} location={editingRoom} onDone={() => setOpen(null)} />}
        {open?.kind === "truck" && open.id === "new" && <TruckDialog onDone={() => setOpen(null)} />}
        {editingTruck && <TruckDialog key={editingTruck.id} truck={editingTruck} onDone={() => setOpen(null)} />}
      </Dialog>
    </>
  );
}
