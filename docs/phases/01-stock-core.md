# Phase 1 · Catalogue, suppliers & stock

**Goal:** every kilogram is traceable from the supplier to the cold room to a truck, with its batch, cost
and supplier.
**Done when:** the owner can register products and suppliers, receive goods (with real weight), load and
unload trucks, record losses, count stock, and see stock per location and batch, with every quantity
explained by the movement history.
**Depends on:** Phase 0. **Questions:** Q4, Q8, Q10, Q11 and Q12 are answered; nothing is open for this
phase.
**Out of scope:** customers and sales (Phase 2), the driver's phone screens (Phase 3).

---

### P1-T01 · Units and conversions · S
- [x] `Unit` table seeded with kg only; per-product `base_unit` (always kg for now). The `Product.base_unit`
      field itself is added with `Product` in P1-T02, defaulting to `catalog.selectors.base_unit()`.
- [x] Quantity helpers with tests; quantities stored in base unit only (`core.money.checked_quantity`
      for what a person types, `catalog.selectors.to_base_quantity` for every quantity entering the system).

Q10 answered: everything is sold by kg. Box and piece units and conversion factors are not built now;
the `Unit` table keeps the door open for other distributors (Q17).

### P1-T02 · Product catalogue · M
- [x] `Category`, `Product` (name, reference, category, base unit, default sale price, minimum stock,
      storage temperature range, active flag, photo). Also an Arabic name and a stand-in drawing (D-030).
- [x] API (list/filter/search/create/update/archive) + admin screens: list with photo cards like the
      prototype, form with photo upload.
- [x] Sale prices change from one day to the next, and sometimes several times in one day
      (2026-10-10): `ProductPrice` holds one price per product with a valid-from **date and time**; the
      price in force at a moment is the latest one at or before it. History is never overwritten.

### P1-T03 · Suppliers · S
- [x] `Supplier` (name, tax ID, phone, address, contacts, notes, active). Agreement link comes in Phase 6.
      Also a reference (`F-001`, generated when left empty), e-mail and city; contacts are
      `SupplierContact` rows (D-032).
- [x] API + admin list/detail/form.

### P1-T04 · Locations and trucks · S
- [x] `StockLocation` (type: cold_room | truck | other, name). `Truck` (plate, name, assigned driver,
      location 1–1). Locations in `inventory`, trucks in `fleet`; a truck's name is its location's (D-033).
- [x] Any number of cold rooms and trucks, managed from an admin screen (Q8: 2 cold rooms, 3+ trucks).
      The "Stock frigo & camions" screen shows them as cards; stock figures join it in P1-T11.
- [x] Object-level permission helper "own truck" for drivers (`fleet.selectors.may_use_location`,
      `may_use_truck`), and the driver's truck in `/api/v1/me` (left open by P0-T06).
- [x] A cold room is also a selling point: over-the-counter sales are regular (Q8), used by P2-T04
      (`counter_sales` flag; `sells` is true for every truck).
- [x] Seed (dev only): two cold rooms, three trucks. Real names come from the client's lists.

### P1-T05 · Batches (lots) · M
- [x] `Batch` (product, supplier, receipt reference, receipt date, unit cost, expiry/use-by) in
      `inventory`. The nullable `agreement` key is added by P6-T01 with the agreement table (D-034).
- [x] Batch number generator (`L-0912` style, per organization): `L-0001`, `L-0002`… under a row lock.
- [x] Read-only API (`listBatches`, paginated, filters product / supplier / search; `getBatch`), office
      only. Batches are created by `inventory.services.create_batch`, called by goods receipts (P1-T07).
- [x] Seed (dev only): 15 recent batches of the sample suppliers, dorade from two suppliers (Q4).

Q4 answered: the same product can come from several suppliers in one month; batches keep them apart.
Q11 answered: a mix such as Symphonie Marine comes from a single supplier, so it is an ordinary product
with ordinary batches. No `parent_batches`.

