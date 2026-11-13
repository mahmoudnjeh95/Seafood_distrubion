# Phase 6 · Lot profit, partnerships & month-end closing → Milestone B

**Goal:** the most important feature. Know the net profit of every lot, share a partnership lot's profit
or loss with the partner supplier with a clear explanation, and pay it.
**Done when:** a real lot worked out by hand with the owner (P0-T02, now one lot instead of one month)
gives exactly the same result in the app, and a real partnership lot is closed and settled.
**Depends on:** Phase 5 (lot costs) and P0-T02.
_Coarse plan: detail each task when the phase starts._

**Rules (client meeting 2026-10-11, `docs/spec/client-meeting-2026-10-11.md`, D-040, D-041):**
- Profit is computed **per lot**: what the lot sold for − its purchase cost − its own costs (typed
  costs, day labour, monthly employees at days × salary / 26, cold-room days, its share of the truck
  costs of the days it was on board, share of rent and accountant). Spoilage is a cost of its lot.
- A lot is closed when fully sold, its costs are in and its customers have paid (Q19); its result is
  then frozen.
- **Partnership lot:** the owner and one partner supplier each put money in. The partner gets their
  profit % of the net profit; in a loss they carry their loss % of it, **deducted from their capital**
  (Q3, D-031). At closing they get their capital back ± their share (Q22). A supplier can be a partner
  in several lots at once.
- Still provisional: D-031's carried-forward loss beyond the capital; Q24's cost split (D-041). Q21 (rent
  split like the cold room) is confirmed.
- Q1 (own products only) fits: a partner shares only in the lots they are in.

---

### P6-T01 · Partnership lots · M
- [x] Partnership on a lot: partner supplier, amount put in by each side, profit %, loss % (D-031). Set
      at receipt (P1-T07 form gets a "partnership" section) or on an open lot before its first sale.
      _Done on the lot page (D-060); the receipt-form section is a TODO in D-060._
- [x] The partner's capital is a ledger per partner and lot: contribution, deduction for a loss, return.
      Separate from the trade payable and from the profit share.
- [x] One partner per lot; a supplier can be in several lots at once, each with its own capital and
      rates (Q22).

### P6-T02 · Lot result engine · L → split
- [x] Pure functions: lot data snapshot (sales lines, purchase cost, cost lines) → result with every step
      shown.
- [x] Handles profit, zero, loss, lot sold in pieces at different prices, spoilage, a loss larger than
      the partner's capital (D-031).
- [x] Live view on an open lot ("so far"), frozen result on a closed lot.
- [ ] **Golden test:** reproduces the hand-made lot of P0-T02 to the millime. _Waiting for P0-T02: the
      golden tests use a lot worked out by hand to the millime (D-061)._

### P6-T03 · Lot closing and settlement · M
- [x] Close a lot: checks (stock 0 or written off, costs in, customer payments as agreed, see the
      meeting's "still to confirm"), then lock + snapshot. Reopen only with reason and audit.
      _Done with P6-T02 (D-061); customer payments are a warning until P2-T06._
      _The customers-paid check reads receivables through one function, ready for P2-T06 (D-068)._
- [x] Settlement to the partner: capital back ± share; payments; three balances per partner (trade
      payable, capital, profit share). _D-066, D-069; loss beyond the capital stays provisional (D-031)._
- [x] Electricity bill arriving after a lot closed: the difference goes to the partner's next
      settlement (D-041), never by reopening the lot. _D-067._

### P6-T04 · Partner statement PDF · S
- [x] Per lot: purchase, sales (customer, kg, price), each cost line, net profit, %, share, payments,
      balance. "Haka bayek": readable by the partner without explanation. _D-072; layout to check by eye._

### P6-T05 · Month-end inventory valuation and COGS · M
- [x] Stock value at month-end by batch; COGS of the month from sale-line snapshots. _D-073._
- [x] Profit is never "purchases − sales": unsold stock stays an asset. _D-073._

### P6-T06 · Monthly closing (accountant) · M
- [x] Monthly result for the accountant: sales, COGS, costs, net result; checks (unapproved expenses,
      unexplained cash differences, open driver days). _D-074; cash differences and driver days wait for Phase 3._
- [x] Accountant review, then owner approval (Q9). Approve → lock + snapshot. It does not change
      partner shares, which are settled per lot. _D-074._

### P6-T07 · Screens · M
- [x] Lot page: sales, costs, result, partner share, with drill-down to every record behind a number.
      _Built with P6-T02/T03 (`LotResultCard`, `SettlementCard`); partner statement PDF on the lot (P6-T04);
      headline figures and cost-of-goods drill-down added in D-105._
- [x] Prototype's "Partage des bénéfices" page reworked as a list of partnership lots (open, closed,
      settled), with the frozen result of closed lots. _List: P6-T01 (`/partenariats`), results D-105._
