# Project status

_Last updated: 2026-10-31 (Phase 9 Règlements & Trésorerie planned; P9-T01 built, D-197)_

## Where we are

- **Phase 9 · Règlements & Trésorerie (D-197, owner request 2026-10-31)** — plan in `docs/phases/09-treasury.md`, T01 → T07.
  **P9-T01 done on branch `treasury-plan`** (awaits CI): new app `treasury` (banks seeded per organization, effets =
  cheques/traites with status history), customer règlement with several lines (`CustomerPaymentLine`, method `mixed`,
  Traite added), allocation by invoice, void cancels effets still in portfolio (refused once one moved on), data migration
  of old payments, `GET/POST /treasury/banks`, `PUT /treasury/banks/<id>`, `GET /treasury/instruments`; the existing
  payment window asks number, bank, échéance and drawer for a cheque or traite. API client regenerated.
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

0. Owner list: merge #220 → #230 in order as CI goes green, then on staging: Camions du jour › Fonds de caisse (set,
   then accept on the phone), close a day with an office count, a "Nouvelle facture" with two BL, an Achat terrain
   validated without invoice then "Facturer la réception", a quote with a picked lot → BL, a receipt "Achat avec TVA"
   → invoice without VAT refused. **Owner action for D-206:** put the company SMTP account in the server `.env`
   (`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`) and redeploy.
1. P9-T01: open the PR from `treasury-plan`, wait for green CI, rebase on `main` if another branch touched
   `docs/STATUS.md`, `docs/DECISIONS.md` (renumber D-197 if taken; D-194 to D-196 went to logout, "Commande d'achat" and the Transferts menu) or `sales` migrations (renumber `0020`), then merge.
   On staging: a customer page → "Enregistrer un règlement" → Chèque, number, BIAT, échéance; the list shows its number;
   the same cheque again is refused; voiding it frees the number.
2. **P9-T02** (next session, new branch from `main`): `SupplierPaymentLine`, `POST /supplier-payments` with `lines`,
   effets issued (`direction=issued`, status `issued`), D-192 plan lines paid from one règlement, receipt and port
   purchase payments as lines, data migration of `SupplierPayment.cash_on` into the effets. Reuse
   `treasury.services.register_instrument` / `instrument_errors` / `cancel_instruments`.
3. Then T03 (full "Nouveau règlement" page, list and detail pages, Paramètres › Banques), T04 portfolio, T05 accounts,
   T06 échéancier, T07 reports.

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
