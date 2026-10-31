# Project status

_Last updated: 2026-10-31 (P9-T03a merged, D-210; P9-T03b lists, detail pages, supplier void built, D-211)_

## Where we are

- **Counter sale, several lots (D-212, owner request 2026-10-31)** — branch `counter-sale-multi-lot` (PR #235), awaits CI and merge: a counter-sale line picks lots with the kilos from each (`SaleLinePick`, API `picks`), the rest oldest first; a single `batch` stays one pick of the whole line; migration `0022_sale_line_picks`. The till's lot cell opens a dialog to choose the lots.

- **Phase 9 · Règlements & Trésorerie (D-197, owner request 2026-10-31)** — plan in `docs/phases/09-treasury.md`, T01 → T07.
  **Merged:** T01 (#223, D-197), T02 (#231, D-208), T03a (#234, D-210: "Nouveau règlement" pages, lines editor,
  Répartir, Banques). **P9-T03b on branch `payment-lists`** (awaits CI, D-211): supplier règlement void (migration
  `purchasing/0014`, every reader skips voided), list filters + totals + Excel for both, detail pages with effet
  history.
- **D-214 (fix, branch `truck-purchase-stock`, awaits CI):** a driver's port purchase goes to the driver's truck (was: first
  cold room); "Journées des chauffeurs" lists the day's purchases with their status until the office checks them.
- **On main 2026-10-31:** D-194 logout asks first (both apps), D-195 "Bon d'achat" renamed "Commande d'achat", D-196 Transferts under the driver's day.
- **Owner list 2026-10-31 (15 points), stacked PRs #220 → #230, merge in that order after green CI:** #220 D-207 no
  customer balance on the phone · #221 D-198 stock cards/list · #222 D-199 amounts 1 250,000 in server messages ·
  #224 D-200 "Nouvelle facture" from ticked BL/BR, Achat terrain makes no invoice · #225 D-201 lot picker on quotes and
  sales (sales migration 0021) · #226 D-202 bought with VAT → invoiced with VAT · #227 D-203 starting cash set by the
  office, accepted on the phone · #228 D-204 office cash count at closing · #229 D-205 expense categories for both apps,
  phone "Payé avec" · #230 D-206 e-mail any PDF. Provisional choices are marked in DECISIONS (D-202, D-204, D-205, D-206).
- **Recent work (2026-10-19 to 10-25), merged or awaiting merge, each to check on staging:** D-193 price floor override,
  D-192 Règlements fournisseurs (T16a–d, side menu), D-191 general cost by calendar day (provisional), D-190 payment in
  "Convertir en vente", D-189 UI units, D-188 site request → quote, site card alignment, D-187 Bilan des caisses.
- **On main, check on staging:** D-186 public site (live on www.fruttidelmare.com), D-185 load BLs in a driver's day,
  D-184 empty truck, D-183 receipt product search, D-182 port cash split, D-181 purchase paid limit, D-179 money
  confirm window, P2-T15 load delivery, P3-T15 notifications, D-159 supplier debts and cheques, D-156 statement PDFs.
- **Phases:** 1 done except P1-T14 owner decisions; 2 mostly done; 3: open T08 field test, T09 Arabic review,
  T10 printing.
- **Staging** (D-036, D-155, `docs/runbook.md`): admin http://app.fruttidelmare.com, driver http://ch.fruttidelmare.com,
  demo logins `owner` / `driver` (password in `~/frutti-staging/.env`). Every merge to `main` deploys staging.
- **Working rules:** no tests or e2e locally, CI checks the PR; one branch and one PR per task; merge only after green.
  A second session may work in the main clone: Phase 9 work happens in the worktree `C:\Mahmoud_workspace\wt-treasury`.

## Next step

0a. D-214: PR from `truck-purchase-stock`, wait for green CI, merge. On staging: as a driver with can-buy, send a port
   purchase from the phone; in the office, "Journées des chauffeurs" shows it "À valider au bureau" and the place is the
   truck; validate it, then the truck's stock holds the kilos.
0. Owner list: merge #220 → #230 in order as CI goes green, then on staging: Camions du jour › Fonds de caisse (set,
   then accept on the phone), close a day with an office count, a "Nouvelle facture" with two BL, an Achat terrain
   validated without invoice then "Facturer la réception", a quote with a picked lot → BL, a receipt "Achat avec TVA"
   → invoice without VAT refused. **Owner action for D-206:** put the company SMTP account in the server `.env`
   (`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`) and redeploy.
1. P9-T03b: PR from `payment-lists`, green CI, fetch and rebase (renumber D-211 / `purchasing/0014` if taken), merge.
   On staging: Achats › Paiements, filter "Annulés", open a règlement, "Annuler" with a reason → its invoice owes
   again; Règlements clients: filter by Traite, the totals and the Excel file follow.
2. **P9-T03c** (small): supplier receipt PDF; pay several plan lines at once from "Règlements fournisseurs".
3. Then T04 portfolio, T05 accounts, T06 échéancier, T07 reports.

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
