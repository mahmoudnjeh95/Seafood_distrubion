# Project status

_Last updated: 2026-10-19 (quote → sale: payment on the spot in "Convertir en vente", D-190)_

## Where we are

- **P3-T16c/d (branch receipt-pay-now, 2026-10-20):** driver purchase screen, office check page and the office receipt form ("Nouvelle réception", only with "Dû dès la réception") ask "Qu'avez-vous donné maintenant ?" (Rien / Une partie / Tout) with a live "Total · Donné · Reste → à définir par le bureau" (D-192). `POST /receipts` takes `payments`. API client regenerated. Awaits CI.
- **D-192 / P3-T16a (branch supplier-settlements, 2026-10-20):** backend of "Règlements fournisseurs" done: `SupplierPaymentPlanLine`,
  `PUT /supplier-invoices/<id>/plan`, `DELETE /supplier-plan-lines/<id>`, `GET /supplier-settlements`, `plan_line` on the payment, dashboard
  `settlements_undefined_late`; API client regenerated. Merged.
- **D-192 / P3-T16b (branch supplier-settlements-ui, 2026-10-20):** office page Achats › "Règlements" (`/achats/reglements`: summary, 4 tabs with counts,
  type and supplier filters, plan lines inline, "Définir le règlement" dialog, "Enregistrer le paiement" opens the payment form prefilled with the
  plan line, "Annuler la ligne"), dashboard alert `settlements_undefined_late`. French only (the admin app has no Arabic keys). Awaits CI.
  **T16c/d done (paying steps).**
- **D-191 (branch fix/finance-review-calculations, 2026-10-19):** finance review of the calculations. Fixed: a general cost
  (rent, insurance) is spread over the calendar days of its month, so a lot in stock all month carries the bill once (it
  carried 30/26 or 31/26 before); kg-days rounded to the gram; the partner-capital docstring corrected. **Provisional**
  (owner to confirm the day rule). Not changed, owner decisions: employer CNSS in the lot cost of employee days, settlement
  of a carried negative balance, cash-flow basis, and a cancelled paid sale in the cash flow. Awaits CI.
- **D-190 (branch quote-convert-payment, 2026-10-19):** "Convertir en vente" on an accepted quote has the payment block
  of the sale form: "Payé en entier" (on for "Client de passage"), amount, method, reference. Before, a walk-in BL
  could not be confirmed and the window had no field to fix it. The API client is regenerated (`is_walk_in` on the
  quote customer). Awaits CI.
