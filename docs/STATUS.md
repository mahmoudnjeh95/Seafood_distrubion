# Project status

_Last updated: 2026-11-09 (roles and access per section, D-306; images built off the server, D-308; WhatsApp assistant P12-T01, D-307; Phase 1 gap review P1-T20 to T26, D-299 to D-305; P11-T15 write-off evidence, D-298; CI on PRs and main pushes only, D-297; Phase 10 Flotte & entretien P10-T01, D-295, #332; accounting review P2-T20, D-291 to D-294, #331; training copy D-290, #330; Perfaxis gaps and client bug list #323–#329; next free decision D-309)_
_Last updated: 2026-11-09 (images built off the server, D-308; Phase 1 gap review P1-T20 to T26, D-299 to D-305; P11-T15 write-off evidence, D-298; CI on PRs and main pushes only, D-297; Phase 10 Flotte & entretien P10-T01, D-295, #332; accounting review P2-T20, D-291 to D-294, #331; training copy D-290, #330; Perfaxis gaps and client bug list #323–#329; next free decision D-310; D-306 is the roles PR, D-307 Phase 12 WhatsApp)_

## Where we are

- **D-308 (owner 2026-11-09): the staging images are built on the CI runner and loaded on the server**, never built
  there (a build on the shared VPS took it down). Branch `deploy-build-off-server`. Check on the first deploy after the
  merge: the "Deploy" step builds both images on the runner, the server's load stays low, the five health checks pass.

- **D-306 roles and access per section (owner request 2026-11-09, branch `user-roles-matrix`, migration `core 0008`):**
  Paramètres › Rôles makes a role with a level per section (Aucun / Lecture / Écriture / Tout); Paramètres ›
  Utilisateurs gives it to someone, and "Accès" sets one person's own levels over their role. The API enforces it
  (`apps/core/access.py`); the built-in roles behave as before. Check on staging: make a role "Commercial" (Bons de
  livraison and Devis in Écriture, the rest Aucun), give it to a test user, log in as them: the menu shows only Ventes,
  a treasury URL shows "no access". Then give a gestionnaire "Salaires" in Lecture and check they see the payroll.
  The WhatsApp assistant session (branch `whatsapp-assistant`) adds a section `assistant` after this merges.

- **Phase 12 · Assistant WhatsApp (D-307, owner request 2026-11-09)** — plan in `docs/phases/12-whatsapp-assistant.md`
  (design and plan under `docs/superpowers/`). **T01 on branch `whatsapp-assistant`:** app `apps.assistant`
  (migration `assistant 0001`), webhook `/api/v1/whatsapp/webhook`, phone link in the Django admin, read-only answers
  by text through the app's own endpoints as the user, Claude Sonnet 5.5. Off until `ASSISTANT_ENABLED=true` and the
  Meta and Anthropic keys are set (runbook "WhatsApp assistant"). Owner only until the roles matrix (`user-roles-matrix`,
  another session) merges; then T05 adds the section `assistant`. Next: T02 write tools with confirmation.
  Owner to do: SIM, Meta Business verification, Anthropic key, INPDP question to the accountant.
- **Phase 10 · Flotte & entretien (D-295, owner request 2026-11-08)** — plan and the owner's answers in
  `docs/phases/10-fleet-maintenance.md`. T01 compteur merged (#332). **T02 to T05 on branch
  `claude/dreamy-carson-bztvxg`, PR #333 (migrations `maintenance 0002` to `0004`, new expense category `vehicles`):**
  maintenance types and plans per truck ("Ajouter les entretiens conseillés", "Entretien effectué" → approved expense,
  general overhead); monthly frigo / cold room service; papers of trucks and people with scans, the block of a truck
  with an expired assurance or visite technique and the owner's one-day permission; nightly `maintenance_warnings`
  (notifications once per step), badges on the menu, Flotte and Camions du jour, overview, driver's phone card.
  Check on staging after the merge: Flotte › Paramètres › "Ajouter les entretiens conseillés"; follow a vidange on a
  truck with a last date; type an assurance expired yesterday, the truck can no longer be assigned, the owner allows
  the day; the phone shows "Entretien et papiers".
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

- **Older entries** (D-241 to D-282, printing P3-T10, Phase 9 merges, SmartFeesh, CI fixes): moved to `docs/status-archive.md`.
- **Staging** (D-036, D-155, `docs/runbook.md`): admin http://app.fruttidelmare.com, driver http://ch.fruttidelmare.com,
  demo logins `owner` / `driver` (password in `~/frutti-staging/.env`). Every merge to `main` deploys staging.
- **Working rules:** no tests or e2e locally, CI checks the PR; one branch and one PR per task; merge only after green.
  Several sessions work at once; recheck decision and migration numbers right before merging.

## Next step

0. **Phase 11 Conformité (D-296, owner 2026-11-08 "need all of them"):** every point of
   `docs/guides/market-readiness-review-2026-11-08.md` is a task of `docs/phases/11-compliance.md`. P11-T01 merged
   (#334): no invoice issued without the seller's address and matricule fiscal; a customer without tax ID or address
   warns. Check on staging: blank the address in Paramètres financiers, a draft cannot be issued.
   **P11-T15 (D-298, branch `claude/write-off-evidence`, migrations `sales 0036`, `documents 0008`):** a customer
   write-off says its motif (écart de règlement / créance irrécouvrable); an irrecoverable one reads "Justificatif
   manquant" until a file is attached from the client's Remises à zéro list. Check on staging: clear a balance as
   "Créance irrécouvrable", see the pill, attach a PDF, the pill goes. Next code tasks without the accountant:
   P11-T16 period lock, P11-T18 lot traceability, P11-T14 certificates received. The owner starts P11-T03 (INPDP,
   hosting), P11-T04 (lawyer), P11-T05 (TTN enrolment) and books the accountant session P11-T06 (unblocks T02, T07–T12).
0. P10-T02 to T05 (D-295): PR #333, merge once CI is green, then the staging checks above. Owner: confirm the
   suggested intervals against each truck's manual, and the paper list with the accountant or the ATTT.
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
