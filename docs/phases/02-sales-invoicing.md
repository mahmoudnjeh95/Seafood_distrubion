# Phase 2 · Customers, quotes, sales & invoicing

**Goal:** sell from the cold room or a truck, invoice correctly for Tunisia, and always know who owes what.
**Done when:** a quote can become a sale and an invoice; stock and customer balance update in one
transaction; partial payments and returns work; quote/invoice/receipt PDFs look professional.
**Depends on:** Phase 1. **Questions:** Q5, Q7 and Q16 are answered; nothing is open for this phase.
TTN / El Fatoora e-invoicing is not built in this phase (D-016); P2-T05 only keeps a hook for it.

---

### P2-T01 · Customers · S
- [x] `Customer` (type: restaurant, hotel, fish shop, supermarket, wholesaler, caterer, individual; tax ID;
      contacts; credit limit; payment terms; active). "Walk-in customer" default record (D-047).
- [x] Admin list/detail with credit limit and payment terms. Balance and history come with sales and
      payments (P2-T04, P2-T06): the detail page has a placeholder card for them.

### P2-T02 · Prices · M
- [x] "Prix du jour" screen: the owner or manager sets the sale price for every product in one go,
      prefilled with the current one. Each row shows the cost of the batches in stock and the margin,
      since purchase costs also change daily (P1-T07).
- [x] A price can be changed again at any time of the day; the change applies from that moment, and
      the screen shows the day's earlier prices with who changed them and when.
- [x] A sale uses the price in force at the moment it is made (`price_in_force` at `sold_at`, D-049, D-051).
- [x] A sale line keeps the price actually charged; later price changes never touch past sales,
      invoices or profit. A quote keeps its own prices until its validity date. (Invoices: P2-T05.)
- [x] Price lists and customer-specific prices; minimum price per product; warning (not block) below it,
      logged in audit. (API and tests only; no price-list screen yet, D-049.)

### P2-T03 · Quotes (devis) · M
- [x] `Quote` + lines, validity date, statuses (draft, sent, accepted, refused, expired) (D-050): new
      `sales` app, `DV-0001` numbers, price in force kept on the line, discount in %, nightly
      `expire_quotes`, "Devis" screens, demo quotes.
- [x] Convert accepted quote → sale (`create_sale_from_quote`, `convertQuoteToSale`, D-051): accepted and
      still valid, same lines and prices, the quote links to its sale. No stock is reserved. (Button on
      the quote page: P2-T04b.)

### P2-T04 · Sales · L → split in two PRs: T04a backend (D-051), T04b screens (D-052)
- [x] `Sale` + lines from a location (cold room or truck). Lines allocated to batches FIFO at confirmation
      (`post_fifo_movements`), one `SaleLineBatch` per batch.
- [x] Each line stores price, discount, **batch, unit cost** (snapshot) → COGS per line and per lot. Tax:
      empty hook until P2-T05.
- [x] `sales.services.confirm_sale(...)` posts sale movements and sets `amount_due`, all in one transaction.
      The receivable proper (payments, balance, credit limit) is P2-T06: `record_receivable` and
      `check_credit` are the hooks.
- [x] Cancel = reversal (returns to the same batches), never deletion.
- [x] Counter sale at a cold room is a first-class flow (regular, Q8): same service, location = cold room,
      walk-in customer by default. (Quick screen: P2-T04b.)
- [x] T04b: "Ventes" list/detail, sale form, quick counter-sale screen, "Convertir en vente" on a quote,
      a lot's sales on the batch page, Playwright tests.

### P2-T05 · Invoices · M
- [x] Gap-free numbering per organization per year.
- [x] Finance settings per organization, with a valid-from date (Q5, D-018): one VAT rate for all
      products (19 %), fiscal stamp (1.000 DT per invoice), whether sale prices include VAT, withholding
      rate. Editable by the owner from a finance settings screen; never hard-coded.
- [x] Optional VAT rate per product (including exempt) that overrides the company default: Tunisian
      fishing products appear as VAT-exempt in the VAT code, to check with the accountant
      (`docs/spec/sample/README.md`).
- [x] Withholding tax (retenue à la source): optional per invoice, chosen before it is issued, at the
      rate from the finance settings. When the rate is 0 % nothing about it appears on the invoice.
      It reduces the amount to collect and is tracked in P2-T06.