- **D-189 (branch ui-polish-units, 2026-10-19):** UI review of both apps. Units no longer shown twice ("DT DT" on the
  dashboard, "kg kg" on the driver's day), dashboard month in French, empty screens stack on a phone, long product
  names wrap on the driver's Vente screen. Awaits CI. Follow-up: one back link per detail page (D-189).
- **D-188 (PR #201, branch web-request-quote, 2026-10-19):** on a site request, the "Suivi du bureau" card is the first
  card and its buttons sit above the note. "Créer un devis" opens the quote in the D-138 window, with the visitor's
  products and kilos already in (price proposed as usual, customer picked by the office). Awaits CI, then check on staging.
- **Product cards (branch site-card-alignment, 2026-10-19):** the public site's product cards are now all the same
  height in a row: the grid stretches them (it used to top-align, so cards were ragged), the name block reserves two
  lines so prices line up, and the quantity and Add button sit at the bottom of every card. Awaits CI.
- **D-186 (merged in PR #198):** a public, animated site (`frontend/apps/site`, :5175; Artlist video and
  photos): catalogue with web prices, basket, order or quote request with a **required phone number**. The office gets
  a bell notification and handles requests in "Site web → Demandes du site". **Every active product shows with its
  photo and the company logo**; "Site web → Produits du site" hides products, orders them and sets a **web-only
  price** (the day's price never changes);
  "Paramètres du site" sets the **phone** (and WhatsApp, e-mail, address, hours) the site shows. Domain
  **https://www.fruttidelmare.com** (bare name redirects; certificate expanded by the deploy). Product cards are
  compact: 5 to 6 per row on a desktop, 2 on a phone, smaller photo and tighter rows (owner, 2026-10-19). Awaits CI.
- **D-185 (on main, #189):** a driver's day (Suivi des chauffeurs, closing) counts the load BLs delivered (sales, cash
  at the door, kg "Vendu" in "Marchandise du camion"); delivering sets `sold_at` to the delivery moment. The owner saw
  the old gap again on 2026-10-18 (4/4 delivered, "Vendu" 0 kg, "Reste" right) on a build without it. Check on staging.
- **D-184 (on main, #196):** the driver's "Vente" tab shows only "Le camion est vide" when nothing is left on the
  truck, no client list. Check on staging with a driver whose truck is empty.
- **D-182 (on main, #192):** cash given at the port beyond the purchase money is split into "payé avec l'argent des
  ventes" and "avancé de sa poche", never both; old sent days are corrected by migration. Check on staging.
- **Wide closing dialog (on main, #191):** the closing window of Journées des chauffeurs › Clôtures is 1 100 px wide,
  so the stock table fits without a side scroll bar. Check on staging.
- **D-183 (on main, #194):** in "Nouvelle réception" the product cell is an empty box: typing a code,
  name, Arabic name or category lists the matching products, as in a quote or a sale. Check on staging.
_Last updated: 2026-10-18 (Caisses page: "Bilan des caisses", whose boxes are whose, D-187)_

## Where we are

- **D-187 (branch box-summary):** Stock › Caisses opens with a "Bilan des caisses": per box type, in hand, at clients
  (to collect), owed to suppliers (to give back) and ours; each list has a one-line note. Awaits CI.
- **D-184 (branch sale-empty-truck):** the driver's "Vente" tab shows only "Le camion est vide" when nothing is left
  on the truck, no client list. Awaits CI, then check on staging with a driver whose truck is empty.
- **D-185 (branch day-figures-load-bl):** a driver's day (Suivi des chauffeurs, closing) now counts the load BLs
  delivered (sales, cash at the door, kg sold); delivering sets `sold_at` to the delivery moment. Awaits CI.
- **D-182 (branch purchase-cash-split):** cash given at the port beyond the purchase money is split into "payé avec
  l'argent des ventes" and "avancé de sa poche", never both; old sent days are corrected by migration. Awaits CI.
- **Branch wide-closing-dialog:** the closing window of Journées des chauffeurs › Clôtures is 1 100 px wide, so the stock table fits without a side scroll bar. Awaits CI, then check on staging.
- **D-183 (branch receipt-product-search):** in "Nouvelle réception" the product cell is an empty box: typing a code,
  name, Arabic name or category lists the matching products, as in a quote or a sale. Awaits CI, then check on staging.
- **D-181 (branch field-purchase-paid-limit):** a port purchase whose sums given exceed its amount is refused (server,
  phone and office form); a lot counted lighter at the office still turns the extra into an advance. Awaits CI.
- **D-180 (on main):** the "Parcours" map and the phone's GPS tracking are switched off (flags, code kept). Check on staging.
- **D-179 (branch money-confirm-popup):** every money action of the driver app (delivery, sale, payment, expense,
  purchase, opening cash and float, closing) opens an "Annuler / Confirmer" window with the amounts. Awaits CI.
  Admin money forms are not converted yet; new money screens must use `ConfirmButton`.
- **P2-T15 / D-178 (branch load-delivery-workflow):** the BL of a load is validated at the load (real BL number, no
  PROVISOIRE), then the driver delivers it in full, in part or not at all from the phone (also offline); only what is
  delivered is sold, the rest stays on the truck; versions, PDF "Commandé / Livré", notifications. Awaits CI.
- **P3-T15 / D-175 (on main):** a bell in both apps; a driver's action notifies the office,
  the office's action notifies the driver, with a tone and a toast (polling every 20 s). Check on staging.
- **Phase 1:** done except P1-T14 (returnable boxes; owner decisions 2–4 are open). **Phase 2:** mostly done.
- **Phase 3:** T01–T07d and T11–T12c are done; open: T08 field test, T09 Arabic review, T10 printing.
- **P2-T13 / D-160:** load parts, draft BL per client, provisional PDF and driver-phone "Mes livraisons" are implemented
  on `load-per-client` / PR #160. CI identified a formatting issue in the corrected test; it is fixed, and CI must pass
  before merge.
- **On main:** D-176/158 cover buying at the port from the office and phone; D-159 covers supplier debts, payments and
  the supplier-paper photo. Staging checks for these and D-156's statement PDF remain.
- **Staging** (D-036, D-155, `docs/runbook.md`): admin http://app.fruttidelmare.com, driver
  http://ch.fruttidelmare.com. Demo logins `owner` / `driver`; password is in `~/frutti-staging/.env` on the server.
  Every merge to `main` deploys staging; check `gh run list`.
- **Plan:** profit per lot shared with partners (D-040); driver's truck chosen per day (D-042). Q21 confirmed; Q24
  (truck-cost split) remains provisional.
- **Working rule (owner, 2026-10-16):** do not run tests locally; commit and let CI check, then fix reported failures.
  One branch and one PR per task; merge only after CI passes.

- **P2-T14 / D-174 (branch transfer-load-grid):** transfer form as a spreadsheet grid per client, "Chambres froides
  (toutes)" as the source, driver "Vente" lists only the load's clients. CI must pass, then check on staging.

## Next step

0. D-190: merge after green CI; on staging accept a quote for "Client de passage", click "Convertir en vente": the
   payment block is there with "Payé en entier" on; "Créer et confirmer" without a method shows "Indiquez le mode de
   paiement" on the field; with a method it confirms. A regular client can pay part now.
0. D-189: merge after green CI; on staging check the dashboard figures (one "DT"), "octobre 2026", and on a phone the
   driver's Ma journée ("… · 31,500 kg") and an empty Livraisons screen (drawing above the text).
0. D-188: merge after green CI; on staging open Site web → Demandes du site, take a request with products, click
   "Créer un devis": the window opens with the products in, the customer is empty; pick one, save; the request page
   stays open. Then accept the quote to create the BL.
0. Product cards (branch site-card-alignment): merge after green CI, then on https://www.fruttidelmare.com check that
   the cards in a row are the same height, prices line up, and the quantity buttons still work.
0. D-186 (PR #198, merged): **live on https://www.fruttidelmare.com** (2026-10-19: certificate holds www and the
   bare name, 41 products with 40 photos, logo; in the uptime watch). Owner, in the admin app: type the phone in
   "Site web → Paramètres du site", set web prices and hide what should not show in "Produits du site", move the
   products out of "À classer"; then send a test order with a wrong then a right phone and see the bell and
   "Demandes du site". Ask the owner to read the page's texts (D-186, provisional).
0. D-183: on staging open Achats → Nouvelle réception, type "dor" in the product cell, take
0. D-187: merge after green CI; on staging open Stock › Caisses: with the demo data, "À nous" shows 50 small and
   50 big (the opening stock), and "Aux fournisseurs (à rendre)" equals the Fournisseurs list added up.
0. D-183: merge after green CI; on staging open Achats → Nouvelle réception, type "dor" in the product cell, take
   "Dorade royale" with Enter: the cursor moves to the next weight and the last cost appears.
0. D-181: merge after green CI; on staging, on the phone type more cash than the total (the "Envoyer" button stays off
   with a red line), and on the office check page lower a price below what was given (error on the last payment).
   Open owner questions from the same review: what a refused purchase does with cash already paid at the port, and
   whether a big gap between the driver's kg and the kg received should warn or block.
0. D-179: merge after green CI; on staging with a phone, check each money button opens the window and "Annuler" sends
   nothing. Then ask the owner whether the admin app's money forms need the same window.
0. P2-T15: merge after green CI; on staging, load two clients, print both BLs (no PROVISOIRE), on the phone deliver one
   in part (one product at zero) and mark the other "Non livré"; check the truck stock, the client balance, the bell, and
   reprint the corrected BL ("Commandé / Livré", version 2).
0. P3-T15: merge after green CI; on staging, log in as `driver` on a phone and `owner` on a PC: start the day / sell →
   the office bell rings; validate a load → the phone rings. Tune the 20 s poll if it is too slow or too heavy.
1. Push the CI fixes for PR #160, wait for green CI, then merge. After deployment, check a load with two clients on
   staging: change one address, validate, print both provisional BLs, confirm one, and verify the driver's "Mes livraisons".
2. Check D-159 on staging (overdue invoice, cheque cashing day, receipt owed at once, monthly supplier statement and
   supplier-paper photo); check D-158 with a real phone (port purchase, office decision notice and closing money).
3. Check D-156's customer and supplier statement PDFs by eye.
4. Phase 3 order: P3-T10 printing spike (real Android/iPhone and printer), P3-T09 Arabic and RTL review, P3-T08
   one-week field test. P3-T14 (D-171) gets a phone check on staging before the field test.

## Open owner decisions

- Backups: configure off-site storage and move the private key to a password manager and USB key (D-139).
- Boxes: opening balances already at clients or owed to suppliers, and a screen for real opening stock (D-135).
- Driver day: exact cash handover on the first send; warning before a load reopens an approved day (D-134).
- Confirm the 24-hour stale-price window (D-150), archived-record dropdown behavior (D-145), and whether approved
  electricity bills under the daily rule are recalculated (D-142).

## Blockers / watch out

- P0-T02: only one real lot has been worked out with the owner; Phase 6 has no target without it. P0-T01: no prototype
  walk-through or client materials yet.
- DNS records and the certificate for `app.` and `ch.` remain owner actions (D-155); Sentry DSN is also pending (D-140).
- TTN / El Fatoora is on hold (D-016). Accountant confirmation is needed for VAT exemptions and e-invoicing; CNSS
  employee rate remains provisional (D-119, Q26).
- Staging VPS is shared: touch only `frutti-staging`; run `sudo nginx -t` before reload; never prune Docker.
- Keep generated API files in sync (`make gen-api` after serializer/endpoint changes); preserve each branch's i18n keys.
- CI stays pinned to `ubuntu-24.04` (#115); move off it deliberately before the hosted image changes on 2026-10-19.