### P1-T06 · Stock ledger and on-hand · L, split into T06a–T06c (2026-10-10)
Read: ARCHITECTURE §4 rule 3, DECISIONS D-006.

#### P1-T06a · Movement ledger, on-hand cache, `post_movement` · M
- [x] `StockMovement` (append-only): type (receipt, transfer, sale, customer_return, supplier_return,
      loss, adjustment, count_correction), product, batch, from_location, to_location, quantity,
      unit_cost, source document (generic FK), user, timestamp, reason, `client_uuid`.
- [x] Which side each type moves: receipt and customer return come in, sale, supplier return and loss
      go out, transfer goes from one location to another, adjustment and count correction go one way.
- [x] `StockOnHand(location, batch)` cache; `inventory.services.post_movement(...)` updates it in the same
      transaction with `select_for_update`; negative stock refused. A repeated `client_uuid` returns the
      movement already posted.
- [x] A location still holding stock cannot be archived (left open by P1-T04).
- [x] Tests: concurrency (two transfers at once), negative stock refused. Demo batches get an opening
      stock and a morning truck load in the seed.

#### P1-T06b · FIFO allocation · S
- [x] `allocate_fifo(product, location, qty)` → list of (batch, qty) oldest first, in the batches'
      FIFO order (D-034), refusing more than the location holds. A preview: nothing locked or posted.
- [x] A helper that posts one movement per allocated batch (used by transfers, sales and losses):
      `services.post_fifo_movements` (D-037).

#### P1-T06c · Rebuild and consistency check · S
- [x] `rebuild_on_hand()` management command + nightly consistency check that reports differences
      (`manage.py rebuild_on_hand [--check]`; the `nightly` container on staging, D-038).
- [x] Tests: rebuild equals cache; a damaged cache is reported, then repaired.

### P1-T07 · Goods receipt from suppliers · M
- [x] `GoodsReceipt` with lines: ordered qty (optional), invoiced qty (net weight, Q12), **accepted net
      qty**, unit cost → creates batches + receipt movements. No gross-weight or glaze fields. No
      `PurchaseOrder` document yet: the ordered weight is typed on the line (D-039).
- [x] Differences (ordered or invoiced vs accepted) visible on the receipt and in a report
      (`listReceiptDifferences`; the receipts list filters on them).
- [x] Purchase prices change from one day to the next (2026-10-10): the unit cost is typed on every
      receipt line and belongs to that batch only. There is no fixed supplier price list. The form
      suggests the last cost paid to that supplier for that product and shows the change against it.
- [x] Purchase price history per product and supplier (date, cost), read from the batches
      (`listBatches?product=&supplier=`; a screen comes with the stock screens, P1-T11).

### P1-T08 · Supplier invoices and payments · M
- [x] `SupplierInvoice` linked to receipts; due date; status (draft, posted, partly paid, paid).
- [x] `SupplierPayment` with allocation to invoices. Supplier balance = invoices − payments.
- [x] Nothing here touches investments or profit shares (separate balances, Phase 6).

### P1-T09 · Transfers between locations · S
- [x] Transfer document (morning load, evening return, cold room → cold room) with lines → transfer
      movements, FIFO batches (D-044).
- [x] Validation by owner/manager; driver confirms receipt in Phase 3 (`confirmed_by` / `confirmed_at`
      left empty until then).
- [x] Client meeting 2026-10-11: a morning load carries the **price per kg of each product** for the
      day (from `ProductPrice`, editable on the load) so the driver knows what to sell at. The evening
      return shows loaded − returned = sold or lost, per product (`getTruckDay`).

### P1-T10 · Losses, adjustments and stock counts · M
- [x] Loss / spoilage with reason and optional photo; above a threshold needs owner approval
      (`StockLoss`, threshold in kg in `StockSettings`, D-045).
- [x] `InventoryCount` per location: count sheet, differences, approval → count_correction movements
      (`StockCount` + `StockCountLine`, D-045). A separate "adjustment" document was not needed: a count
      corrects any difference, a loss records any shortage with its reason.

