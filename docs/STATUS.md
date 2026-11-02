# Project status

_Last updated: 2026-11-02 (receipt corrections are not spoilage, D-270, PR open; next free decision D-271)_

## Where we are

- **P3-T10 printing (D-278, branch `driver-receipt-printing`, awaits CI):** "Imprimer le reçu" on the driver's sale receipt and "Mes achats", 58/75/80 mm setting, office copy, ESC/POS over Web Bluetooth. **Blocker:** the Digipos DPP-58 did not show in an iPhone BLE scanner, so it is likely classic Bluetooth: next step is the Android scan test (Serial Bluetooth Terminal); if classic, wrap the app with Capacitor or change printer.

- **P9-T10 finished (D-256, branch `bl-gap-finish`, awaits CI):** "TTC" button on a BL line of Nouveau règlement (pay up to
  goods + estimated VAT and stamp), owner-only "Abandonner l'écart" on a partly paid invoice (lots picked, typed amount,
  recorded with the invoice), statement PDF line and BL-screen estimate. Check on staging: pay a BL 250,900 with TTC, invoice
  it with VAT, it reads Payée; pay another at its goods, invoice, give up the gap as owner.

- **PM follow-up 2026-11-02 (D-270, P1-T17, branch `receipt-correction-kind`, PR open):** a goods receipt's correction is its own
  movement kind, so it counts in the kg received and the purchases, not in spoilage. Hand-made adjustments are unchanged.
- **Owner request 2026-11-02 (D-269, P1-T16, branch `receipt-edit-revisions`, PR open):** a goods receipt (BR) can be
  changed after saving while no invoice carries it: supplier reference, notes, VAT, and each line's weights, cost and
  use-by date. A weight change posts an adjustment; cost and VAT lock once something valued has left the lot. Every change
  is a revision with a reason; the BR page shows "Modifier" and the history.
- **D-268 (owner request 2026-11-02, branch `receipt-no-auto-invoice`, PR awaits CI):** the office receipt form no longer makes a supplier invoice ("Dû dès la réception" removed, D-159 superseded for it). The BR detail page has "Créer la facture" with the BR preselected. Money given at the reception is an advance the invoice takes. Check on staging: a new BR shows "Pas encore facturée" with the link; the link opens the invoice form with the BR ticked.
- **P9-T10 (D-256, branch `bl-invoice-gap`, awaits CI):** a BL paid at its goods and invoiced later no longer looks silently
  paid. Estimate of the invoice (`GET /invoices/estimate`, `estimated_extra` on open BL), invoice `payment_state` /
  `paid_total` / `extra_over_goods`, filter and pill on Factures, gap banner with a link to a new règlement. Not done:
  "Régler TTC" and a per-invoice give-up (see the phase file). Timbre exemption per customer: none, ask the accountant.
  Check on staging: pay a BL at its goods, invoice it with VAT, the invoice reads "Payée en partie".

- **D-259 (2026-11-02, provisional, PR open):** the driver's "Fonds de caisse" and "Argent pour les achats" for the day go
  back to 0 when the office approves the day, not when the driver sends it (changes D-242). A new load on an approved day
  does not bring them back.

- **D-257 (2026-11-02, branch `lot-split-writeoff`):** clearing a customer or supplier balance to zero now asks which
  lots it goes on ("Sur quels lots ?", amounts adding up to the balance). The loss (customer) or gain (supplier) changes
  those lots' result and the partner's share; settled lots are not offered. Check on staging: clear a small customer
  balance onto one lot and see the line "Soldes clients remis à zéro (perte)" in that lot's result.
