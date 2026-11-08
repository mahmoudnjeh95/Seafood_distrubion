# Project status

_Last updated: 2026-11-08 (accounting review P2-T20, D-291 to D-294, #331; training copy D-290, #330; Perfaxis gaps and client bug list merged #323–#329; next free decision D-295)_

## Where we are

- **P2-T20 accounting review (D-291, branch `claude/awesome-albattani-r48y7b`, merged 2026-11-08 (#331)):** review in
  `docs/guides/accounting-review-2026-11-08.md` (bugs B1 to B11, missing Tunisian obligations, finance UX). Fixed:
  an invoice's lines take the VAT rate their BL showed (goods not bought with VAT stay exempt on a mixed invoice, B2),
  and the 1 000 DT withholding threshold leaves out the stamp and fees (B3). Check on staging: one BL with a product
  bought with VAT and one without; its invoice taxes only the first and equals the BL TTC + 1 DT stamp.
  B4 (D-292, migration `partners 0006`): "Soumis à la retenue à la source" on the customer (on by default); off, the
  customer's invoices carry none. Check: untick it on a customer, invoice 1 200 DT, net to pay = TTC.
  B5 (D-293): a lot's revenue is without VAT also when prices include VAT.
  B1 (D-294, migration `purchasing 0025`): a supplier invoice owes HT + VAT of the receipts bought with VAT + stamp.
  Check: a receipt "Achat avec TVA" of 1 000 DT, its invoice shows TVA 190, timbre 1, total 1 191 to pay.
- **D-290 training copy (owner request 2026-11-08, branch `claude/charming-cori-q7fqcg`, merged 2026-11-08 (#330)):** same stack on
  `app1.fruttidelmare.com` / `ch1.fruttidelmare.com`, only the database apart (`frutti_training`, services
  `training-backend`/`training-worker` in `compose.staging.yml`), "Formation" tag on screen only, papers identical to
  the real ones, reset by hand with `reset-training.sh` (runbook "Training copy"). Next: owner adds the DNS records
  (`app1`, `ch1` → 217.182.205.137), then run `~/frutti-training/bin/reset-training.sh --apply` once and
  check the tag, a PDF and a driver receipt on app1/ch1.

- **Perfaxis gaps (owner answers 2026-11-07, D-285):** the owner compared the Perfaxis Achat/Vente/Avoir manual and kept
  five gaps, built one PR each, stacked on `credit-note-refunds`: (1) **P1-T18 contested goods receipt** (branch
  `receipt-dispute`, migration purchasing 0023): "Contester" with a motif, no supplier invoice takes it until "Lever la
  contestation"; (2) **P2-T17 BL "non facturable" or "offert"** (branch `bl-billing`, migration sales 0034, D-286):
  owed but never invoiced, or given away at 100 % discount; (3) **P2-T18 "Refacturer"** (branch `rebill-credit-note`,
  migration sales 0035, D-287): a draft from a full credit note that took no goods back; (4) **P2-T19 attachments** (branch `document-attachments`,
  migration documents 0007, D-288): "Documents associés" on quotes, BL, invoices, purchase orders, receipts, supplier
  invoices; (5) **P1-T19 supplier price requests** (branch `supplier-price-requests`, migration purchasing 0024,
  D-289): Achats › Demandes de prix, offers compared, one order per chosen supplier. Not wanted: Bureau d'ordre, exempt/export
  customers, internal purchase requests, foreign currency, services.

- **D-284 (branch `credit-note-refunds`, stacked on #323, migrations sales 0033, treasury 0008):** an avoir asks, per line
  with kilos, remis en stock / mis en perte / non repris; when the invoice was paid it asks "Rembourser maintenant"
  (caisse or bank) or "À rembourser plus tard". Debt first, then refund. Trésorerie › Remboursements clients lists and
  pays them. Check on staging: pay an invoice, avoir partiel with one line back in stock and one in loss, refund later,
  then pay it from Remboursements clients and see the caisse journal.

- **P2-T16 / D-283 (client document "13 bugs avec captures", branch `claude/jolly-feynman-76x5xb`, migrations core 0007,
  partners 0005, catalog 0007, sales 0032, purchasing 0022):** done 01 net price column, 02 "Bons de livraison" wording,
  03 "— n BL" per client in Nouvelle facture, 07 clients/suppliers sorted by Réf., 08 Paramètres › Types de clients,
  09 identification type + number, 10 open the new invoice, 12 Trésorerie › Soldes d'ouverture (OUV out of the BL
  list), 13 draft prefix with its own counter (drafts read BROUILLON-… or BFA-…; definitive number at validation).
  Part of 04: Paramètres › TVA and the product's VAT as a list. **Not done:** 04's document columns/TTC amounts,
  05 and 06 (credit notes with refunds), 11 (one delivery cycle for every BL): they need owner decisions (D-283).

- **D-281 (owner request 2026-11-03, branch `claude/serene-gates-6iaad1`, migration `fleet 0010`):** driver receipts
  print one copy per tap (client/supplier, then "COPIE BUREAU"), with the seller's address, phone and MF
  (`my-receipt-header`), a Qté/Prix/Montant table and "Préparé par". A delivered BL stays on screen with its receipt;
  today's delivered BL are listed again (`my-deliveries/done`) in Mes livraisons and on the sale screen. A new load on a
  sent day locks the phone to Ma journée until "Je confirme la reprise" (`my-day/resume`); the server refuses the rest
  meanwhile. Check on staging (Android): deliver a BL, print twice; send the day, reload the truck, the tabs grey out.
- **D-282 (same branch):** the receipt prints as a picture (canvas → ESC/POS raster): logo at the top, each product's
  Arabic name under the French one, the rest in French; "Imprimer en image" off = old text mode. The driver app's
  Arabic is now Tunisian derja (provisional, native review in P3-T09). Check on the real printer: speed and darkness.
- **P3-T10 print after confirmation (D-278 addendum, branch `claude/practical-allen-66nje7`):** "Imprimer le reçu" on the
  purchase confirmation (sent, kept offline or changed) and on a sale kept on the phone ("Provisoire" receipt). Check on
  staging (Android, Chrome): send a purchase, the summary shows the button; in airplane mode save a sale, print it.
- **P3-T10 printing (D-278, merged #311):** "Imprimer le reçu" on the driver's sale receipt and "Mes achats", 58/75/80 mm setting, office copy, ESC/POS over Web Bluetooth. **Blocker:** the Digipos DPP-58 did not show in an iPhone BLE scanner, so it is likely classic Bluetooth: next step is the Android scan test (Serial Bluetooth Terminal); if classic, wrap the app with Capacitor or change printer.

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

0. P2-T20: merged 2026-11-08 (#331); staging checks above. Then the review's next points (B6 to B9 need the
   owner or the accountant; then the "Déclarations du mois" screen); the accountant answers the "à confirmer" points of the review.
0. Perfaxis gaps and the client bug list: merged 2026-11-08 (#323–#329). Staging checks: the phase files P1-T18,
   P1-T19, P2-T16 to P2-T19; ask the owner about bug 11 (stock out at delivery for direct BL) and bug 4's columns.
0. D-281/D-282: PR from `claude/serene-gates-6iaad1` (owner asked to merge once green). Then the real-printer check:
   a picture receipt on the Digipos (if it is BLE) or the Capacitor wrapper.
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
