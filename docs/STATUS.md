# Project status

_Last updated: 2026-10-12_

## Where we are

- **Phase:** 1 is done. Phase 2 (sales) is mostly done (T07 returns, T08 PDFs and the T09 remainder may be
  in flight), Phase 5 (costs) is done, Phase 6 has T01 to T03 done (more may have landed), and **Phase 3
  (driver app) has T01 to T06 done**. Phase 0 agent work is done; its human items are under Blockers.
- **On `main`:** everything above plus the driver app: start of day with truck pick and cash float
  (D-090), sale on the road (D-091), expenses with receipt photo (D-092), losses and returns (D-093),
  end-of-day closing with the office page `/journees` (D-094); PRs up to #47.
  Every merge to `main` deploys staging.
- **Staging** (D-036, `docs/runbook.md`): admin http://admin.217-182-205-137.sslip.io:8095, driver
  http://chauffeur.217-182-205-137.sslip.io:8096. Demo logins `owner` / `driver`, password in
  `~/frutti-staging/.env` on the server. Check that the last deploy of `main` succeeded
  (`gh run list`).
- **The plan changed (2026-10-11, `docs/spec/client-meeting-2026-10-11.md`):** profit is computed and
  shared **per lot**, not per month (D-040); lot costs: day labour, employees at days × salary / 26,
  cold room per day, truck costs of the day split over the lots on board, rent and accountant "like a
  salary" (D-041); a driver's truck is chosen per day (D-042). Q21 (rent split) and Q24 (truck-cost
  split) are still provisional.
- **How we work (2026-10-11):** Mahmoud lets agents open and merge PRs (green CI only) with `gh`;
  `.claude/settings.json` allows `gh pr merge`. Several agents work in parallel, each in its own
  worktree and branch; agents never edit this file, the orchestrator does. Decision numbers are handed
  out in advance. The client is not available: build with the stand-in data of `docs/spec/sample/`.

## Next step (do this first)

1. **Mahmoud: try the driver app on staging** (login `driver`) with the office on `/journees`; this is the
   start of P3-T08. Collect what confuses a driver; keep it simple (D-090).
2. Phase 3 remaining, in this order: **P3-T07a to T07d** (offline, split in the phase file), **P3-T09**
   Arabic, **P3-T10** printing (spike first, needs a real printer).
3. Phase 3 gaps found while building (not yet tasks): an approved day should block more sales and
   expenses that day (D-094); a driver cannot collect a customer payment on the phone yet; recent
   customers first and creating a customer on the phone (D-091); a truck sale should use the load's
   price (D-051); the running total on the sale screen uses the daily price, the receipt the server's.
4. Other waves: P2-T07/T08/T09, P6-T04 to T07 (check `gh pr list` and `docs/phases/` for what landed).

## Blockers / waiting on client

- **P0-T02** (worked example) is not started; it is now **one real lot** worked out by hand with the
  owner (purchase, sales, each cost, partner share). Phase 6 has no target without it. D-031's
  uncovered loss, Q21 and Q24 are provisional; P0-T02 should confirm them.
- **P0-T01**: no prototype walk-through or client materials yet (stand-ins in `docs/spec/sample/`).
- **P0-T11 human items:** a domain for HTTPS (staging is plain HTTP, D-027); a Sentry project and its DSN.
  The CI deploy key logs in as `debian` (full sudo): a separate server or a server-side pull is advised.
- **TTN / El Fatoora is on hold** (D-016) although Q5 says it is required now.
- **For the accountant** (`docs/spec/sample/README.md`): the VAT code lists Tunisian fishing products as
  exempt, which does not match "19 % for all"; e-invoicing is mandatory since 01/01/2026. Supplier
  invoices carry no VAT until then (D-043).
- **Provisional, to confirm with the client:** supplier due date +30 days and payment methods (D-043);
  loss approval threshold 2 kg (D-045); no supplier credit note yet (a posted invoice cannot be corrected).
- **Provisional (P2-T06, P6-T03):** default credit policy `block`; ageing runs from invoice/sale date;
  a loss beyond the partner's capital stays on the profit-share balance (D-066); no customer-credit
  refund yet; no owner override with reason to close a lot with unpaid sales (D-068).

## Watch out

- **The staging VPS is shared with other clients' production sites.** Touch only `frutti-staging`
  (containers, folder, nginx site); run `sudo nginx -t` before any reload; never prune Docker there.
