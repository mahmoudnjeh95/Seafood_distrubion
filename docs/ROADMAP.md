# Roadmap

Phases run in order; each one depends on the one before. Two milestones put the software in the client's
hands early instead of at the very end. Detailed tasks are in `docs/phases/`.

| # | Phase | Delivers | Blocked by questions |
|---|---|---|---|
| 0 | [Discovery & foundations](phases/00-foundations.md) | Client answers, running skeleton, login, CI, design system | none |
| 1 | [Catalogue, suppliers & stock](phases/01-stock-core.md) | Products, cold room + truck stock, batches, receipts, transfers, losses | none |
| 2 | [Customers, quotes, sales & invoicing](phases/02-sales-invoicing.md) | Quotes → sales → invoices, payments, customer balances, PDFs | none |
| 3 | [Driver app](phases/03-driver-app.md) | Phone app: day start, sales, payments, expenses, losses, day close, offline, Arabic, receipt printer | none (printer model to choose) |
| 4 | [Go-live: daily operations](phases/04-go-live.md) | Data entry from paper notebooks, production, backups, monitoring, training | none |
| | **Milestone A** | **The client runs daily operations in the app** | |
| 5 | [Expenses, payroll & assets](phases/05-expenses-payroll.md) | Expenses with approval, salaries, depreciation | none |
| 6 | [Partnerships, closing & profit sharing](phases/06-profit-sharing.md) | Agreements, month-end closing, supplier shares, statements | P0-T02 (worked example) |
| | **Milestone B** | **First month closed and partners paid from the app** | |
| 7 | [Reporting & dashboards](phases/07-reporting.md) | Dashboards, reports, Excel/PDF exports, alerts | none |
| 8 | [Scale & integrations](phases/08-scale.md) | Multi-company (confirmed goal), TTN e-invoicing (on hold), accounting export, customer portal | Q18 |
| 9 | [Règlements & Trésorerie](phases/09-treasury.md) | Règlements with several means (cash, cheques, traites) over several invoices, portfolio of effets, bank and cash accounts, échéancier (D-197, owner 2026-10-31) | Q29 (provisional answers) |

## Why this order

- **Stock before sales.** A sale has to take stock from somewhere, and its batch tells us which supplier
  it belongs to. Profit sharing depends on that link existing from the very first sale.
- **Go-live after Phase 3, not at the end.** Real use finds the real problems. Expenses and profit sharing
  need several weeks of real sales anyway.
- **Profit sharing is Phase 6 in code, but Phase 0 in thinking.** P0-T02 checks the calculation by hand on
  one real month before any code is written. The data it needs is recorded from Phase 1 onwards.

## Rules for every phase

- A phase is finished when every task's acceptance criteria pass, CI is green, and STATUS.md is updated.
- Phases 5–8 are written at a coarser level on purpose. Detail their tasks when the phase starts, using
  the answers to the open questions; don't plan in detail what the client hasn't confirmed.
- Task sizes: **S** ≈ one short session, **M** ≈ one full session, **L** ≈ split it into sub-tasks first.
