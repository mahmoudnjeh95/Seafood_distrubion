# Project status

_Last updated: 2026-11-01 (P9-T08 Trésorerie in the Perfaxis layout, D-230, on branch `treasury-perfaxis`)_

## Where we are

- **D-235 on branch `party-document-counts` (awaits CI):** in "Nouveau règlement client" and "Nouveau paiement
  fournisseur", each customer and supplier in the list shows its BL (or BR), invoices and total. New read endpoint
  `treasury/party-documents`; the total is provisional (see D-235).
- **Phase 9 · Règlements & Trésorerie (D-197, owner request 2026-10-31)** — plan in `docs/phases/09-treasury.md`.
  **Merged on main:** T01 (#223) customer règlement lines and the `treasury` app · T02 (#231) supplier lines, our effets
  issued · T03a (#234) "Nouveau règlement", Répartir, Banques · T03b (#237) lists, detail pages, supplier void · T03c
  (#240) supplier receipt PDF, several plan lines at once · T04a (#241) Portefeuille, remise en banque, encaissé,
  retirer, débité · T04b (#242) impayé, Restituer · T04c (#243, D-218) our effet rejected by the bank.
- **P9-T08 merged (#259, D-230; #260 forms and CSV export, D-232):** the Perfaxis layout: a ribbon of icon buttons on
  every treasury screen (`TresorerieRibbon`), the Bordereau de versement, the états des factures, the forms in panels.
- **P9-T05a merged (#246, D-219):** the accounts and the movement ledger. The ribbon now has Agence bancaire, Caisse
  liquide and the two journals (D-233, on branch `treasury-accounts-ribbon`). Decisions D-220 to D-229 are the other
  session's stack; do not reuse them.
- **Other work on main (other sessions):** D-214 port purchases on the truck and the day (#245), D-213 the office alone
  counts the driver's cash, D-212 counter sale on several lots, D-194 to D-207 owner list.
- **Phases:** 1 done except P1-T14 owner decisions; 2 mostly done; 3: open T08 field test, T09 Arabic review,
  T10 printing; 9 in progress (T05 to T07 left, plus T08 review).
- **Staging** (D-036, D-155, `docs/runbook.md`): admin http://app.fruttidelmare.com, driver http://ch.fruttidelmare.com,
  demo logins `owner` / `driver` (password in `~/frutti-staging/.env`). Every merge to `main` deploys staging.
- **Working rules:** no tests or e2e locally, CI checks the PR; one branch and one PR per task; merge only after green.
  Several sessions work at once; recheck decision and migration numbers right before merging.

## Next step

1. P9-T08: open the PR from `treasury-perfaxis`, wait for green CI, rebase on main, merge. On staging: Règlements
   clients (the ribbon at the top), Règlements fournisseurs, Portefeuille › Bordereau de versement (tick an effet in
   "En attente" → Encaissé; tick one → Impayé), Facture de vente and Facture d'achat (grouped totals).
2. P9-T05 (other session, branch `treasury-accounts`): when merged, add Agence bancaire, Caisse liquide and the
   journals to the ribbon.
3. Then T06 échéancier and alerts, T07 reports.
4. **Owner action for D-206:** the company SMTP account in the server `.env`, then redeploy.

## Open owner decisions

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