### P1-T11 · Stock screens · M
- [x] Admin stock page like the prototype: location cards, product cards with per-location kg, low-stock badge.
- [x] Product → batch → movement history drill-down; movement list with filters.
- [x] **Average purchase price** per product: weighted by kg over the batches still on hand, with the
      last cost next to it (client meeting 2026-10-11). For pricing only; sales stay FIFO (D-040).

### P1-T12 · Truck of the day · S
Client meeting 2026-10-11, D-042: a driver is not tied to one truck.
- [x] Drop the "one active truck per driver" constraint; `Truck.driver` becomes the usual driver only.
- [x] Truck assignment per date (truck, driver, date), set by the office or by the driver; provisional:
      one driver per truck and one truck per driver each day. Phase 3's `DriverDay` builds on it.
- [x] `may_use_location`, `may_use_truck` and `/me` read today's assignment, falling back to the usual
      driver when there is none.

**Phase acceptance test (end-to-end):** receive 60 kg dorade (62 invoiced) → load 15 kg to truck 1 →
record 1.5 kg loss on truck 1 → count cold room → all on-hand numbers match the ledger, and the supplier
balance shows the invoice.

### P1-T13 · Purchase orders and partial receipts · M (added 2026-10-12)
- [x] `PurchaseOrder` (bon d'achat, `BA-0001`) with lines (product, kg, agreed price); status open, partly received,
      received, closed, cancelled (D-076).
- [x] A goods receipt (BR) can be made against an order, with only part of its products or weights; several BR per
      order; received and remaining kg per line.
- [x] Close an order whose rest will not come; cancel one nothing was received on.
- [x] Screens: "Bons d'achat" tab (list, form, detail), "Recevoir" opens the BR form pre-filled with what remains.

### P1-T14 · Returnable boxes (caisses) · M (added 2026-10-13, D-124, Q27)
Boxes are a count ledger next to the kg stock, never products. Steps 1 to 4 merged (#95, #97, #98, #100).
- [x] `BoxType` (small, big) and an append-only `BoxMovement`, posted only through a service in a transaction (D-124). (#95)
- [x] Holders: locations, clients and suppliers. Movements: receive, load, leave, collect, return, write off. (#95, #97)
- [x] Balances derived from the ledger, never negative (D-006). (#95)
- [x] Admin "Caisses" page (balances and history). (#98)
- [x] Box section on the client page (`CustomerBoxesCard` on the customer page).
- [x] Goods receipt and transfers carry an optional box count, default 0. (#97)
- [x] Driver: sale with boxes (online), pickup visit (online), day view with loaded, left and collected counts. (#100)
- [x] Owner decision 2: the truck's "expected boxes" is the real ledger balance, not today only. (#107)
- [x] Owner decision 3: box actions (sales with boxes, pickups) in the driver offline queue, idempotent retries. (#107)
- [x] Owner decision 4: truck-to-cold-room "return" movement (`truck_return`), posted with the transfer. (#107)
- [x] Arabic box texts (#102, provisional until a native speaker reviews them).
- [ ] Browser check of the driver box screens on a real phone.
- [x] Opening stock of the company's own boxes: movement kind `opening` into a location, and the owner's 50 small
      and 50 big boxes in `seed_dev` (D-135).
- [ ] Open: opening balance for boxes already at a client or owed to a supplier; a screen or command to type an
      opening stock on a real database (D-135).
- [x] "Bilan des caisses" on the Caisses page: in hand, at clients (to collect), owed to suppliers (to give back),
      and the company's own boxes; a one-line note on each of the three lists (D-187).

### P1-T15 · Stock adjustment by hand · S (added 2026-11-02, D-241)
- [x] "Ajuster le stock" on the product page: add or remove kilos of a lot at a place, with the reason
      (`adjustment` movement, `services.adjust_stock`, `POST /stock/adjustments`, owner and manager).
- [x] The average purchase price is worked out again from the stock on hand; the success message shows it before and after.
- [ ] Check on staging: add 10 kg to a lot, remove it again; the average on the product page and on Prix du jour moves.
