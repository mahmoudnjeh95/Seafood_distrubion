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
- Still provisional: D-031's carried-forward loss beyond the capital; Q21 and Q24 cost splits (D-041).
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