- **Sales, 2026-11-02, D-245 (branch `sales-no-payment`, PR #284, awaits CI):** the office's sale forms, "Vente comptoir" and "Convertir en vente" show no payment; an office sale is unpaid and the office API refuses a payment. The treasurer takes it in Règlements clients, the walk-in customer included (provisional change of D-047). The driver's phone is unchanged. The sale detail links "Encaisser au trésorier" while something is owed.
- **D-246 (2026-11-02, PR #283, provisional):** a new invoice's "Facture avec TVA" starts unchecked and is
  checked only when a BL holds goods bought with VAT. Regenerated the API client. Check on staging: a new invoice
  from a BL without VAT-bought goods opens with the box unchecked.
- **Primes are paid when added (D-244, owner request 2026-11-02, PR #282).** The prime form asks for a payment method and
  date; the payment is a salary payment of kind `prime` and writes its treasury movement ("Prime : <name>"), so the
  treasurer's journal shows it. Primes added before this change have no payment (see D-244 provisional).
- **Owner request 2026-11-02, P1-T15 (D-247, PR #280, awaits merge):** "Ajuster le stock" on the product page adds or
  removes kilos of a lot at a place, with a reason (`adjustment` movement, `POST /stock/adjustments`, owner and manager).
  The average purchase price is worked out again from the stock on hand; the success message shows it before and after.
- **D-242 (2026-11-02, PR open, provisional):** sending a driver's closing resets that driver's "Fonds de caisse" and
  "Argent pour les achats" for the day to 0 (`fleet.services.end_driver_day`). The day's own figures stay. Check on staging:
  Camions du jour › Fonds de caisse after a closing is sent shows 0 for that driver.
- **Owner request 2026-11-02, D-243 (branch `partner-capital-advance`, awaits CI):** in a lot's "Partenariat" section the
  owner can give the partner an advance from the capital they put in ("Donner une avance"): `ADVANCE` entry on the capital
  ledger with the means and reference, up to the capital still in, while the lot is open or closed. The settlement pays
  the rest. The money is a treasury movement the day it is paid (as settlements, D-240).

- **2026-11-02, D-241 (merged, PR #276):** the side menu's Banques became **Trésorier** (opens Encaissement);
  Règlements clients, Règlements fournisseurs and Portefeuille left the menu, the treasury ribbon links them.
- **D-261 (branch `treasury-highlight`, awaits CI):** Trésorier stays lit on every treasury ribbon screen (nav items
  can own more paths, `owns`).

- **2026-11-02, D-260 (branch `driver-purchase-approval`, awaits CI):** a change of the purchase money during a running day
  is a proposal the driver approves on the phone ("J'accepte ce montant"); until then the amount in force stays. Changes D-248.
  Check on staging: Camions du jour › Fonds de caisse on a started day shows "En attente du chauffeur"; the phone's day screen
  shows the proposal with the accept button; after approval the amount changes.
- **All PRs merged, none open (2026-11-01).** On main and staging since 2026-10-31: D-208 to D-236, among them D-220 driver's
  day corrected by the office only, D-221 amount separators, D-222 e-mail addresses, D-223 numbering and prefixes, D-224 VAT
  on the BL, D-225 and D-226 règlement motif and "Total à régler" (a customer payment is now the règlement page), D-227
  cold-room estimate, D-228 salaries approved when generated, D-231 several lots on a transfer, D-234 salary payments,
  primes and advances in the treasury, D-235 party counts in the règlement lists, D-236 bank details.
- **CI and deploy fixes:** the month-start test failures (#256), build heap 1536 MB on the VPS (#261).
- **SmartFeesh:** `SmartToolsAgro/SmartFeesh` is pushed only when the owner says "push main" (D-209). It is at #234.
- **D-252 on branch `customer-supplier-write-off` (awaits CI):** "Remettre le solde à zéro" for a customer (owner; the rest
  is a loss on the customer, shown on the account) and for a supplier (owner; a gain on the supplier). Two steps: the
  reason, then the exact balance typed again. Provisional: the loss does not yet change the profit per lot (open question).
  Check on staging: customer card › Remettre le solde à zéro, then the supplier card.
- **Phase 9 · Règlements & Trésorerie (D-197, owner request 2026-10-31)** — plan in `docs/phases/09-treasury.md`.
  **Merged on main:** T01 (#223) customer règlement lines and the `treasury` app · T02 (#231) supplier lines, our effets
  issued · T03a (#234) "Nouveau règlement", Répartir, Banques · T03b (#237) lists, detail pages, supplier void · T03c
  (#240) supplier receipt PDF, several plan lines at once · T04a (#241) Portefeuille, remise en banque, encaissé,
  retirer, débité · T04b (#242) impayé, Restituer · T04c (#243, D-218) our effet rejected by the bank.
- **P9-T08 merged (#259, D-230; #260 forms and CSV export, D-232):** the Perfaxis layout: a ribbon of icon buttons on
  every treasury screen (`TresorerieRibbon`), the Bordereau de versement, the états des factures, the forms in panels.
- **P9-T05a merged (#246, D-219):** the accounts and the movement ledger. The ribbon now has Agence bancaire, Caisse
  liquide and the two journals (#262, D-233).
- **Other work on main (other sessions):** D-214 port purchases on the truck and the day (#245), D-213 the office alone
  counts the driver's cash, D-212 counter sale on several lots, D-194 to D-207 owner list.
- **Phases:** 1 done except P1-T14 owner decisions; 2 mostly done; 3: open T08 field test, T09 Arabic review,
  T10 printing; 9 in progress (T05 to T07 left, plus T08 review).
- **Staging** (D-036, D-155, `docs/runbook.md`): admin http://app.fruttidelmare.com, driver http://ch.fruttidelmare.com,
  demo logins `owner` / `driver` (password in `~/frutti-staging/.env`). Every merge to `main` deploys staging.
- **Working rules:** no tests or e2e locally, CI checks the PR; one branch and one PR per task; merge only after green.
  Several sessions work at once; recheck decision and migration numbers right before merging.

## Next step

0. P1-T17 (D-270): merge the PR once green. On staging: correct a receipt from 100 to 90 kg; the lot result shows 90 kg received and no spoilage.
0. P1-T16 (D-269): merge the PR once green. On staging: a receipt with an accepted weight and a cost change, then Prix du jour and the stock page.
0. **D-249 (`day-office-checks`, PR #278):** merge once green. On staging, Suivi des chauffeurs or Clôtures à vérifier: refuse a driver expense (reason), validate a port purchase (its kilos enter the truck), then "Remettre le camion en stock" and approve the day.
0. D-243: open the PR from `partner-capital-advance`, wait for green CI, merge. On staging: a lot with a partner, "Donner une
   avance" for part of the capital, check the ledger line and the remaining capital, then settle the lot.
0. P1-T15 (#280): merge once green. On staging: a product, "Ajuster le stock", add 10 kg to a lot then remove it; the average on the product page and on Prix du jour moves.
1. Owner: check on staging the merged points above, first a customer payment from the card ("Enregistrer un règlement"
   opens the règlement page, "Total à régler" shows) and a salary payment ("Débité de la trésorerie").
2. P9-T05b: expenses paid, sales paid on the spot, partner settlements, port purchases and the driver's approved day post
   to the ledger; salaries are done (D-234). Then T05c, the Comptes page and "Compte" in the forms.
3. Then T06 échéancier and alerts, T07 reports. New decisions start at D-244.
   Withholding rule D-250 (PR #277, awaits CI): retenue à la source on invoices of 1 000 DT TTC and more, none below;
   check on staging with a rate set in Paramètres financiers.
4. **Owner action for D-206:** the company SMTP account in the server `.env`, then redeploy.

## Open owner decisions

- D-234 (provisional): an advance above the month's due needs a confirmation. Primes are not subject to CNSS (owner, D-263).
- Q29 (D-197, provisional): invoice paid when the effet is received or when cashed; the company's bank accounts; bank
  charges of an impayé; endorsing customer traites to suppliers.
- Backups off-site and the private key (D-139); boxes opening balances (D-135); driver day cash handover (D-134);
  24-hour stale-price window (D-150), archived-record dropdowns (D-145), electricity bills (D-142); D-191 day rule.

## Blockers / watch out

- P0-T02: only one real lot worked out with the owner; P0-T01: no prototype walk-through yet.
- DNS and certificate for `app.` and `ch.` and the Sentry DSN remain owner actions (D-155, D-140).
- TTN / El Fatoora on hold (D-016); VAT exemptions and the CNSS employee rate need the accountant (D-119, Q26).
- Staging VPS is shared: touch only `frutti-staging`; `sudo nginx -t` before reload; never prune Docker.
- Keep generated API files in sync (`make gen-api`); preserve each branch's i18n keys when merging.
