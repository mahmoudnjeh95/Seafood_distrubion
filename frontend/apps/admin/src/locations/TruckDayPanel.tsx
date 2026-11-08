import {
  useListFleetAlerts,
  assignTruck,
  type Truck,
  type TruckAssignment,
  unassignTruck,
  useListMembers,
  useListTruckAssignments,
  useListTrucks,
} from "@frutti/api";
import { useTranslation } from "@frutti/i18n";
import {
  Card,
  Field,
  Input,
  Pill,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  Td,
  Th,
  toast,
} from "@frutti/ui";
import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { truckStates } from "../fleet/shared";
import { fieldErrors } from "../lib/errors";

// Radix Select cannot hold an empty value: this one stands for "nobody assigned" (the usual driver, if any, drives it).
const NOBODY = "none";
// The truck is left free that day, even for its usual driver.
const FREE = "free";

/** Today's date in the browser, as the `YYYY-MM-DD` the date input and the API use. */
function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function refreshAssignments(queryClient: QueryClient) {
  return queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && query.queryKey[0].startsWith("/api/v1/truck-assignments"),
  });
}

/** One truck of the day, one driver (D-046). Owners and managers set it; the server enforces the rules. */
export function TruckDayPanel({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const dateId = useId();
  const [date, setDate] = useState(todayIso);
  const [failure, setFailure] = useState<string | null>(null);
  // A truck with maintenance or papers soon or late carries its badge (P10-T05, D-295).
  const states = truckStates(useListFleetAlerts().data);

  const trucks = useListTrucks({ status: "active" });
  const members = useListMembers();
  const assignments = useListTruckAssignments({ date });

  const drivers = (members.data ?? []).filter((member) => member.role === "driver" && member.is_active);
  const rows = assignments.data ?? [];
  const ofTruck = new Map<number, TruckAssignment>(rows.map((row) => [row.truck_id, row]));
  const truckOfDriver = new Map<number, string>(
    rows.flatMap((row) => (row.driver ? [[row.driver.id, row.truck_name] as [number, string]] : [])),
  );

  const change = useMutation({
    mutationFn: async ({ truck, driver }: { truck: Truck; driver: string }) => {
      const current = ofTruck.get(truck.id);
      if (driver === FREE) {
        await assignTruck({ truck: truck.id, free: true, date });
        return;
      }
      if (current) await unassignTruck(current.id);
      if (driver === NOBODY) return;
      try {
        await assignTruck({ truck: truck.id, driver: Number(driver), date });
      } catch (error) {
        // The truck must not end up without its driver because the new choice was refused.
        if (current)
          await assignTruck({
            truck: truck.id,
            ...(current.driver ? { driver: current.driver.id } : { free: true }),
            date,
          });
        throw error;
      }
    },
    onSuccess: async (_unused, { driver }) => {
      setFailure(null);
      toast.success(
        t(
          driver === NOBODY
            ? "admin.truckDay.removed"
            : driver === FREE
              ? "admin.truckDay.freed"
              : "admin.truckDay.assigned",
        ),
      );
      await refreshAssignments(queryClient);
    },
    onError: async (error) => {
      const fromServer = fieldErrors(error);
      setFailure(fromServer.driver ?? fromServer.truck ?? fromServer.detail ?? t("admin.truckDay.error"));
      await refreshAssignments(queryClient);
    },
  });

  const list = trucks.data ?? [];

  return (
    <section aria-label={t("admin.truckDay.title")} className="flex flex-col gap-3">
      <p className="text-ink-2">{t(canEdit ? "admin.truckDay.intro" : "admin.truckDay.readOnly")}</p>
      <div className="max-w-[220px]">
        <Field label={t("admin.truckDay.date")} htmlFor={dateId}>
          <Input
            id={dateId}
            type="date"
            value={date}
            onChange={(event) => event.target.value && setDate(event.target.value)}
          />
        </Field>
      </div>

      {failure && (
        <p role="alert" className="rounded-chip bg-bad-soft px-3 py-2 text-[0.88rem] font-semibold text-bad">
          {failure}
        </p>
      )}

      {list.length === 0 ? (
        <p className="text-ink-2">{t("admin.truckDay.noTrucks")}</p>
      ) : (
        <Card className="p-2">
          <Table>
            <thead>
              <tr>
                <Th>{t("admin.truckDay.truck")}</Th>
                <Th>{t("admin.locations.form.driver")}</Th>
              </tr>
            </thead>
            <tbody>
              {list.map((truck) => {
                const assignment = ofTruck.get(truck.id);
                const value = assignment ? (assignment.driver ? String(assignment.driver.id) : FREE) : NOBODY;
                const unavailable = truck.condition !== "ok";
                return (
                  <tr key={truck.id} className={unavailable ? "bg-bad-soft" : undefined}>
                    <Td>
                      <span className="font-semibold">{truck.name}</span>{" "}
                      <span className="num text-[0.82rem] text-ink-2">{truck.plate}</span>
                      {states.has(truck.id) && (
                        <Pill tone={states.get(truck.id) === "late" ? "bad" : "warn"} className="ms-2">
                          {t(`admin.fleet.badge.${states.get(truck.id) ?? "soon"}`)}
                        </Pill>
                      )}
                      {unavailable && (
                        <Pill tone="bad" className="ms-2">
                          {t(`admin.locations.conditions.${truck.condition}`)}
                        </Pill>
                      )}
                    </Td>
                    <Td>
                      <Select
                        value={value}
                        disabled={!canEdit || change.isPending || unavailable}
                        onValueChange={(driver) => change.mutate({ truck, driver })}
                      >
                        <SelectTrigger aria-label={t("admin.truckDay.driverOf", { truck: truck.name })}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NOBODY}>
                            {truck.driver
                              ? t("admin.truckDay.usual", { name: truck.driver.name })
                              : t("admin.truckDay.nobody")}
                          </SelectItem>
                          <SelectItem value={FREE}>{t("admin.truckDay.free")}</SelectItem>
                          {drivers.map(({ user }) => {
                            const fullName = `${user.first_name} ${user.last_name}`.trim() || user.username;
                            const elsewhere = truckOfDriver.get(user.id);
                            const onThisTruck = assignment?.driver?.id === user.id;
                            return (
                              <SelectItem key={user.id} value={String(user.id)}>
                                {elsewhere && !onThisTruck
                                  ? t("admin.truckDay.busyOn", { name: fullName, truck: elsewhere })
                                  : fullName}
                              </SelectItem>
                            );
                          })}
                        </SelectContent>
                      </Select>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </Card>
      )}
    </section>
  );
}