- [x] "Clôture mensuelle" for the accountant. _`/cloture` (D-074)._
- [x] Clôture mensuelle: each partner's share of the month's shared costs (rent, electricity, fuel,
      salaries), and the existing figures made clickable to where they come from. _Owner request, D-122._

### P6-T08 · One purchase is one lot; partner on the products ticked · L → split (added 2026-11-10, D-320, Q31)
Owner: one achat is one lot, its products share the lot number; a partner may share only one or two of them.
- [x] **T08a · Lot above the batch.** Model `inventory.Lot` (organization, number, supplier, received_on, source);
      `Batch.lot` FK; numbering `L-0042-1`; the receipt and the port purchase create one lot and one line per product;
      data migration (each receipt → one lot, other batches → one-line lots, old number kept). API + `make gen-api`.
      _Done 2026-11-10 (migration `inventory 0017`): `create_lot`, `create_batch(lot=...)`; the batch API gives
      `lot_number` and `line_number`. A transformation's output is still a lot of its own until T08d._
- [ ] **T08b · Show the lot.** Lot page (lines, stock, sales per product); "L-0042 · Crevette" on stock, BL, labels,
      lot pickers and the driver's phone; search by lot number finds every line.
      _Done 2026-11-11 (branch `lot-page`): `GET /lots/<id>` (`selectors.lot_detail`), page `/stock/lot-complet/:lotId`
      with kg received, sold, lost and in stock per product, link "Lot (achat)" on a product's page, lot search by the
      lot's number. BL, labels, pickers and the phone already print the line number `L-0042-1` beside the product.
      Left: the lot link from the receipt page and the stock list._
