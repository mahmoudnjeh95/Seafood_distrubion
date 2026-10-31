# Phase 9 · Règlements & Trésorerie (D-197)

_Owner request of 2026-10-31._ A customer settles several invoices at once and pays with several means: some cash,
three traites and three cheques, each with its own due date. The same for what we pay suppliers. Then every cheque
and traite is followed until the money is really in (or out of) the bank, and the office sees its cash and bank
balances and what falls due.

Order: T01 → T07. One branch and one PR per task. Owner and manager write; the accountant reads; drivers keep
cash only on the phone (as today, D-133).

## Vocabulary (what the screens say)

| Word | Meaning |
|---|---|
| **Règlement** | One document (`RG-…` customer, `RF-…` supplier): who, the day, several **moyens de paiement**, and how the total is **affecté** to invoices. |
| **Ligne de paiement** | One means inside a règlement: Espèces, Chèque, Traite, Virement, Carte bancaire. |
| **Effet** | A cheque or a traite: a paper with a number, a bank, a drawer (tireur) and a due date (échéance). |
| **Portefeuille** | The effets we received and still hold (not yet at the bank). |
| **Remise en banque** | A deposit slip (bordereau): several effets handed to one of our bank accounts on a day. |
| **Encaissé / Impayé** | The bank credited the effet / the bank returned it unpaid. |
| **Compte de trésorerie** | Caisse (cash), a bank account, a driver's cash. Each has an append-only list of movements. |
| **Échéancier** | Effets to cash and effets to pay, by due date. |

## Rules that hold in every task

- A règlement's total = the sum of its lines = what is affecté to invoices + what stays as credit (avance).
- Affectation is per règlement, not per effet (customers do not say "this cheque pays FA-0107"). The office picks the
  invoices and amounts, or presses "Affecter automatiquement" (oldest due first).
- A règlement is never edited. A typing mistake is **annulé** (reason) and typed again. A règlement whose effet is
  already at the bank, cashed or unpaid cannot be annulé: the effet's own life handles it (T04).
- An **impayé** never edits the old règlement: it writes a new record that puts the amount back on the customer's
  balance (and the bank charges as an expense), and the invoices it paid owe again.
- The balance drops when the effet is received (provisional, Q29). The **encours** (balance + effets not yet cashed)
  is shown next to it and is what the credit limit checks (T07).
- The **retenue à la source** is not a payment line: it stays on the invoice's certificate (D-063), which already
  lowers what the customer owes. The règlement screen shows it next to each invoice so nobody counts it twice.
- Three separate balances stay separate (supplier payables, partner capital, profit shares).
- Money in `Decimal`, 3 places; every write in a service inside a transaction; audit on create, void, status change.

## Tasks

### P9-T01 · Treasury foundations + customer règlement with several lines (backend) · L
- [x] New app `treasury`: `Bank` (the list of Tunisian banks, editable per organization, seeded), `Instrument` (an
      effet: received or issued, cheque or traite, number, bank, drawer, amount, issued day, due day, status, the
      customer or supplier, the règlement number), `InstrumentEvent` (every status change: from, to, day, who, note).
- [x] Statuses. Received: `portfolio` (En portefeuille), `deposited` (Remis en banque), `cashed` (Encaissé),
      `unpaid` (Impayé), `returned` (Restitué), `endorsed` (Endossé à un fournisseur), `cancelled` (Annulé).
      Issued: `issued` (Émis), `debited` (Débité), `rejected` (Rejeté), `cancelled`. T01 writes `portfolio` and
      `cancelled` only; T04 writes the others.
- [x] `CustomerPaymentLine`: one row per means (method, amount, reference, the effet for a cheque or a traite).
      `CustomerPayment.method` is the line's method, or `mixed` ("Plusieurs moyens") when the lines differ.
      Customer methods get `bill` (Traite).
- [x] `POST /customer-payments` takes `lines` (1 to 50). A cheque asks number, bank and due day; a traite asks number,
      bank and due day, not before the day received; a due day at most 365 days ahead (provisional); the same effet
      (kind, bank, number) cannot be recorded twice. The old single `amount` + `method` still works (driver app).
- [x] Affectation by invoice: an allocation row names a `sale` or an `invoice`; an invoice's amount is spread over its
      BLs, oldest first.
- [x] Voiding a règlement cancels its effets still in portfolio, and is refused once one has moved on.
- [x] Data migration: every existing payment gets its one line; an old cheque payment gets its effet (bank empty,
      "à compléter"): in `portfolio` when received in the last 30 days, taken as `cashed` when older, `cancelled` when
      voided; the office reviews the portfolio once T04 ships.
- [x] API: `GET/POST /treasury/banks`, `PUT /treasury/banks/<id>`, `GET /treasury/instruments` (filters: direction,
      kind, status, customer, supplier, due from/to, search). Payment detail returns its lines and their effets.
- [x] Receipt PDF lists the lines (several, or a cheque/traite); the customer statement says "Plusieurs moyens".
- [x] Office, minimal until T03: the "Enregistrer un règlement" window asks number, bank, échéance and drawer for a
      cheque or a traite (Traite added to the methods).
- [ ] Check on staging: record a cheque with its bank from a customer page; the règlement list shows its number; a
      second règlement with the same cheque is refused; voiding it frees the number.
- [x] Tests: lines add up, effet checks, duplicate effet, invoice affectation, void rules, migration, API permissions.