- [x] Issued invoice is immutable; corrections via `CreditNote`.
- [x] Leave a clear hook for TTN e-invoicing (Phase 8 backlog, D-016). Nothing is sent to TTN for now.
- [x] VAT is optional on each invoice ("sans TVA") and its rate and amount are editable on the draft, with the
      stamp and withholding rate prefilled from the settings; typed values are flagged and audited; all frozen
      at issue (D-056). Credit note dialog, print-friendly invoice page, finance settings screen (D-057).

### P2-T06 · Customer payments and balances · M
- [x] `CustomerPayment` (cash, cheque, transfer, card) allocated to invoices; unallocated credit kept.
- [x] Customer balance, ageing (0–30, 31–60, 60+ days).
- [x] Credit limit per customer, enforced on the server at sale time for every seller, drivers included
      (Q16). Above the limit the behaviour is a company setting (D-018): block the sale, ask the owner or
      manager for approval, or warn and log.
- [x] Withholding tax: the amount withheld is recorded against the invoice with its certificate (number,
      date, file); the receivable is reduced; totals per period are available to the accountant.
      (D-062 to D-065. Screens: "Règlements", balance and history on the customer page, certificate card on the invoice.)

### P2-T07 · Customer returns · S
- [x] Return → stock movement back (or to loss) + credit note. (D-070: a credit note with a stock choice.)

### P2-T08 · PDFs · M
- [x] WeasyPrint templates for quote, invoice, receipt, credit note, styled like the prototype's quote. (D-071; layout to check by eye on staging.)
- [x] Introduce Celery + Redis for generation; files stored in file storage (media volume; object storage later, D-071).

### P2-T09 · Admin screens · M
- [x] Quotes, sales, invoices, customers, payments screens. Customer page shows balance + history.
      (Quotes P2-T03, sales P2-T04b, customers P2-T01, invoices P2-T05, payments and balance P2-T06.)
- [x] Quick counter-sale screen for the cold room (`/ventes/comptoir`, P2-T04b, D-052).

### P2-T10 · Bon de livraison as source of truth (D-095) · M
- [x] BL number `BL-2026-0001`, yearly restart, given at validation (replaces the draft number); walk-in sales get one too.
- [x] BL PDF; "Valider et imprimer le BL" validates a draft first. UI says "BL" on the sale page.
- [x] Offline driver: no offline validation; the server gives the next free number on reconnect.
- [x] Part 2 (D-101): invoice from one or several BLs of a customer (N:1), BL invoiced at most once; "À facturer" filter and grouped invoicing on the sales list.
- [x] Part 3a (D-120): quotes, expenses, salary and supplier payments to `PREFIX-YEAR-NNNN`.
- [ ] Part 3b: driver app shows the BL number; the other codes (RG, FF, transfers, losses, counts...) yearly.

### P2-T11 · "Documents" page: every document as chains, with its actions (D-102) · M
Asked by Mahmoud (2026-10-12) from a screenshot of another ERP. Devis = commande client and bon d'achat (BA) =
commande fournisseur: no separate CC or CF document. Chains: DV → BL → FA → AV and BA → BR → FF.
- [x] Part 1: `GET /document-index` (new app `doclist`, no table): rows from `sales.selectors.document_rows` and
      `purchasing.selectors.document_rows`, with parents, tone, PDF kind and the actions allowed for the role.
