# Architecture

Read only the section you need. Why each choice was made is in `DECISIONS.md`.

## 1. Shape of the system

A **modular monolith**: one Django backend split into domain apps with clear boundaries, one PostgreSQL
database, and two React front ends (admin and driver) that share a design system and a generated API
client. We split into services later only if one module really needs it; the boundaries below make that
possible without a rewrite.

```
 apps/admin (React, desktop)  ─┐
                               ├─ HTTPS /api/v1 (JSON, OpenAPI) ─ Django + DRF ─ PostgreSQL
 apps/truck (React PWA, phone) ┘                                      │
                                                     Celery + Redis (PDFs, closings, exports)
                                                     S3-compatible storage (receipts, photos, PDFs)
```

## 2. Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.13 (3.12+ supported), uv for dependencies, Django 5.2 LTS, Django REST Framework, drf-spectacular (OpenAPI) |
| Database | PostgreSQL 16+ |
| Jobs | Celery + Redis, added when first needed (PDF generation in Phase 2) |
| Files | django-storages → S3-compatible bucket (local folder in dev) |
| PDFs | WeasyPrint (HTML templates → PDF) |
| Frontend | React 19 + TypeScript 6, Vite 8, pnpm workspaces + Turborepo |
| Server state | TanStack Query |
| Client state | Zustand (UI state, multi-step forms, offline queue) |
| Forms / validation | React Hook Form + Zod (Zod schemas generated from OpenAPI with orval) |
| UI | Tailwind CSS + shadcn/ui, themed with the prototype's tokens |
| Tables | TanStack Table + TanStack Virtual |
| Driver app offline | vite-plugin-pwa (service worker) + IndexedDB queue |
| i18n | Django i18n + i18next. French default; Arabic (RTL) ready from day one |
| Tests | pytest + factory_boy; Vitest; Playwright for end-to-end critical flows |
| Quality | ruff, mypy (django-stubs), import-linter; eslint, prettier, tsc |
| Ops | Docker Compose (dev), Docker image (prod), GitHub Actions CI, Sentry |

## 3. Repository layout

```
backend/
  config/                 settings (base / dev / test / prod), urls, celery
  apps/
    core/                 Organization, User, roles, permissions, audit log, Money/Qty helpers
    catalog/              products, categories, units and conversions
    partners/             suppliers, customers, contacts
    inventory/            locations (cold room, trucks), batches, movement ledger, stock counts
    purchasing/           purchase orders, goods receipts, supplier invoices and payments (D-043)
    sales/                quotes, sales, invoices, credit notes, price lists
    payments/             customer receipts and their allocations
    fleet/                trucks, driver days, day closings, cash reconciliation
    expenses/             expense categories, expenses, approvals
    hr/                   employees, salary records, salary payments
    assets/               fixed assets, depreciation
    partnerships/         partnership lots, capital ledger
    closing/              lot costs and results, lot settlements, monthly closing (D-040)
    reporting/            read-only report queries and exports
    notifications/        office ⇄ driver notifications, written from audit entries (D-175)
    storefront/           public site: site products and web prices, orders and quote requests (D-186)
    treasury/             banks, cheques and traites (effets) and their life; later cash and bank accounts (D-196)
    demo/                 seed_dev: demo organization, logins and catalogue (may call every app)
  manage.py
frontend/
  apps/admin/             owner/back-office web app
  apps/truck/             driver PWA
  apps/site/              public site: catalogue, orders and quote requests, no login (D-186)
  packages/ui/            design tokens, icons, illustrations, shared components
  packages/api/           generated TypeScript client + Zod schemas (do not edit by hand)
  packages/monitoring/    Sentry error reporting of both apps, off without a DSN (D-140)
docs/                     STATUS, roadmap, phases, decisions, questions, spec
prototype/                approved clickable mockup
docker-compose.yml
```

### Inside each Django app

```
apps/<name>/
  models.py       data only, no business logic beyond simple properties
  services.py     every write: functions like post_movement(...), issue_invoice(...); @transaction.atomic
  selectors.py    reusable read queries
  api/            serializers.py, views.py, urls.py  (thin: validate → call service → serialize)
  tests/
```

Boundary rule (enforced with import-linter): an app may call another app's `services` and `selectors`,
never its models' internals or private helpers. `core` depends on nothing.

## 4. Hard technical rules

1. **Money** is `DecimalField(max_digits=14, decimal_places=3)`, wrapped by a `Money` helper. Rounding is
   `ROUND_HALF_UP` to 3 places at defined points only (line totals, document totals). No floats, anywhere,
   including the frontend: amounts travel as strings in JSON.
2. **Quantities** are `DecimalField(max_digits=12, decimal_places=3)` in the product's base unit (usually kg).
3. **Stock ledger.** `StockMovement` rows are append-only (type, product, batch, from/to location, qty,
   unit cost, user, timestamp, source document). `StockOnHand(location, batch)` is a cache updated in the
   **same transaction** with `select_for_update`. Negative stock is refused. A nightly check rebuilds
   on-hand from the ledger and reports any difference.
4. **Snapshots.** Sale lines store the price, cost, batch and tax used at that moment. Closings store a copy
   of the agreement terms they used. Later edits never change history.
5. **Immutability.** Issued invoices, posted movements, approved expenses and approved closings cannot be
   edited. Corrections are new documents (credit note, adjustment movement, reopened closing with reason).
   A driver's day closing is reopened by a new load of that date, also once approved: the send it undoes is
   kept as a record (`DayReopening`, D-134).
6. **Tenancy.** Every business model has `organization = ForeignKey(Organization)` (shared reference
   tables such as units excepted, D-029). Querysets are scoped by
   a base manager / mixin. One organization exists today.
7. **Idempotency.** Write endpoints used by the driver app accept a client-generated UUID
   (`client_uuid`, unique per organization). Retrying the same request never creates a duplicate.
8. **Permissions** are checked in the API layer (DRF permission classes + per-object checks). Roles today:
   `owner`, `manager`, `driver`. Drivers only see their truck of the day (D-042), their own day, and allowed customers.
9. **Audit.** Create/approve/cancel actions on financial and stock records write an `AuditLog` entry
   (who, what, when, before/after).
10. **API** is versioned under `/api/v1/`. The OpenAPI schema is the contract; the TS client is generated.
11. **Numbering.** Invoice and quote numbers come from a gap-free per-organization, per-year sequence,
    allocated inside the issuing transaction.

## 5. Scalability path (what we do now vs later)

| Concern | Now | Later, when needed |
|---|---|---|
| More users / trucks | Stateless app containers, DB indexes, pagination everywhere | Horizontal app scaling, read replica for reports |
| Heavy work | Celery jobs for PDFs, closings, exports | Separate worker pools / queues |
| More companies | `organization` FK on every table | Self-service onboarding, per-org settings, billing |
| A module outgrows the monolith | Clean app boundaries, services API | Extract that app to its own service |
| Native driver app | PWA | Wrap with Capacitor (Bluetooth printer, camera) |
| Reporting volume | SQL selectors | Materialized views or a separate analytics DB |

## 6. Environments

- **dev**: `docker compose up` (Postgres, Redis, backend, both front ends).
- **staging**: deployed from `main` automatically, sample data, used for client demos.
- **prod**: deployed from tags; daily DB backups with a tested restore.