- Mahmoud's Windows machine: `gh` is at `C:\Program Files\GitHub CLI\gh.exe` (logged in as
  `mahmoudnjeh95`). No `make`, `pnpm`, `docker`, `psql` or gettext on the PATH;
  `npx -y pnpm@10.28.0 <command>` works. For Playwright, put a `pnpm.cmd` shim
  (`@npx -y pnpm@10.28.0 %*`) on the PATH. For tests, `initdb -A trust -E UTF8 --locale=C` a PostgreSQL
  18 cluster in the scratchpad on its own port (5433, 5434…: parallel sessions each use their own) and
  set `DATABASE_URL`. **The UTF8 encoding is required** (the default WIN1252 breaks the Arabic tests).
  The machine is slow when several agents run: logins can take 5 s, so Playwright may need longer
  timeouts locally (do not commit them).
- Parallel branches always collide on the same shared files: `frontend/packages/i18n/src/fr.ts` (keep
  each task's keys in its own block), the generated API client (regenerate, never hand-merge),
  `App.tsx` routes, `seed_dev.py` and its test, `ENUM_NAME_OVERRIDES` in `config/settings/base.py`
  (every enum named `kind`/`status`/`method` needs an entry), and `DECISIONS.md` (keep number order).
- Run `make lint` before every commit (or `make hooks` once); CI runs the same checks.
- API: 401 = not logged in, 403 = role not allowed (D-023). Every view sets a permission class, scopes its
  queryset with `.for_organization(org)` (D-022) and names its operation with `operation_id` (D-026).
- UI: no hard-coded text (`packages/i18n/src/fr.ts` + `t()`); `formatMoney` / `formatQuantity` /
  `formatDate`; logical CSS classes (D-025); token colours only (D-024); API calls through `@frutti/api`.
- Stock changes only through `inventory.services.post_movement` or `post_fifo_movements` (D-035, D-037);
  never write `StockOnHand`. Nobody picks batches by hand: take stock with `post_fifo_movements`.

## Last session (2026-10-12)

Driver app, one task per step: **P3-T01** (truck pick, day start with cash), **P3-T02/T03** (stock, sale,
receipt), **P3-T04** (expenses), **P3-T05** (loss with photo, return of the unsold), **P3-T06** (closing and
office review). PR #45 (contains #42, closed), then #47 for the sidebar e2e. Backend tests could not run on
the author's machine (no PostgreSQL): CI is the only check. GitHub Actions had been blocked by billing for
a while (jobs failed in 2 s); it works again. Driver endpoints are all `my-*` and driver-only.

## Recently done

- 2026-10-13 · Clôture mensuelle (owner request, D-122): a new card shows each partner's share of the
  month's shared costs (rent, electricity, fuel, salaries), by category, from the raw cost their lots
  carried. Existing figures made clickable: stock rows to the lot page, expense categories to `/charges`
  filtered by category and the month's dates (`ExpensesPage` now reads filters from the URL); sales,
  spoilage and salaries link to their list pages without a date filter yet. Full itemized drill-down
  (individual sales/expense/loss/payroll rows behind each month total) is a follow-up, not done here.

- 2026-10-12 · D-121 (owner request, not a phase-file task): a sale line can pick a lot by hand instead of
  FIFO. Built on the counter sale screen first; backend (`requested_batch`, `prefer_batch_id`, the new
  `locations/<id>/stock/<product_id>/batches` endpoint) works for any sale line, so the regular sale screen
  can get the same picker later with no backend change. Migration `sales.0013`. A short lot tops up from the
  other lots automatically (warned, never negative — D-006 stays). Not yet committed/pushed.
- 2026-10-12 · Driver app fixes: "Mon stock" tab built (was a placeholder); "Ma journée" shows the kilos
  still in the truck when nothing was loaded today; a screen that crashes shows a message instead of a blank page.
- 2026-10-12 · P2-T11 part 1: "Documents" page `/documents` (every DV, BL, FA, AV, BA, BR, FF as chains with their
  actions, D-102); part 2: one devis delivered in several BL (D-115).
- 2026-10-12 · P3-T01 to P3-T06 (driver app)
- 2026-10-11 · P2-T05, P2-T06, P5-T02, P5-T05, P6-T01, P6-T02, P6-T03
- 2026-10-11 · P1-T11, P2-T02, P2-T03, P2-T04, P5-T01, P5-T03, P5-T04
- 2026-10-11 · P1-T08, P1-T09, P1-T10, P1-T12, P2-T01 (first parallel wave)
- 2026-10-11 · Plan updated after the client meeting (per-lot profit)
- 2026-10-11 · P1-T06c rebuild and nightly check