### P9-T02 · Supplier règlement with several lines (backend) · M
- [ ] `SupplierPaymentLine` (method, amount, reference, effet issued); `SupplierPayment.method` `mixed`; `cash_on`
      moves to each line's effet (kept on the payment for the old rows).
- [ ] `POST /supplier-payments` takes `lines`; allocation per supplier invoice as today (D-043), and "auto" oldest
      due first. Issued effets: our cheque number, our bank account (T05: the account it will be debited from).
- [ ] D-192 plan lines: "Enregistrer le paiement" from several plan lines in one règlement; each named line → `paid`.
- [ ] Receipt "payer maintenant" (D-192) and port purchases (D-176) write lines too (one line each, as now).
- [ ] Void rules and data migration as in T01. Tests.

### P9-T03 · Office: the règlement screens (clients and fournisseurs) · L
- [ ] "Nouveau règlement" full page (not a small dialog): customer (or supplier) picker with its balance, encours and
      credit limit; left, the open invoices (number, date, due day, total, retenue, already paid, rest, days late)
      with a tick and an amount each; right, the payment lines (add Espèces / Chèque / Traite / Virement / Carte;
      cheque and traite ask number, bank from the list, drawer prefilled with the customer, due day); a "Répartir"
      helper for N effets of equal amounts monthly; bottom bar "Total reçu · Affecté · Reste en avance" live, red
      when the affecté exceeds the total. "Affecter automatiquement" fills oldest due first.
- [ ] Confirm window with the summary (D-179 style), keyboard friendly (Tab through lines, Enter adds a line).
- [ ] Règlements clients / fournisseurs list pages: filters (party, dates, method, status, search), totals of the
      filter, columns number, day, party, total, moyens (chips), affecté, avance, state; Excel export.
- [ ] Règlement detail page: lines with each effet's state and history, affectation, avance left with "Affecter",
      "Annuler" (reason), PDF reçu de règlement (lines and invoices), link to the customer statement.
- [ ] Settings › Banques: list, add, rename, deactivate.
- [ ] i18n FR. Vitest for the totals and the "Répartir" helper.

### P9-T04 · Portefeuille: the life of an effet · L
- [ ] Page Trésorerie › Portefeuille: tabs À remettre (portfolio), En banque, Encaissés, Impayés, Émis (ours); filters
      due day, bank, party, kind; totals; overdue in red.
- [ ] Remise en banque: tick effets, choose our bank account and the day → a bordereau (`BR-…`) with its PDF.
- [ ] Encaissé (one or many, the day the bank credited); Impayé (day, reason, bank charges): the customer owes again
      the amount (new record, D-197), charges as an expense "Frais financiers", the invoices owe again.
- [ ] After an impayé: Restituer (paper given back), or replace it by a new règlement.
- [ ] Endosser: give a received effet to a supplier as a payment line of a supplier règlement (provisional: allowed
      for cheques and traites still in portfolio).
- [ ] Issued effets: Débité (day), Rejeté (day, reason: the supplier is owed again).
- [ ] Each change is an `InstrumentEvent` and an audit entry; notifications to the owner on an impayé.

### P9-T05 · Accounts and movements · L
- [ ] `TreasuryAccount`: Caisse (one per organization, more allowed), bank accounts (bank, RIB, label), each driver's
      cash; opening balance and day. `TreasuryMovement`: append-only (account, day, signed amount, kind, source).
- [ ] Movements written by: customer and supplier cash lines, transfers and cards (to the bank chosen), effets
      cashed or debited, salaries, approved expenses paid, partner settlements, port purchases paid in cash, bank
      charges. A backfill command writes the history from the existing records.
- [ ] Driver cash: money a driver collects goes to that driver's account; the approved day closing moves it to the
      Caisse (D-134 reopening reverses it by a new movement).
- [ ] Versement espèces → banque, transfer between accounts, retrait; arrêté de caisse (counted vs expected, gap
      recorded with a reason).
- [ ] Trésorerie › Comptes page: balance per account, movements with running balance, filters, Excel export.

### P9-T06 · Échéancier and alerts · M
- [ ] Trésorerie › Échéancier: by week and month, effets to cash (in) and to pay (out), plan lines (D-192), and the
      forecast bank balance; red when a day goes below zero.
- [ ] Dashboard alerts: "N effets à remettre cette semaine", "N effets impayés", "Paiements fournisseurs du JJ/MM :
      X DT, solde prévu insuffisant". Notification the day before an issued effet falls due.

### P9-T07 · Reports and balances · M
- [ ] Customer page and ageing: solde, encours (solde + effets not yet cashed), credit limit checked on the encours.
- [ ] Cash flow report (D-116) built from the treasury movements, with opening and closing balances per account.
- [ ] Supplier side: what we owe, and our effets not yet debited.
- [ ] Rapprochement bancaire (import a bank statement and match it): backlog, only if the accountant asks.

## Defaults chosen without the owner (provisional, D-197)

- Banks: the list of Tunisian banks is editable in Paramètres › Banques.
- Drivers keep cash only on the phone; cheques and traites are entered at the office.
- Driver cash moves to the Caisse at the approved day closing (T05).
- Bank charges of an impayé or a remise go to expenses ("Frais financiers").
- Due day of an effet at most 365 days ahead.
- The balance drops when the effet is received; the encours is shown next to it (Q29).
