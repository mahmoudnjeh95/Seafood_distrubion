# Phase 13 · Easier for the office and the drivers

**Goal:** the points of the application review of 2026-11-09 (owner: "start the other points from the review now",
2026-11-13). Each task is one PR. Owner's standing rule (2026-11-10): take the recommended option, do not ask.
Things already planned elsewhere are not repeated here (P1-T27 purchase suggestions, P3-T08 driver trial, Phase 11).

## Office

- [x] **P13-T01 · Global search (Ctrl+K)** · M (D-330). One box in the header of every page finds customers,
      suppliers, products, lots, BL and invoices (five of each, two letters at least), only in the sections the person
      may read; Enter or a click opens the record.
      _Done 2026-11-13: app `apps.search`, `GET /search?q=`, `GlobalSearch` in the admin header._
      Check on staging: Ctrl+K, type part of a customer's name, Enter opens their page; a manager without "Clients"
      sees no customers in it.
- [ ] **P13-T02 · Standing orders** · M. "Refaire la dernière commande" on a customer, and a weekly template per
      customer that prepares the BL drafts of the day.
- [ ] **P13-T03 · Last price for this customer** · S. While typing a sale or quote line: the last price sold to this
      customer for the product and the margin against the lot's cost.
- [ ] **P13-T04 · Overdue reminders** · S. From the ageing list: send the statement by e-mail or WhatsApp (wa.me link)
      to one or many overdue customers.
- [ ] **P13-T05 · Form drafts kept** · S. The long forms (receipt, port purchase, invoice, sale) keep what was typed in
      the browser until saved or abandoned.
- [ ] **P13-T06 · Saved filters and bulk actions** · M. Lists keep their filters; print, e-mail or approve several rows.
- [ ] **P13-T07 · Audit history screen** · S. Read the existing audit log per record and for the owner, filtered.
- [ ] **P13-T08 · Two-step login** · M. TOTP for owner and accountant.

## Drivers

- [ ] **P13-T09 · Customer card before selling** · S. Balance, credit left, boxes owed, call button.
- [ ] **P13-T10 · "Same as last time"** · S. The customer's usual products first in the sale, one tap repeats.
- [ ] **P13-T11 · Route of the day** · M. Ordered stops with "open in Maps" and call.
- [ ] **P13-T12 · Delivery proof** · M. Signature or photo at delivery, kept with the BL.
- [ ] **P13-T13 · End-of-day summary shared** · S. Share the day's report by WhatsApp.
