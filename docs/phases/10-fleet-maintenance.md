# Phase 10 · Flotte & entretien (D-295)

_Owner request of 2026-11-08._ Keep the trucks and the cold rooms running and their papers valid: the
compteur (odometer) the driver types each evening drives the km-based maintenance (vidange, filtres…), the frigo
units and the cold rooms have a monthly service, and the papers of each truck and each person warn before they
expire. There is no GPS for the km: the driver types the compteur.

Order: T01 → T05. One branch and one PR per task. New app `apps.maintenance` (uses `fleet`, `hr`, `expenses` and
`notifications` through their services and selectors only).

## Owner answers (2026-11-08)

| # | Question | Answer |
|---|---|---|
| 1 | Compteur | The driver types it **at the end of the day** (when he sends his day). The office is warned, and a truck that needs maintenance shows a warning **badge on its truck icon**. |
| 2 | Photo of the compteur | **Optional.** |
| 3 | Maintenance plans | "Every X km or Y months, whichever comes first". Every interval and warning threshold is a **setting** (Paramètres entretien), nothing hard-coded. |
| 4 | Frigo | A **monthly** service, for the **truck units and the company's cold rooms**. **No temperature readings.** |
| 5 | Papers | Truck: assurance, vignette, visite technique, frigo certificate (engin isotherme / ATP), extincteur. Person: permis, certificat médical, carnet sanitaire. **No carte grise, no CIN.** Warnings at 30, 15, 7 days and on the day. |
| 5b | Expired assurance or visite technique | The truck **cannot be assigned**; the **owner can allow one day with a reason** (kept in the history). |
| 6 | Costs | Expenses tied to the truck, **general overhead**: not charged to the lots, partners' results unchanged. |
| 7 | Who is warned | **Owner and manager**; each driver sees his own truck and papers on the phone. |

Tunisian rules that set the defaults (intervals stay settings, to confirm with the accountant / ATTT once): RC
assurance is compulsory and often taken for 3, 6 or 12 months; the vignette is yearly with a deadline set by the
finance law; goods vehicles pass the visite technique (ATTT) about yearly; the isothermal / refrigerated vehicle
certificate (ATP) has its own validity; food handlers renew their health certificate about yearly; a permis C needs a
medical renewal.

## Rules that hold in every task

- Readings and maintenance records are **append-only**: a wrong one is corrected by a new record with a reason.
- Writes go through `apps.maintenance.services` inside a transaction; permissions are checked on the server. Drivers
  write only their own truck's compteur and see only their own truck and papers.
- Costs are expenses (category "Entretien camion" / "Papiers camion"), tied to the truck, general overhead (answer 6).
- Every business table has `organization`; audit on create and correction.

## Tasks

### P10-T01 · Compteur readings

- [x] App `apps.maintenance`: `OdometerReading` (truck, driver day, km, source driver/office, photo, note, warning),
      `MaintenanceSettings` (one per organization; `max_day_km`, default 600).
- [x] Driver: `GET/POST /my-day/odometer` (multipart, optional photo). Refused below the truck's last reading, and on
      a day already sent. A jump above `max_day_km` × days since the last reading is kept with a warning and the office
      is told (notification `odometer.jump`).
- [x] Phone: the "Clôture" screen asks the compteur (required in the screen, optional photo) and records it just
      before sending the day. The history's earlier days do not ask it.
- [x] Office: `GET /fleet/odometer` (each truck's last reading), `GET/POST /trucks/{id}/odometer-readings` (list,
      correction with a reason, may be lower), the photo, `GET/PATCH /maintenance-settings` (`max_day_km`).
- [x] Admin: new menu entry **Flotte & entretien** (`/flotte`): trucks with their last compteur, the readings of a
      truck with photos and warnings, "Corriger le compteur", and the setting.
- Not done here: the server does not refuse a closing without a compteur (old phones, a broken compteur); the office
  sees which days have none. Revisit once every phone runs the new version.

### P10-T02 · Paramètres entretien and maintenance plans

- [x] Maintenance types per organization (vidange, filtres, freins, pneus, courroie, batterie…) with default
      interval in km and/or months and warning thresholds (km and days before), all editable.
- [x] Plan per truck (a type, its own interval if different, the last done km and date).
- [x] "Entretien effectué": date, compteur, garage, cost, note → reschedules the next one; the cost becomes an
      expense tied to the truck (general overhead).
- [x] Status per plan: ok / bientôt (orange) / en retard (red), from the last reading and the average km per day.

### P10-T03 · Frigo maintenance (trucks and cold rooms)

- [x] Same plans for the truck frigo units and the company's cold rooms (`inventory.StockLocation` of kind cold
      room), counted in months only (monthly by default). No temperature readings (answer 4).
- Done as: `MaintenanceType` (target truck / frigo / cold_room, `every_km`, `every_months`, `warn_km`, `warn_days`),
  `MaintenancePlan` (on a truck or a cold room, own interval, last done), `MaintenanceRecord` (append-only). The
  suggested types come with "Ajouter les entretiens conseillés". A cost is an approved expense of the new default
  category "Entretien et papiers des camions" (`vehicles`), or "Froid et stockage" for a cold room, **without** the
  truck tag (a truck-tagged expense is a truck cost of the day, split over the lots, D-041).

### P10-T04 · Papers with expiry dates

- [ ] Truck papers: assurance, vignette, visite technique, certificat engin frigorifique, extincteur. Person papers
      (on `hr.Employee`): permis, certificat médical, carnet sanitaire. Number, issue and expiry date, scan, cost.
- [ ] Warnings at 30, 15, 7 days and on the day (thresholds in the settings).
- [ ] Expired assurance or visite technique: `fleet.assign_truck` refuses the truck; the owner allows one day with a
      reason (recorded, audited).
- [ ] Renewal cost → expense tied to the truck (general overhead).

### P10-T05 · Warnings everywhere

- [ ] Notifications to owner and manager when a plan turns orange or red and when a paper reaches a threshold
      (once per threshold, a daily task).
- [ ] Badge on the truck icon (orange / red) in the admin lists and on "Camions du jour"; "Flotte & conformité"
      overview (per truck and per person, green / orange / red, what falls due this month).
- [ ] Phone: the driver sees his own truck's warnings and his own papers.
