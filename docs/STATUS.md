# Project status

_Last updated: 2026-10-31 (P9-T04b merged, D-217; P9-T04c rejected effets built, D-218)_

## Where we are

- **Phase 9 · Règlements & Trésorerie (D-197, owner request 2026-10-31)** — plan in `docs/phases/09-treasury.md`.
  **Merged:** T01 (#223, D-197) customer règlement lines and the `treasury` app · T02 (#231, D-208) supplier lines,
  our effets issued · T03a (#234, D-210) "Nouveau règlement" pages, Répartir, Banques · T03b (#237, D-211) lists with
  filters/totals/Excel, detail pages, supplier void · T03c (#240, D-215) supplier receipt PDF, several plan lines paid
  at once · T04a (#241, D-216) Portefeuille, remise en banque with bordereau PDF, encaissé, retirer, débité.
  · T04b (#242, D-217) impayé of a customer effet (the customer and the sales owe again, bank charges as an expense),
  Restituer. **P9-T04c on branch `effet-rejected`** (awaits CI, D-218): our effet rejeté by the bank
  (`purchasing.RejectedEffet`, `RejectedRelease`, migration `purchasing/0015`): the supplier and the invoices are owed
  again. Endorsing waits for Q29.
- **Other work merged 2026-10-31 (other sessions):** D-194 to D-207 (owner list, PRs #217–#230), D-212 counter sale on
  several lots (#235), D-213 the office alone counts the driver's cash (#239). D-214 (#238, truck purchase stock) is
  still open in another session; the next free decision number is D-217.
- **Earlier, check on staging:** D-193 price floor override, D-192 Règlements fournisseurs, D-191 general cost by day,
  D-190 payment in "Convertir en vente", D-189 UI units, D-188 site request → quote, D-187 Bilan des caisses, D-186
  public site, D-185 load BLs, D-184 empty truck, D-181 purchase paid limit, D-179 money confirm window.
- **Phases:** 1 done except P1-T14 owner decisions; 2 mostly done; 3: open T08 field test, T09 Arabic review,
  T10 printing; 9 in progress (T04b to T07 left).
- **Staging** (D-036, D-155, `docs/runbook.md`): admin http://app.fruttidelmare.com, driver http://ch.fruttidelmare.com,
  demo logins `owner` / `driver` (password in `~/frutti-staging/.env`). Every merge to `main` deploys staging.
- **Working rules:** no tests or e2e locally, CI checks the PR; one branch and one PR per task; merge only after green.
  Several sessions work at once: Phase 9 happens in the worktree `C:\Mahmoud_workspace\wt-treasury`; recheck the
  decision and migration numbers right before merging.

## Next step

1. P9-T04c: PR from `effet-rejected`, green CI, fetch and rebase (renumber D-218, `purchasing/0015` if taken), merge.
   On staging: a supplier règlement with one of our cheques → Portefeuille › Émis → tick it → Rejeté par la banque →
   the supplier balance is up and its invoice owes again; pay it with a new règlement.
2. Staging checks of T04a/T04b: a remise en banque and its bordereau PDF; an impayé with charges (Charges shows them).
3. Then T05 accounts (caisse, banks, driver cash), T06 échéancier and alerts, T07 reports.
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
