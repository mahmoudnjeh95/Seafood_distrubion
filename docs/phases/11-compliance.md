# Phase 11 · Conformité avant mise sur le marché (D-296)

_Owner request of 2026-11-08 ("need all of them"), from `docs/guides/market-readiness-review-2026-11-08.md`._
Every point of the review becomes a task here. Not all of them are code: a task marked **Owner**, **Accountant** or
**Lawyer** is done outside the repo, and the code task that depends on it waits for its answer (never invent a rate
or a legal rule, `CLAUDE.md`). Rates and thresholds of the 2026 finance law are **settings**, never hard-coded; the
accountant confirms the values from the JORT and the DGI notes.

One branch and one PR per code task. Review IDs in brackets (F1, R1…).

## Rules that hold in every task

- A legal mention missing on a document blocks only what the law needs (the seller on an invoice); the rest warns.
- Every new tax computation follows the existing pattern: pure functions, a settings version in force on the day,
  values copied onto the document when it is issued (D-057, D-018).
- Declarations are **prepared** (screens and exports to copy into the DGI / CNSS portals), not filed by the app.

## Tasks

### Wave 1: before the first paying client

- [x] **P11-T01 Invoice legal mentions (F2, F3)** · S · code. An invoice is not issued without the seller's address
  and matricule fiscal (refused by the server, "Émettre" disabled, link to Paramètres financiers); a customer without
  a tax ID or an address shows a warning on the draft. _Done 2026-11-08._
- [ ] **P11-T02 Withholding made by the company (R1)** · L · code, rates from the **Accountant**. Rates per kind of
  payment (purchases ≥ 1 000 DT TTC, rent, fees) in the settings; a supplier and an expense say whether they are
  subject; the payment withholds and owes the rest; a **certificate** PDF for the supplier; monthly totals. Split:
  T02a settings and supplier flag, T02b withholding on supplier payments and expenses, T02c certificate PDF and list.
- [ ] **P11-T03 Data protection and hosting (L1, L3)** · M · **Owner + Lawyer**, then code. INPDP declaration (and
  transfer authorization while the servers are outside Tunisia), production server apart from other clients,
  off-site backups (D-139), retention of accounting data 10 years. Code: privacy page in the admin and driver apps,
  export of an organization's data, retention rule in the runbook.
- [ ] **P11-T04 Contracts (L2, S1, S2)** · **Lawyer**. Software licence / subscription and terms of use (liability
  on tax settings stays with the client and their accountant); model contract for a partner lot (capital, profit and
  loss rates, cost keys, closing). Code afterwards (S): the lot statement prints the contract reference and a
  signature block for both.
- [ ] **P11-T05 TTN / El Fatoora (F1)** · L · **Owner** first: TTN enrolment, signing certificate (TunTrust), the
  TEIF specification (Q18, D-016). Code: TEIF XML of an invoice and a credit note, signature, sending and status,
  TTN reference and QR code on the PDF. Split once the specification is in hand.

### Wave 2: one session with the accountant, then code

- [ ] **P11-T06 Accountant session** · **Accountant**. Answers: VAT regime per product category (fresh, frozen,
  processed; F4), deduction prorata, 25 % VAT withholding of public buyers (F7), stamp on a full credit note (F8,
  B9), supplier tax status (R2), cash rules of the 2026 finance law (E1), CNSS rates and primes (P2, B6, B7), IRPP
  and CSS rules (P1), TCL / TFP / FOPROLOS rates (F6, P4). Write the answers in `OPEN_QUESTIONS.md` (Q5, Q26, new Q30+).
- [ ] **P11-T07 VAT per product category (F4)** · M · after T06. Category default rate, "Exonéré" printed instead of
  0 %, deduction prorata computed for the month.
- [ ] **P11-T08 Deductible VAT on purchases and expenses (F5)** · M · after T06. VAT, supplier tax ID and supplier
  invoice number on expenses; supplier invoices already carry VAT (D-294).
- [ ] **P11-T09 Public buyers (F7)** · S · after T06. Customer type "public": VAT withholding on top of the
  withholding on the amount.
- [x] **P11-T10 Supplier tax status (R2)** · S. Régime réel / forfaitaire / sans matricule on the supplier (forced
  to "sans matricule" without a tax ID), and "Retenue à la source sur nos paiements" (on by default), used by T02
  (D-319). _Done 2026-11-10._
- [x] **P11-T11 Cash limit on payments out (E1)** · S. Supplier payments already confirm a cash line at or above the
  limit (D-273); a port purchase records it at validation. A cash expense at or above the limit is kept but flagged
  "Espèces ≥ plafond" (likely not deductible), warned in the form (D-318). _Done 2026-11-10; the exact 2026 rule stays
  for the accountant (P11-T06)._
- [ ] **P11-T12 Payroll (P1, P2, P3, P4, B8)** · L · after T06. IRPP scale, professional expenses and family
  deductions, CSS, payslip PDF, hire and leave dates with prorata, quarterly CNSS return export, TFP and FOPROLOS.
  Until then the module is sold as "suivi des salaires".

### Wave 3: after the first clients

- [ ] **P11-T13 Déclarations du mois (F6)** · M · after T07, T08, T02. Collected and deductible VAT, carried credit,
  stamps, withholdings made, TCL, TFP, FOPROLOS; export.
- [x] **P11-T14 Withholding certificates received (R3)** · S. Already built in P2-T06: a certificate per invoice
  (file, void), and the withholding summary (`withholding-summary`) by period, month and customer: a year filter gives
  the yearly total. _Checked 2026-11-10._
- [x] **P11-T15 Write-off evidence (E2)** · S. A customer write-off says its motif: a settlement gap or an
  irrecoverable debt; the latter reads "Justificatif manquant" until a file is attached (D-298). _Done 2026-11-09._
- [x] **P11-T16 Period lock (E3)** · M. The owner locks the books up to a past day (Paramètres › Période
  verrouillée); money movements and typed dates of expenses, day labour, receipts, supplier invoices, payments and
  credit notes in the locked period are refused; reopening needs a reason (D-317). _Done 2026-11-10._
- [ ] **P11-T17 Accounting export (E4)** · M · plan of accounts from the **Accountant**. Journal entries (CSV / Excel).
- [x] **P11-T18 Lot traceability (M1)** · Built by P1-T23 (D-302): catch area, production method, origin, supplier
  health approval, scientific name, and the recall sheet of a lot. _Checked 2026-11-10._
- [x] **P11-T19 Cold chain readings (M2)** · Built by P1-T24 (D-303): a range per cold room and truck, readings by the
  office and the driver, alert out of range, arrival temperature on the receipt. _Checked 2026-11-10._
- [ ] **P11-T20 Closed seasons (M3) and port purchase circuits (M4)** · S · **Lawyer / DGPA** for the rules first.
- [ ] **P11-T21 New organization onboarding (L4)** · L. Sign-up of a company, fiscal setup wizard with neutral
  defaults, subscription, tests that one organization never reads another's data.
