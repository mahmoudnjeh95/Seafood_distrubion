# Project status

_Last updated: 2026-11-02 (side menu: one Trésorier entry, D-241; next free decision D-242)_

## Where we are

- **2026-11-02, D-241 (branch `treasury-menu`, PR #276, awaits CI):** the side menu's Banques becomes **Trésorier**
  (opens Encaissement); Règlements clients, Règlements fournisseurs and Portefeuille leave the menu, the treasury ribbon
  links them. Routes and pages unchanged; nothing else renamed.
- **All PRs merged, none open (2026-11-01).** On main and staging since 2026-10-31: D-208 to D-236, among them D-220 driver's
  day corrected by the office only, D-221 amount separators, D-222 e-mail addresses, D-223 numbering and prefixes, D-224 VAT
  on the BL, D-225 and D-226 règlement motif and "Total à régler" (a customer payment is now the règlement page), D-227
  cold-room estimate, D-228 salaries approved when generated, D-231 several lots on a transfer, D-234 salary payments,
  primes and advances in the treasury, D-235 party counts in the règlement lists, D-236 bank details.
- **CI and deploy fixes:** the month-start test failures (#256), build heap 1536 MB on the VPS (#261).
- **SmartFeesh:** `SmartToolsAgro/SmartFeesh` is pushed only when the owner says "push main" (D-209). It is at #234.
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

1. Owner: check on staging the merged points above, first a customer payment from the card ("Enregistrer un règlement"
   opens the règlement page, "Total à régler" shows) and a salary payment ("Débité de la trésorerie").
2. P9-T05b: expenses paid, sales paid on the spot, partner settlements, port purchases and the driver's approved day post
   to the ledger; salaries are done (D-234). Then T05c, the Comptes page and "Compte" in the forms.
3. Then T06 échéancier and alerts, T07 reports. New decisions start at D-237.
4. **Owner action for D-206:** the company SMTP account in the server `.env`, then redeploy.

## Open owner decisions

- D-234 (provisional): whether primes are subject to CNSS (accountant); an advance above the month's due needs a confirmation.
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
