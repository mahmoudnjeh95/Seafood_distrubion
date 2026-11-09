import {
  getGetDayRouteQueryKey,
  type RoutePoint,
  type RouteStop,
  setCustomerLocation,
  useGetDayRoute,
} from "@frutti/api";
import { canAccess, useSession } from "@frutti/auth";
import { formatDateTime, useTranslation } from "@frutti/i18n";
import { Button, Card, toast } from "@frutti/ui";
import { useQueryClient } from "@tanstack/react-query";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

/** A driver whose last point is older than this is "not seen" while his day runs. */
const SILENT_AFTER_MS = 10 * 60_000;
const REFRESH_MS = 30_000;
const LINE = "#1f6f8b";

/** The route of a driver's day on OpenStreetMap: the line, the start, and the truck where it was last seen (D-166). */
function RouteCanvas({ points, stops }: { points: readonly RoutePoint[]; stops: readonly RouteStop[] }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const fitted = useRef(false);

  useEffect(() => {
    if (container.current === null) return;
    const created = L.map(container.current, { scrollWheelZoom: false }).setView([34.74, 10.76], 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
      // The site sends no referrer by default (same-origin policy); OpenStreetMap blocks tile requests without one.
      referrerPolicy: "origin",
    }).addTo(created);
    map.current = created;
    layer.current = L.layerGroup().addTo(created);
    // The dialog is still opening: measure the box again once it has its size.
    const timer = window.setTimeout(() => created.invalidateSize(), 250);
    return () => {
      window.clearTimeout(timer);
      created.remove();
      map.current = null;
      layer.current = null;
      fitted.current = false;
    };
  }, []);

  useEffect(() => {
    const group = layer.current;
    const current = map.current;
    if (group === null || current === null) return;
    group.clearLayers();
    if (points.length === 0) return;
    const path: L.LatLngTuple[] = points.map((p) => [p.latitude, p.longitude]);
    L.polyline(path, { color: LINE, weight: 4, opacity: 0.8 }).addTo(group);
    for (const [index, stop] of stops.entries()) {
      L.circleMarker([stop.latitude, stop.longitude], {
        radius: 9,
        color: "#fff",
        weight: 2,
        fillColor: "#e08a1e",
        fillOpacity: 0.95,
      })
        .bindTooltip(
          `${index + 1} · ${stop.customers.map((customer) => customer.name).join(", ") || "?"} · ${stop.minutes} min`,
        )
        .addTo(group);
    }
    L.circleMarker(path[0]!, { radius: 7, color: "#fff", weight: 2, fillColor: "#2e9e5b", fillOpacity: 1 }).addTo(
      group,
    );
    L.circleMarker(path[path.length - 1]!, {
      radius: 10,
      color: "#fff",
      weight: 3,
      fillColor: "#d64545",
      fillOpacity: 1,
    }).addTo(group);
    if (!fitted.current) {
      current.fitBounds(L.latLngBounds(path), { padding: [30, 30], maxZoom: 17 });
      fitted.current = true;
    }
  }, [points, stops]);

  return <div ref={container} className="h-[72dvh] min-h-96 w-full overflow-hidden rounded-control" />;
}

/** The customers of one stop; the owner or manager can save the stop as the place of a customer who has none. */
function StopCustomers({ stop, dayId, canSave }: { stop: RouteStop; dayId: number; canSave: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const save = async (customerId: number) => {
    try {
      await setCustomerLocation(customerId, {
        latitude: stop.latitude.toFixed(6),
        longitude: stop.longitude.toFixed(6),
      });
      toast.success(t("admin.dayOverview.detail.route.placeSaved"));
      await queryClient.invalidateQueries({ queryKey: getGetDayRouteQueryKey(dayId) });
    } catch {
      toast.error(t("admin.dayOverview.detail.route.placeFailed"));
    }
  };
  return (
    <span className="flex flex-wrap items-center gap-x-2">
      {stop.customers.map((customer) => (
        <span key={customer.id} className="flex items-center gap-1">
          {customer.name}
          {canSave && !customer.has_place && (
            <Button variant="ghost" onClick={() => void save(customer.id)}>
              {t("admin.dayOverview.detail.route.savePlace")}
            </Button>
          )}
        </span>
      ))}
    </span>
  );
}

/** The route map is switched off on the owner's request (D-180); set to true to show it again. */
export const ROUTE_MAP_ENABLED = false;

export function RouteMap({ dayId, running }: { dayId: number; running: boolean }) {
  const { t } = useTranslation();
  const k = "admin.dayOverview.detail.route";
  const session = useSession();
  const canSave = session.data ? canAccess(session.data, "day_closings", "write") : false;
  const route = useGetDayRoute(dayId, { query: { refetchInterval: running ? REFRESH_MS : false } });
  const points = route.data?.points ?? [];
  const stops = route.data?.stops ?? [];
  const last = route.data?.last ?? null;
  const silent = running && last !== null && route.dataUpdatedAt - Date.parse(last.recorded_at) > SILENT_AFTER_MS;
  return (
    <Card className="space-y-2 p-4">
      {route.isError ? (
        <p className="text-ink-2">{t("common.serverUnreachable")}</p>
      ) : last === null ? (
        <p className="text-ink-2">{route.isPending ? t("common.loading") : t(`${k}.empty`)}</p>
      ) : (
        <>
          <p className={silent ? "text-warn" : "text-ink-2"}>
            {t(`${k}.lastSeen`, { when: formatDateTime(last.recorded_at) })}
            {silent && ` · ${t(`${k}.silent`)}`}
          </p>
          <RouteCanvas points={points} stops={stops} />
          <p className="text-[0.8rem] text-ink-2">{t(`${k}.legend`, { count: points.length })}</p>
          <h4 className="pt-1 font-semibold">{t(`${k}.stops`, { count: stops.length })}</h4>
          {stops.length === 0 ? (
            <p className="text-ink-2">{t(`${k}.noStops`)}</p>
          ) : (
            <ol className="space-y-1">
              {stops.map((stop, index) => (
                <li key={stop.started_at} className="flex flex-wrap justify-between gap-x-3">
                  <span className="flex flex-wrap items-center gap-x-2">
                    <span>
                      {index + 1} · {formatTime(stop.started_at)} – {formatTime(stop.ended_at)}
                    </span>
                    <StopCustomers stop={stop} dayId={dayId} canSave={canSave} />
                  </span>
                  <strong>{t(`${k}.minutes`, { count: stop.minutes })}</strong>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </Card>
  );
}
