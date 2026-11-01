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
- [x] `SupplierPaymentLine` (method, amount, reference, effet issued); `SupplierPayment.method` `mixed`; `cash_on`
      moves to each line's effet (kept on the payment for the old rows).
- [x] `POST /supplier-payments` takes `lines`; allocation per supplier invoice as today (D-043), and "auto" oldest
      due first. Issued effets: our cheque number, our bank account (T05: the account it will be debited from).
- [x] D-192 plan lines: "Enregistrer le paiement" from several plan lines in one règlement; each named line → `paid`.
- [x] Receipt "payer maintenant" (D-192) and port purchases (D-176) write lines too (one line each, as now).
- [x] Data migration as in T01. Tests. (Void: supplier règlements had none; it comes with the T03 screens.)

### P9-T03a · Office: the "Nouveau règlement" forms and the banks · M
- [x] "Nouveau règlement client" full page (`/reglements/nouveau`, D-210): customer picker with balance, overdue,
      effets in portfolio, encours (solde + effets, red over the credit limit) and credit limit; the open invoices and
      BLs not invoiced (due day, days late, rest) with an amount each and "Solder"; the payment lines (shared editor:
      Espèces / Chèque / Traite / Virement / Carte; cheque and traite ask number, bank, due day, drawer prefilled with
      the customer); "Répartir" for N effets of equal amounts a month apart (numbers counted on, odd millimes on the
      last); bottom bar "Total reçu · Affecté · Reste en crédit" live, red when the affecté exceeds the total;
      "Affecter automatiquement" fills oldest due first.