- [ ] **T08c · Partnerships on the lot.** `LotPartnership` points to the lot, several per lot, each with its ticked
      lines; one line may be in several partnerships (capital together ≤ the line's purchase value, profit rates
      together ≤ 100 %); receipt form: a "Partenaires" section per lot and per line who shares it; migration of
      existing partnerships (their one batch ticked, two partners on one receipt stay one lot).
  - [x] **T08c1 · The partnership's lot and lines** (D-323, migration `partnerships 0005`): `LotPartnership.lot`
        and `PartnershipLine` (the lines it shares); every partnership so far shares its one batch, a new one too;
        the API gives `lot_number` and `line_ids`; search by lot number. No change in the results yet.
  - [ ] **T08c2** (with T08d, they cannot be split without wrong shares): several partners per line and several
        lines per partnership, the checks on capital and rates, the receipt form's "Partenaires" section.

  **Implementation plan for T08c2 + T08d (written 2026-11-12 after reading the code; three PRs, in order):**

  Today, per line (`Batch`): `closing.LotResult` freezes the line's net *and* the partner's share
  (`engine.lot_result` with `LotSnapshot.partnership` from `selectors._terms` → `live_partnership_of_batch`);
  `close_lot` calls `partnerships.record_lot_closed`; `settle_lot` → `settle_partnership(lot_result_id=…)`;
  `late_drift` shares a line's drift at the partnership's rate; `CapitalEntry`, `ProfitShareEntry` and
  `PartnerSettlement` carry a bare `lot_result_id`. Constraint `one_live_partnership_per_lot` (one live partnership
  per batch) and `PartnerSettlement.partnership` one-to-one stay true in the new model.

  1. **PR 1 · Partnership result (backend only, no visible change for one-line partnerships).**
     _Done 2026-11-13 (D-324, migrations `closing 0003`, `0004`, `partnerships 0006`), golden tests in
     `closing/tests/test_partnership_result.py`. One change from the text below: a line shared alone by one
     partnership still shows the share on its own result (same figures), so the existing tests stay unchanged._
     - New `closing.PartnershipResult` (organization, partnership FK, status closed/reopened, `net_result` = sum of
       its lines' frozen nets, `partner_share`, `capital_deducted`, `uncovered_loss`, `capital_to_return`,
       `owner_share` = net − share, `data` JSON: the lines with their `LotResult` id and net, and the steps,
       closed/reopened by and at; one closed per partnership by constraint).
     - The engine's line result stops computing a share: `lot_result` gets `partnership=None` for lines, and a new
       `engine.partnership_result(terms, lines)` reuses `partner_share(terms, Σ net)` (rounding once, D-031).
     - `close_lot` freezes the line only; then, for each live partnership ticking that line whose every ticked line
       now has a closed `LotResult`, it freezes a `PartnershipResult` and calls `record_lot_closed` with its id.
       A partnership with `terms_pending` still blocks the closing of its lines.
     - `reopen_lot` of a line also reopens the partnership results that include it (refused once settled, as now).
     - `late_drift` and `book_late_adjustments` work per partnership: drift = Σ live nets of its lines − frozen net.
     - Ledgers and the settlement: add `partnership_result_id` (nullable) next to `lot_result_id`; old rows keep
       `lot_result_id`; new rows set the new field. `settle_lot` takes the partnership (by id) instead of a batch.
     - Migration: for every closed `LotResult` with a partnership, a `PartnershipResult` copying its share fields,
       one line; ledgers and settlements get its id. Old line results keep their partner columns as history.
     - Golden tests: shrimp +2 400 / squid −500 shared 50 % → 950; a loss sum uses the loss rate; one-line
       partnerships give the same figures as before to the millime (run every existing closing test unchanged).
  2. **PR 2 · Several lines and several partners (backend + API).**
     - `create_partnership(lot=…, lines=[…])`; `update_partnership` may change the lines before the first sale of any
       of them. Checks: lines of that lot only; on each line, the live partnerships' profit rates together ≤ 100 %
       and loss rates together ≤ 100 %; their partner capitals together ≤ the line's purchase value (kg × cost)
       summed over the partnership's lines (D-320 3). Drop `one_live_partnership_per_lot`; keep one live
       partnership per partner per lot.
     - Transformation of a shared line (Q30): the output line joins the source's lot and its partnerships.
     - API: partnership create/update take `lot` and `lines`; the lot page lists each partnership with its lines.
  3. **PR 3 · Screens and papers.**
     - Receipt form: a "Partenaires" section per receipt (partner, capital, rates, "partagé" tick per product)
       instead of the per-line partner column; lot page: result per product, each partnership's netted result,
       "Clôturer" per product, "Régler" per partnership; partner statement PDF one block per lot, a line per shared
       product and the netted total; reports per partner read `PartnershipResult`.
     - Check on staging: the owner's example of D-320 and the two-partner case (Ali 40 %, Salah 30 % on shrimp
       +1 000 → 400 and 300, the owner 300).
- [ ] **T08d · Shared result and closing.** Each partnership's result = sum of its ticked lines' results (engine
      unchanged per line); profit or loss rate on the sum; a transformed shared line's output stays in its
      partnerships (Q30); closing checks on the ticked lines only; the owner's
      lines close alone; one settlement and one capital return per lot; lot costs typed on the lot split by kg.
- [ ] **T08e · Statement and reports.** Partner statement PDF: one block per lot, a line per shared product, the
      netted total; reports per partner (P7) and month closing read the lot.
- [ ] **Golden test:** the owner's example (shrimp +2 400, squid −500 shared at 50 %, sardine +300 not shared) gives
      950 to the partner and leaves the sardine's 300 to the owner. A second case: shrimp +1 000 shared by Ali 40 %
      and Salah 30 % gives 400 and 300, the owner 300.
- [ ] Check on staging: a receipt of three products, partner on two; sell the two out; the shared part closes and is
      settled while the third is still in stock.