- [x] Part 1: `/documents` screen: type chips (Ventes / Achats), search, status and period, tree or list, the
      actions run from the row (send, accept, refuse, → BL, valider, annuler, → facture, émettre, supprimer,
      → BR, clôturer, valider FF) or open the right form (modifier, avoir, réception, facture fournisseur, payer);
      "Nouveau document" (devis, BL direct, comptoir, bon d'achat, BR direct, facture fournisseur).
- [x] Part 2 (D-115): one devis delivered in several BL: `one_live_sale_per_quote` dropped, kg delivered /
      remaining per quote line (`selectors.quote_delivery`), "Convertir en vente" / "→ BL" proposes the kg left
      and refuses more; the devis page shows what is left and all its BL.
- [ ] Later: supplier return (RF) once a supplier credit note exists (`RF-` is already the supplier payment code).

### P2-T12 · Product first, no location on the sales screens (D-144) · M
Asked by the owner (2026-10-14): the seller picks the products, not the cold room or the truck.
- [x] Sale form, counter sale, quote-to-sale dialog and quote form: no location field. The place is found from the rows
      (`lib/placeStock.ts`); the grid shows the kilos left in all the places and where each product leaves from.
- [x] Sales list, sale page, a lot's sales and the quote page: no "Lieu" column or line.
- [ ] Owner question: may one sale take kilos from a cold room and a truck at once? (D-144)

### P2-T13 · Truck load split by client, one BL per client (D-160) · M
Asked by the owner (2026-10-16): the client is known from the start, so the load names who buys what.
- [x] A load (cold room → truck) holds a part per client: products, prices, small/big boxes and the delivery address.
      What is left unassigned stays on the truck for the road ("sans client").
- [x] The address starts from the client's record and is changed for this load's BL only (never written back).
- [x] Validating the load makes a draft BL per client (`Sale.transfer`), printable as "PROVISOIRE" with the address and
      the boxes; confirming it at the delivery takes the stock off the truck and gives the boxes to the client.
- [x] Driver phone: "Mes livraisons" lists the draft BL of the truck's load (`GET /my-deliveries`), one card per client with
      address, products, boxes and total; "Livré" confirms it (online only for now). A driver also sees the BL of their truck's load.
- [ ] Later: confirm a delivery offline (queue), adjust a quantity on the spot, collect payment from the same card.

### P2-T14 · Transfer typed like a spreadsheet, from the cold rooms together; driver sells to the load's clients (D-174) · M
Asked by the owner (2026-10-17).
- [x] The transfer form uses the sale grid (`LinesGrid`): one grid per client and one for what stays on the truck; the
      client's own price is proposed, and each grid shows the kilos left once the other parts are served.
- [x] "Départ" offers "Chambres froides (toutes)" or a truck, never one cold room: each line takes its kilos from the
      cold rooms that hold them (`Transfer.from_cold_rooms`). Truck → truck stays possible (no clients, no price).
- [x] Each client keeps their own BL, address and fiche (D-160, D-161).
- [x] Driver phone, "Vente": when today's load names clients, only those clients and the walk-in customer are listed
      (`GET /my-customers`, `on_load`); a client with a BL to deliver opens it; "Nouveau client" is hidden.
- [ ] Owner check on staging: a load for two clients from two cold rooms, then the driver's "Vente" list.

### P2-T15 · The BL of a load is validated at the load and delivered by the driver, in full, in part or not at all (D-178) · L
_(owner's workflow of 2026-10-17, all twelve points agreed)_
- [x] The load gives each client a validated BL with its BL number (no PROVISOIRE); nothing is sold before the delivery.
- [x] Delivery status: à livrer, livré, livré en partie, non livré; filter and pills in Ventes and on the load page.
- [x] Phone: kg delivered per line (less, more, zero takes it off), boxes, cash taken, note; "Non livré" with an optional
      note; works offline (queue). The price never changes.
- [x] Only what is delivered leaves the truck and is owed; the rest stays on the truck and goes back with the return.
- [x] Every change makes a version (`SaleRevision`); the office editing a BL on the road makes one and tells the driver.
- [x] PDF: "Commandé / Livré" columns, version, the driver's note; an empty "Livré" column on the BL to deliver.
- [x] Sending the day closing makes the BL still to deliver "non livré".
- [x] Notifications: delivered, delivered in part, not delivered (office); BL changed or cancelled (driver).
- [ ] Owner check on staging: a load for two clients, one delivered in part from the phone, one not delivered; reprint.

**Phase acceptance test:** quote 5 kg Crevette Royale at 42.000 → accept → sale from cold room → invoice
210.000 with VAT 19 % (on top or included, per the company setting) + fiscal stamp 1.000 → customer pays
100.000 → balance shows the rest; stock and batch updated; PDF correct.

### P2-T16 · Accounting review fixes: invoice VAT per line, withholding threshold (D-283) · S
- [x] An invoice's lines propose the VAT rate their BL showed; lines the BL showed without VAT are exempt (B2).
- [x] The withholding threshold of 1 000 DT is on the total without VAT + VAT, stamp and fees left out (B3).
- [x] Per-customer "soumis à retenue à la source" flag (B4, D-284): only the customers who withhold get it.
- [x] Lot revenue without VAT when prices include VAT (B5, D-285).
- [x] Supplier invoice VAT and stamp (B1, purchasing, D-286): VAT rate on the receipt, the payable with VAT and stamp.