- [x] The supplier form (`/achats/paiements/nouveau`) uses the same lines editor, "Répartir" and bar ("Reste en
      avance"); a plan line still fills its one line.
- [x] Confirm window with the summary (D-179) before either is sent.
- [x] Banques page (`/tresorerie/banques`, side menu Finance › Banques, link from Paramètres): list, add, rename,
      take off / put back. Owner and manager write; the accountant reads.
- [x] i18n FR. Vitest for the lines, the totals and "Répartir". E2E of the supplier payment updated.

### P9-T03b · Office: règlement lists, detail pages and the supplier void · M
- [x] Règlements clients / fournisseurs list pages (D-211): filters (search, days, means, state), totals of the
      filter by means (voided left out), means as chips, voided marked, Excel export of the filter.
- [x] Règlement detail pages (`/reglements/<id>`, `/achats/paiements/<id>`): lines with each effet's state and
      history, what it settled, credit/advance left with "Affecter", "Annuler" (reason), PDF reçu (customer).
- [x] Void a supplier règlement (D-211): allocations undone (invoice status back), plan lines open again, effets
      cancelled; refused once an effet was debited or for port money. Every supplier balance, debt, statement and
      report reads only the règlements not voided.
- [x] Tests: void and its readers, list filters, totals, export, effet history (both sides); vitest for the filters.

### P9-T03c · Supplier receipt PDF and several plan lines at once · S
- [x] PDF "reçu de paiement fournisseur" (lines, effets, invoices), PDF and e-mail buttons on the detail page (D-215).
- [x] "Payer" several plan lines at once from "Règlements fournisseurs" (tick boxes, "Payer la sélection", D-215).

### P9-T04a · Portefeuille: remise en banque, encaissé, débité · M
- [x] Page Trésorerie › Portefeuille (`/tresorerie/portefeuille`, D-216): tabs À remettre, En banque, Encaissés,
      Émis (à débiter), Débités, Bordereaux; filters search, kind, bank, due days; totals (count, amount, late);
      overdue in red; tick effets, an action bar with the steps of the tab.
- [x] Remise en banque: tick effets in portfolio, choose the bank and the day → a bordereau `RB-2026-0001` (model
      `Deposit`) with its PDF (document kind `bank_deposit`), opened at once; each effet "Remis en banque".
- [x] Encaissé (one or many, the day the bank credited; also from the portfolio, cashed at the bank's counter);
      Retirer de la banque (back to the portfolio); our effets Débité.
- [x] Each change is an `InstrumentEvent` and an audit entry. Tests; vitest for the tabs.

### P9-T04b · Portefeuille: impayé and restituer · M
- [x] Impayé (day, reason, bank charges) of a customer effet at the bank or already credited (D-217): a new record
      `sales.UnpaidEffet`, the customer owes the amount again; what its règlement had settled on sales beyond its
      credit is taken back newest first (`UnpaidRelease`), so those sales owe again; the charges become an approved
      expense "Frais financiers"; the office is told; the account history and the statement show "Effet impayé".
- [x] After an impayé: Restituer (paper given back); the customer pays with a new règlement.
- [x] Portefeuille: tab Impayés, steps "Impayé" (one effet at a time) and "Restituer"; the règlement's page shows
      the impayé. Tests.

### P9-T04c · Endosser, and our effets rejetés · M
- [x] Issued effets: Rejeté (day, reason, D-218): `purchasing.RejectedEffet`, the supplier is owed again; the
      règlement's advance absorbs it first, then the invoices it settled owe again, newest first (`RejectedRelease`).
      Portefeuille › Émis › "Rejeté par la banque"; the règlement page and the supplier statement show it. Tests.
- [ ] Endosser: give a received effet to a supplier as a payment line of a supplier règlement. **Waits for the owner
      (Q29: may customer traites be endorsed to suppliers?)**; not built, per the open-question rule.

### P9-T05a · Accounts and movements (backend) · M
- [x] `TreasuryAccount` (Caisse, bank accounts with bank and RIB, each driver's cash; opening balance and day; one
      default per kind), `TreasuryMovement` append-only (account, day, signed amount, kind, source), D-219. Every
      organization starts with "Caisse" and "Banque principale" (provisional names).
- [x] Movements written by: customer and supplier cash, transfer and card lines (to the account chosen, else the
      default), the cash a driver takes (that driver's cash), effets cashed (the remise's account; at the counter: the
      Caisse), taken back after cashing, our effets debited (their account, else their bank's). A voided règlement
      writes the opposite movements. `backfill_treasury` writes the history (run at each staging start, safe again).
- [x] Versement espèces → banque, retrait, virement between accounts (MT-…, annulable); arrêté de caisse (counted vs
      expected, gap as a movement with its reason).
- [x] API: accounts, statement with running balance and its Excel export, transfers, arrêtés; `account` on règlement
      lines and on the remise. Tests.

### P9-T05b · Driver cash, salaries, expenses, partners, port purchases · M
- [ ] Driver cash: the approved day closing moves the cash the office counted to the Caisse (D-213); the D-134
      reopening keeps it (that cash already reached the office); the day's fund given to the driver.
- [ ] Movements written by: sales paid on the spot, salaries, approved expenses paid (bank charges included),
      partner settlements, port purchases paid by the driver; the backfill writes their history.

### P9-T05c · Trésorerie › Comptes page · M
- [ ] Balance per account, movements with running balance, filters, Excel export; new account, versement / retrait /
      virement, arrêté de caisse; "Compte" in the règlement forms and the remise en banque.

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

### P9-T08 · Trésorerie in the Perfaxis layout (D-230) · M
_Owner request of 2026-11-01: the module looks like the Perfaxis one (the ribbon of icon buttons, the grids, the
bordereau de versement, the états des factures); the flow and the rules stay ours. No backend change, no migration._
- [x] `TresorerieRibbon` on every treasury screen: Encaissement, Décaissement, Banque, Portefeuille, Bordereau de
      versement, Ordre de paiement, Facture de vente, Facture d'achat; the current screen is highlighted.
- [x] Bordereau de versement (`/tresorerie/bordereau`): En attente, Encaissé, Impayé; tick effets in a column, then
      Encaissé / Impayé / Restituer with the same dialogs as the Portefeuille.
- [x] États des factures (`/tresorerie/etats/ventes`, `/tresorerie/etats/achats`): invoices grouped by customer or
      supplier, net à payer, réglé, restant, état, totals.
- [x] Forms in the Perfaxis layout (D-232): Encaissement and Décaissement forms with a toolbar (Enregistrer, Retour) and
      two titled panels (informations encaissement / décaissement, informations client / fournisseur).
- [x] Export of the états (D-232): "Exporter (Excel)" writes a CSV that Excel opens (`;`, French decimal commas).
- [x] Agence bancaire and Caisse liquide (accounts, cash counts) and the Journal des banques and Journal des caisses
      (statements with running balance, Excel link) on the ribbon, over the P9-T05 accounts API (D-233).
- Sidebar unchanged: the e2e spec lists the modules by name; the treasury is reached from its existing entries.

## Defaults chosen without the owner (provisional, D-197)

- Banks: the list of Tunisian banks is editable in Paramètres › Banques.
- Drivers keep cash only on the phone; cheques and traites are entered at the office.
- Driver cash moves to the Caisse at the approved day closing (T05).
- Bank charges of an impayé or a remise go to expenses ("Frais financiers").
- Due day of an effet at most 365 days ahead.
- The balance drops when the effet is received; the encours is shown next to it (Q29).
