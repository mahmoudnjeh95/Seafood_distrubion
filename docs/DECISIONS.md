# Decisions log

One entry per decision. Newest at the bottom. Status: **accepted**, **provisional** (waiting on a client
answer), or **superseded by D-xxx**. Change a decision by adding a new entry, never by rewriting an old one.

---

**D-001 · Modular monolith: Django + DRF + PostgreSQL** · accepted · 2026-10-09
Sales, stock, payments and profit sharing must stay consistent in one transaction. A single database and
one deployable make that simple. Domain apps with enforced boundaries keep the option to split later.

**D-002 · React + Vite single-page apps, not Next.js** · accepted · 2026-10-09
The general ERP frontend guidance recommends Next.js. We use Vite instead because the backend is Django,
every screen is behind a login (no SEO or server-rendering need), and the driver app needs a service worker
for offline use, which is simpler with Vite + vite-plugin-pwa. The rest of that guidance is kept: TypeScript,
TanStack Query, Zustand, Zod, React Hook Form, Tailwind + shadcn/ui, TanStack Table, monorepo.

**D-003 · Two front ends (admin, truck) in one pnpm + Turborepo monorepo** · accepted · 2026-10-09
The driver app stays small and fast on a phone and can later be wrapped as a native app; the admin app can
grow without affecting it. Both share `packages/ui` and the generated `packages/api`. No micro-frontends.

**D-004 · `organization` foreign key on every business table** · accepted · 2026-10-09
Costs almost nothing now and avoids a painful migration if the product is later sold to other distributors.

**D-005 · Money and weights as Decimal with 3 places** · accepted · 2026-10-09
The Tunisian dinar has 1,000 millimes. Floats cause rounding errors in invoices and profit shares.
Amounts are sent as strings in JSON.

**D-006 · Stock = append-only movement ledger + on-hand cache** · accepted · 2026-10-09
Every kilogram must be traceable from receipt to sale or loss. The cache is updated in the same transaction
and can always be rebuilt from the ledger.

**D-007 · All writes go through a services layer** · accepted · 2026-10-09
The same business operation is triggered from the admin app, the driver app, offline sync, imports and
background jobs. Keeping it in one function per operation avoids duplicated rules.

**D-008 · Session cookie authentication + CSRF, same domain** · accepted · 2026-10-09
Simpler and safer than storing tokens in the browser. Works for the PWA because it is served from the
same domain. Revisit if a native app or third-party API clients appear.

**D-009 · Batch-level costing with automatic oldest-first (FIFO) batch allocation** · provisional · 2026-10-09
Supplier profit attribution needs to know which supplier's batch each sale came from. Drivers will not
pick batches by hand, so the system allocates the oldest batch first. Waiting on Q4 and Q7.

**D-010 · Agent workflow: STATUS.md pointer, one task per session** · accepted · 2026-10-09
Each session reads `docs/STATUS.md` and only the current phase file instead of the whole repo, and updates
STATUS before ending. Tasks have IDs (`P1-T06`) so the pointer is exact.

**D-011 · Third-party agent skill `find-skills` vendored in `.claude/skills/`** · accepted · 2026-10-09
Installed at the user's request from vercel-labs/skills (commit 13e4063). It is committed to the repo
(not installed user-level) because cloud sessions start from a fresh clone. Review any skill before adding it.

**D-012 · Exact, two-week-old dependency versions; TypeScript 6.0 for now** · accepted · 2026-10-09
JS packages are pinned to exact versions released at least two weeks earlier, which lowers the risk of
a compromised fresh release. TypeScript stays on 6.0 because typescript-eslint supports `<6.1`; move to
7.x when it is supported. Python dependencies are locked with uv (`backend/uv.lock`).

**D-013 · uv for Python, pnpm for JavaScript** · accepted · 2026-10-09
Both are fast, produce lockfiles, and are already used in CI images. Dev Docker images run the same
tools (`ghcr.io/astral-sh/uv`, `node:22` + corepack).

**D-014 · Batch-level FIFO costing confirmed** · accepted · 2026-10-10
Confirms D-009, which is no longer provisional. Q4: the same product can come from several suppliers in
one month and their batches are tracked separately. Q7: a sold kilo is valued at its own batch cost,
oldest batch first.

**D-015 · Plan changed after the client answers** · accepted · 2026-10-10
TTN / El Fatoora e-invoicing moves from the Phase 8 backlog to P2-T10 (Q5: required now). Arabic for the
driver app moves to P3-T09 (Q14) and Bluetooth receipt printing to P3-T10 (Q13). Printing on iPhone may
force a native wrapper, so the PWA choice in D-002 and D-003 is re-examined by the P3-T10 spike. An
`accountant` role is added in P0-T05 (Q9). Tax rate and fiscal stamp are organization settings, not
constants, because selling to other distributors is a confirmed goal (Q17).

**D-016 · TTN / El Fatoora e-invoicing on hold** · accepted · 2026-10-10
Changes D-015: P2-T10 is removed and its task list is kept in the Phase 8 backlog. Q5 says e-invoicing is
required now, but Mahmoud decided not to implement it for now. P2-T05 keeps a hook; the app issues PDF
invoices only until this is picked up again.

**D-017 · Staging and production on a VPS** · accepted · 2026-10-10
One rented server running the Docker stack: cheapest and fully under our control. We maintain the
server and the backups ourselves (P4-T03). Provider and size are still to choose.

**D-018 · Rules that may vary are organization finance settings** · accepted · 2026-10-10
VAT rate, fiscal stamp, whether sale prices include VAT, the withholding rate (hidden on invoices when
0 %) and the behaviour above a customer's credit limit (block, approval, warn) are settings per
organization with a valid-from date, editable by the owner. Other distributors will need other values
(Q17), and several of these were not fixed by the client.

**D-019 · OVH as VPS provider; stand-in data until the client's materials arrive** · accepted · 2026-10-10
Completes D-017: staging and production run on OVH. Separately, `docs/spec/sample/` holds example
products, suppliers, customers, locations, employees, an invoice and a partner agreement, built from
public Tunisian sources with invented companies and people. It feeds seeds, tests and demos only; real
client data replaces it at go-live. It does not replace P0-T02, which needs one real month.

**D-020 · Prices are dated, never fixed** · accepted · 2026-10-10
Purchase and sale prices both change from one day to the next. Purchase cost belongs to the batch
created by each receipt, with no supplier price list. Sale price is a `ProductPrice` with a valid-from
date and time, because it can change several times in one day; it is set from a "Prix du jour" screen. Sale lines snapshot the price charged and the batch cost, so past sales and
closed months never move when a price changes.

**D-021 · Quality tooling choices (P0-T04)** · accepted · 2026-10-10
- Line length 120 for Python (ruff) and TypeScript (prettier): the scaffold already used long lines.
- ESLint runs the type-aware rules, so an un-awaited promise is an error.
- The app boundary rule is a custom import-linter contract (`backend/tooling/import_contracts.py`), so
  new apps are covered without editing the config. Interpretation of ARCHITECTURE §3: `core` is the
  shared kernel and may be imported whole by every app; other apps expose only `services` and
  `selectors`; tests and `TYPE_CHECKING` imports are exempt.
- Python is pinned to 3.13 (`backend/.python-version`), the version of the Docker image.
- GitHub Actions are pinned to the commit of a release at least two weeks old, like JS packages (D-012).
- `.gitattributes` forces LF line endings so formatters give the same result on Windows.
- Known gap: D-012 covers direct JS dependencies only. pnpm's `minimumReleaseAge` would also cover
  transitive ones, but it rejects the current lockfile (rolldown 1.2.13, two days old on 2026-10-10).
  Turn it on the next time the lockfile is refreshed.

**D-022 · Core app choices (P0-T05)** · accepted · 2026-10-10
- Users log in with a username, not an email: drivers may have no email address.
- A user gets a role through a `Membership` (user, organization, role), so the same model serves
  several companies later (Q17).
- Tenancy is explicit: business code reads with `Model.objects.for_organization(org)`. No hidden
  thread-local filter, so background jobs, the shell and tests behave like requests. The API layer
  (P0-T06) must scope every queryset this way.
- `AuditLog` is append-only in code: saving an existing entry, deleting one, and bulk update or delete
  all raise. Decimals inside `before` / `after` are stored as strings.
- Money and quantity are plain `Decimal` values rounded by `money()` / `quantity()` and stored in
  `MoneyField` / `QuantityField`, not a wrapper class: Django, DRF and JSON handle Decimal natively.
  The helpers refuse floats with a `TypeError`.
- `django-stubs-ext` is a runtime dependency: it lets typed code subscript Django classes.

**D-023 · Authentication and permission choices (P0-T06)** · accepted · 2026-10-10
- The API answers 401 when nobody is logged in and 403 when the role is not allowed. The apps rely on
  it: 401 shows the login screen. DRF's stock session authentication answers 403 for both.
- Login is protected against CSRF explicitly and limited to 8 attempts per minute per account and 30
  per address. The counters live in Django's default in-process cache, so with several server
  processes each one counts separately: move them to Redis when Redis arrives (P2-T08), and set DRF's
  `NUM_PROXIES` in production so the address is the client's, not the proxy's.
- A wrong password, an unknown user and a disabled account get the same answer.
- Roles are checked by DRF permission classes built on `HasRole`; the front-end guard only improves the
  experience. The admin app accepts owner, manager and accountant; the driver app accepts driver.
- React Router for routing and TanStack Query for the session, in a shared `@frutti/auth` package
  (API helper with CSRF, session hooks, login page, route guard). It is hand-written until the
  generated client exists (P0-T09).
- Playwright tests live in `frontend/e2e` and start the backend and both apps themselves.

**D-024 · Design system choices (P0-T07)** · accepted · 2026-10-10
- Tailwind CSS 4 is configured in CSS, so the "preset" is one stylesheet, `packages/ui/src/styles.css`,
  imported by each app. The prototype's tokens stay CSS variables and are exposed as utilities
  (`bg-surface`, `text-ink-2`, `rounded-card`...).
- Light and dark switch by changing the variables (device preference, or `data-theme` on `<html>` set by
  the theme switch and kept in localStorage). Components never use Tailwind's `dark:` variant.
- Fonts are self-hosted with fontsource packages instead of Google Fonts: the driver app must work
  offline. They have no Arabic glyphs: choose an Arabic font in P3-T09.
- Icons and illustrations are the prototype's own drawings, kept as one SVG sprite (`sprite.svg`) with
  typed `Icon` and `Illustration` components. No icon library.
- Components follow the shadcn/ui approach (source in the repo, Radix for Select and Dialog, sonner for
  toasts) but are written by hand against our tokens, not generated by the shadcn CLI.
- Coral is reserved for the main action of a screen; status colours carry meaning, never decoration.

**D-025 · Internationalisation choices (P0-T08)** · accepted · 2026-10-10
- Texts live in one typed file per language in `packages/i18n` (`fr.ts` is the reference, `ar.ts` may be
  incomplete and falls back to French). Keys are checked by the compiler. Texts are bundled, not
  loaded over the network, so the driver app can show them offline.
- The language is a property of the user account, applied by the route guard after login (texts,
  `lang` and `dir` on `<html>`). The server answers a logged-in user in that language too.
- Amounts, weights and dates are formatted from the strings the API sends, with `Intl` and the locales
  `fr-TN` and `ar-TN` (Western digits in both). No JavaScript number is created for an amount.
- Layout uses logical CSS (`ms-`, `me-`, `border-e`, `text-start`) so it mirrors in Arabic.
- Server messages are written in French in the code; translations go in `backend/locale/`.

**D-026 · API contract choices (P0-T09)** · accepted · 2026-10-10
- The OpenAPI schema is committed (`frontend/packages/api/openapi.yaml`) next to the client generated
  from it, so a pull request shows every change of the contract. CI regenerates both and fails on a
  difference.
- orval generates plain functions, TanStack Query hooks, types and Zod schemas. All of them go through
  one hand-written transport, `packages/api/src/http.ts` (session cookie, CSRF token, `ApiError`).
- Every endpoint gets an explicit `operation_id` (`login`, `getSession`, `listMembers`...): it becomes
  the function name in the client.
- A backend test fails on any schema warning, because a warning means a wrong type in the client.

**D-027 · Staging on the shared OVH VPS, plain HTTP for now** · accepted · 2026-10-10
- The VPS also hosts other clients' production sites. Frutti gets its own Docker project, folder and one
  nginx site; nothing else on the server is changed. Its containers listen on 127.0.0.1 only.
- No domain yet (Mahmoud's choice), so staging is served on http://217.182.205.137, ports 8095 (admin)
  and 8096 (driver), with secure cookies, HSTS and the HTTPS redirect switched off by environment
  variables. Production keeps them on by default. Consequences until a domain exists: logins travel
  unencrypted, and the driver app cannot be installed as a PWA (service workers need HTTPS).
- Images are built on the server from a `git archive` of the committed code, so the server needs no
  access to the private repository. Secrets live in `~/frutti-staging/.env` on the server only.
- Staging demo accounts get a random password (`seed_dev --password`), never the development one.

**D-028 · Cloud session hook written by hand** · accepted · 2026-10-10
The `session-start-hook` skill named in P0-T10 does not exist from a trusted source (only small
third-party skills, 34 to 151 installs). The hook is a plain Claude Code `SessionStart` setting, so it
was written directly. It runs only when `CLAUDE_CODE_REMOTE=true`: installs backend and frontend
dependencies and starts PostgreSQL with the `frutti` role.

**D-029 · Units are shared reference data; typed weights are checked, not rounded (P1-T01)** · accepted · 2026-10-10
- `catalog.Unit` has **no** `organization` key: a kilogram means the same for every company, like a
  currency code. This is the one exception to "every business table has an organization". Anything a
  company decides about a unit (a box weight for one product) will live on its own organization-scoped
  rows, not on `Unit`.
- A data migration seeds `kg` only (Q10). Units are never deleted from the admin.
- Every quantity entering the system goes through `catalog.selectors.to_base_quantity(value, unit)`. It
  refuses any unit but kg today, so box or piece units later change one function.
- `core.money.checked_quantity` checks a weight a person typed or a scale gave and **refuses** more than
  3 decimals, negatives (the movement type carries the direction), zero (unless allowed, for counts)
  and values too large for a `QuantityField`. Rounding silently would change stock without anyone noticing.

**D-030 · Product catalogue choices (P1-T02)** · accepted · 2026-10-10
- `Product` has no price column: the sale price is the latest `ProductPrice` at or before a moment
  (D-020). A new product gets its first price from now; later prices go through `setProductPrice`, may be
  planned for later, and are refused in the past. Prices are append-only, like the audit log.
- Extra fields not in the brief: an optional **Arabic name** (drivers can work in Arabic, Q14, and the
  sample list has one) and a **drawing** from the prototype shown until a product has a real photo.
- Storage temperature is a min/max pair in °C with one decimal; either end may be empty ("≤ -18 °C").
- Product lists are **not paginated**: a catalogue holds tens of products. Revisit if one exceeds ~500.
- Every member reads the catalogue (drivers will sell from it); owners and managers change it
  (`ReadMemberWriteOwnerOrManager`). The Django admin shows catalogue rows read-only, so every change
  goes through the services and the audit log.
- Services raise Django's `ValidationError` with a message per field; one API exception handler turns it
  into a 400 shaped like serializer errors. Every app uses this from now on.
- **Photos** are re-encoded on upload (upright, at most 1200 px, WebP, no metadata: no GPS position),
  get a new random file name each time, and are served by the API to members of the same organization
  only (`/products/{id}/photo?v=…`, cached for good because the address changes with the photo). Loss
  photos and receipts will follow the same pattern. Staging keeps them in the `media` Docker volume.
- `seed_dev` moved from `core` to a new `demo` app, which may call every app, and now also creates the
  12 stand-in products of `docs/spec/sample/products.csv`.

**D-031 · Two share rates per partner; uncovered loss carried forward (Q3)** · provisional · 2026-10-10
- Mahmoud, 2026-10-10: a partner agreement has a **profit %**, used when the month's net result on the
  partner's products is a profit, and a **loss %**, used when it is a loss. The two may differ. A month
  with a zero result gives a zero share.
- Provisional, until the client confirms: when the loss share is larger than the remaining capital (or
  the partner has no capital), the capital goes down to zero and the rest becomes an amount the partner
  owes, kept in the profit-share balance and recovered from their next profit shares. Capital is never
  negative. The three balances (trade payable, capital, profit share) stay separate.
- Stand-in data: Pêcherie Kerkennah 40 % / 25 %, Surgelés du Sahel 30 % / 20 % (`docs/spec/sample/`).

**D-032 · Suppliers (P1-T03)** · accepted · 2026-10-10
- New `partners` app (ARCHITECTURE §3), which will also hold customers in Phase 2.
- `Supplier` adds three fields to the brief's list: a **reference** (`F-001`, as in the sample list; left
  empty, the server gives the next `F-NNN`), an **e-mail** and a **city**. Contacts are `SupplierContact`
  rows (name, role, phone, e-mail); a change that sends `contacts` replaces the whole list, and the audit
  log keeps the before/after list.
- The **tax ID** (matricule fiscal) is optional, unique per organization when given, and stored as
  `1234567A/A/M/000` (or `1234567A` alone); spaces, dots, dashes and missing slashes are accepted when
  typed, and a 6-digit number gets its leading zero. Other shapes are refused. Provisional: loosen it if
  the client's real list has suppliers with another identifier (CIN of a lone fisherman).
- Suppliers are **office data**: owner, manager and accountant read them, owner and manager change them,
  drivers get 403 (`ReadOfficeWriteOwnerOrManager`, new in `core.permissions`). Purchases will use it too.
- No delete: archive / restore, like products. Lists are not paginated (a handful of suppliers).
- Agreement type, balances and purchase history are **not** on `Supplier`: they come from purchases,
  payments and Phase 6 agreements. The detail screen shows a placeholder card for them.
- E2E tests log the owner in once (`owner.setup.ts`, saved session in `frontend/e2e/.auth/`): logging in
  in every test hit the limit of 8 logins a minute per account.

**D-033 · Locations and trucks (P1-T04)** · accepted · 2026-10-10
- `StockLocation` lives in a new `inventory` app (stock movements will join it in P1-T06); `Truck` in a new
  `fleet` app (driver days join it in Phase 3). `Truck.location` is a one-to-one key written by name
  (`"inventory.StockLocation"`), so `fleet` imports only `inventory.services` / `selectors`.
- A truck's **name is its location's name**, so stock screens and truck screens never disagree. A truck
  is created, renamed and archived through `fleet`; the location API refuses to create or change a truck
  location. Location names are unique per organization; plates too, stored in capitals with single spaces.
- `counter_sales` marks a cold room (or other location) where customers buy at the counter (Q8);
  `sells` is true for trucks and for those. Seeded cold rooms both sell at the counter (provisional).
- One active truck per driver at most (database constraint). Only an active member with the `driver`
  role of the same company can be assigned. Archiving a truck archives its location and takes it back
  from its driver. From P1-T06, a location still holding stock must not be archived.
- **Own truck:** `fleet.selectors.may_use_location(membership, location_id)` and `may_use_truck`. The
  office (owner, manager, accountant) may use every location; a driver only their active truck's. The
  truck API applies it (a driver lists and reads only their own truck, changes nothing); locations are
  office-only (drivers get 403 and learn their truck from `/me`).
- **`/me` truck:** `core` may not import `fleet`, so `core.session` holds a lookup that `fleet` registers in
  `FleetConfig.ready()`. `/me` returns `truck: {id, name, plate, location_id}` or null.
- The admin "Stock frigo & camions" screen manages locations for now (cards like the prototype); P1-T11
  adds the stock figures to the same screen.

**D-034 · Batches, their numbers, and the first paginated list (P1-T05)** · accepted · 2026-10-10
- `Batch` lives in `inventory`, next to the stock it will carry. It points to `catalog.Product` and
  `partners.Supplier` by name, like `Truck` does to its location. Unit cost is DT per kg without VAT, on
  the batch only (D-020); zero is allowed (free goods), negative and sub-millime costs are refused
  (`core.money.checked_amount`, the amount twin of `checked_quantity`). A receipt date in the future and
  a use-by date before receipt are refused. A batch is never edited: corrections come as new documents.
- **Numbers:** `L-` and at least 4 digits, per organization, from a `BatchCounter` row locked with
  `select_for_update` (a test runs four receipts at once). A refused batch uses no number. Gaps are
  possible only if a later step of the same transaction fails, and nothing requires batch numbers to be
  gap-free (unlike invoices).
- **FIFO order** is receipt date, then id (`inventory.models.FIFO_ORDER`, `selectors.batches_oldest_first`);
  P1-T06 allocates over it. Lists show newest first.
- **No `agreement` column yet:** the agreement table comes with P6-T01, which adds the nullable key and
  fills it from the agreement in force at each receipt date. A placeholder integer now would only have to
  be converted later.
- **Batches are created only by services** (goods receipts from P1-T07; the demo seed now). The API is
  read-only and office-only, like suppliers.
- **Pagination:** lists that keep growing (batches, later movements, invoices) use `core.api.pagination.PagedList`
  (`limit` / `offset`, 50 by default, 200 at most, answer `{count, next, previous, results}`). Short lists
  (products, suppliers, locations) stay unpaginated.
- Demo batches have no stock yet: the ledger (P1-T06) or the receipts (P1-T07) should give them an
  opening stock in the seed.

**D-035 · Stock ledger and on-hand cache (P1-T06a)** · accepted · 2026-10-10
- `StockMovement` and `StockOnHand` live in `inventory`. A movement has a kind, one batch (its product is
  copied for fast totals), a `from` and/or `to` location, a positive quantity (the locations give the
  direction), the batch's cost per kg at posting, an optional source document (generic key), the user,
  `occurred_at` (when it happened; a driver offline may sync later) and `created_at` (when posted), a
  reason and an optional `client_uuid`.
- **Sides per kind:** receipt and customer return only come in; sale, supplier return and loss only go
  out; a transfer goes between two different locations; an adjustment or a count correction names one
  location, the side giving the direction. Losses and adjustments need a reason. Locations must be
  active and of the same company.
- **Append-only** like the audit log: saving an existing movement, `update()` and `delete()` raise.
  Movements write **no** `AuditLog` entry: the ledger already records who, what and when, and an audit row
  per kilo moved would double the largest table.
- **Locking:** `post_movement` locks the on-hand rows it touches with `select_for_update`, always in
  location-id order, so crossed transfers cannot deadlock (tested with 8 at once); a missing row is created
  at zero first (`bulk_create(ignore_conflicts=True)`). Stock never goes below zero (a check constraint
  backs the service). A `client_uuid` already posted returns the existing movement.
- A location holding stock cannot be archived (also blocks archiving a loaded truck); the admin dialogs
  now show the server's reason.
- **Demo stock:** the 15 demo batches are received into the cold rooms (frozen products into "Chambre
  froide 2") and Camion 1 is loaded once. Each seeded movement has a fixed `client_uuid` (uuid5), so the
  staging deploy can run the seed every time without moving stock again.
- Tests using several database connections (`transaction=True`) also set `serialized_rollback=True`:
  otherwise the flush between tests deletes the `kg` unit made by a data migration.

**D-036 · One host name per app on staging; the apps re-read the session when refused** · accepted · 2026-10-10
- Browsers keep cookies per host name, not per port. With both staging apps on 217.182.205.137, logging
  in as `driver` on the driver app replaced the owner's session in the admin app, whose requests then
  got 403. Staging now serves each app on its own name from sslip.io (a public DNS that answers the
  address written in the name): `admin.217-182-205-137.sslip.io:8095` and
  `chauffeur.217-182-205-137.sslip.io:8096`. The bare address redirects to the name. Production gets
  one name per app on the real domain for the same reason.
- `remote-deploy.sh` writes `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` on every deploy
  (they are not secrets), so servers set up earlier follow. sslip.io is an outside service: if it is
  down, staging is unreachable by name until the domain exists.
- Both apps build their query client with `@frutti/auth`'s `createQueryClient()`: any 401 or 403 makes
  them read `/me` again, so an ended session shows the login screen and a session replaced by another
  account shows the wrong-app notice, instead of a screen whose saves fail with a generic error.
- gunicorn runs with `--no-control-socket`: its control socket wanted to write in the `app` user's home
  folder, which does not exist in the image, and logged an error at every start. Nothing used it.

**D-037 · FIFO allocation and multi-batch movements (P1-T06b)** · accepted · 2026-10-10
- `inventory.selectors.allocate_fifo(organization, product_id=, location=, quantity=)` previews which
  batches a quantity would come from: the location's on-hand rows of that product, oldest receipt first
  (`FIFO_ORDER`), each batch emptied before the next. More than the location holds is refused on
  `quantity`, with the kg available. Nothing is locked or posted.
- `inventory.services.post_fifo_movements(...)` does it for real: it locks every on-hand row of the
  product at both locations in (location, batch) order, the same order `post_movement` uses, splits the
  quantity oldest first and posts one movement per batch, all in one transaction (refused as a whole).
  Kinds that take nothing (receipt, customer return) are refused. Used by transfers (P1-T09), sales
  (Phase 2) and losses (P1-T10).
- **Idempotency** for a request split over several batches: the n-th movement gets
  `uuid5(client_uuid, n)`; a retry finds part 0 and returns all the parts already posted.
- A destination row that does not exist yet is created during posting; in the rare case that two
  requests create it while crossing, PostgreSQL aborts one with a deadlock error (no hang) and the client
  retries. The test with 8 crossed loads and returns at once passes.

**D-038 · Stock on hand checked against the ledger, nightly and on demand (P1-T06c)** · accepted · 2026-10-11
- `inventory.selectors.on_hand_differences(organization)` sums the movements per (location, batch) and
  compares them with `StockOnHand` in **one SQL statement**, so both are read from the same snapshot
  and a movement posted meanwhile never shows as a false difference. Missing rows and rows with no
  movement are covered (full outer join).
- `inventory.services.rebuild_on_hand(organization, actor)` sets the cache back to the ledger and writes
  one `stock.on_hand_rebuilt` audit entry with the rows before and after. It first takes
  `LOCK TABLE … IN EXCLUSIVE MODE` on the cache: writes wait a few milliseconds, reads do not, and
  since `post_movement` touches the cache before writing its movement, no movement is caught halfway.
  A ledger that would give negative stock (only possible by editing the database) is refused, not
  "repaired".
- `manage.py rebuild_on_hand` repairs every organization; `--check` only reports and fails (exit 1) on a
  difference, logging each one as an error (Sentry once its DSN is set). Repairing stays a human
  decision: a difference means a bug or a hand edit, to be understood first.
- **Nightly, without Celery or the shared server's crontab:** a `nightly` service in
  `compose.staging.yml` runs the backend image and sleeps until just after 03:00 UTC (04:00 in Tunisia),
  then runs the check. It moves to Celery beat when Celery arrives (ARCHITECTURE: Phase 2).

**D-039 · Goods receipts (P1-T07)** · accepted · 2026-10-11
- New `purchasing` app (ARCHITECTURE §3): `GoodsReceipt` (number `BR-0001`… per organization from a locked
  counter, supplier, receiving location, date, supplier's delivery note or invoice number, notes, who
  typed it) and `GoodsReceiptLine` (product, its batch one-to-one, ordered kg or empty, invoiced kg,
  accepted kg, cost per kg). Weights are net (Q12).
- **Saved = posted.** `services.create_receipt` checks everything first, then in one transaction makes one
  batch per line (`inventory.services.create_batch`, cost on the batch, D-020), posts a `receipt`
  movement of the **accepted** weight with the line as source document, and audits. There is no draft
  and no edit: a mistake is corrected by a supplier return or an adjustment, like every posted record.
  A receipt typed later for an earlier day posts its movement at noon of that day.
- **No `PurchaseOrder` yet:** the client works from notebooks and phone calls; the optional ordered
  weight on the line gives the "ordered vs received" difference. A purchase order document can be
  added later without changing receipts.
- **Errors per line** come back on flat keys `lines.<index>.<field>` (and the header's on their own
  field), all at once. Weights and costs travel as strings and are checked by the service
  (`checked_quantity`, `checked_amount`), so a typed "20,5" is refused there, not rounded.
- **Amounts:** invoiced amount = invoiced kg × cost (what the supplier will charge, P1-T08); accepted
  amount = accepted kg × cost (value entering stock). Each line is rounded, then added. A line differs
  when accepted ≠ invoiced, or ≠ ordered when there was an order; `listReceiptDifferences` is the report.
- **Last cost:** `inventory.selectors.last_batches_from(supplier)` (latest batch per product). The form
  fills the cost with it until the person types one, and shows the change in percent.
- **Admin screens:** "Achats" lists receipts (paginated, search, "with differences" filter), a receipt
  page shows lines, batches and the weight-difference notice of the prototype, and "Nouvelle
  réception" records one. Browser-side previews of amounts use exact `bigint` thousandths
  (`apps/admin/src/lib/decimal.ts`, unit-tested: the admin app now runs vitest); the server stays the
  reference. `formatPercent` joins the i18n formatters.
- Demo: receipt `BR-0001` from Mareyeur Port de Sfax today, dorade 62 kg ordered and invoiced, 60 kg
  accepted (the prototype's difference and the start of the Phase 1 acceptance test).

**D-040 · Profit is computed and shared per lot, not per month (client meeting)** · accepted · 2026-10-11
Source: `docs/spec/client-meeting-2026-10-11.md`. Partly supersedes the month-end parts of Q2, Q3 and Q9
and the Phase 6 plan written from them.
- The unit of profit is the **lot** (`Batch`). A lot collects its sales (FIFO already links each sale
  line to its batches), its purchase cost, and its own costs: typed costs (fuel, transport, misc.), day
  labour, monthly employees at days × salary / 26, cold-room days, and a share of rent and accountant.
- A lot is **closed** when it is fully sold (or written off) and settled; its result is then frozen
  (immutable, corrections are new records on a later settlement). Spoilage is a cost of its own lot.
- **Partnership lot:** the owner and a partner supplier each put an amount into the lot. On closing,
  the partner gets their % of the net profit, or carries their % of the loss, deducted from the capital
  they put in (Q3). Confirmed: one partner per lot, two rates (D-031), settlement = capital put in ±
  their share; a supplier can be a partner in several lots at once. Capital, trade payable and profit
  share stay three balances.
- A partnership lot never mixes with other lots: it is its own `Batch`, and FIFO already keeps batches
  apart from the cold room to the truck to the sale.
- The **average purchase price** per product (weighted by kg on hand) is shown for pricing only; it never
  values a sale (Q7 stays FIFO per batch).
- The month-end closing stays for the accountant's monthly result (P6), but no longer decides partner
  shares.

**D-041 · Lot cost rules: cold room, salaries, truck, general costs** · accepted · 2026-10-11
- **Cold room:** monthly electricity bill → split over cold rooms by a weight per room (default equal,
  set by the owner) → per day → per lot by kg held that day (from the ledger, as Q2 said). Until the
  bill is typed, the previous month's daily rate is used; when it arrives, the difference on lots
  already closed is booked on the next settlement, never by reopening them. Confirmed.
- **Monthly employees:** days worked on the lot × monthly salary / 26 (client, 2026-10-11).
- **Truck costs of the day** (transport, labour, misc. tagged to a truck and a date): split over the
  lots on that truck's load that day, **by kg loaded** (provisional: the client said "split over the
  lots", not how).
- **Rent, accountant and other general costs:** "like a salary" (client): monthly amount / 26 per day;
  each day's amount split over the lots in stock that day by kg held, the same way as the cold room
  (**confirmed 2026-10-13**, Q21).
- **Day labour:** one record (date, worker, amount paid, optional lot). Typed from the lot or from the
  calendar, it is the same record; without a lot it is a general cost.

**D-042 · A driver's truck is chosen per day, not fixed** · accepted · 2026-10-11
Supersedes the "one active truck per driver" and "own truck" parts of D-033 (client meeting).
- A driver may drive truck X today and truck Y tomorrow. The truck of the day is set by the office or by
  the driver from the phone; one driver per truck per day (confirmed). It lives on the driver's day (`DriverDay`, P3-T01), not on the truck.
- "Own truck" becomes "the truck of my open day": `may_use_location` / `may_use_truck` and `/me` read
  the open day. Until Phase 3 exists, the `Truck.driver` field stays as the default proposal.
- A truck load carries the price per kg of each product for that day; the evening return shows sold vs
  returned (P1-T09, P3-T01, P3-T06).

**D-043 · Supplier invoices, payments and the supplier balance (P1-T08)** · accepted · 2026-10-11
- In `purchasing` (not a separate `payments` app, which ARCHITECTURE §3 now keeps for customer
  receipts): `SupplierInvoice` (number `FF-0001`… per organization, supplier, the supplier's own invoice
  number, date, due date, status, total, notes, who typed and who posted it), `SupplierInvoiceReceipt`
  (receipt one-to-one: a receipt is on one invoice at most, draft or posted; with its amount),
  `SupplierPayment` (number `RF-0001`…, date, amount, method, cheque/transfer reference, notes) and
  `SupplierPaymentAllocation` (payment → invoice, amount). Numbers come from a locked `DocumentCounter`
  per organization and kind; a deleted draft leaves a gap (these are not fiscal numbers).
- **The amount is never typed:** an invoice's total is the sum of its receipts' invoiced amounts
  (invoiced kg × cost per line, rounded per line, D-039). A supplier whose paper invoice differs is
  corrected on the receipt side (later: supplier credit note), not on the invoice. No VAT on supplier
  invoices for now: costs are without VAT (D-020); provisional until the accountant answers Q5.
- **Status:** `draft` (receipts, dates, reference and notes can change; can be deleted) → `posted`
  (immutable, counts in the balance; `post` can be given on create/update to post at once; a zero total
  is refused) → `partly_paid` → `paid`, moved only by allocations. A posted invoice is never edited or
  deleted; a correction will be a supplier credit note (not built yet).
- **Payments** are immutable. Allocations go to posted, not fully paid invoices of the same supplier,
  never above what is left on an invoice, and together never above the payment. The part not allocated
  is an **advance**: already deducted from the balance, allocated later (`allocateSupplierPayment`).
  Errors come back on `allocations.<index>.<field>`, like receipt lines. Methods: cash, cheque,
  transfer, bill of exchange (traite), other (provisional list).
- **Supplier balance = posted invoices − payments** (negative = advance). The balance endpoint also
  gives what is still owed on invoices, what is overdue (due date passed), unallocated advances, drafts
  and receipts not invoiced yet; the supplier page shows it. It is the **trade payable only**: a
  partner's capital and profit share (D-040, Phase 6) are separate balances and never pass through
  these tables.
- **Due date:** typed; the form proposes invoice date + 30 days (provisional, no client answer on
  payment terms). An archived supplier can still be invoiced and paid (debts outlive the archive).
- Permissions as receipts: owner/manager write, accountant reads, drivers 403. Enum schema names are
  pinned (`SupplierInvoiceStatusEnum`, `PaymentMethodEnum`) so later sales documents do not collide.
- Admin "Achats" gets tabs Réceptions · Factures · Paiements: invoice list (status, overdue, supplier
  filters), invoice page (post, edit, delete draft, pay), invoice form (pick the supplier's receipts not
  invoiced yet), payment form (spread over the oldest due dates, or pay the invoice it came from),
  payments list with "Affecter" for advances. Demo: `FF-0001` for `BR-0001` (1 471,500 DT), posted,
  `RF-0001` 500 DT by cheque: Mareyeur Port de Sfax owes 971,500 DT.

**D-044 · Transfers between locations (P1-T09)** · accepted · 2026-10-11
- `Transfer` + `TransferLine` live in `inventory` (number `TR-0001`… from a locked `DocumentCounter` row
  per organization and series, reused by the next stock documents). A line is a **product and kg**, one
  line per product; batches are never picked by hand: validation calls `post_fifo_movements` per line
  with the line as source document, and `movements_from_sources` reads back which batches went.
- **Kind comes from the places, never typed:** into a truck = `load`, out of a truck = `return`,
  anything else (cold room ↔ cold room, truck ↔ truck) = `internal`.
- **Draft → validated (or cancelled).** Owner and manager prepare and validate (the accountant reads,
  drivers get 403: transfers are office documents until Phase 3). A draft moves nothing and can be
  changed (lines replaced) or cancelled; validation moves the stock and freezes the document, and a
  mistake is corrected by a transfer the other way. "Save and validate" is one transaction: a refusal
  leaves no draft behind. A day still to come can be prepared but is validated that day. A transfer
  typed for an earlier day posts its movements at noon of that day (as receipts do).
- **Refusals:** every line is tried inside its own savepoint, so all the lines short of stock come back
  together on `lines.<index>.quantity`, then the whole validation is refused. Lines are posted in
  product order, so two transfers validated at once lock rows in the same order (no deadlock; tested
  with opposite line orders). The transfer row itself is locked, so one draft is never validated twice.
- **Price of the day** (client meeting): only load lines carry `unit_price`. Left empty, the service takes
  the `ProductPrice` in force at the transfer's moment; a typed price must be > 0. It is stored on the
  line, so later price changes never rewrite a load. No price in force and none typed is refused on
  `lines.<i>.unit_price`. The form shows the price in force and the kg available at the source.
- **Truck day** (`getTruckDay?location=&date=`): per product, kg loaded and returned by the **validated**
  transfers of that date, loaded − returned = "sold or lost" (the client's formula), the day's price
  (last validated load's) and its value. Provisional: it reads documents, not the ledger, so stock
  already on the truck in the morning is not counted; until sales are recorded (Phase 2/3), kilos sold
  stay on the truck in the ledger. Phase 3's day closing replaces this with sales and losses.
- **Phase 3 hook:** `confirmed_by` / `confirmed_at` (the driver confirms the load on the phone) and a
  `client_uuid` (a retried request returns the transfer already made) exist but nothing sets the
  confirmation yet. No reliance on `Truck.driver` (D-042).
- **Screens:** the "Stock" entry gets section tabs (Emplacements, Transferts); "Transferts" lists them
  (search, type), a form creates or edits a draft ("Tout reprendre" fills a return with everything at
  the source), and a transfer page shows lines, batches, price and value, the actions of a draft, and
  the truck's day. `GET /locations/{id}/stock` gives the kg per product of a place.
- Demo: Camion 2's day (morning load with dorade at 25.000 DT instead of 24.500, evening return) and a
  draft load of Camion 3; fixed `client_uuid`s keep the seed idempotent. Three spectacular enum names are
  pinned (`StockLocationKindEnum`, `TransferKindEnum`, `TransferStatusEnum`) so a second "kind" or
  "status" choice set elsewhere does not rename them.

**D-045 · Losses and stock counts (P1-T10)** · accepted · 2026-10-11
- **Loss** (`StockLoss`, `PE-0001`… from the `DocumentCounter` of D-044): location, product, kg, reason
  (avarié, abîmé ou écrasé, date dépassée, rupture du froid, autre) with a note, day, optional photo,
  `client_uuid` for the driver app (Phase 3). Kilos leave **oldest batch first** (`post_fifo_movements`,
  kind `loss`, the loss as source, the ledger reason "Avarié · note"); nobody picks the batch. A loss is
  checked against the stock when typed (FIFO preview) and again when posted.
- **Threshold in kg, provisional:** `StockSettings.loss_approval_threshold` per organization, default
  **2 kg**, changed by the owner only (`updateStockSettings`). Up to it a loss leaves the stock at once;
  above it it stays `pending` (nothing moves) until the **owner** approves (posted then) or refuses with a
  reason. The owner's own losses never wait. Kg rather than dinars: the driver who reports a loss in
  Phase 3 does not see costs; a value threshold can be added later. Owner-only actions are checked in
  the view (403 for a manager). A decided loss never changes; a photo can be joined **once** (proof),
  turned upright, shrunk and stored as WebP like product photos (the helper moved to `core.images`).
- **Count** (`StockCount` + `StockCountLine`, `INV-0001`…): starting one for a location makes the sheet,
  one line per batch held, with the kg the ledger expects at that moment (a snapshot); one open count per
  location (constraint + row lock). People type the kg found (0 when nothing); approval needs every line
  counted and posts one `count_correction` per line whose counted kg differ from the **sheet**, applied to
  the current stock. So movements made while counting (a truck loaded meanwhile) are not undone; a
  shortage larger than what the batch still holds is refused on that line and nothing is posted. Lines
  are posted in batch order (same lock order as other postings). Errors name lines by their place on the
  sheet as the API lists them (`COUNT_SHEET_ORDER`). Provisional: a batch found that is not on the sheet
  cannot be added yet.
- Owner and manager start, fill, approve and cancel counts and record losses; the accountant reads;
  drivers get 403 (Phase 3 adds their loss report from the phone).
- **Screens:** "Pertes" (list by status, the threshold and its owner dialog, a form with an optional
  photo, a loss page with batches, cost, photo and the owner's approve / refuse) and "Inventaires" (list,
  a dialog to start a sheet, the sheet with "Reporter l'enregistré", live differences, save, approve,
  cancel) join the stock section tabs.
- Demo: PE-0001 (1.5 kg of mussels on Camion 1, the prototype's loss, already out), PE-0002 (4 kg of rouget
  waiting for the owner) and an open count INV-0001 of the frozen cold room.

**D-046 · Truck of the day: assignment per date (P1-T12)** · accepted · 2026-10-11
Builds D-042 before Phase 3's `DriverDay` exists.
- `fleet.TruckAssignment` (organization, truck, driver, date): unique per truck and date and per driver and
  date (database constraints, plus clear service errors naming who has the truck or where the driver is).
  `Truck.driver` stays as the **usual driver**; the "one active truck per driver" constraint is gone, a
  driver may be the usual driver of several trucks.
- Truck of the driver today = today's assignment; without one, the truck they usually drive unless
  another driver was assigned to it that day (then none). Several usual trucks: first by name.
  `may_use_truck`, `may_use_location`, the truck list for drivers and `/me` all use it.
- Set by owner/manager for any driver and any day, or by a driver for themselves (today or later).
  The office must remove an assignment before giving the driver another truck; a driver's own new choice
  replaces their previous one. Accountant reads only. Archiving a truck drops its assignments from today.
- API: `GET/POST /api/v1/truck-assignments`, `DELETE /api/v1/truck-assignments/<id>`. Admin: "Camions du
  jour" section on the stock screen. A driver-side screen to pick the truck comes with Phase 3.

**D-047 · Customers (P2-T01)** · accepted · 2026-10-11
- `Customer` and `CustomerContact` live in the `partners` app beside suppliers and copy D-032: reference
  `C-NNN` generated when left empty, optional tax ID in the same `1234567A/A/M/000` shape (unique per
  organization when given), contacts replaced as a whole list, no delete (archive / restore), audit before/after.
- Fields beyond the suppliers': `kind` (restaurant, hotel, fish shop, supermarket, wholesaler, caterer,
  individual), `credit_limit` (Decimal, 3 places, 0 = no credit, Q16) and `payment_terms_days` (0 to 365,
  0 = on delivery). What happens above the limit is a company setting of P2-T06, not stored here.
- **Walk-in customer** ("Client de passage"): `is_walk_in`, one per organization (partial unique
  constraint), created by `partners.services.ensure_walk_in_customer` (idempotent; the seed and counter
  sales call it), never archived, credit limit always 0. It is listed last.
- Customers are **office data** like suppliers: owner, manager and accountant read, owner and manager
  change, drivers get 403 (`ReadOfficeWriteOwnerOrManager`). Provisional: the driver app (Phase 3) will need
  a narrower endpoint (name, reference, credit left) for choosing a customer on credit; add it then.
- The balance, opening balances (`opening_balance_dt` of the sample CSV) and history are not on `Customer`:
  they come from sales, invoices and payments (P2-T04 to P2-T06). The seed loads limits and terms only.
- `ENUM_NAME_OVERRIDES` in the schema settings names the customer kind enum `CustomerKindEnum`: several
  models have a `kind` field and the generated names collided.

**D-048 · Stock screens and purchase prices (P1-T11)** · accepted · 2026-10-11
- Read-only: three office endpoints in `inventory` (drivers get 403): `getStockOverview` (each active location
  with kg and cost, each product with kg per location, low-stock flag and prices), `getProductStock` (the same
  for one product plus the batches still on hand with their locations) and `listMovements` (the ledger,
  paginated, filters location / product / batch / kind / date_from / date_to). Nothing writes `StockOnHand`.
- **Value of a location** = sum of kg × the unit cost of each batch it holds (cost, never sale price).
- **Average purchase price** of a product = cost per kg weighted by the kg still on hand over all batches and
  places (`selectors.average_purchase_cost`); empty without stock. **Last cost** = unit cost of the latest batch
  received (by receipt date, then id), kept even when that batch is sold out. Both are pricing information
  only; a sale is still valued FIFO per batch (D-040).
- **Low stock** = total kg over every place is below `Product.min_stock` (a minimum of 0 never warns). The
  stock page lists products that hold stock, plus active products with a minimum, so an empty shelf shows low.
- UI: "Emplacements" (`/stock`) keeps its cards and gains kg and cost on each, then product cards like the
  prototype; new "Mouvements" tab (`/stock/mouvements`); product page `/stock/produits/:id`; batch page
  `/stock/lots/:id`. Filters on the movement list are native selects (a Radix select cannot hold "all").

**D-049 · Prices (P2-T02)** · accepted · 2026-10-11
- **Prix du jour** (`GET/POST /api/v1/price-board`, screen `/prix`): every active product with the price in
  force, the cost of the batches in stock and the margin. Costs come from `inventory.selectors.on_hand_of`
  (all locations together): last cost = the most recently received batch still in stock, average = weighted
  by kg in stock; the margin (DT/kg and % of the price) is taken against the **average** cost. A product
  with no stock shows no cost. Costs are office data: drivers get 403 on the board; the accountant reads.
- `catalog.services.set_sale_prices` saves many prices in **one transaction** (all or nothing, products
  locked in id order). Each changed price is a new `ProductPrice` from that moment (D-030: history is never
  overwritten, so changing it again the same day just adds a row); a price equal to the one in force is
  skipped. The board lists the prices that started today with who set them and when.
- **Minimum price** per product (`Product.min_price`, optional, set from the board). A price below it is
  accepted and returned in `below_minimum` (screen warning); the audit logs `product.price_below_minimum`.
  Changing the minimum is audited too (`product.min_price_set`).
  The admin sale form and the counter sale also show a red alert as the price is typed (2026-10-14): still
  a warning, never a block.
- **Price lists** (`PriceList` + `PriceListItem`): a name, optionally one customer (one list per customer,
  customer checked through `partners.selectors`), an active flag and items (product, price) replaced as a
  whole on update; audited. API `price-lists` (members read, owner/manager write). No admin screen yet.
- `catalog.selectors.price_in_force(product, at, customer_id=None)` is the single answer to "what do we
  charge": the customer's active list price if it holds the product, else the daily price. Provisional: a
  price list has no validity dates and no quantity tiers. The sale line snapshot and the use of this
  selector by sales are P2-T04; loads keep reading the daily price (D-044).

**D-050 · Quotes, and the new `sales` app (P2-T03)** · accepted · 2026-10-11
- New `sales` app (ARCHITECTURE §3), which sales, invoices and credit notes (P2-T04, P2-T05) will extend.
  Its own `DocumentCounter` (organization, series, locked with `select_for_update`) gives `DV-0001`… per
  organization. The number is taken when the draft is created and a quote is never deleted, so there are
  no gaps. Not per year, unlike ARCHITECTURE §4.11: a quote has no legal numbering; invoices (P2-T05)
  can use a per-year series in the same table ("FA-2026").
- `Quote`: customer (`partners.Customer`), optional **location** (the cold room or truck whose stock the
  form shows, information only: **nothing is reserved**), quote date (not in the future), validity date
  (included; default quote date + **3 days**, the prototype's "valable 3 jours", provisional), notes,
  status, who prepared, sent and answered it, refusal reason, `client_uuid` (the seed; later the driver
  app). `QuoteLine`: product (one line per product), kg, price per kg, **discount in %** (0–100, two
  decimals), and the amounts computed by the service: gross = kg × price, discount = gross × % / 100,
  each rounded once half up, amount = gross − discount. Quote totals (gross, discounts, total excl. tax)
  are stored by the service with the lines.
- **Prices:** a line without a typed price takes what the customer is charged at the quote's moment (now
  for today, noon of an earlier day: same rule as loads, D-044) through
  `catalog.selectors.price_in_force(product, at, customer_id=)` (D-049): the customer's active price list
  when it holds the product, else the daily price. The line keeps it: later price or list changes never
  touch the quote (D-020). The form proposes the same price ("Prix du client (liste) : …" or "Prix en
  vigueur : …"). No price and none typed is refused on `lines.<i>.unit_price`. Minimum prices (D-049) are
  not checked on quotes yet.
- **VAT hook:** `tax_amount` is empty and `total` = total excl. tax until P2-T05's finance settings (D-018)
  decide the rate and whether prices include VAT. The quote page shows "TVA : avec la facturation". No
  fiscal stamp on a quote.
- **Statuses:** draft → sent → accepted or refused; a sent quote whose validity date has passed is
  expired. Only a draft changes (lines replaced as a whole) and only a draft can be sent (not once its
  validity date has passed). Accepting needs a sent quote still valid; refusing (with an optional reason)
  is allowed even after the validity date. Every step is audited and locks the quote row.
- **Expiry** is read and written: `selectors.current_quote_status` shows a sent quote past its date as
  expired in lists, filters and pages at once; the nightly `expire_quotes` command (staging `nightly`
  service, after the stock check) writes the status down with `expired_at` and an audit entry. A draft
  never expires: its dates can still be changed.
- **P2-T04 hook:** the accepted quote keeps customer, location, lines and prices. Converting it into a
  sale is P2-T04's (no `converted_sale` key yet), which also decides whether an accepted quote can still
  be converted after its validity date.
- Office documents like transfers: owner and manager prepare, send and record answers, the accountant
  reads, drivers get 403 (`ReadOfficeWriteOwnerOrManager`). API: `listQuotes` (paginated, status,
  customer, days, search), `createQuote` / `updateQuote` (`send_now` saves and sends in one
  transaction), `getQuote`, `sendQuote`, `acceptQuote`, `refuseQuote`. `QuoteStatusEnum` is pinned in
  `ENUM_NAME_OVERRIDES`.
- **Screens:** "Devis" (list with status filter and search), a quote page laid out like the prototype's
  printed quote with a follow-up card and the actions of its status, and a form showing the price in
  force and the kg held at the chosen location for each product, with exact previews of the amounts
  (`percentOf` joins `lib/decimal.ts`).
- Demo: DV-0001 to Restaurant Le Corail (5 kg Crevette Royale at 42.000, Calamar, Symphonie Marine:
  379.500, the prototype's quote and the start of the Phase 2 acceptance test), one sent to Hôtel Thyna,
  one accepted, one refused, one draft; dated the day of the first seed, so the sent ones expire later.

**D-051 · Sales: documents, lots sold, cancellation and quote conversion (P2-T04a)** · accepted · 2026-10-11
- In the `sales` app: `Sale` (number `VE-0001`… from the quotes' `DocumentCounter`, taken with the draft;
  a sale is never deleted, so no gaps), customer, **place** (a cold room with `counter_sales` or a truck:
  `StockLocation.sells`), `sold_at` (date and time; not in the future, 5 minutes of clock margin), status
  `draft` → `confirmed` or `cancelled`, notes, the quote it came from, totals as on quotes (`tax_amount`
  empty, `total` without VAT: P2-T05 hook), `cost_total`, the payment on the spot and `amount_due`.
  `SaleLine`: product (one line per product), kg, price per kg actually charged, `price_source`
  (customer's list, daily price, quote, typed), `below_minimum`, discount %, amounts, `cost_amount`.
- **Prices:** an empty price takes `catalog.price_in_force(product, sold_at, customer_id=)` (D-049) and is
  kept on the line (D-020); a draft keeps its moment's prices until it is retyped. A price below the
  product's minimum is accepted, flagged on the line and audited at confirmation (`sale.price_below_minimum`).
- **Lots (D-040):** confirming posts each line with `post_fifo_movements` (kind `sale`, the line as source,
  at `sold_at`), lines in product order inside their own savepoints (all shortages come back together on
  `lines.<i>.quantity`, then all is refused; the sale row is locked), and writes one **`SaleLineBatch`**
  per batch taken: kg, the batch's cost per kg then, cost = kg × cost (rounded once) and the line's
  amount **shared by kg** (each part rounded, the last batch takes the rest, so parts add up to the line).
  `selectors.batch_sales` / `batch_sales_totals` give a lot's kg sold, revenue, COGS and margin over
  confirmed sales: the sales side of the Phase 6 lot result. `getBatchSales` exposes it (office only).
- **"Save and confirm"** (`confirm_now`) is one transaction: a refusal leaves no draft behind. A
  `client_uuid` already used returns the same sale (driver app, seed).
- **Cancel = the sale stays.** A draft just becomes cancelled. A confirmed sale needs a reason; its kilos
  come back **to the same batches at the same place** by `customer_return` movements (cost = the batch's,
  unchanged), its lot rows stay and stop counting (status). No separate reversal document: the ledger's
  return movements, the cancelled status, who/when/why and the audit entry are the reversal. Hooks: an
  invoiced sale will need a credit note (P2-T05); money already paid becomes customer credit (P2-T06).
- **Payment on the spot** (minimal until P2-T06): `amount_paid` (≤ total), `paid_in_full`, method (cash,
  cheque, transfer, card: `SalePaymentMethodEnum`, a list of its own since suppliers use traite and not
  card) and a reference; `amount_due` = total − paid is the receivable. `check_credit` and
  `record_receivable` are the P2-T06 hooks; today `check_credit` only enforces that the **walk-in
  customer** (used when no customer is given, `ensure_walk_in_customer`, D-047) pays everything.
- **From a quote:** `create_sale_from_quote` takes an **accepted quote still valid** (validity date not
  passed, provisional), same customer, products, kg, prices and discounts (`price_source` = quote), place =
  the quote's or one given. The quote stays accepted; `Sale.quote` links them and the quote API shows its
  live `sale`. One live sale per quote (partial unique constraint); after cancelling it, the quote may
  be converted again. Audited `quote.converted`.
- **Who:** owner and manager sell anywhere and cancel; the accountant reads; a **driver** sells (creates,
  changes and confirms their own drafts) only from the truck of their day (`fleet.may_use_location`, 403
  otherwise), always "now" (a `sold_at` sent by a driver is ignored until Phase 3's offline sync), sees
  only the sales they made, never costs (cost fields are null) and cannot cancel. A truck sale takes the
  customer's price in force, not the load's price (D-044): provisional, to align in Phase 3.
- API: `listSales`, `createSale`, `getSale`, `updateSale`, `confirmSale`, `cancelSale`,
  `convertQuoteToSale`, `getBatchSales`. Pinned enum names: `SaleStatusEnum`, `SalePaymentMethodEnum`,
  `SalePriceSourceEnum`. Demo: a walk-in counter sale paid cash, a Camion 1 sale by the driver to Le
  Corail partly paid, Sidi Mansour's accepted quote converted on credit, a draft for Hôtel Thyna.

**D-052 · Sales screens and the counter sale (P2-T04b)** · accepted · 2026-10-11
- **"Ventes"** (`/ventes`, the menu's "Ventes & factures" until invoices exist): list with status filter
  and search, the amount still owed per confirmed sale. Sale page (`/ventes/:id`): lines with their price
  source, the lots each line came from (links to the batch page) with cost, totals (VAT "avec la
  facturation"), paid on the spot, still owed, cost of goods and margin (office only, the server sends
  them null to drivers), a follow-up card, and the actions of its status: edit and confirm a draft,
  cancel (a confirmed sale asks for a reason in the dialog; the server's message shows under the field).
- **Sale form** (`/ventes/nouvelle`, `/ventes/:id/modifier`): customer ("Client de passage" first, which
  sends no customer), the places that sell, an optional date and time (empty = now), lines like the quote
  form (the customer's list price or the daily price proposed, stock of the place shown, exact previews),
  payment on the spot (paid in full, amount, method, reference), "Enregistrer le brouillon" or
  "Enregistrer et confirmer". Server errors land under their field or line (`lines.<i>.<field>`).
- **Counter sale** (`/ventes/comptoir`), the client's regular flow (Q8): the first cold room open to
  counter sales and the walk-in customer are preselected; product, big kg and price inputs (the price in
  force proposed), "Ajouter" builds a basket (the same product weighed again adds its kilos: one line per
  product, as the server wants), the total in large type, the method as toggle buttons (cash by default),
  "Encaisser" creates and confirms the sale paid in full in one request, then the screen empties for the
  next customer and links to the sale just made. No receipt printing yet (P2-T08).
- **Quote → sale:** an accepted quote without a live sale shows "Convertir en vente": a dialog picks the
  place (the quote's by default) and creates a draft or a confirmed sale, then opens it; the quote's
  follow-up card links to its sale. The accepted note says it can be converted until its validity date.
- **Lot drill-down:** the batch page (`/stock/lots/:id`) gains "Ventes de ce lot": kg sold, revenue, cost,
  margin and each sale (`getBatchSales`), the sales side of the lot result of Phase 6.
- `sales/shared.ts` holds the statuses, tones, methods and `refreshAfterSale` (sales, quotes, batches,
  locations, stock, price board). Playwright: `admin.sales.spec.ts` (demo sales, counter sale, draft →
  confirm → lot → cancel, a line short of stock, quote conversion); its products (rouget, sardine,
  poulpe) are ones the other tests leave alone.

**D-053 · Expenses, lot costs and truck costs of the day (P5-T01)** · accepted · 2026-10-11
- New `expenses` app (ARCHITECTURE §3) with its own `DocumentCounter` (`DP-0001`… per organization; a
  deleted draft leaves a gap, not a fiscal number). **Categories** (`ExpenseCategory`): every organization
  gets the brief's 11 default categories (personnel, day labour, transport, fuel, cold storage, handling,
  rent, accountant, administration, financial, miscellaneous), each with a fixed `code` the app relies on;
  a data migration gives them to existing organizations and a `post_save` signal on `Organization` to new
  ones (`services.ensure_default_categories`, idempotent). The **owner only** adds, renames and archives
  categories (403 for a manager); a default category is renamed but never archived.
- **Expense:** date (not in the future), category, amount (> 0, millimes), payment method (the same list
  as supplier payments, so one `PaymentMethodEnum`), description, payee, notes, receipt (a photo turned
  upright and stored as WebP like loss photos, or a PDF kept as is, 8 MB at most; replaceable while open,
  once decided only joined if there was none), who entered and who decided it, `client_uuid`.
- **What it is charged to:** a **lot** (`batch`: the whole amount is a cost of that lot; the date cannot
  precede the lot's arrival), or a **truck** (a truck cost of that day), never both (DB constraint), or
  neither (a general cost). The truck day is the expense's date.
- **Statuses:** draft (office; editable, deletable) → approved or rejected (reason required); `pending`
  ("à approuver") is the hook for the driver's expenses from the phone (P3-T04: `create_expense(submit=True)`
  with the driver as `entered_by`): editable by the office, not deletable. Owner **and** manager approve
  (brief), the accountant reads, drivers 403 for now. Approved and refused expenses never change; a
  correction is a new expense (no negative "reversal" expense yet). Only approved expenses count.
- **Truck costs of the day** (D-041, **Q24 provisional**): each expense tagged to a truck and a day is
  split on its own over the lots loaded into that truck that day by validated transfers (loads and
  truck→truck), **by kg loaded** (what came back in the evening is not taken off). The pure function
  `allocation.allocate_truck_day_costs` (over `split_by_weight`) works in integer millimes and grams:
  each lot gets its exact share rounded down, the millimes left go to the largest remainders (ties: the
  heavier lot, then the smaller id), so **the shares add up to the expense to the millime**. A truck day
  with nothing loaded charges no lot: the cost stays general. The lots and kg come from new inventory
  selectors (`batches_loaded`, `truck_days_of_batch`), read from the ledger movements of transfer lines.
- **Lot costs:** `expenses.selectors.lot_cost_lines(organization, batch_id=)` returns the typed lines of a
  lot (kind `lot` = typed on it, including day labour; `truck_day` = its share, with truck, kg and the
  day's kg), approved only by default; `lot_cost_total` sums them. Phase 6's lot result reads this; the
  cold room (P5-T02), salaries (P5-T04) and general costs (P5-T05) will add their own kinds.
- API: `listExpenses` (paginated; status, category, lot, truck, days, search), `getExpenseTotals` (same
  filters: count, approved, waiting), `createExpense` / `updateExpense` (`approve_now`), `getExpense`
  (with the truck-day `shares`), `deleteExpense`, `approveExpense`, `rejectExpense`, `addExpenseReceipt`
  (multipart; the file itself is read at `/expenses/<id>/receipt`), `listExpenseCategories`,
  `createExpenseCategory`, `updateExpenseCategory`, `getLotCosts?batch=`. Pinned enum names:
  `ExpenseStatusEnum`, `LotCostKindEnum`.
- **Screens:** "Charges" in the menu becomes "Dépenses" (list with status, category, dates, search and
  totals; the owner's categories dialog), a form (charge générale / un lot / un camion, receipt, "Enregistrer
  et approuver"), an expense page (approve, refuse with reason, delete a draft, receipt, the split over the
  truck's lots). The lot page (Stock › lot) gets a "Coûts du lot" card with links to add an expense or a
  day of labour on it.
- Demo: DP-0001 fuel of Camion 2's day (85 DT, approved, split over its morning load), DP-0002 transport
  on a shrimp lot, DP-0003 rent (draft), DP-0004 accountant (waiting), DP-0005 ice (refused).

**D-054 · Day labour: one record, two ways in (P5-T03)** · accepted · 2026-10-11
- Day labourers live in `expenses`, not `hr`: they are not employees (no payroll, no CNSS). `DayLabourer`:
  name (unique per organization, case-insensitive), phone, usual daily pay (optional, proposed when a day is
  added), notes, archived flag. Owner and manager write, the accountant reads.
- **A day worked is one record with its expense** (client meeting §6, D-041): `DayLabourEntry` is a
  one-to-one extension of an `Expense` of category `day_labour`. The expense carries the date, amount,
  payment method, lot, notes and the approval; the entry adds the labourer and the work type (loading,
  stock, store, cleaning, other; pinned `WorkTypeEnum`). Typed from the calendar or from a lot
  (`createDayLabour` with or without `batch`), it is the same row, listed in the calendar, in the
  expenses list and on the lot (`lot_cost_lines`), and counted once. Without a lot it is a general cost.
- The day-labour category cannot be used in the plain expense form, and a day-labour expense is changed
  or deleted only through the calendar endpoints (`updateDayLabour`, `deleteDayLabour`, drafts only);
  approval goes through `approveExpense` / `rejectExpense` like any expense. No amount typed: the
  labourer's usual pay; neither: refused on `amount`.
- **Screens:** "Calendrier journaliers" (month grid, Monday first, each day showing people, total and lot
  numbers; clicking a day lists who worked, the lot link, status, approve/delete, and a form to add a
  day, "Ajouter et approuver") and "Journaliers" (list, add, edit, archive). `?lot=` opens today's day
  with the lot chosen (from the lot page); `?jour=` opens a day.
- Demo: Ali Ben Salah (40 DT), Moncef Trabelsi (35 DT), Hichem Gharbi (variable); Ali unloading a shrimp
  lot today (approved), Moncef cleaning yesterday (approved), two drafts two days ago.

**D-055 · Employees, salaries and days on a lot, the `hr` app (P5-T04)** · accepted · 2026-10-11
- **App `hr`:** `Employee`, `SalaryRecord`, `SalaryAdjustment`, `SalaryPayment` (+ allocations),
  `LotWorkDay`. It imports no other app's models; the lot of a work day is read through
  `inventory.selectors.batch_of` and the login through `core` selectors.
- **Private pay:** the owner reads and writes; the accountant reads; **managers and drivers get 403 on
  everything** (`ReadOwnerOrAccountantWriteOwner`), even for their own salary. The admin screens show a
  "Paie réservée" page to a manager. The Django admin never shows salaries.
- **Employee:** reference `E-NNN`, name, position, phone, hire date, fixed gross monthly salary, CNSS number
  and employer rate (default **17,07 %**, from the sample data: provisional, the accountant confirms), an
  optional login (one login per employee). No fixed truck (D-042). Archived, never deleted.
- **Salary record** per employee per month (first day of the month, unique): base, bonus, overtime,
  deductions, `gross = base + bonus + overtime`, `employer_cnss = gross × rate`, rounded once,
  `net = gross − deductions` (what the employee receives). The rate used is kept on the record.
  **Expense of the month = gross + employer CNSS** (deductions are money kept from the employee, not a cost
  reduction: provisional). `monthly_personnel_expense` is the selector P5-T01 and the month closing read.
- **Generate the month** creates drafts for every active employee with a salary and a hire date not after
  the month, who has none yet; idempotent; no future month; no pro-rata in the hire month (type the base).
- **Draft → approved**, one by one or the whole month. A draft can be changed or deleted; an approved record
  is immutable and corrected by a `SalaryAdjustment` (signed amount, reason, audit; the due amount may not
  fall below zero). Due = net + adjustments.
- **Payments** copy D-043: `PS-0001` numbers, a payment is immutable, allocations go to approved records of
  the same employee, never above what is left; the unallocated part is an advance, allocated later
  (`allocateSalaryPayment`). Errors on `allocations.<index>.<field>`. The payment is a cash movement apart
  from the expense. Methods: cash, cheque, transfer, other (provisional). Unpaid = approved due − allocated,
  shown per employee, per month and over all months (`getPayrollSummary`, `unpaid` on employees).
- **Days on a lot:** `employee_cost_for_lot_days(days, monthly_salary) = days × salary / 26`, rounded once
  (pure selector, tested). A `LotWorkDay` keeps the salary and the cost as they were when typed (snapshot);
  days are a fraction (two decimals, 0 < days ≤ 1), at most 1 day per employee and date in all; the lot is
  optional; deletable until lots are closed (Phase 6, provisional). `employee_cost_of_lot` sums a lot.
- **Screens:** "Personnel & salaires" (`/salaires`): "Paie" month view (generate, approve, edit, pay, adjust,
  unpaid badge) and "Employés" (list, page with salaries, payments and "Jours sur lot", form). Demo:
  7 stand-ins of `docs/spec/sample/employees.csv`, last month approved and paid except two, this month in
  draft, three days on a lot. `SalaryStatusEnum` and `SalaryPaymentMethodEnum` are pinned in
  `ENUM_NAME_OVERRIDES`.

**D-056 · Finance settings and VAT: optional per invoice, editable on the draft (P2-T05)** · accepted · 2026-10-11

- **`FinanceSettings`** is versioned per organization with a `valid_from` day (D-018, Q5): VAT rate (default
  19 %), fiscal stamp (1.000 DT), prices with or without VAT, withholding rate (default 0), and the seller
  printed on invoices (legal name, address, phone, tax ID, trade register). Owner edits (`saveFinanceSettings`),
  office roles read; saving again for the same day replaces that day's version; the past is refused; the
  change is audited. Issued invoices keep their values.
- **Per-product VAT** (`Product.vat_rate`, null = the company rate, 0 = exempt). Fishing products may be
  exempt in the VAT code: to confirm with the accountant (provisional, nothing hard-coded).
- **VAT is optional on each invoice** (`apply_vat`): the person chooses "Facture avec TVA" on the draft; the
  company setting only proposes. Without VAT nothing about VAT is computed or shown.
- **The VAT value is editable on a draft:** rate per line (`vat_rate`, flagged `vat_rate_overridden` when it
  differs from the product's/company's) and the amount per rate (`InvoiceVatLine.amount`, flagged
  `amount_overridden` against `computed_amount`, refused above what the lines hold). The stamp and the
  withholding rate are prefilled from the settings and editable too (`*_overridden`). Every typed value goes
  to the audit log (`overrides`). All freezes at issue.
- **Arithmetic** (`sales/invoicing.py`, pure, half up to the millime once per rate): prices without VAT add
  VAT on top, prices with VAT extract it; a typed amount replaces the computed one of its rate; each line
  takes its share, the last line the rest, so lines always add up. Withholding = (total HT + VAT) × rate,
  stamp excluded, and it reduces the amount to collect (P2-T06 tracks it).

**D-057 · Invoices, credit notes, numbering (P2-T05)** · accepted · 2026-10-11

- **`Invoice` + `InvoiceLine` from a confirmed sale** (`createInvoice`): one live invoice per sale, a draft
  has no number and can be changed (`updateInvoice`, PUT with every value again) or thrown away
  (`deleteInvoice`); `issue_now` issues in the same call. Issuing (`issueInvoice`) takes the next number,
  today's date, the settings in force, and copies seller and customer; from then on it never changes.
- **Gap-free numbering** per organization per year: `FA-2026-0001` (invoices), `AV-2026-0001` (credit notes),
  taken under a row lock on `DocumentCounter` only at issue, in the same transaction, so a rollback leaves no
  gap (ARCHITECTURE §4.11).
- **`CreditNote`** is the only correction: `full` returns everything left and cancels the invoice,
  `partial` returns kilos or an amount without VAT per line, with the line's VAT; it cannot exceed what is
  left; stock is not touched here (customer returns: P2-T07).
- **TTN hook:** `einvoice_status` (`not_sent`) and `einvoice_reference` on invoices and credit notes; nothing
  is sent (D-016, Phase 8).
- **Receivable:** issuing posts `record_invoice_receivable` (hook for P2-T06). Roles: owner and manager write,
  the accountant reads (the server refuses the others).
- **Screens:** "Factures" (`/factures`, invoices and credit notes tabs), the invoice page (print-friendly
  document, `print:` classes hide the shell; a draft shows the VAT toggle and typed values beside what the
  settings propose), "Facturer" on a confirmed sale, the credit note dialog, "Paramètres financiers"
  (`/factures/parametres`). The VAT preview is computed by the server on "Enregistrer et recalculer".

**D-058 · Cold-room cost per day, estimate then correction (P5-T02)** · accepted · 2026-10-11
- In `expenses`. `ElectricityBill` (month, one-to-one with an `Expense` of category cold storage: one record,
  so it also feeds the books; typed after the month ends, one per month, a refused one can be retyped).
  `ColdRoomWeight` per cold room (default 1, owner only). Approving the bill (`approve_expense` or the
  bill's endpoint) freezes `ColdRoomMonthRate` per active room (weight, part of the bill, estimate rate used):
  rooms get `split_by_weight(bill, weights)`, each room's part is spread evenly over the month's days, each
  day over the lots in the room that day by kg: shares add up to the millime at every level.
- **Kg held** come from the ledger replayed by date: `inventory.selectors.kg_by_batch_by_day` /
  `kg_by_batch_on_day` / `first_movement_day` (end-of-day balance per place, local date; the day a lot
  moves is charged to the room it ends the day in).
- **Estimate:** a month with no approved bill uses the latest earlier billed month's daily rate per room
  (month part / days), flagged `estimated`; nothing before the first bill. When the real bill is approved
  each lot gets a `LotCostAdjustment` (real minus estimate, per room, signed, dated that day, immutable):
  a closed lot is never reopened, the later settlement picks the line up (D-041). Frozen estimates are
  not recomputed.
- `lot_cost_lines` gains kinds `cold_room`, `cold_room_adjustment`, `general` (plus `location_name`, `month`,
  `estimated`; `expense_id` may be null for an estimate). Screen "Chambres froides : coût"
  (`/charges/froid`). Pinned enum `LotCostAdjustmentKindEnum`. Provisional: weights are read at approval
  time; rooms archived later keep their frozen rows.

**D-059 · General costs on lots, like a salary (P5-T05)** · accepted · 2026-10-11
- `RecurringCost` (template: category, monthly amount, first/last month) generates the month's `Expense`
  (`generate_recurring_costs`, idempotent, owner/manager); `GeneralCostPeriod` marks an expense as a general
  cost covering `months` months from `first_month` (bill over several months is spread equally, exact to
  the millime). Templates are owner-only; generated and multi-month costs follow the expense approval.
  Such an expense is changed/deleted only through its own endpoints.
- Charge to lots (**Q21 confirmed 2026-10-13**): each month part / 26 per day, each day split over the lots
  in stock anywhere that day by kg held (end-of-day ledger balance, the same split as the cold room, D-041);
  days with nothing in stock charge nobody. Only
  approved expenses count; days up to today. Screen "Frais généraux" (`/charges/frais-generaux`).

**D-060 · Partnership lots and the partner's capital ledger (P6-T01)** · accepted, provisional points marked · 2026-10-11
- New `partnerships` app (ARCHITECTURE §3). `LotPartnership`: lot (`Batch`), partner (a `Supplier`), what the
  owner and the partner put in (`owner_capital`, `partner_capital`), **profit %** and **loss %** (two
  decimals, 0-100, D-031), status `open` → `closed` (the lot's result is frozen, D-061) → `settled` (P6-T03),
  or `cancelled`; notes, who and when, the cancel reason. **One live partnership per lot** (partial unique
  constraint, cancelled ones excluded); a supplier may be partner in any number of lots, each with its own
  capital and rates (Q22). Pinned enums `PartnershipStatusEnum`, `CapitalEntryKindEnum`.
- **When:** on a lot that still has stock and has **no confirmed sale** (`sales.batch_sales_totals`; a sale
  cancelled later gave its kilos back and does not count). The terms change, and the partnership can be
  cancelled (reason required), only under the same condition; afterwards they are what the result uses.
  Changes on a lot are serialized by a PostgreSQL advisory lock on the lot (`core.locks.lock_lot`, shared
  with the closing).
- **Capital ledger** (`CapitalEntry`, per partner and lot, signed, append-only like the stock ledger):
  `contribution` (+, posted with the partnership), `correction` (± the difference when the capital is changed
  before the first sale), `loss_deduction` (−, posted by the closing), `loss_reversal` (+, when a closed lot is
  reopened), `return` (−, capital paid back: at settlement, P6-T03, or when a partnership is cancelled). The
  balance is the sum. It never touches the supplier's trade payable (D-043) nor the profit share: **three
  balances**. `capital_put_in` (contributions and corrections) is what a lot result starts from;
  `capital_by_partner` sums a partner over their lots.
- **Who (provisional):** the owner writes; the owner and the accountant read; managers and drivers get 403
  (`core.permissions.ReadOwnerOrAccountantWriteOwner`). API: `listPartnerships` (paginated; status, partner,
  lot, search; cancelled ones only on request), `createPartnership`, `getPartnership` (with the ledger and
  `has_sold`), `updatePartnership`, `cancelPartnership`.
- **Screens:** the lot page (Stock › lot) gets a "Partenariat" section (terms, capital now, ledger; "Mettre en
  partenariat", "Modifier" and "Annuler le partenariat" for the owner while the lot is unsold); the menu's
  "Partage des bénéfices" opens "Partenariats" (list by status, search, a link to each lot). **TODO:** the
  goods-receipt form (P1-T07) has no "partenariat" section yet: a receipt makes one lot per line, so it would
  be per line; for now the owner opens the new lot and sets the partnership there before its first sale.
- Demo: Pêcherie Kerkennah (F-001, 40 % / 25 %) shares the seiche lot KRK-1192 (owner 200.000, partner
  107.500), set before the demo sales, so Sidi Mansour's converted quote is its first sale; 18.000 DT of
  transport typed on it (DP-0010).

**D-061 · The lot result engine, closing a lot and its frozen result (P6-T02)** · accepted, provisional points marked · 2026-10-11
- New `closing` app. `engine.py` is **pure** (no database): a `LotSnapshot` (the lot's sale rows with kg,
  price, revenue and cost from the sale snapshots; stock written off or found; cost lines by kind; the
  partnership terms) → a `ComputedResult` with **every step**: revenue − purchase cost of the kg sold (COGS,
  D-051) − kg written off − each kind of cost = **net result**, then the partner's and the owner's shares.
  `engine.to_json` gives the same JSON for the live result and the frozen copy; the API sends it as is.
- **Shares (Q3, D-031):** profit → partner = profit % × net, rounded half up once to the millime; loss →
  the partner carries loss % × loss, rounded once, **taken from their capital**; what the capital cannot
  cover is `uncovered_loss`, owed by the partner (D-031, still provisional; recovering it from their next
  profit shares belongs to the settlement, P6-T03); zero → nothing, no rate. The owner's share is always net −
  partner share, so **the two add up to the net result** (property test). Capital to return = capital −
  deducted; payable to the partner at settlement = capital to return + a profit share.
- **Spoilage (our choice):** a loss posts `loss` movements at the lot's cost, which are not in COGS (COGS is
  the sale rows only). The engine reads the lot's `loss`, `count_correction` and `adjustment` movements (out =
  written off, in = found again) and charges their value at the movement's cost as its own step "Pertes et
  écarts". Supplier returns are not a cost of the lot (the supplier takes the goods back). So for a closed lot
  (stock 0): COGS + written off = (received − returned) × cost. Kilos still in stock are shown at cost and are
  **not** a cost: an open lot shows its result "so far".
- **Costs:** every approved line of `expenses.lot_cost_lines`, whatever its `kind`, read generically (`kind`,
  date, category name, amount, the expense when there is one): typed costs (`lot`), truck-day shares
  (`truck_day`); the cold-room and general-cost kinds of P5-T02/T05 plug in unchanged (unknown kinds are
  listed after the known ones). Employees' days come from `hr.lot_work_days_of` (kind `employee`, the cost kept
  on the day). **If P5 adds employee days to `lot_cost_lines`, drop the hr read** so they are not counted twice.
- **Closing** (`close_lot`, owner only, `closeLot`): refused while stock remains (sell it or record a loss),
  while costs typed on the lot wait for approval, without `costs_confirmed` (only a person knows every cost is
  in), or when already closed. Customers still owing on the lot's sales (the payment on the spot is all the
  system knows until P2-T06) are a **warning** kept with the result (`payments_unverified`);
  `selectors.CUSTOMER_PAYMENTS_BLOCK` turns it into a refusal once P2-T06 lands. Closing writes a `LotResult`
  (figures as columns + the whole JSON with the checks), posts the partner's loss deduction on the capital
  ledger and closes the partnership, in one transaction under the lot's advisory lock; one closed result per
  lot (partial unique constraint). Two closings at once: one wins, the others are refused (tested).
- **Immutable:** a `LotResult` is never updated or deleted (queryset guards). A cost or sale recorded after the
  closing changes only the live figure (`live_net_result`) and goes to the partner's next settlement (D-041,
  P6-T03). **Reopen** (`reopenLot`, owner, reason required, audited): the result stays as history with status
  `reopened`, the deducted loss share comes back to the capital (`loss_reversal`), the partnership is open
  again; a settled partnership is not reopened. Pinned enums `LotResultStatusEnum`, `LotOutcomeEnum`,
  `LotStateEnum`.
- **Who (provisional):** the owner closes and reopens; the owner and the accountant read (`getLotResult`);
  managers and drivers get 403 (the result shows margins, partner shares and employee costs, D-055). The lot
  page's "Résultat du lot" card shows each step, opening on the sales, losses, expenses or employees behind
  it, the partner's share, the closing checks, the drift after closing and earlier closings.
- Known gaps: P2-T07 partial customer returns will need the result to read returned kilos; a sale cancelled
  after its lot closed puts stock back on a closed lot (shown as drift); hr days on a closed lot can still be
  deleted (D-055's hook). The P0-T02 golden lot is still missing: the golden tests use a lot worked out by hand
  (`closing/tests/test_engine.py`), to be joined by the client's real lot.

**D-062 · Customer receivable, payments and balance (P2-T06)** · accepted, provisional points marked · 2026-10-11
- **Nothing is stored twice.** `sales/receivables.py` computes what each confirmed sale owes from the documents:
  the sale's total until it has an issued invoice, then the invoice's `net_to_pay` (VAT and stamp in,
  planned withholding out) less its credit notes, with a withholding certificate's amount replacing the planned
  withholding (D-063). Less what was paid on the spot and what payments were allocated to it = **outstanding**.
  `Sale.amount_due` is only that outstanding amount kept up to date for lists (`refresh_sale_due`, called by
  `record_receivable`, `record_invoice_receivable`, credit notes, payments, certificates).
- **Balance of a customer** = what their sales owe − all paid on the spot (cancelled sales included) − all
  payments (voided ones left out). Negative = **customer credit** held by the company: an unallocated payment,
  money paid on a sale cancelled afterwards, a credit note beyond what was owed. Supplier payables, invested
  capital and profit shares are untouched (separate balances, ARCHITECTURE rule).
- **`CustomerPayment`** (`RG-0001`… per organization, cash/cheque/transfer/card like sales, received day not in
  the future, reference, notes) with `PaymentAllocation` rows to sales. By default a payment settles the
  customer's **oldest open sales first** (by invoice date, else sale date); a list may name sales and amounts
  (never more than a sale still owes); what is left stays credit and `allocate_customer_payment` can settle
  sales with it later. Never edited or deleted: `void_customer_payment` (reason, who, when) makes its
  allocations stop counting. The walk-in customer cannot have payments (they pay on the spot, D-047).
- **Ageing** 0-30, 31-60, 61+ days since the **invoice date (else sale date)** — *provisional*: the client has
  not said whether they age from the invoice or the due date; `overdue` (past the due date = invoice date +
  payment terms) is given separately so both views exist.
- Customer account history (sales at what they owe now, paid on the spot, payments) with a running balance
  ending on the balance. API: `listCustomerPayments`, `createCustomerPayment`, `getCustomerPayment`,
  `allocateCustomerPayment`, `voidCustomerPayment`, `getCustomerBalance`, `getReceivablesAgeing`.
- **Lot closing (D-068):** `closing.selectors.customers_owing` now reads `sales.selectors.outstanding_by_sale`
  and `CUSTOMER_PAYMENTS_BLOCK` is `True`: a lot with a sale still owed money cannot be closed until it is paid
  (override with a reason: still not built, owner decision pending).

**D-063 · Withholding certificates (P2-T06)** · accepted, provisional points marked · 2026-10-11
- `WithholdingCertificate` per issued invoice: number, date, **amount really withheld**, file (photo stored as
  WebP or PDF, 8 MB, random file name, served by `withholding-certificates/<id>/file`, joined at creation or
  later). One live certificate per invoice; a mistake is voided (reason) and typed again; never deleted.
- The invoice keeps the withholding it planned at issue (D-057, frozen); the certificate's amount **replaces**
  it in the receivable, so a customer who withheld more or less changes what they still owe. Provisional: no
  rule limits the amount to the planned one (the customer decides), only to the invoice's total with tax.
- For the accountant: `getWithholdingSummary` (certificate dates, both ends included): total, per month, per
  customer, each certificate, and issued invoices that planned a withholding but have no certificate yet. Office
  roles read (the accountant included), owner and manager write. Audited.

**D-064 · Credit limit and its company policy (P2-T06)** · accepted, provisional points marked · 2026-10-11
- `FinanceSettings.credit_policy` (versioned like the other settings, D-018/D-056): `block` (default, the safe
  choice while the client has not decided: *provisional*), `approval`, `warn`. Owner edits it on the finance
  settings screen.
- `check_credit` runs inside `confirm_sale` for **every seller, drivers included** (Q16): balance now + what
  this sale leaves unpaid must not exceed the customer's `credit_limit` (0 = pays at once). The customer row is
  locked so two sellers cannot both pass. `block` refuses on `credit_limit`; `warn` lets it through,
  `credit_status = warned` and an audit entry `sale.credit_limit_exceeded`; `approval` leaves the sale a
  **draft marked `pending`** (`sale.credit_approval_requested` audited) until the owner or a manager confirms
  it with `approve_credit` (a driver sending it gets 403); the sale then shows `approved`, who and when.
  Editing a pending draft asks again. A sale paid in full on the spot is never limited.
- Test factories now give customers a 100 000 DT limit so tests selling on credit stay about their own subject.

**D-065 · Payments screens and permissions (P2-T06)** · accepted · 2026-10-11
- Office only: owner and manager write, the accountant reads, drivers get 403 on payments, balances and
  certificates (collecting money on the phone, D-047's narrow customer endpoint and the driver balance view
  belong to Phase 3). Not in this task: refunding credit, returns (P2-T07), PDFs/receipts (P2-T08).
- Screens: "Règlements" (`/reglements`: ageing of all customers with "Encaisser", withholding totals per
  month, every payment with void), the customer page now shows balance, ageing, open sales, history and
  "Enregistrer un règlement"; the sale page shows the credit status and "Approuver et confirmer"; the invoice
  page a "Certificat de retenue" card; the finance settings screen the credit policy. Playwright:
  `admin.payments.spec.ts`. Pinned enums: `SaleCreditStatusEnum`, `CreditPolicyEnum`.

**D-066 · Settlement with the partner and the three balances (P6-T03)** · accepted, provisional points marked · 2026-10-11
- A closed partnership lot is **settled** once (`closing.services.settle_lot` → `partnerships.services.settle_partnership`,
  `PartnerSettlement` one per partnership, `SettlementPayment` lines). Partnership status `closed` → `settled`.
- **Three balances per partner, three ledgers, never added together** (D-031, D-040): *trade payable* (D-043,
  read from `purchasing.supplier_balance`, never written here); *capital* (`CapitalEntry`, D-060: a settlement
  posts the `return` of what is left after a loss share); *profit share* (new append-only `ProfitShareEntry`,
  signed, + the company owes the partner, − the partner owes the company). Kinds: `share` (profit share, posted
  at settlement), `uncovered_loss` (D-031's loss beyond the capital, −), `late_adjustment` (D-067), `payment` (−).
  `partnerships.selectors.partner_balances` gives the three numbers.
- **Arithmetic:** capital to return = capital balance (already net of a deducted loss share). The partner's
  profit-share balance B over **all their lots** = earlier entries + this lot's `share` (+) or `uncovered_loss`
  (−). Paid = capital + max(B, 0). A negative B is **recovered from this lot's share first**; what the share
  cannot cover stays on the profit-share balance (`carried_out`) for their next settlement and is **never taken
  from the capital** (D-031: "recovered from their next profit shares"; provisional until P0-T02).
- **Payments:** `payments` (method from the supplier-payment list, amount, reference, date) must add up to
  exactly what is paid, to the millime; nothing to pay means none. **No partial settlement** (provisional: the
  lot is settled in one go, possibly with several payment lines such as cash + cheque). A settled lot cannot be
  reopened (D-061); a correction is a late adjustment on the partner's next settlement.
- Concurrency: the lots of the partner involved are locked (`lock_lot`) in lot-id order, then the partnership
  row; a second settlement of the same lot is refused. Audited (`partnership.settled`).

**D-067 · A cost arriving after the lot closed goes to the partner's next settlement (P6-T03, D-041)** · accepted, provisional points marked · 2026-10-11
- The frozen `LotResult` is never touched and the lot is never reopened. `closing.selectors.late_drift` compares
  the live net result with the frozen one: `drift = live − frozen`. The partner's share of it is
  `share(frozen + drift) − share(frozen + already booked)` using the lot's two rates (so adjustments telescope
  to exactly `share(live) − share(frozen)`, whatever their number, no rounding drift; tested).
- It is booked as a `late_adjustment` profit-share entry (`basis` = the change of net result it covers, so the
  next call books only the rest) by `book_late_adjustments` (owner, `bookLateAdjustments`) or automatically
  by the partner's **next settlement**, which books the drift of every closed lot of that partner first. A cost
  after the lot's own settlement therefore reduces the partner's next payout (or sits as an amount they owe).
- Provisional: the owner's share of a late cost is not tracked (only the partner's side is a balance); a late
  adjustment never comes out of capital. The same mechanism carries a late **sale** or the electricity bill
  difference of D-041 (P5-T02), whatever put the live net result off the frozen one.

**D-068 · "Customers paid" check behind one function (P6-T03, Q19)** · accepted, provisional · 2026-10-11
- Q19: a lot closes when sold out, costs in and customers paid. Receivables now come from one place,
  `closing.selectors.customers_owing(organization, snapshot)`: what each sale still owes (`amount_due` = sale
  total − payment on the spot). **P2-T06 (customer payments) replaces only that body** (and flips
  `CUSTOMER_PAYMENTS_BLOCK`); the checks, the frozen `payments_unverified` flag and the screen stay as they are.
- Still a **warning, not a refusal** until P2-T06: today a credit sale cannot be paid after the sale, so a hard
  block would make such a lot impossible to close. Once P2-T06 lands, `CUSTOMER_PAYMENTS_BLOCK = True` makes it
  blocking (owner decision pending on an override with a reason; not built).

**D-069 · Who may settle, API and the lot page (P6-T03)** · accepted, provisional points marked · 2026-10-11
- Same rule as D-060/D-061 (provisional): the owner settles, books late adjustments, closes and reopens; the
  owner and the accountant read; managers and drivers get 403. API (`closing` app): `getLotSettlement`
  (state `none` / `not_closed` / `ready` / `settled`, preview or record, late drift, the partner's profit-share
  ledger on the lot, the three balances), `settleLot`, `bookLateAdjustments`, `getPartnerBalances`.
- The lot page gets a "Règlement du partenaire" card under "Résultat du lot": what is paid step by step, the
  payments dialog with the amount still to type, the late-cost notice with a button to carry it now, and the
  three balances. The full P6-T07 screens (list of partnership lots by status, partner page) are not built.
- Known gaps: no settlement PDF (P6-T04); a cancelled partnership with capital returned is not part of the
  balances beyond its ledger; the settlement uses today's date (no back-dating field).

**D-110 · Back button, truck-of-day menu entry, sticky filter bars** (numbered D-070 until 2026-10-12, a duplicate) · accepted · 2026-10-11
- `AdminShell` shows a "Retour" button on every page that is not a menu entry (previous page, or the parent menu
  entry when opened directly). "Camions du jour" (D-046) is its own menu entry `/camions`, no longer a section of
  the Stock page. Filter bars of list pages use the `filter-bar` class: sticky under the 62px top bar.
**D-070 · Customer returns on credit notes (P2-T07)** · accepted, provisional points marked · 2026-10-11

- **No separate "return" document:** a return is a credit note (D-057) with a `stock` choice for the kilos it
  gives back: `none` (default: weight dispute, price gesture; nothing moves), `restock` or `loss`. One choice
  per note, in the dialog and in `createCreditNote`.
- **`restock`:** the kilos re-enter the sale's place (cold room or truck) by `customer_return` movements, on
  the batches the sale line left (`SaleLineBatch`, in order, up to what each has not yet got back), at the
  cost they left with. **`loss`:** the same, then a `loss` movement writes them off on the same batch at once,
  with the credit note as reason: no owner approval (D-045), the note is the proof. Provisional: the client may
  want a threshold or a photo for returned goods.
- **`CreditNoteLineBatch`** records, per credit note line and sale batch, the revenue taken back and, when goods
  came back, kilos and cost. `selectors.batch_sales_totals` and the lot result (`closing` reads
  `selectors.net_of`) are **net** of them, so a return lowers the lot's revenue and COGS; a `loss` then adds
  the spoilage through the ledger. A price correction lowers revenue only. `batch_sales` rows keep gross
  values and add `returned_quantity`, `credited_revenue`, `returned_cost`.
- **A sale cancelled after a full credit note** returns only the kilos not already returned.
- **Not done (provisional):** a return on a lot that is already **closed** changes the live numbers but not
  the closed snapshot (use the late-adjustment path, D-067, by hand); no refund of money (P2-T06 credit);
  a return cannot exceed the sale's kilos still out, per batch.

**D-071 · PDF documents, Celery and Redis (P2-T08)** · accepted, provisional points marked · 2026-10-11

- **New `documents` app, generic.** Apps register what can be printed (`documents.services.register(kind,
  provider)`); a provider returns a `Printable` (template, context, version, file name). Sales registers quote,
  invoice, credit note and receipt in `sales/printing.py` (templates in `sales/templates/sales/pdf/`, one base
  page and number formats in `documents`). Later documents (partner statement P6-T04, month-end) only add a
  provider and a template.
- **WeasyPrint** renders HTML to A4 PDF (DejaVu Sans, thin-space thousands, comma decimals, page numbers).
  It needs Pango: the Docker image and the CI backend job install it; the Windows machine does not have it,
  so the one test that really renders skips there and the others check the HTML and use a stand-in renderer.
  **Layout was not checked by eye yet**: open each PDF on staging and adjust the templates.
- **Celery + Redis.** `config/celery.py`; broker `CELERY_BROKER_URL` (default `redis://localhost:6379/0`). With
  `CELERY_EAGER` the job runs inside the request: default in dev (`make backend` needs no Redis or worker) and
  in tests. Staging runs `redis` and a `worker` (same image and media volume as the API); production must too.
  The nightly service stays as it is (D-038); moving it to Celery beat is later.
- **One file per document.** `GeneratedDocument(kind, object_id, version, file)`; `version` is the document's
  last change (`updated_at`, plus the allocated sum for a receipt), so a changed document (cancelled invoice,
  edited quote) is remade on the next request and an untouched one never is. Old file deleted on remake.
- **API:** `GET /documents/<kind>/<id>/pdf` (office roles read; drivers 403): 200 the file, 202 `pending` (ask
  again), 500 `failed` (`?retry=1` queues again; polling alone never does), 400 for a draft invoice (no number
  yet), 404 for another organization. A job queued less than 90 s ago is not queued twice. The admin app's
  "PDF" button (`lib/PdfButton`) opens a tab at the click, polls every second for up to a minute, then shows it.
- **Storage:** Django's default storage (the media volume today, served only through this endpoint with random
  file names). Object storage is a settings change (`STORAGES["default"]`), not yet done: provisional, with
  `django-storages` when a bucket exists.
- **Not done:** receipts for the driver app (Phase 3: drivers get 403 here), PDFs by e-mail or WhatsApp, Arabic
  layout (right-to-left, with P0-T08), e-invoice (TTN) QR code (D-016).

**D-090 · Driver app kept deliberately simple; first screen "Ma journée" (P3-T01, part)** · accepted · 2026-10-11
The drivers are not used to phones: big text, one job per screen, almost no typing, prices filled in for them.
`GET /api/v1/my-truck-day` (drivers only) returns the day's load of the driver's own truck (D-046) with the
price per kg; the first screen shows the truck and that load. A driver
with no truck sees the active trucks as big buttons (`GET /my-truck-choices`, those taken by another driver are
greyed) and picks one with the existing `POST /truck-assignments`. `fleet.DriverDay` (truck, driver, date, opening
cash; one per driver and day) is opened by `POST /my-day` and read by `GET /my-day`; asking twice keeps the first.

**D-091 · Sale on the road, first version (P3-T02, P3-T03)** · accepted, provisional points marked · 2026-10-11
Driver-only read endpoints: `GET /my-stock` (the truck's stock per product with today's daily price) and
`GET /my-customers?search=` (name and city, walk-in last, 30 rows). The sale screen sends no price: the server
prices the lines as for any sale (customer's list, else daily price) and the receipt shows its result; the screen's
running total uses the daily price, so it may differ for a customer with their own price list (**provisional**,
D-051 still open). The driver types the kg and what the customer pays; the rest is credit, and the server
refuses above the credit limit (its message is shown). Payment is cash for now. A `client_uuid` per sale makes
a retry safe. Receipt: on screen and the phone's share sheet. Not yet: recent customers first, creating a
customer, other payment methods, offline (P3-T07).

**D-092 · Expenses from the road (P3-T04)** · accepted · 2026-10-11
A driver enters an expense with `POST /my-expenses` (multipart: category, amount, optional note, optional receipt
photo, `client_uuid`), through `expenses.services.submit_road_expense`: cash, today, a cost of the driver's truck of
the day (D-041), status "À approuver" until the office decides; the photo is joined in the same transaction. The
driver picks among four categories only (fuel, transport, handling, miscellaneous: `ROAD_CATEGORY_CODES`), listed by
`GET /my-expense-categories`; `GET /my-expenses` shows their own entries of today with the decision.

**D-093 · Losses and returns from the road (P3-T05)** · accepted · 2026-10-11
`POST /my-losses` (multipart: product, kg, reason, note, photo, `client_uuid`) records a loss on the driver's truck
today through `inventory.services.report_road_loss`: the usual threshold applies (small ones leave the stock at once,
heavy ones wait for the owner) and the photo is joined in the same transaction. `POST /my-return` brings **everything**
left on the truck back to the cold room of its latest validated load (else the first active cold room) as one validated
return transfer; partial returns stay possible from the admin transfer screen.

**D-094 · End-of-day closing of a driver's day (P3-T06)** · accepted, provisional points marked · 2026-10-12
New app `dayclose`, model `DayClosing` (one per `fleet.DriverDay`): expected cash, counted cash, difference,
driver note, the day's summary kept as sent, and the office's decision. **Expected cash = cash at the start + cash
sales − the day's road expenses** (rejected ones left out); other payment methods and credit are shown, not counted
in the till. The summary (`dayclose.selectors.day_summary`) is computed from sales (confirmed, by this driver, from
the truck, that day), road expenses, and per product loaded / sold / lost / returned / remaining. The driver sends
once (`POST /my-day-closing`); the difference is shown without judgement. The office (owner, manager; the accountant
reads) lists days at `/journees` and either approves (locks the day: a second send or review is refused) or asks for a
justification, after which the driver sends again with a note. Status names: submitted, justification, approved.
**Not done:** approving a day does not yet block further sales or expenses by that driver the same day (**provisional**);
the day's customer payments collected by the driver ("other payments") wait for a driver collection screen.

**D-073 · Month-end stock valuation and cost of goods sold (P6-T05)** · accepted · 2026-10-11

- **Profit is never purchases − sales.** The month's result is: sales (revenue without VAT) − cost of the goods
  *sold* − spoilage − expenses − payroll. What was bought and is still in stock stays an asset.
- **Valuation at the end of a day** (`inventory.selectors.stock_valuation`): the ledger replayed by date, all
  places together (transfers cancel out), lot by lot at the lot's cost per kg. A past month-end gives the same
  answer later, whatever was sold since.
- **COGS and revenue come from the sale-line snapshots** (`sales.selectors.month_sales`: `SaleLineBatch` of
  confirmed sales sold in the month), **less what credit notes issued in the month took back** (D-070). A sale
  cancelled afterwards no longer counts: the month then drifts from its frozen copy (D-074 shows it).
- **Roll-forward** (`ledger_by_kind`): opening value + receipts − supplier returns − sales + customer returns
  − losses ± count corrections and adjustments = closing value, each movement valued once (kg × the cost it
  carries, rounded). Any gap against the lot-by-lot valuation is only rounding and is shown
  (`rounding_difference`). The check `cogs_matches_ledger` compares the ledger's cost of sales with the snapshots.
- **Spoilage** of the month = losses, count corrections and adjustments at cost (a returned-and-lost customer
  return is a loss too). **Expenses** = approved expenses dated in the month, all categories (lot costs, truck,
  day labour, electricity, recurring rent and accountant...). **Payroll** = the month's approved salary
  expense (`hr.monthly_personnel_expense`); the days × salary / 26 of employees on lots are an allocation to
  lots, not a second cost.
- Provisional: an expense covering several months (an insurance for a year) counts whole in the month it is dated;
  no depreciation yet (truck, D-016 notes); VAT is not part of the result.

**D-074 · Monthly closing for the accountant (P6-T06)** · accepted, provisional points marked · 2026-10-11

- **Flow (Q9):** a month that is over is **reviewed** by the accountant (or the owner), then **approved** by the
  owner, which freezes it (`MonthlyClosing`, immutable like `LotResult`; reopening keeps the copy as history,
  with a reason and an audit entry). It does not change the partners' shares: those are settled per lot (D-040).
- **Blocking checks** (review and approval are refused): expenses of the month not approved, salaries still
  drafts, losses waiting for the owner. **Warnings:** draft sales, COGS different between snapshots and
  ledger. **Listed but not tracked yet:** unexplained cash differences and open driver days (Phase 3).
- **The review keeps a fingerprint of the figures** (revenue, COGS, spoilage, expenses, payroll, net result,
  stock values). Approving after they moved is refused: "le comptable doit refaire la vérification".
- **Locked** means the frozen copy is what the month says; a cost or sale recorded afterwards is not blocked
  but shown as `live_net_result` against the frozen figure (provisional: no guard on dating records in a
  closed month yet).
- **API** (`/months`, `/months/<yyyy-mm>`, `review`, `approve`, `reopen`): the owner and the accountant read and
  review; only the owner approves and reopens; managers and drivers get 403. The current month cannot be closed.

**D-072 · Partner statement PDF (P6-T04)** · accepted · 2026-10-11

- **One statement per partnership lot**, kind `partner_statement`, id = the partnership's (`GET /documents/partner_statement/<id>/pdf`,
  office roles). Provider in `closing/printing.py`, template `closing/pdf/partner_statement.html`; it reads the
  frozen result of a closed lot, or the live "so far" result of an open one (the page then says so).
- **Reads top to bottom, no accounting words:** the agreement (each side's capital, the two rates); what was
  bought; every sale (date, customer, kg, price); losses; every cost line by group; the result step by step
  (`+ sales − cost of the kg sold − losses − costs = net`), then one sentence ("le lot a rapporté X; vous recevez
  40 % : Y"); the capital back and what is paid; the settlement with its payments, and the capital movements.
- **Remade when a figure changes:** the file's version is a hash of the result, the capital and profit-share
  ledgers and the settlement date, so settling a lot or booking a late adjustment gives a new file.
- **Not done:** one statement covering several lots of a partner (the three balances over time) and sending
  it by e-mail or WhatsApp; Arabic ("Haka bayek" in the partner's language) comes with P0-T08.

**D-076 · Purchase orders (bon d'achat) and partial receipts (P1-T13)** · accepted · 2026-10-12
Amends D-039 ("no `PurchaseOrder` yet"): the owner asked for a bon d'achat before the bon de réception (BR), with
deliveries that can arrive in parts.
- **`PurchaseOrder`** (`BA-0001`… per organization, same counter table as invoices) with lines (product, ordered kg,
  agreed price per kg). It moves no stock and owes nothing: only receipts do. Saved = final: no edit; a mistake is
  cancelled (before any delivery) and typed again.
- **A receipt may point at an order** (`GoodsReceipt.purchase_order`, `GoodsReceiptLine.order_line`). It carries only
  the products and weights that arrived: one order is received in as many BR as the supplier makes deliveries. Only
  products of the order are accepted; the supplier must match. Typing a receipt without an order still works.
- **Received = accepted kg** of the order's receipt lines; remaining = ordered − received, never below zero. More than
  ordered is accepted (a delivery of 105 kg on 100 kg completes the line).
- **Status follows the receipts** (`services.refresh_order_status`, under a row lock on the order): `open` → `partly_received`
  → `received` when every line is in full. `close_order` (owner/manager) ends a partly received order whose rest will not
  come (`closed`); `cancel_order` only when nothing was received (`cancelled`). Closed and cancelled orders take no receipt.
- **Ordered kg on a linked receipt line stays empty:** the order carries what was asked for, so a partial delivery is not
  flagged as a weight difference; invoiced vs accepted still is.
- **The cost is still typed on every receipt line** (the real price of the day, D-020); the form starts from the order's
  agreed price. Invoices (D-043) still charge receipts, not orders.
- API: `listPurchaseOrders` (filters supplier, status incl. `pending`, search), `createPurchaseOrder`, `getPurchaseOrder`,
  `cancelPurchaseOrder`, `closePurchaseOrder`; `createReceipt` takes `purchase_order`; `listReceipts` filters on it.
  Same permissions as receipts (office reads, owner and manager write, D-032).
- Screens: tab "Bons d'achat" in Achats (list, form, detail with ordered / received / remaining per line and its
  receipts); "Recevoir" on the order opens the receipt form pre-filled with what remains; the receipt form also offers
  the supplier's pending orders.
- **Not done:** editing an order, a PDF of the bon d'achat (with P2-T08's PDF service), a supplier-facing copy.
**D-095 · The Bon de livraison (BL) is the source of truth for sales (P2-T10)** · accepted · 2026-10-12
- Asked by Mahmoud: every sale movement (stock and money) is tracked from the BL once validated or printed;
  the invoice stays an optional document made afterwards.
- **A validated `Sale` is the BL.** No new table. `confirm_sale` already takes stock (FIFO), fixes cost and
  records the receivable; it now also **replaces the draft number (`VE-0001`) by the BL number
  `BL-2026-0001`** (`Sale.number`, so lists, payments, invoices and lot reports all show it). The draft number
  is kept in the audit line `sale.confirmed` (`draft_number`).
- **Numbering rule for every document code: `PREFIX-YEAR-NNNN` (4 digits), restarting each year** (counter
  series `BL-2026`, same helper as invoices `FA-` and credit notes `AV-`). Taken inside the validating
  transaction: a refused validation leaves no gap. Quotes `DV-`, drafts `VE-`, payments, expenses and
  purchasing codes still use the old `PREFIX-NNNN`; moving them to the yearly format is a later pass.
- **Offline driver:** a driver cannot validate offline (a sale stays a draft on the phone). When the
  connection is back the server validates and gives the next free BL number of the year, so no number is ever
  reserved on a phone and no clash is possible.
- **Printing validates:** screen "Valider et imprimer le BL" confirms a draft then opens the PDF. The PDF
  (`delivery_note`, `GET /documents/delivery_note/<sale id>/pdf`) exists only for a validated sale; shows kg,
  prices, total, paid/due and a signature box.
- **Walk-in customers also get a BL** (Mahmoud, 2026-10-12).
- Sales validated before this change were renumbered by migration `0007` in validation order.
- **Next (P2-T10 part 2):** one invoice for several BLs of the same customer (replaces
  `one_live_invoice_per_sale`; an invoice line points to its BL line; a BL is invoiced at most once).
**D-096 · Offline, first step: a hand-written service worker, no library (P3-T07a)** · accepted · 2026-10-12
`apps/truck/public/sw.js` (about 80 lines) plus a web manifest and icons: the app opens without signal after its
first visit and can be put on the home screen. The app files answer from the cache and refresh in the background;
API reads (not `/api/v1/auth/`) go network first and fall back to the last answer; writes are never touched. This keeps
what the screens showed in the **Cache Storage** instead of IndexedDB: simpler, no new dependency (`vite-plugin-pwa`
was not added: one more package to keep in step with Vite 8). IndexedDB comes with the write queue (P3-T07b), where
it is needed. The truck app's queries use `networkMode: "offlineFirst"` so they ask even without signal and get the
saved answer. Logging out deletes the saved API answers, so the next driver on the phone sees none of them. A banner
says when there is no signal. Not yet shown: the time of the last update on each screen.

**D-109 · An approved day is closed; recent customers first (follow-up of D-091, D-094)** (numbered D-095 until 2026-10-12, a duplicate) · accepted · 2026-10-12
Once the office approves a driver's day, that driver gets 403 on sales, road expenses, losses and returns for the
rest of that day (`dayclose.selectors.refuse_if_day_approved`, called by the driver views). `GET /my-customers` puts the
customers the driver sold to most recently first (up to 8), then the others by name, the walk-in customer last.

**D-097 · Queue of unsent sales in IndexedDB (P3-T07b)** · accepted · 2026-10-12
A sale made without connection (or when the request fails for network reasons) is kept in IndexedDB
(`apps/truck/src/salesQueue.ts`, store `sales` keyed by the sale's `client_uuid`) and the driver sees a receipt marked
"gardée sur le téléphone" with the screen's own figures. Sending (`syncSales.ts`) runs at start, on the `online` event,
after each successful sale and every 30 s, oldest first, one at a time; the server's idempotency on `client_uuid` makes
a repeat harmless. A **network error or a 401 stops the run and keeps everything**; any other server answer (400, 403...)
marks that sale **refused** with the server's message: it stays in the queue and on screen, never dropped (the office
side of this is P3-T07d). A line "N ventes attendent le réseau" is always visible while something waits. The stock
shown on the sale screen is the truck's stock minus the kilos of waiting sales, and a sale above it is blocked, so an
offline driver cannot promise more than the truck holds. Expenses, losses and the closing are not queued yet (T07c).
Not covered by automated tests (the truck app has no unit-test setup and IndexedDB needs a browser): checked in the
field test.

**D-098 · Expenses and losses join the queue; the closing waits for it (P3-T07c)** · accepted · 2026-10-12
`queue.ts` now holds three kinds (sale, expense, loss) in the same IndexedDB store, sent in the order they were made by
`sync.ts`; the receipt photo is kept with the item (IndexedDB stores files). Screens use `sendOrKeep`: send now, or keep
on the phone when there is no connection; a server refusal is shown at once and not kept. Waiting losses also count in
the kilos "promised", so a loss cannot be reported above what the truck holds. The **closing is refused while anything
waits or there is no connection** (the button is disabled with the reason), so the figures the office receives are
complete. Returning the unsold stock (`my-return`) is not queued: it needs a connection.

**D-099 · Refused sends are reported to the office (P3-T07d)** · accepted · 2026-10-12
When the server refuses an item waiting on a phone (D-097, D-098), the phone keeps it (status "refused"), shows it to the
driver with the server's reason and a "Compris" button, and reports it with `POST /my-sync-problems` (kind, what, reason,
the item's `client_uuid`: the same item reported twice makes one `dayclose.SyncProblem`). The report is retried on later
runs until it works. The office sees the open ones at the top of `/journees` ("Envois refusés") and marks them "Traité"
(`GET /sync-problems`, `POST /sync-problems/<id>/resolve`, owner and manager; the accountant reads). The office never has
to guess what is stuck on a phone, and nothing is dropped silently. **Not done:** a notice to the driver when the office
moves stock to or from their truck during the day (the stock shown refreshes at the next connection; the server check
still protects against overselling).

**D-108 · Security review of the API: what was found and closed (P4-T05)** · accepted · 2026-10-12
- `apps/core/tests/test_api_security.py` walks **every route** of the API: each has a role permission (none relies on
  "any logged-in user"), a logged-out visitor gets 401 everywhere, and each role (owner, manager, accountant, driver)
  gets 403 exactly where D-023, D-060 and D-091 say. A new view that forgets its permission class fails there. On a fully
  seeded company, the owner of *another* company asks every route with the real ids: no row, no change, empty lists
  (D-022). Approved expenses, bills, salaries, posted invoices and validated transfers refuse PUT/PATCH/DELETE (they
  already did; the test now pins it). The views write nothing themselves, and the admin is read-only for business data.
- **Holes found, each with a test, and closed:** (1) `/api/v1/schema` was readable by every logged-in user, a driver
  included: now owner and manager only. (2) No limit on the size of a request: the 8 MB photo check ran after the whole
  upload was on disk; `RequestSizeLimitMiddleware` answers 413 above `MAX_REQUEST_BYTES` (10 MB, as nginx) before reading.
  (3) The login limits of D-023 lived in each gunicorn worker's memory (3 workers: 24 attempts a minute, not 8): the
  cache is Redis when `DJANGO_CACHE_URL` is set, and **production refuses to start without it** (staging compose sets
  it). (4) The Django admin login (`/django-admin/login/`) had no throttle at all: `AdminLoginThrottleMiddleware`, 8 a
  minute per address. (5) A driver could swap or drop their truck assignment after opening the day, then sell from
  another truck than the one the day's cash and closing are counted on: refused once the day is open (the office can
  still move it); asking again for the same truck is still accepted.
- Settings pinned by tests: cookies HttpOnly and SameSite=Lax, `X-Frame-Options: DENY`, production HTTPS-only with secure
  cookies and HSTS by default, CSRF token required for a logged-in session to write.
- **Not changed, on purpose:** no general rate limit on the rest of the API (the driver app replays queues of sales after
  a lost connection: a limit would need tuning with real use; put `limit_req` on the reverse proxy if abuse appears).
  A PDF receipt is checked by its `%PDF-` header and size only, then served as `application/pdf` (nosniff in production).
  Sales and invoices views are reviewed in a follow-up after PR #55.

**D-100 · A partner named at the goods receipt, capital and rates filled in later (P6)** · accepted, provisional points marked · 2026-10-12
- On a receipt line the owner may pick a **partner** (the receipt's own supplier is allowed: the same person can be supplier and partner). The lot gets a `LotPartnership` with `terms_pending = true`, capital 0 and rates 0, created in the receipt's transaction by `partnerships.services.designate_partner` (no capital ledger entry yet). Only the owner may do it (400 on `lines.N.partner` for others).
- The owner completes it with the usual edit (`update_partnership`); sending both rates clears `terms_pending`, and the capital becomes the first ledger entry. **While pending, the terms may be filled in even after sales** (the shares are only computed at closing); once filled, the usual rule applies (fixed after the first sale).
- `close_lot` is refused while the terms are pending. **Provisional:** sales are not blocked meanwhile. Screens: partner select per receipt line, "À compléter" pill on the lot and its partnership section, "Partenaire" badge and filter on the suppliers list and page.

**D-103 · Arabic for the driver app, provisional (P3-T09)** · accepted, **texts to be reviewed by a native speaker** · 2026-10-12
The language switch (`LanguageSwitch` in `@frutti/auth`: "Français | العربية", each name written in its own language)
is on the driver login screen and above the screens of the driver app. Logged out it changes the page and the choice is
saved on the account at login; logged in it is saved on the account at once (`PUT` language, D-023 route guard applies
it). The phone remembers the last language for the next login screen (`localStorage`, device only). `ar.ts` now
translates everything the driver app shows (`truck.*`, login, common, roles) in short plain sentences; **nothing else
is translated**: the admin app stays French, and a missing key shows the French text. Arabic plurals are written once
for all six forms. Amounts, weights and dates keep Western digits (`format.ts`). The layout was already built with
logical CSS (D-025); the one physical `text-right` was fixed. **Not done:** server messages (validation errors, the
reasons of a refused sale) come back in French: Django has no Arabic catalogue yet (`backend/locale/`), which needs the
`.po` translations and gettext tooling; the native-speaker review of every Arabic text; a visual right-to-left check on a
real phone.

**D-101 · One invoice for several BL of a customer (P2-T10 part 2)** · accepted · 2026-10-12
- `Invoice.sale` is gone: an invoice has `sales` (through `InvoiceSale`, with `is_live`). Partial unique
  `one_live_invoice_per_sale` moved to `InvoiceSale`: a BL is on one live invoice (draft or issued) at most;
  a full credit note sets `is_live` false on all its BL, which may then be invoiced again. Migration `0008`/`0009`
  copies the old one-to-one links.
- `create_invoice(sales=[...])` (or `sale=` as before): confirmed BL of one named customer; lines follow the
  BL in date order and keep their `sale_line` (the invoice PDF names the BL under each line). One fiscal
  stamp and one withholding for the whole invoice. API: `POST /invoices` takes `sale` or `sales`; an invoice
  reads `sales` (and `sale` = the first, for older screens); `GET /sales?uninvoiced=true` lists the BL left.
- **Receivable per BL** (payments are allocated per BL): what the invoice asks (net to pay − credit notes ±
  certificate) is **shared over its BL by the amount each holds on the invoice**, last BL takes the rounding
  rest (`receivables.split`); the VAT of the invoice is shared the same way into each `Sale.tax_amount`. For
  one BL nothing changes. **Provisional:** a partial credit note on one BL's line lowers the invoice as a
  whole, so its effect is spread over the BL; the stock goes back to the right BL's place.
- A BL on a draft grouped invoice cannot be cancelled until that draft is deleted.
- Screen: "Ventes" → filter "À facturer", tick BL, "Facturer la sélection" (same customer, checked on the server).

**D-102 · One "Documents" page reads every document from the apps that own them (P2-T11)** · accepted · 2026-10-12
Asked by Mahmoud from another ERP's screen: one list of every document, children under their parent, the next action on
each row. **Devis = commande client, bon d'achat = commande fournisseur** (Mahmoud): no CC or CF document. A BL may
start without a devis and a BR without a bon d'achat. **No new table and no generic `Document` model**: each app
describes its own documents with `apps.core.documents.DocumentRow` from its selectors (`sales.selectors.document_rows`:
DV, BL, FA, AV; `purchasing.selectors.document_rows`: BA, BR, FF) and the read-only app `doclist` merges them
(`GET /document-index`, newest day first, at most 1000 rows with `truncated`). A row carries its `parents` as keys
(`"BL:12"`; an FF lists all its BR, an FA its BL), a `tone` for the colour (draft, waiting, done, cancelled), the model's
own status label, the PDF kind when one exists in that state, and **`actions`: what the person may do next, computed
on the server** from the same rules as the services and empty for the accountant (drivers get 403). The page draws the
tree itself (each document under the first parent present; a parent outside the period makes it a root) and runs each
action through the endpoint of the owning app (`sendQuote`, `confirmSale`, `issueInvoice`, `postSupplierInvoice`...),
or opens the existing form for what needs one (edit, credit note, receipt from an order, supplier invoice, payment):
the forms keep their rules (price in force, FIFO, credit limit) in one place instead of a second copy in a side panel.
Type and status filters run in the browser so the chips can count every type of the period; period and search run on
the server. `/achats/factures/nouvelle?reception=<id>` now ticks that receipt. **Not done:** one devis in several BL
(P2-T11 part 2, agreed with Mahmoud), supplier return RF (no supplier credit note yet, and `RF-` numbers supplier
payments).

**D-105 · Lot page summary and the list of partnership lots with their frozen figures (P6-T07)** · accepted · 2026-10-12
- The lot page already carried the result and the partner share (P6-T02/T03). It now opens with four headline figures (sales, lot costs, net result, partner's or owner's share) and the "Coût d'achat des kg vendus" step drills down to the cost of each sale, like sales and costs do.
- The "Partage des bénéfices" list (`/partenariats`) gets the net result and the partner's share of each **closed** lot, read from `GET /lot-figures?batch_ids=` (closing app, frozen `LotResult` rows only, at most 200 ids). Open lots show "Pas encore clôturé": their live result is computed lot by lot and stays on the lot page, to keep the list cheap. The `partnerships` app does not import `closing` (the dependency runs the other way).

**D-113 · Commercial and stock reports (P7-T02, P7-T03)** · accepted · 2026-10-12
New app `reports` (read-only; owner, manager and accountant, never a driver) and the page **Rapports** (menu "Pilotage",
four tabs, each with an Excel file). **Sales** by customer, product, truck, driver, day, week or month: number of
sales, kg, revenue without VAT, cost of the goods sold and margin, net of the credit notes of the period. They are the
rows of the monthly closing (`sales.report_rows`), so a report and the closing never differ by a dinar. The **driver** of
a truck is the one who opened that truck's day on the phone (`fleet.drivers_by_truck_day`, D-090); a truck day nobody
opened, or a counter sale, shows "—". **Stock value** by place and product at the purchase cost of each lot; **slow
lots** (no movement for N days, default 30, longest idle first); **losses and weight differences** per product over a
period, at the lot's cost per kg. Excel files (`openpyxl`, amounts kept as exact numbers with three decimals, a totals
row) are plain downloads next to each table. **Not done:** sales by supplier and by payment method (listed in P7-T02),
a driver/period comparison chart, and the Arabic texts (the page is French, like the rest of the admin app).

**D-106 · Stock cannot leave before it arrived (review, round 2)** · accepted · 2026-10-12
- `post_fifo_movements` and `selectors.allocate_fifo` (new `day` argument, given by `record_loss`) only take batches
  with `received_on` on or before the document's day (the local day of `occurred_at`; today when none). A transfer,
  loss or sale typed for an earlier day can no longer take a batch received afterwards, which made the daily replay of
  the ledger (`kg_by_batch_by_day`, month-end valuation) show negative balances.
- A document of today is unaffected (a batch is never received in the future). When only later batches exist for
  that day, the document is refused with the usual "Stock insuffisant" message.
- Tests that sell on past days must create their batch with an older `received_on`
  (`sales/tests/test_payments.py::stocked` now does; it was the only test relying on the old behaviour).
- Also: a product still in stock cannot be archived (PR #59); a receipt whose supplier delivery-note number is already
  on another receipt of the same supplier shows a non-blocking warning in the form (a note can cover two deliveries).

**D-111 · The driver collects customer payments on the phone (P3-T11)** · accepted · 2026-10-12
`POST /my-payments` (driver only) calls `sales.services.record_customer_payment` (D-062): today's date, cash by
default, allocated to the customer's oldest open sales. `CustomerPayment.client_uuid` (sales migration 0010, unique per
organization when set) makes a retry from the phone record it once. `GET /my-payments` lists the driver's own payments of
the day. `GET /my-customers` now also returns `owes` (what each customer owes, from the receivables), and the phone shows
it on the "Encaisser" screen. Payments join the offline queue as a fourth kind (D-098) and a refused one is reported to the
office like the others (kind `payment`, D-099). **In the day's cash:** expected cash = opening cash + cash sales + cash
payments collected − expenses; non-cash payments collected are added to "other payments"; `payments_cash` is shown on the
driver's closing screen and on `/journees`. An approved day refuses new payments (D-095). The walk-in customer cannot pay
later (the service refuses it). Cash only on the phone for now (cheques and transfers are entered at the office).

**D-104 · The owner's dashboard (P7-T01)** · accepted · 2026-10-12
`GET /dashboard` (owner and accountant; a manager gets 403 and the page falls back to the welcome) answers for the current
month up to today. **Profit and cash are two separate groups.** Profit: sales, gross margin and net operating result come
straight from `closing.monthly.month_report` (nothing is recomputed), plus last month's sales for the % change. Cash: money
collected this month (what customers paid on the spot at a confirmed sale plus their later payments, voided ones left out:
`sales.selectors.cash_collected`), what customers still owe and the overdue part (the ageing page's "customers who owe",
`sales.selectors.receivables_overview`), and the stock value at cost (the month-end valuation, which for the current month is
today's stock). Alerts: the five biggest overdue customers (and how many more), driver days not yet approved
(`dayclose.selectors.waiting_for_office`) and expenses sent for approval (`expenses.selectors.waiting_for_approval`).
**Not done:** lots with pending partner terms (needs #58), low stock and expiring batches (P7-T07), charts (kept simple).

**D-114 · In-app alerts on the dashboard (P7-T07)** · accepted · 2026-10-12
The dashboard's alerts card (D-104) gains three alerts, each from a read-only selector in the app that owns the data, each
showing at most five items and a count of all: **low stock** (`inventory.low_stock_products`: active products under their
`min_stock`, emptiest first), **lots expiring** (`inventory.expiring_batches`: kilos still in stock, `use_by` within 3 days or
already past; the 3 days is `closing.dashboard.EXPIRY_ALERT_DAYS`, provisional, to confirm with the client) and **unexplained
cash differences** (`dayclose.selectors.unexplained_cash_differences`: driver days not approved with counted cash different
from expected, where the driver left no note or the office asked for a justification and has not got it). **Fourth alert:** partner lots whose terms are still to fill in (D-100, `partnerships.selectors.pending_terms`, links to the lot). **Not done:** SMS/WhatsApp (Phase 8); no per-user read/dismiss state.

**D-112 · Data import from Excel and opening balances (P4-T01)** · accepted · 2026-10-12
- New app `dataimport` (owner only, `openpyxl`). One Excel template per kind (products, suppliers, customers,
  employees), downloaded from **Import de données** (`GET /imports/<kind>/template`): French titles on row 1
  (a star marks a required column; titles are matched without case, accents or star), an "Aide" sheet explains
  each column.
- `POST /imports/<kind>` (multipart `file`, `dry_run` default true) returns a report row by row: created, skipped
  (reference already known: the same file may be sent again) or error with **column and reason**. It runs the real
  services (`create_product`, `create_supplier`, `create_customer`, `create_employee`) in one transaction, so every
  screen rule applies and each row is audited. A dry run, or any error, rolls everything back: **all or nothing**.
  The screen offers "Importer" only after a clean check.
- Products need an existing category (a typo is an error, not a new category) and a price above 0; customers take
  their type by French label or code; numbers accept a comma; dates are JJ/MM/AAAA.
- Opening balances (customer and supplier debts, opening stock per location and lot) come in later slices of the
  same task.

**D-115 · A devis is delivered in as many BL as needed (P2-T11 part 2)** · accepted · 2026-10-12
Agreed with Mahmoud: the kilos left on a devis stay open for another BL. The constraint `one_live_sale_per_quote` is
gone (migration `0011`); nothing new is stored. What is left is **computed**: `sales.selectors.quote_delivery` adds the
kilos of every sale made from the quote that is not cancelled, **drafts included** (their kilos are spoken for), and
matches them to the quote lines **by product** (a BL whose lines were retyped still counts; a product quoted twice fills
its first line first; kilos beyond the quote are ignored). `create_sale_from_quote(lines=[{quote_line, quantity}])` takes
part of each line and refuses more than what is left ("Il reste 2.000 kg à livrer sur cette ligne", under the line);
without `lines` it takes everything left; a quote delivered in full is refused. The quote is row-locked meanwhile, so two
people cannot deliver the same kilos. Cancelling a BL frees its kilos. API: `POST /quotes/<id>/convert` takes `lines`; a
quote reads `sales` (all its BL, oldest first; `sale` stays = the last one), `remaining_quantity`, and per line
`delivered_quantity` / `remaining_quantity`. Screens: one dialog (`quotes/DeliverDialog`) for the devis page and the
"Documents" page, prefilled with the kg left; the devis page shows "Reste à livrer" per line and all its BL; on
"Documents" a devis keeps "→ BL" until it is delivered in full, then turns green. **Not done:** the same for a bon
d'achat needed nothing (partial receipts exist since D-076); a devis has no "close the rest" action yet (the rest simply
stays open until its validity date).

**D-116 · Financial reports (P7-T04)** · accepted · 2026-10-12
Five reports on the **Finances** tab of Rapports, **owner and accountant only** (the manager and drivers get 403: this is
the company's money), each with a date or month filter where it makes sense and an Excel file. Everything is read from the
selector that owns the number, nothing is recomputed: **month result** = `closing.selectors.month_result` (the monthly
closing's own report: revenue, cost of goods, spoilage, expenses by category, personnel, net result); **customers who
owe** = the receivables of D-062 (balance, overdue, ageing 0-30 / 31-60 / 61+; customers whose credit we hold are left
out); **suppliers owed** = `purchasing.supplier_balance` per supplier (posted invoices minus payments, overdue, and goods
received but not invoiced, which are not owed yet; partner capital and profit shares stay out, D-040); **unpaid
salaries** = `hr.unpaid_by_employee`. **Cash flow** by day, week (Monday) or month: in = paid on the spot at confirmed
sales (by sale day) + customer payments (by received day, voided left out); out = supplier payments + salary payments +
approved expenses (an approved expense is taken as paid on its date, whatever its payment method: provisional). It is a
movement report, not a bank reconciliation: there is no opening balance. Payroll accruals are not cash and appear in the
month result only.

**D-117 · Partnership report (P7-T05)** · accepted · 2026-10-12
Tab **Partenaires** on Rapports (owner and accountant only), one row per partner and a totals row, with a date range and an
Excel file. **Over the period** (by entry date, straight from the two partner ledgers, `partnerships.partner_flows`): capital
put in, loss share deducted from the capital (net of reversals), capital returned; profit share earned, losses beyond the
capital (owed by the partner), late adjustments (signed) and shares paid out. **Today** (the same selectors as the partner
screens, `capital_by_partner` and `profit_share_balance_of_partner`, so the report never disagrees with them): capital still
in the company and the share still due (negative: the partner owes it). The three balances (capital, profit share, trade
payable) stay separate (D-031, D-040); the supplier payable is in the Finances tab, not here. A lot's settlement
appears as its capital return and its share payment. **Not done:** a per-lot breakdown under each partner (the lot screens
have it), and Arabic texts.

- **Opening stock** (slice 2): kind `opening_stock`, one row per lot: product and supplier by reference, location
  by name, kg, cost per kg, reception date. Each row creates a batch (`receipt_reference` "STOCK-OUVERTURE") and
  posts a `receipt` movement through `inventory.services`, so the ledger and FIFO work as for any lot. Sending the
  file again skips a lot already imported (same product, supplier, date, cost); the same lot twice in one file is
  an error (group the kilos).
- Customer and supplier opening debts: slice 3.

**D-119 · The employee's own CNSS is computed and withheld (P5-T04, follows D-055)** · accepted, **provisional rate** · 2026-10-12
Until now `SalaryRecord.net = gross − deductions` with `deductions` typed by hand, so an approved salary with nothing
typed showed net = gross: the employee's own CNSS contribution was never taken off. Now `Employee.employee_cnss_rate`
(default **9,18 %**, provisional: the accountant confirms it, like the employer's 17,07 %; Q26) and, on each record,
`employee_cnss_rate` (copied from the employee when the month is generated, and changeable on a draft like the employer
rate) and `employee_cnss = gross × rate`, rounded once. **net = gross − employee_cnss − deductions.** The contribution is
its own line (payroll table, month totals, the salary dialog's preview, the employee's page, `payroll_summary`), not
hidden in "deductions", which stay for what is typed by hand (advances, absences). **The company's cost is unchanged**
(gross + employer CNSS): the employee's share is part of the gross, withheld and paid to the CNSS. **Existing data:**
approved salaries keep their figures (rate 0): they are history and immutable; draft salaries get the employee's rate in
the migration. The import template has a column for the rate. **Not done:** income tax (IRPP) and other legal
withholdings (Q26); a payslip PDF does not exist yet (nothing to update there); the CNSS declaration itself.

- **Opening debts** (slice 3): kinds `customer_debts` and `supplier_debts`, one row per debt (party by reference,
  amount, date, notes). A customer debt is a confirmed `Sale` with `is_opening` (number `OUV-<year>-0001`, no
  lines, no stock, attached to the archived place "Solde d'ouverture"): it ages from its date, payments are
  allocated to it, and it is never invoiced nor counted in sales counts or lot results. A supplier debt is a
  posted `SupplierInvoice` with `is_opening`, its amount typed and no receipts; payments settle it like any other.
  A re-sent file skips a debt already there (same party, amount, date). Cancelled with a reason if wrong.

**D-120 · Yearly numbers for quotes, expenses, salary payments and supplier payments (P2-T10 follow-up)** · accepted · 2026-10-12
- New documents of these four kinds are numbered `PREFIX-YEAR-NNNN` and restart every year, like BL, invoices and
  credit notes: `DV-2026-0001` (quotes), `DP-2026-0001` (expenses), `PS-2026-0001` (salary payments),
  `RF-2026-0001` (supplier payments). The year is the day the document is created.
- **Existing records keep their old number** (`DV-0001`): history is not renamed. Both styles coexist; the old
  counters stay as they were (provisional: a later pass may renumber if the accountant asks).
- Counters: sales and expenses use one counter row per `PREFIX-YEAR` series; hr `PaymentCounter` and purchasing
  `DocumentCounter` gained a `year` column (0 = the numbers without year), so the unique key is
  organization (+ kind) + year.
- **Still plain sequential** (not in this decision): draft sales `VE-`, customer payments `RG-`, supplier invoices
  `FF-`, transfers, losses, counts, goods receipts, purchase orders.

**D-121 · Picking a lot by hand on a sale line (owner request, counter sale)** · accepted · 2026-10-12
- FIFO (D-009) stays the default everywhere, but a sale line may now name the lot it wants kilos from first:
  `SaleLine.requested_batch`, resolved and checked (same organization, same product as the line) in
  `sales.services._checked_batches`. `inventory.services.post_fifo_movements` takes an optional
  `prefer_batch_id`: that lot moves to the front of the FIFO order, the rest keeps oldest-first. Stock never
  goes negative (`on_hand_never_negative`, D-006): a short lot is topped up from the other lots automatically,
  same as a line with no lot named; the till warns before sending the sale when the typed weight is more than
  the chosen lot holds, but does not block it.
- New read endpoint `GET /inventory/locations/<id>/stock/<product_id>/batches` (`inventory.selectors.location_batches`)
  lists a product's lots at one location, oldest first, each with its supplier and the location's name — a
  hint for the till (which cold room, which supplier), **never printed on a devis or a BL**.
- Built first for the counter sale screen (`CounterSalePage.tsx`); `SaleWriteSerializer` accepts `batch` on
  every line (`SaleLineWriteSerializer`), so a regular sale or quote-to-BL screen can get the same picker
  later without a backend change.
- Considered and rejected: truly letting the chosen lot's on-hand go negative. It would mean relaxing
  `on_hand_never_negative` for every module sharing `StockOnHand` (losses, transfers, counts) and teaching
  `rebuild_on_hand` (D-038) to treat a negative ledger as a known state instead of corruption — too large a
  change for what the owner actually needed (sell now, reconcile the lot later).
**D-122 · Clôture mensuelle: clickable figures and each partner's share of the shared costs (owner request)** · accepted · 2026-10-13
- The owner pointed out that rent, electricity, fuel and the other costs the lot result engine already
  splits over the lots in stock (D-041) land on partnership lots too: a partner effectively carries part of
  these charges, and the month closing should show it, not just the month's own total.
- New `closing.partner_costs.month_partner_cost_shares`: for every partnership (any status) with a cost
  line dated in the month (`closing.selectors.cost_rows_for_batch`, reusing the lot result engine's cost
  rows), groups the **raw cost** their lots carried by category and totals it per partner — not weighted by
  the partner's profit or loss %, so it answers "where did this charge go", the same breakdown already on
  the lot page (`LotResultCard`), just totalled across lots. An employee's day/monthly cost has no single
  category (its title is their name): grouped under a fixed `employee` key instead. Exposed as
  `MonthReport.partner_costs`, a new card on `/cloture` next to "Dépenses approuvées".
- `expenses.LotCostLine` and `closing.engine.CostRow` gained `category_id` (the underlying `ExpenseCategory`
  id, `None` for an employee's day): what the new card's category rows link to on `/charges?category=…`.
- Made existing month-closing figures clickable: the stock valuation rows already had a lot id (link to
  `/stock/lots/<id>`); "Dépenses par catégorie" rows now link to `/charges` filtered by that category and
  the month's date range (`ExpensesPage` reads `category`/`date_from`/`date_to` from the URL on mount);
  "Ventes", "Pertes et écarts d'inventaire" and "Salaires du mois" link to their list pages without a date
  filter (those screens do not take one yet — a smaller follow-up, not blocking this).
- Not done here: a full itemized drill-down (the individual sales, expense lines, losses and payroll
  entries behind each month-level total) would need new list endpoints per line; this session reused what
  already exists (lot-level cost rows, stock valuation rows, expense categories) rather than add new ones.
**D-123 · Paramètres: company logo, users, own profile (owner request, not a phase-file task)** · accepted · 2026-10-13
- The owner asked for a place to manage the company and its accounts. Single organization only; the
  multi-company onboarding stays in Phase 8. New fields: `Organization.logo` and `User.avatar` (ImageFields,
  re-encoded to WebP by `core.images.reencoded_photo`, stored under a new random name on each upload so
  caches never show an old picture). Legal identity (name, address, phone, MF, trade register) stays on the
  versioned `FinanceSettings` (D-043) and is shown in Paramètres; it is edited on `/factures/parametres`.
- Users are managed by the owner only (`IsOwner`, server-enforced). Deleting a user means **deactivating**
  the membership and the login: other rows keep their history. The last active owner cannot be demoted or
  deactivated (`services._guard_last_owner`).
- No email or SMS exists, so a password reset is the owner typing a new password for someone (the old one
  stops working and the sessions are closed). A person changes their own password from "Mon profil", which
  asks for the current one; the session stays open (`update_session_auth_hash`).
- Each person sets their own photo and display name from "Mon profil" (topbar avatar links there). Avatars
  and logos are served by authenticated endpoints, not public media URLs; a member's photo is visible only
  to people in the same organization.
- Not yet: printing the logo on documents (planned with the PDF templates). Done in D-125.

**D-124 · Returnable boxes (caisses): a count ledger, separate from kg stock (Q27)** · accepted · 2026-10-13
- Two box types (small, big). Boxes are **counted in whole units** in their own append-only movement table
  (`BoxMovement`: organization, box type, count, from and to, source document, posted through a service in a
  transaction). They are never products and never touch `StockOnHand`, kg, FIFO or lots (no lot tracking).
- Holders are **locations** (cold rooms, trucks), **clients** and **suppliers**. Balances are derived from the
  ledger: boxes per location, boxes held by each client, boxes owed to each supplier. A box left at a client
  stays out of the truck until collected.
- Supplier boxes: boxes received from a supplier must go back to that supplier. Each supplier has a balance
  "boxes owed", separate from money (supplier payables) and from partner capital (three-balances rule).
- Sign convention (step 1, `apps/boxes`): locations and clients show arrivals minus departures; a **supplier shows
  receipts minus returns**, i.e. what we owe it, which is never negative.
- No deposit and no money in the box ledger (owner answer). No tare: box weight is not in kg figures.
- Lost or broken boxes are a **company overhead** (write-off movement with a reason), not charged to clients or
  drivers, and not part of a lot's costs (so they do not change partner profit, D-040 / D-041).
- Driver app: count on loading, "boxes left" on a sale, "boxes collected" on a pickup visit, and a box
  reconciliation at the evening closing (D-094), the same way as kg. Admin: a "Caisses" page under Stock and a
  box section on the client page.
- **Status after PR #100:** built: steps 1 to 4 of the ledger (#95 ledger, #97 receipt and transfer hooks, #98 admin "Caisses" page, #100 sale with boxes online, pickups online, day view with loaded, left and collected counts). **Open, owner decisions, not built:** (2) the truck's "expected boxes" is the real ledger balance, not today only; (3) box actions (sales with boxes, pickups) go into the driver offline queue with idempotent retries; (4) a truck-to-cold-room "return" movement, posted with the transfer. Also open: Arabic box texts, and a browser check of the driver screens.

**D-125 · Invoice PDF follows the company's paper invoice; the uploaded logo everywhere (owner request)** · accepted · 2026-10-13
- The owner sent their current paper invoice (facture 2026M30013) and asked for the same page "with a small
  enhancement". `sales/pdf/invoice.html` now draws that layout: logo and company block top left (address,
  Tél, MF, "Identifiant unique" = tax-id number + key letter), boxed "Facture N°", a Date | Client box, the
  client block (Client, Code client = `Customer.reference`, Type, Adresse, Téléphone, MF), a ruled lines table
  (Code Art = product reference, Désignation, Qté, Unité, P.U.H.T, Remise %, Prix HT, Tva %) drawn down to a
  fixed height like the form, the Frais / Timbre fiscal box, the totals box (HT avant remise, remise, HT, TVA,
  TTC, in TND), "Arrêtée la présente Facture à la somme de : … Dinars … Millimes" (`documents/words.py`,
  traditional French spelling), the signature area and a footer with the address and "Page x / y".
- The enhancements over the paper form: the unit, the lots under each line, the delivery note numbers, the
  due date ("Payable à réception" without one), VAT per rate when there are several, withholding and net to
  pay when applied, the "ANNULÉE PAR AVOIR" banner and the notes.
- "Type" (personne morale / physique) is read from the category letter of the customer's tax id (M / P),
  else "Personne physique" for a "Particulier"; blank otherwise. Code client and phone are read live from the
  customer (not frozen on the invoice). "Frais" has no field yet and prints 0,000 like the paper form.
- Every PDF gets the logo uploaded in Paramètres (`documents.services.render_html` adds it as a `data:` URI;
  the shared header of `pdf_base.html` prints it, the invoice its own header). A stored PDF's version carries
  the logo's file name, so a new logo makes old files stale and they are made again on the next request.
- The admin top bar and the driver app header show the logo instead of the default mark, and it becomes the
  browser-tab icon once logged in (`useFavicon`); the default icon stays for the login page (the logo
  endpoint needs a session). The admin app got a default `favicon.svg`.
- The product list the owner forwarded (ART0002 to ART0060) is not imported by this change; the codes print
  as soon as products carry them as `reference` (through the data import or the product page).

**D-126 · "Frais" on invoices; the owner's article codes as product references (owner decision)** · accepted · 2026-10-13
- `Invoice.fees` ("Frais", DT): an amount the office types on the draft (empty = none), printed in the Frais
  box of the PDF (D-125) and on the invoice page. It adds to the total like the fiscal stamp: no VAT on it and
  no withholding (`total_incl_tax = HT + TVA + timbre + frais`), so the customer owes it through `net_to_pay`.
  It is not lot revenue: lot profit still comes from the sale lines only.
- `CreditNote.fees`: a full credit note gives back all the fees still on the invoice, a partial one none (like
  the stamp), so a cancelled invoice leaves nothing owed. Migration `sales.0015`.
- The owner's product list: only the article codes are taken (`catalog/product_codes.py`, ART0002 to ART0060).
  `manage.py set_product_codes --organization <id>` reports, `--apply` writes each code into the `reference`
  of the product with the same name (case, accents and spaces ignored), through `update_product` (audited).
  No product is created and nothing else changes. Left alone and reported: no product with that name, several
  products with it, the code already on another product, and names the list gives twice (ART0047 and ART0055
  were both "Maklouba rosé congelé M0"). It must be run on the server.
- Owner answer (2026-10-13): "Maklouba rosé congelé M0" takes ART0047; ART0055 is removed from the list and
  stays unassigned.
- Dry run on staging (2026-10-13): only 2 of the 38 codes matched a product (crevette royale, Calamar); the other
  36 articles are not in the catalogue. Owner answer: create them. `set_product_codes --create-missing` creates
  each missing article with its code as reference and its name as in the list, in kg, in a category "À classer"
  for the owner to sort, and **with no sale price**: prices are not taken from the list, the screens show "no
  price" until one is set on the price board. A code another product already has is left alone and reported.
- Applied on staging on 2026-10-13: 2 codes written, 36 products created; a second run reports 38 unchanged.

**D-127 · Admin can record returnable boxes on a receipt and on a load (bug, owner report)** · accepted · 2026-10-13
- Found: the admin app had no way to post a box movement. The receipt and transfer APIs took `boxes` since P1-T14b,
  but the admin forms never sent it, and the Caisses page was read only. The box types are a fixed choice
  (`BoxType`, small and big), not a table, so "no box type exists" was not the cause. Nothing was seeded wrongly.
- Fix: a "Caisses reçues avec la livraison" card on the receipt form and a "Caisses chargées dans le camion" card on
  a load (shown only for a load), both sending the counts the server already takes. A draft load reloads its saved
  counts: `TransferDetail` now returns `boxes`, because saving a draft replaces them. The empty Caisses page links to
  both forms for whoever may record them.
- Still open, not built: an opening balance (boxes already at clients, in cold rooms, or owed to suppliers). It needs
  a movement kind with one side outside the ledger, and a decision on the sign for a supplier. Proposed as a small
  owner-approved follow-up, not in this change.
- Load question (owner): keep the count as a field on the load transfer (one document, posted in the same transaction
  as the kg), not as a separate movement screen. A separate movement would need its own source document and could drift from the load.

**D-128 · Editing a monthly cost template updates its months not yet approved (owner report)** · accepted · 2026-10-13
- The owner changed a monthly cost (Frais généraux) and the month result did not move: the template change only
  applied to months generated later. Now `update_recurring_cost` also rewrites the expense of every month already
  generated whose expense is still a draft or waiting for approval (amount, category, name, payee, payment method),
  through `update_expense` (audited). An approved month keeps its amount: a correction is a new expense.
- The month result counts approved expenses only, so the change shows there once the expense is approved.
- The admin refreshes the month screen and the dashboard after any expense change (`refreshExpenses`).
**D-129 · Closing waits for the phone's waiting sales and says why; a sale sent again is not refused (follow-up of D-090, D-091, D-094)** · accepted · 2026-10-13
- The closing stays blocked while any item of the phone queue is pending (D-090). The page now says how many wait and why (no connection, no answer, server busy, session ended), has a retry button, and sends them as it opens. Pure gate in `closingGate.ts`.
- A send gives up after 25 s (`SEND_TIMEOUT_MS`, `sync.ts`), so one hung request no longer blocks every later sync until the page is reloaded.
- 408, 429, 502, 503 and 504 keep the item pending (the server is busy, it did not refuse the item). Other 4xx and 500 still make it refused and reported to the office. 401 keeps it pending and reports the ended session.
- Backend: a sale the server already has under the same `client_uuid` is answered 201 with that sale, checked before the day-approved check, so a retry after approval is not refused as a new sale. A new sale on an approved day is still 403 (D-094).

**D-130 · A truck's day starts from what it held, not from today's loads (bug on staging, 2026-10-13)** · accepted · 2026-10-13
- Cause: the driver's Clôture showed "vendu" above "chargé" (Crevette 109 sold, 100 loaded). Nothing was oversold:
  the ledger never goes below zero (`post_fifo_movements` refuses, DB check `on_hand_never_negative`). The kilos
  sold had stayed on the truck from an earlier day, and `truck_day` only counts today's validated transfers.
- `inventory.selectors.location_stock_before`: what a location held at the start of the day, from the ledger
  (movements dated before it). `day_summary` shows it per product as `opening`.
- `unexplained` = left (ledger) - (opening + loaded - returned - sold - lost). It is never clamped: a gap is shown in
  red with "prévenez le bureau" (stock out or in without a sale, loss or transfer of this driver).
- Historical ledger rows and closing snapshots are not changed; old snapshots simply lack the two new fields.
- Driver screens other than Ma journée get a "Retour à Ma journée" button under their content (`BackToDay`).
- Not changed (open): an offline sale is dated when it is sent (`sold_at` is the server's moment for a driver),
  so a sale made yesterday and sent today counts as today's sale and its price is today's. (Changed by D-133.)

**D-131 · Every document uses the invoice's header and footer, in the PDFs and on screen (owner request)** · accepted · 2026-10-13
- The owner asked that every printed PDF and every document view in the app carry the frame of the facture
  (D-125). The header and footer moved from `sales/pdf/invoice.html` into `documents/pdf_base.html`: logo or
  company name, address, Tél, MF, Identifiant Unique, RC top left; boxed "<Document> N° …", a Date | Client
  box and the client block (Client, Code Client, Type, Adresse, Téléphone, MF) top right; "Adresse : … ·
  Téléphone : …" and "Page x / y" at the foot of every page. Devis, bon de livraison, avoir, reçu and the
  partner statement now print it; each keeps its own body (lines, totals, signatures).
- A provider gives the header `doc_date` and `party` (a dict: label, name, address, phone, tax_id, plus
  `reference` / `type` when that row should print); `banner` (status stamp) and `head_meta` (BL numbers,
  due date, validity…) are template blocks. The partner statement shows "Partenaire" where the others show
  "Client", dated the closing day (closed lot) or the printing day (open lot, which re-renders daily).
- The Identifiant Unique is read from the tax id by `documents.services.unique_identifier` (template filter
  `unique_id`), so every document prints it, not only the invoice.
- In the admin app, `lib/DocumentFrame.tsx` (`DocumentHeader`, `DocumentFooter`) draws the same frame on the
  invoice, quote and sale (BL) pages, with the logo from Paramètres. The invoice shows its frozen seller; a
  quote or BL shows the finance settings in force (`useSeller`). The quote's customer link moved to "Suivi".
  The quote/sale customer payload gained `phone` for the client block.

**D-132 · A driver day worked on after it was sent is sent again (follow-up of D-094)** · accepted · 2026-10-13
- Seen on staging: a driver sent the day, was loaded again and kept selling. The phone showed the new figures but the
  closing kept the old count, could not be sent again ("déjà envoyée"), and the office would have approved figures
  that were no longer the day's.
- `dayclose.selectors.changed_since_sent(closing)` compares the sent summary with the day as it is now (opening cash,
  sales, payments, credit, expenses, expected cash, and per product loaded / sold / lost / returned; not the stock
  left in the truck, which moves on later days). Exposed as `changed_since_sent` on the driver's closing and the
  office detail. An approved day never counts as changed.
- While it is true, the driver can send the day again (new count, the summary saved again; audit
  `day_closing.resubmitted`), and the office **cannot approve** (400) until the day is sent again; it can still ask
  for a justification. The phone shows the count form again with a warning; the office dialog shows a warning and
  the approve button is disabled. Selling after sending stays allowed (only an approved day is closed, D-109).
  (Changed by D-134: sending closes the day and a new load of that date opens it again; `changed_since_sent`
  reads D-134's list of changed figures.)

**D-133 · A driver's sale is dated when it was made, as the phone says, within limits (owner decision; follow-up of D-091, D-094, D-129, D-130)** · accepted · 2026-10-13
- Before: for a driver `sold_at` was the server's clock, so a sale made without connection yesterday and sent today
  was today's sale, at today's price, in today's closing.
- Now the phone sends the moment the driver validated the sale in `sold_at` (the field `POST /sales` already had),
  sent at once or kept in the queue; `sync.ts` sends it with the queued sale. A sale queued by the earlier app has
  none and takes the time it was queued (`madeAtOf`), the same moment. The phone is not trusted: the server checks
  the time before using it (`sales.services.moment_from_phone`, then the sale view), in this order:
  1. A sale already recorded under the same `client_uuid` is answered as recorded, before any check (D-129, kept).
  2. **Clock tolerance: 5 minutes, both ways** (the existing `CLOCK_MARGIN`). Within it the server's own clock dates
     the sale: an online sale is dated exactly as before, and a phone a little fast or slow never moves a sale to
     another day around midnight. No time sent: the server's clock, as before.
  3. More than 5 minutes in the future: refused, 400 on `sold_at`, naming the time and asking to check the phone.
  4. The driver's truck **of that day** (D-042: the day's assignment, else the usual truck): another truck is 403.
  5. The driver's day **of that date** must not be approved (D-094): 403 "Votre journée du JJ/MM/AAAA est approuvée
     par le bureau : elle est fermée, plus rien ne s'y ajoute." A day sent but not approved still takes the sale.
     Only the sale's own day counts: a later day already approved does not refuse it.
  6. The stock (below): 400 on the line.
- **No day started on that date: the sale is accepted.** Starting a day needs a connection and selling does not, and
  an online sale never needed a started day; refusing would throw away every sale of a driver who had no signal all
  day. Such a sale is dated on its day, from the truck the driver had that day, and belongs to no day closing.
- **What follows the date.** Everything reads `sold_at`: the price in force at that moment, the sales lists, the day
  summary and closing of that day (`dayclose.selectors.day_summary`), the customer's balance and ageing (the sale's
  day until it is invoiced, then the invoice's), reports, month figures and lot results. `confirmed_at` and
  `created_at` still say when the sale reached the server.
- **Stock ledger.** A movement has `occurred_at` (when it happened) and `created_at` (when it was recorded); the day
  figures replay the ledger by `occurred_at`. The late sale's movements are appended today and dated at the sale:
  no row is rewritten or reordered. Recomputed, the opening stock (D-130) of every later day drops by its kilos,
  which is right: they had left the truck. New check, for a driver's sale dated on an earlier day only
  (`post_fifo_movements(held_since_then=True)`, `inventory.selectors.least_held_since`): a lot gives at most the
  lowest end-of-day balance the truck has had of it from the sale's day until now. So no day in between starts
  below zero, and the lot taken was on the truck that day (profit per lot). Otherwise 400 "Stock insuffisant à
  cette date : « Camion » n'a gardé que X kg de ce produit depuis le JJ/MM/AAAA." Checked per day, not per hour:
  a load typed afterwards is dated at noon (D-039), so hours inside a day prove nothing.
- **Refusals reach the office.** Any refusal above is a 400 or 403: the queue marks the sale refused and reports it
  as a sync problem (D-099, D-129); nothing changed there. Online, the driver reads the message on the sale screen.
- **Not corrected by a late sale** (known, accepted):
  - Closing figures kept "as sent" (`DayClosing.summary`): the snapshot of the sale's day when it was already sent,
    and of the days in between, approved or not, keep the old cash and stock. Only live figures move.
  - The BL number is the next of the year the sale is confirmed in, not of the year it was made in.
  - Returnable boxes: a box movement only has its recording date, so the boxes count on the day they are recorded.
  - Expenses, losses, customer payments and box pickups kept on the phone are still dated when they are sent.
  - A month already closed changes in its live figures (shown as drift, D-074), like a sale typed late by the office.
  - The price is the server's price in force at that moment, not the one the phone showed (P3-T02, D-051 open).
  - Lots: among what the truck has held since, FIFO runs when the sale is recorded; sales recorded in between may
    already have taken the older lot.
  - A phone clock set wrong in the past cannot be seen, as long as the driver had the truck and the kilos that day.
  - The check on stock held since is not applied to a sale typed late by the office, nor to a driver's draft that
    waits for a credit approval and is confirmed later.
  - A driver still cannot close a day that is over (the closing endpoints are today's only). (Changed by D-134:
    the history sends a day left running.)

**D-134 · Sending the closing closes the driver's day; a new load of that date opens it again; the history of days (owner decisions 2026-10-13 and 2026-10-14; follow-up of D-094, replaces D-109's lock, reworks D-132; carries D-129, D-130 and D-133)** · accepted · 2026-10-14
- **The owner's rule.** One day per driver and date. Sending the closing closes it: `DriverDay.ended_at` is set
  (`fleet.services.end_driver_day`, inside `submit_day_closing`). From then on the driver gets 403 "Votre journée
  est clôturée : elle rouvre quand le bureau recharge votre camion." on road expenses, losses, returns, customer
  payments and box pickups (`dayclose.selectors.refuse_if_day_closed`, was `refuse_if_day_approved`), and on sales
  (below). Before, only an approved day was closed. The driver cannot open the day again: `POST my-day` returns
  the same day, still closed.
- **How this decision moved.** First built on 2026-10-13 as "a later sale needs a new day": the driver started a
  numbered second day on the same date with a new cash float. The owner changed it on 2026-10-14, before it was
  merged: no second day, the same day opens again, and what opens it is a new load. `DriverDay.number`, the days
  numbered per date and the windows between them are gone.
- **A load reopens the day.** When the office validates a load (a transfer into a truck) dated today, the day that
  truck's driver had sent today runs again, in the load's own transaction. `inventory.services.validate_transfer`
  sends the signal `load_validated`; `dayclose.signals` answers with `dayclose.services.reopen_days_after_load`
  (inventory does not import dayclose, which depends on it). `ended_at` is cleared and the closing takes the new
  status **`reopened`** ("Rouverte"). The driver sells, then sends the closing again, and the day ends at that send.
  Not reopened by: a load dated another day, a return, a move between cold rooms, a load into another truck, or a
  load into a truck the driver no longer has that date (`fleet.selectors.closed_days_on_truck`).
- **An approved day reopens too (owner decision): the one exception to "an approved closing never changes".** The
  approval is not lost. Each reopening writes a `DayReopening` row, never changed afterwards: the send as it was
  (status, expected and counted cash, difference, note, figures, when it was sent, who reviewed it and when), the
  load and who validated it. The audit log has `day_closing.reopened` too. This is the "reopened closing with
  reason" of ARCHITECTURE §4 rule 5: the reason is the load. Nothing else undoes an approval.
- **Cash already handed over (owner decision).** The cash counted at a send that a load undid went to the office.
  `day_summary` has `handed_over` (the counted cash of the day's reopenings, added up), and `expected_cash` is what
  the driver should hold now: opening cash + cash sales + cash payments - expenses - handed over. So at the next
  send the driver counts only the money in hand. Cash missing at the first count is still missing at the last one:
  the last closing's difference is the whole day's. **Assumed, not typed by anyone:** the driver gave the office
  exactly what they counted. One who kept the money counts it again, and the surplus is a difference to explain in
  the note.
- **While the day is reopened** the office can neither approve nor ask (only a `submitted` closing is reviewed).
  The list has a "Rouvertes" filter; the dialog says the day was reopened and lists the sends that were undone. A
  reopened day is left out of the dashboard's days waiting for the office and of its unexplained cash differences.
  The office's question (`review_note`) survives a reopening and the phone still shows it.
- **D-132 kept, read on one comparison.** `changed_since_sent` is now "`changes_since_sent` has a row": the day's
  figures and, per product, opening / loaded / sold / lost / returned / left, all over the day's window. While it
  is true the office cannot approve (400), the driver sends the day again, the phone shows the day's records and
  the count form with a warning, and the office dialog lists each figure as sent against now. D-132's "selling
  after sending stays allowed" is replaced by the rule above; the case it was written for (loaded again after
  sending) is now a reopening.
- **A day is a window of its date** (`fleet.selectors.day_window`): from local midnight to the moment its closing
  was sent, and at the latest the end of the date. While the day runs (never sent, or reopened) it is the whole
  date.
- **Which sales a day takes (D-133 carried):** `dayclose.selectors.refuse_sale_outside_day`, called by the sale
  view after the truck check, with D-133's order kept (a sale already recorded under its `client_uuid` is answered
  first, D-129; then the clock checks; then the truck of that day):
  1. No day started on that date: accepted, the sale belongs to no closing (D-133, unchanged).
  2. Made at or after the moment the day ended: 403, with the message above for today, and for an earlier date
     "Votre journée du JJ/MM/AAAA était déjà clôturée quand cette vente a été faite : elle n'est pas enregistrée.
     Prévenez le bureau."
  3. The day is approved: 403 with D-133's messages.
  4. Otherwise accepted. In particular **a sale made before the closing was sent and received after it is recorded
     on that day** while the office has not approved it; the closing then counts as changed (above).
- **A refusal never waits for ever.** Each one is a 403: the phone's queue marks the sale refused and reports it to
  the office (D-099, D-129, `sync.ts` unchanged). Online, the driver reads the message on the sale screen.
- **The sent figures stay as sent.** `DayClosing.summary` is not rewritten by a late sale. The phone shows a sent
  day as sent (`selectors.day_answer`), and the day's records whenever the driver is about to send again: the
  office asked a question, a load reopened the day, or the records changed since the send.
- **Stock per day (D-130 carried).** Everything is read from the ledger on one clock, `occurred_at`: `opening` is
  the truck's balance at the start of the window (`inventory.selectors.location_stock_at`), `loaded` / `returned` /
  `lost` are the transfer and loss movements dated inside it (`location_moves_between`), `sold` the driver's sales
  made inside it, `remaining` the balance at the end of the window (what the truck holds now while the window is
  open). So opening + loaded - returned - sold - lost = left, and `unexplained` is only stock that moved with no
  sale of this driver, loss or transfer. What the office moves after the send (the truck unloaded in the evening)
  stays out of the sent day. Customer payments and road expenses are cut on `created_at` (they are dated when they
  are sent, D-133).
- **The driver's screens (D-129, D-130 carried).** The closing screen and the history share `DayReport.tsx`: the
  wait for the phone's unsent items with its reason and the retry button (`closingGate.ts`), the send as it opens,
  the opening stock and the gap in red, "Déjà remis au bureau", and the notice of a reopened or changed day. On a
  closed day "Ma journée" says the day reopens with a load and has a button to ask the server again; no cash float
  is asked a second time. A day sent before D-130 has no opening stock in its kept figures and is shown without it.
  The office's stock table shows "Au départ" and "Écart" too.
- **History:** the driver sees their last 60 days (`GET my-days`, `GET my-days/<id>`) and can send a day from there
  (`POST my-days/<id>/closing`): the answer to the office's question, or a day left running on an earlier date.
  "Ma journée" shows a warning when the office asked about a day. The office's `/journees` page filters by driver
  or truck name and dates (last 200 rows).
- Migrations `fleet.0004` (`ended_at`), `dayclose.0003` (days already sent end when their closing was sent) and
  `dayclose.0004` (`DayReopening`, the `reopened` status). The Arabic texts are provisional (D-103).
- **Known limits:**
  - The load screen does not warn before it reopens a day, also an approved one. The Journées page shows it after.
  - Nothing is pushed to the phone: it learns of the reopening when it next asks the server (a screen opened, the
    button on "Ma journée"). The sale screen does not check the day first: a sale tried on a closed day is refused
    by the server (online the driver reads why; kept on the phone, it is reported to the office when it is sent).
  - Once reopened, the day takes every sale of its date, also one the phone says was made while it was closed.
  - A load typed for an earlier date does not reopen that date's day. It changes its figures: the day is sent
    again before approval (D-132), and an approved day keeps its figures as sent.
  - Within the 5 minutes of clock tolerance the server's clock dates the sale (D-133): a sale made in the last
    minutes before the closing and received just after it counts as made after it, and is refused. The closing
    screen does not let the driver send while a sale waits on the phone (D-129), so this needs two phones or a
    request still in flight.
  - The stock a late sale may take is checked per day, not per hour (D-133).
  - A sale made after an earlier date's closing stays refused and the office types it.
  - A day sent before this change may have sales made after its send (then allowed until approval): they are
    outside its window and in no closing.
  - The office list does not flag the days whose figures changed; the dialog does (it reads the day's records).
  - The monthly closing's "driver days closed" check still does not list days left running (D-074).
  - A driver still cannot close a day that is over (the closing endpoints are today's only).

**D-135 · Boxes the company already owns enter the ledger as an opening stock (owner answer; follow-up of D-124, D-127)** · accepted · 2026-10-13
- Owner answer: the company starts with **50 small and 50 big boxes** of its own.
- Before, a box could only enter the ledger on a receipt from a supplier, which also raises what we owe that
  supplier. Company boxes posted that way would have shown as 100 boxes to give back.
- New movement kind `opening` ("Stock initial"): no sender, and the receiver must be a **location** (cold room or
  truck). It raises that location's balance only, so the supplier balances stay what was really lent
  (three-balances rule). Posted through `post_box_movement` like every other kind, audited, append-only.
  Migration `boxes.0003` (the choices of `kind` only).
- `seed_dev` posts the owner's figures into "Chambre froide 1 (frais)" (`apps/demo/boxes.py`), once per box type:
  a type that already has an opening stock is left alone, so a second run and every later deploy add nothing.
  Staging gets them on the deploy that follows the merge. Which cold room holds them was not said: the first one
  is an assumption. A wrong room or figure is corrected by new movements, never by an edit.
- The admin Caisses page shows the kind in its history, from "Hors stock".
- **Still open, not built:** an opening balance for boxes already at a client or already owed to a supplier (the
  sign question of D-127), and a screen or command to type an opening stock on a real database. `opening` refuses
  a client or a supplier until that is decided.

**D-136 · The expenses list opens on this month (Mahmoud's request)** · accepted · 2026-10-14
- Numbers D-134 and D-135 are taken by work not yet on `main` (`driver-day-history`, `box-opening-stock`).
- Before: "Dépenses" listed every expense ever, with two optional date fields. Now a "Mois | Période" switch in the
  filter bar: **Mois** (the default) shows one calendar month, this month on opening, with ‹ › to walk the months;
  › stops at this month, since no expense is dated in the future. **Période** keeps the two date fields; it starts
  on the dates of the month shown, and both fields empty means every date.
- The count and the approved / waiting totals follow the dates, like every other filter: in "Mois" they are the
  month's totals. The search, the status and the category also stay inside the month shown, so an old expense is
  found by its number only after going to its month or emptying the period. The "nothing found" message names the
  month for that reason.
- A link with `date_from` / `date_to` (the month closing's cost lines, D-122) opens on that month when the dates are
  exactly one month, else on that period. Frontend only (`expenses/period.ts`): the API already had both parameters.
- Not done: the month is not kept in the address, so coming back from an expense returns to this month.

**D-137 · Pickers hide archived records; a lot picker shows its place, lot and supplier in colour (Mahmoud's request)** · accepted · 2026-10-14
- A dropdown lists only active places, products, trucks, categories and suppliers. An archived one stays in the list
  only when it is the current value of that field (a saved record or a link still points at it), so the field
  never shows blank. The manage dialogs (expense categories) still list archived ones, to restore them.
- The lot picker (counter sale, D-121) is the only dropdown that lists a product's lots, so it carries the colours:
  place in green (`text-good`), lot number in yellow (`text-lot`), supplier in grey (`text-ink-2`), or in gold
  (`text-gold`) with the word "partenaire" when the supplier is a partner (D-060). The word keeps the mark readable
  without colour.
- New tokens `--lot` and `--gold` in `packages/ui/src/styles.css`, for light and both dark themes (`--warn` is too
  close to a yellow to tell apart from the gold).
- Other product dropdowns list catalogue products, with no place or lot, so they keep the plain name. Frontend only.

**D-138 · "Nouveau document" opens the creation form in a window on the Documents page** · accepted · 2026-10-14
- Asked by Mahmoud: creating a devis, BL, vente comptoir, bon d'achat, réception or facture fournisseur from
  Documents must not leave the list. The six screens are the same pages as before, shown in a wide window
  (`doclist/NewDocumentDialog.tsx`). Inside it, `lib/embedded.ts` (`useLeave`) closes the window instead of
  navigating; closing (saved or cancelled) refreshes the list. The window's own breadcrumb links are hidden.
- Guard: Escape or a click outside asks "Abandonner ce document ?" when something was typed or picked (a select
  option) and not saved yet; "Continuer la saisie" keeps it. Annuler and the saved path close at once. The edit
  detection is event-based (typing, picking), so a field typed and then emptied still asks.
- Not changed yet: the row actions that still open a page (edit, receive from a BA, supplier invoice from a
  reception, pay, credit note).

**D-139 · Nightly encrypted backups of the database and the media files, kept 30 days, restored in a drill (P4-T03)** · accepted · 2026-10-14
- `deploy/backup.sh <project>` runs from the `debian` user's crontab at 02:30 UTC (a cron line, not a container: it
  must reach Docker and outlive the stack it backs up). It writes `~/<project>/backups/<UTC time>/` with
  `db.dump.gpg` (`pg_dump --format=custom` from the db container), `media.tar.gz.gpg` (the `<project>_media` volume,
  tarred by a throwaway `postgres:16-alpine` container with no network) and a plain `manifest.txt` (fingerprint,
  PostgreSQL version, SHA-256). It prints one `BACKUP OK ...` line (sizes, duration, kept, removed, off-site) or
  `BACKUP FAILED ...: <reason>` with exit code 1, to `~/<project>/backup.log`, for monitoring (P4-T04).
- **Encryption: gpg to a public key**, not age or openssl. gpg is already on the server (no package, no image) and in
  Git for Windows (the machine that decrypts), and OpenPGP will be readable for decades. age is not on the server and
  has no official image; openssl has no simple, authenticated public-key format for large files (`cms` reads the whole
  file to decrypt). The data is encrypted while it streams, so nothing readable touches the disk; `--rfc4880` keeps
  classic packets (AES-256 with MDC) that every OpenPGP tool reads, and gpg runs with a throwaway home, never the
  `debian` keyring. The key is RSA 4096 (fingerprint `8C69CE47FE726683B3732261C5D2D8A982D43BCF`), made on Mahmoud's
  machine without a passphrase: the file is the secret. The public key is in git (`deploy/backup-public-key.asc`) and
  installed by every deploy; the private key never goes to the server or git, and the owner must keep it (password
  manager and USB key). The server therefore cannot read its own backups, and neither can a thief of the bucket.
- **Retention: 30 days** on the server, by the folder's date in its name; a run of a few MB a night is nothing next to
  the disk. Off-site, the bucket's own lifecycle rule deletes old copies: the script never deletes off-site, so its
  keys can be write-only.
- **Off-site: rclone** (`rclone/rclone:1.68.2`, official, pinned) to any S3 bucket named by `BACKUP_S3_ENDPOINT`,
  `BACKUP_S3_REGION`, `BACKUP_S3_BUCKET`, `BACKUP_S3_PREFIX`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`
  in `~/<project>/.env` (empty lines added on staging). An empty bucket means local copy only, said in the log line.
  The secrets reach the container by name (`-e NAME`), never on the command line. Short timeouts: an unreachable
  bucket fails the run in seconds to minutes, after the local copy is kept. **Missing: the bucket itself**, to be
  created by the owner (another provider or region than the VPS).
- **Restore: `deploy/restore.sh`**, run where the private key is. It decrypts locally and streams into a new
  `frutti-restore-<time>` container (`postgres:16-alpine`, its own network, no port) and volume, on local Docker or on
  `RESTORE_SSH`, prints the exact row count of every table and, with `RESTORE_BACKEND_IMAGE`, runs
  `rebuild_on_hand --check`. It never touches a running database; `--remove` deletes what it made. The in-place
  emergency restore is a written command sequence in the runbook, not a script, and is not drilled yet.
- Backed up: the database and the media volume. Not backed up: `.env` (a deploy recreates it; the off-site keys go in
  the password manager), Redis (keeps nothing, D-071), code, images and the nginx site (git).
- Drill on 2026-10-14 (runbook "Backups"): 99 tables with the same row counts as live (1 551 rows), 24 of 24 media
  files, stock check "0 difference(s)".

**D-140 · Monitoring: Sentry in the API and both apps, a recorded nightly stock check, an uptime workflow (P4-T04)** · accepted · 2026-10-14
- No new paid account. Everything is off until the owner creates a Sentry project and puts its DSN in the
  server's `.env`; the uptime watch runs on GitHub Actions, which the repository already has.
- **Sentry, API:** unchanged (`SENTRY_DSN`, nothing sent when empty, `send_default_pii=False`), plus the release
  (`SENTRY_RELEASE`, the deploy's `<time>-<commit>`) and the tag `app=api`.
- **Sentry, admin and driver apps:** new package `@frutti/monitoring` (`@sentry/react` 10.75.3, the mature 10.x
  line; 11.x is three weeks old). The DSN is read **at build time** (`VITE_SENTRY_DSN`), because the apps had no
  run-time configuration and the server builds the images on every deploy: `SENTRY_DSN_FRONTEND` in `.env` goes
  to the `web` image as a build argument (`Dockerfile`, `deploy/compose.staging.yml`). Empty: `Sentry.init` is never
  called and nothing leaves the browser. Each report carries the tag `app=admin|truck`, the release and the
  environment. Personal data: the user's id only (`RequireRole`), no IP (`sendDefaultPii: false`), no query strings
  (a search can hold a customer's name) and no console breadcrumbs. React's root error callbacks report the errors a
  route's error screen catches. One browser project for both apps is enough (the tag tells them apart); the API can
  use the same DSN or its own.
- **Nightly stock check:** `rebuild_on_hand --check` records its run in `core.JobRun` (one row per job: when, ok or
  failed, number of differences; a crash is recorded as failed). `JobRun` has no `organization`: the check runs
  once over every company, it is not business data. `GET /api/v1/health/stock-check` answers `{status, checked_at}`
  with `status` ok (200) or failed, late (no run for 26 hours) or never (503). It is public like `/health`
  (`AllowAny`, no authentication), so the watcher needs no login or secret, and it shows only a time and a state: not
  the number of differences, nor any product, place or company. It is not folded into `/health`: Docker and the
  deploy use `/health` to know whether the API is up, and a failed stock check must not restart or block the API.
  The `nightly` container also runs the check once when it starts, so a fresh deploy does not read as "never".
  The repair (`rebuild_on_hand` without `--check`) does not clear the state; the next check does.
- **Uptime and alert:** `.github/workflows/uptime.yml`, every 15 minutes (and by hand): the admin app, the driver
  app, `/api/v1/health` and the stock check status, each retried twice before it counts. Any failure fails the run,
  and GitHub e-mails the account that owns the scheduled runs (the one that put the workflow on `main`, or last
  changed its cron line). No secret, no deploy key, no checkout, no third-party action (so nothing to pin);
  `permissions: {}`; `ubuntu-24.04` like CI. Addresses can be overridden by repository variables
  (`UPTIME_ADMIN_URL`, `UPTIME_DRIVER_URL`) for production.
- Limits: GitHub runs schedules late at busy times and turns them off after 60 days without repository activity; a
  failure e-mails on every run until it is fixed or the workflow is disabled. The check sees staging from outside
  only (no disk, memory or backup check; backups are P4-T03).

**D-141 · Security review before production: what was found after D-108, what is closed, what is left (P4-T05)** · accepted, two points for the owner · 2026-10-14
- **Reviewed:** every API view added since D-108 (day closings and reopenings D-129 to D-134, late sales D-133, the
  driver's history of days, payments and box pickups, Documents and the PDFs D-102/D-131, Paramètres and users D-123,
  logo/avatar/receipt/loss/certificate uploads, the Excel import P4-T01, reports and their Excel files, the price board
  and product codes), the object checks between two drivers of the same company, ids sent in a request body, login,
  password change and reset, sessions of a deactivated user, production settings, nginx, the two front ends and the
  dependencies (`pip-audit` on `uv.lock`: nothing; `pnpm audit`: 21 advisories, all in undici under orval).
  The D-108 sweep (a role on every route, 401/403 per role, another company's ids) still passes on all new routes.
- **Closed, each with a test in `apps/core/tests/test_api_security.py` that fails without the fix:**
  1. *Medium.* A driver could "choose" for the day the truck another driver had already started the day on (their
     usual truck, with no assignment that date): the first driver lost the truck mid-day and the second sold its stock.
     `POST /truck-assignments` by a driver is now refused (400 on `truck`) when another driver has a day on that truck
     that date. The office may still move it (unchanged).
  2. *Medium.* Excel exports wrote any text starting with `=` as a live formula. A driver can set their own display
     name (`/me/profile`), which the sales report by driver exports; managers name customers, suppliers and products.
     `reports.exports.workbook_bytes` now stores every text cell as text (same value shown).
  3. *Low.* `POST /me/password` checked the old password without any limit: a session left open on a shared computer
     could guess it. 8 tries a minute per account (`password_change` throttle), as the login.
  4. *Low.* The Excel import (owner only) unpacked any zip: a 5 MB file can unpack to gigabytes in memory. Refused
     above 100 MB unpacked, before openpyxl opens it.
  5. *Low, no test (a race).* Two owners deactivating or demoting each other at the same moment could both pass the
     "last owner" guard: every active owner row is now locked first.
  6. *Low, dev machines only.* undici < 7.29.1 (TLS, header injection, DoS advisories) came with orval:
     `pnpm-workspace.yaml` overrides it to 7.29.1 (released 2026-09-04, D-012). `pnpm audit` is clean.
- Pinned by new tests (already right): a deactivated member's open sessions answer 401 at the next request; a
  password reset by the owner ends the member's sessions; another company's customer, product, place, truck, driver
  or sale sent in a body is refused on that field and nothing changes.
- **For the owner (not changed, it would change what a driver can do):** a driver's late sale (D-133) has no limit
  on how far back the phone may date it, and a sale dated on a day the driver never started belongs to no closing, so
  its cash is expected in no closing. The "stock held since" check limits it to kilos the truck kept since that day.
  Proposal: refuse a phone time older than a few days, or show the office the sales outside any closing.
- **Listed, not changed (low):** a driver's road expense accepts any expense category of the company (it still waits
  for approval); `/django-admin/` answers on both public app hosts (throttled, business data read-only): restrict it by
  address in the production nginx; the driver app's offline queue is not tied to the driver who filled it, so on a
  shared phone the next driver's session sends it (sales are refused by the truck check, payments and pickups are
  not); the truck's usual driver (office field) accepts any member, not only active drivers; usernames typed by the
  owner are not checked for odd characters; the per-account login limit lets anyone lock a known username out for a
  minute (D-023 trade-off). Deploy and monitoring (other tasks): production must set `DJANGO_NUM_PROXIES=2` if it
  keeps the host nginx plus the web container (with 1, every visitor shares one login limit); once HTTPS is on,
  `SECURE_SSL_REDIRECT` redirects the container health check on plain HTTP (exempt `api/v1/health` or send
  `X-Forwarded-Proto` in the check).
- **Accepted as D-108 said:** PDFs and receipts served inline as `application/pdf` with nosniff; no general rate limit
  on the API; drivers read prices and minimum prices (D-049), managers read margins (D-113).

**D-142 · Cold-room and general costs charged by the hour, not by the day (owner's request, 2026-10-14)** · accepted · 2026-10-14
- **Why:** a lot that came in at 00:28 and went out at 21:38 on the same day was charged nothing: the day was
  allocated by the stock at the end of the day (D-058, D-059), which is empty for such a lot. Rent, insurance and
  electricity must follow the time a lot actually spends in the room.
- **Rule (replaces "per day by kg held" of D-041, D-058 and Q21 for the split; the monthly amount / 26 and the
  electricity bill stay as they were):** a day's amount is 24 equal hours (to the millime). Each hour is shared over
  the time the lots spent in the room in that hour, each stretch of time by the kilos it held. Time the room was
  empty is charged to nobody. So a lot that stays 00:28 to 21:38 pays 21 h 10 min of the room's cost. Today counts
  only up to now.
- **Ledger:** `inventory.selectors.held_slices_by_hour` replays the ledger by the movement times (not by the day):
  `{place: {day: {hour: [(seconds, {lot: kg})]}}}`. `kg_by_batch_by_day` (end of day) is kept for the stock check.
- **Pure functions:** `expenses.costing.allocate_room_days` and `allocate_general_days` take that hourly structure;
  `split_by_weight` keeps every hour exact to the millime. `kg_days` is kg x hours / 24 as before.
- **Consequence to know:** lots already closed or costs already approved (`LotCostAdjustment` rows booked under the
  daily rule) are not rewritten. Lines computed after this change use hours, so for a lot whose month was already
  corrected under the daily rule, the estimate line and the correction no longer add up to the bill's real share
  (the gap is the difference between the two rules for that lot). Open point for the owner: recalculate the
  approved bills, or apply the hourly rule only from a date.
- **Shown on the lot:** the cost lines show the same kg-days quantity as before.

**D-143 · Paramètres > Utilisateurs: the owner can change a user's login and name, and delete an account that has no history (owner's request, 2026-10-15)** · accepted · 2026-10-15
- **Why:** the owner could not correct a typo in a name or login, and could not remove a test or mistaken account; only deactivation existed.
- **Change a user:** the owner edits the login identifier, first name and last name (`PATCH members/<id>`). The login stays unique (refused with a field error when taken). Audited as `membership.profile_changed`.
- **Delete a user:** `DELETE members/<id>`, owner only. Refused when the account:
  - is the owner's own account (`Vous ne pouvez pas supprimer votre propre compte`);
  - would leave the organization without an active owner (D-141 guard);
  - also has access to another company (deactivate it instead);
  - has any history: invoices, closings, driver days, fleet assignments or audit entries that name the user as actor. These are `PROTECT` foreign keys, so the delete is rolled back and the owner is told to deactivate instead.
- **What is kept:** D-123 still stands for accounts with history, which are deactivated, never deleted. The audit trail keeps an entry `membership.deleted` with the login and role.
- **Not done:** the audit entries that name the deleted account as the *target* (not the actor) keep the old id; no soft-delete column exists.

**D-144 · Sales screens: the product first, the place found from the lines, no location field or column (P2-T12)** · accepted · 2026-10-14
- Asked by the owner (2026-10-14): the seller should not pick "Depuis" (cold room or truck) and guess which place holds
  the product. The sale form, the counter sale, the quote-to-sale dialog and the quote form no longer show a location
  field; the sales list, the sale page, the lot's sales and the quote page no longer show a "Lieu" column or line.
- The sale's place is **found from the rows**, in the browser (`apps/admin/src/lib/placeStock.ts`): the place that holds
  every row's kilos, the fullest first. Stock of all the places is read together (`usePlacesStock`); the grid's stock
  cell shows the kilos left in all the places after the row, red when the row takes more than there is; under each
  product the grid says where it leaves from (`admin.lines.origin`).
- When no single place holds the whole sale, the form refuses it and names the products: a sale still takes its kilos
  from one place only (the model keeps `Sale.location`). The server validates the stock again as before.
- Still open for the owner: whether one sale may take kilos from a cold room and a truck at once. If yes, `SaleLine` gets
  its own location and the sale-level field goes (a model change, a new decision). The PDFs of the BL and invoice may
  still print the place: left as they are for now.

**D-145 · Archived records leave every dropdown, except the one a saved record already uses (owner's request, 2026-10-15)** · accepted · 2026-10-15
- Every picker lists only active places, products, trucks, customers, suppliers, categories, labourers and lots. An archived
  entry stays in a picker only when the form's current value is that entry (`apps/admin/src/lib/pickable.ts`), so an old
  quote, sale, receipt, order, loss, transfer, expense or cost never shows a blank field. D-137 covered the list filters
  and the expense and counter-sale pickers; this extends it to the forms.
- Forms that fetched only active records now fetch all of them and filter in the browser: quote, sale, receipt, purchase
  order, loss, transfer, expense, general cost, day labour and an employee's work day. Places that hold stock still count
  active places only.
- A lot of an archived product leaves the lot pickers (expense, day labour, employee work day): the lot's product now says
  `is_active` (`BatchProductSerializer`), and the generated client is regenerated.
- Not changed, on purpose: the box "Holder" filter on Caisses still lists archived holders that have a box balance, because
  boxes still out at a holder must stay findable until they come back; the driver phone's stock lines still show an archived
  product the truck holds (a list of stock to count, not a picker; the server refuses the sale).

**D-146 · Client start: empty the demo data, keep the real master data (`prepare_client_start`)** · accepted · 2026-10-15
- Asked by Mahmoud (2026-10-15) before the delivery: the staging database goes to the client as it is, with no demo rows. Kept: the organization and its settings, the logins (passwords replaced), the cold rooms and trucks
  (`StockLocation`, `Truck`, trucks without a driver), the expense categories, the products whose code starts with
  `ART` (the owner's article list, D-126), and the five employees named at the run. Emptied: everything else of the
  organization (stock, boxes, purchases, sales, invoices, customers, suppliers, costs, payroll, closings, documents,
  prices, counters, audit log). Stock and debts start at zero.
- Kept products have their price, their minimum price and their minimum stock cleared, as the 36 products of the owner's
  list already are: the owner sets the prices on the price board.
- **Why SQL and not the ORM.** The ledgers refuse deletion in Python on purpose (stock, boxes, prices, audit, closings,
  capital entries). The command deletes one organization's rows with SQL inside one transaction; Django's foreign keys
  are deferred, and `SET CONSTRAINTS ALL IMMEDIATE` checks them before the end, so a dangling reference rolls the whole
  reset back. Without `--apply` the same steps run and are rolled back. This is a one-time reset before go-live, not a
  feature of the running app.
- `Organization.real_data_since` marks the reset. `seed_dev` adds nothing once it is set, so the deploy's demo seed
  (`remote-deploy.sh`) cannot refill the client's database. The logins' passwords are replaced by random ones that the
  command prints once; the owner changes them in Paramètres > Mon profil.
- Import rule (found by CI after #137 landed, 2026-10-15): `prepare_client_start` reads other apps' models, which the
  app-boundary contract forbids. It is the one exempt command (`RESET_COMMANDS` in `backend/tooling/import_contracts.py`,
  PR #139), because the reset is raw SQL on purpose. Owner to note: moving it onto the services later would remove the exception.
- Not done by the command: media files of the deleted records (receipts, PDFs) stay on the volume, unreferenced. The
  opening stock of the company's boxes is not re-entered (zero, as asked); the screen for a box opening stock on a real
  database is still to build (STATUS).

**D-147 · The company logo is the driver app's tab icon, also on the login screen (D-125 follow-up)** · accepted · 2026-10-15
- Asked by the owner (2026-10-15): the driver's browser tab must show the company icon. Before, the logo was set only
  after login, so the login screen and a phone that had logged out showed the Frutti icon of `index.html`.
- The truck app remembers the logo URL it last saw in `localStorage` (`frutti-truck-logo`) and uses it while no session
  is known. It is a per-phone convenience, not data: the logo is on every document. Blocked storage keeps the default icon.
- `useFavicon` no longer forces `type="image/webp"` on the icon: the logo may be a PNG or JPEG, and a wrong type can make
  the browser skip it. The admin app gets the same fix.
- Not changed: the home-screen icon of the installed app (`public/icon-*.png` and the manifest) stays the Frutti icon; a
  company icon there would need a build per company or a server-made manifest.

**D-148 · Driver app: prices refreshed every minute, a notice when a price changes (P3-T02)** · accepted · 2026-10-15
- Asked by the owner (2026-10-15): a driver must not sell at an old price without knowing it, and must see a notification
  when a price changes during the day.
- The truck's stock and today's prices (`listMyStock`) are asked again every minute while the phone is online, on
  reconnect and when the app comes back to the front (`apps/truck/src/myStock.ts`). Every screen shares that one query.
- A change of a product's price, against the price the phone last saw, raises a notice on every screen (`PriceNotice`,
  `priceWatch.ts`) until the driver acknowledges it. A product the phone never saw is not a change: its first price is
  only remembered. The last prices seen are kept on the phone (`frutti-truck-prices`, cleared at logout), so a change
  made while the app was closed is still announced. No system notification yet: that needs push.
- The stock and sale screens show "Prix reçus le ..." when offline, from the time the prices were last received.
- **Not done, open for the owner:** the server still prices a phone sale at the price in force at the sale's moment
  (`catalog.price_in_force` at `sold_at`, D-133), not at the price the phone showed. So a sale made on a stale price (a
  change not yet refreshed, or offline) is charged the new price. The phone could send the price it showed (the sale
  line's `unit_price`, the API already accepts it), but `my-stock` shows the daily price only, not the customer's own
  price list (D-049) that the server would apply, so sending it now would charge those customers the daily price instead of their list price.
  Next step: show the customer price list on the phone, then send the shown price. Owner to confirm the rule first.

**D-149 · Driver day: "Aujourd'hui" at a glance at the top (P3-T02 follow-up)** · accepted · 2026-10-15
- Asked by the owner (2026-10-15): the driver sees the day's main figures at once: sales (count and total), cash to hold,
  expenses, and kilos left on the truck.
- Shown only while the day runs. Sales, cash and expenses come from the server's day summary (`getMyDaySummary`); the
  kilos left are the truck's stock less what waits on the phone. Sales still waiting to be sent are not in the figures:
  the card says how many there are (`TodayAtAGlance.tsx`).

**D-150 · A driver's sale carries the price the phone showed, checked by the server (closes D-148's open point)** · accepted · 2026-10-15
- The phone sends `unit_price` on each line of a sale: the price it showed. The server (`services._shown_price`) accepts
  it only when it was a daily price of that product at some moment in the 24 hours before the sale's moment
  (`PHONE_PRICE_WINDOW`, `shown_price_in_force`). Otherwise the line is refused: "Ce prix n'est plus valable".
  The sale line's `price_source` is `shown` (new choice, migration `sales.0016`).
- The customer's own price list wins over the shown price (D-049): such a line is priced at the list, `price_list`.
- Why 24 hours: a sale kept on the phone keeps the price in force when it was made, so a change the phone had not
  refreshed is allowed for a day. A driver offline for more than a day has the sale refused and sees why; the office
  sees it on `/journees`.
- A driver's price that was never a real price is refused: before, a driver's API call could charge any price.
- Open (D-148 follow-up): the phone still shows the daily price to a list customer.

**D-151 · Expenses, losses, customer payments and box pickups keep the moment the driver's phone says (P3-T07c, D-133)** · accepted · 2026-10-15
- Asked by the owner (2026-10-15): a record entered on the phone without signal must count in the day it was made, not the
  day it was sent. Sales already did this (D-133); the same rule now covers the four other records.
- The phone sends `made_at` (the time it was entered, `createdAt` of the queued item). The server checks it with the
  same rule as a sale (`apps/core/clock.py`: not in the future, a few minutes of clock margin ignored) and refuses the
  record on a day already sent before that moment or approved (`refuse_sale_outside_day`, D-134, D-094). A record
  entered on a day the office approved is now refused, as D-094 intends.
- Expenses: `spent_on` is the day of `made_at`; the closing counts them by `made_at`. Payments: `received_on` is the day
  of `made_at`; the closing counts them by `made_at`. Boxes: the day of a movement is `made_at`, else its creation.
- Losses: the kilos leave the stock at `made_at` (the movement's `occurred_at`), and the server checks the truck held
  them then (`held_since_then`), as for a late sale.
- Records without `made_at` (the office's, and phones that send none) keep the old rule: the day they are recorded.

**D-152 · A driver adds a customer on the phone; the stock list shows product photos (P3-T03, P3-T02)** · accepted · 2026-10-15
- Asked by the owner's list (2026-10-15): a driver can add a customer they sell to, and sees each product's photo on the
  stock and sale lists.
- `POST /my-customers` (`createMyCustomer`): a name, and optionally a phone and a city. The customer is a restaurant
  (the default kind), with a credit limit of zero (cash only) and no credit terms until the office sets them. A name an
  active customer already has is refused (case not counted): the driver picks that customer instead.
- Adding a customer needs the network: the button is off offline, with a short line saying so. It is not queued, so a
  customer never has to be merged later (a queued one would need a sync rule of its own).
- `my-stock` gives each line the product's photo address (`photo_url`, empty when there is none). The driver app shows
  the photo, or a plain mark with the first letter when there is none or it does not load.
- Not done: the office's list of customers shows what the driver added the same way as any other customer (no mark).

**D-153 · The sale screen shows the price the selected customer pays (closes D-150's open point)** · accepted · 2026-10-15
- `my-stock` takes an optional `customer`: each line's price is then the one that customer pays (their own price list
  first, else the daily price), the same rule the server uses for a sale (`catalog.price_in_force`, D-049).
- The sale screen reads the stock for the customer chosen; the total on the phone is the total the server will charge.
  The server already charged a list customer their list price (D-150); this only makes the phone show it too.
- Offline, a customer never asked for before has no price of its own yet: the daily prices stay on screen until the
  phone is online (the server still applies the list price).

**D-154 · The driver sees the company logo: every member reads it, and the phone keeps a copy (corrects D-147)** · accepted · 2026-10-15
- Found on staging: the driver's header and tab icon showed no logo, and the login screen showed the default mark. The
  logo endpoint allowed owner, manager and accountant only, so a driver's request for the logo got 403. D-147 relied on
  that URL, so it never worked for a driver.
- The logo is read by every member of the organization (`ReadMemberWriteOwnerOrManager`); only owners and managers
  change it. Same reason as D-125: the logo is on every document already, so it is not private.
- The login screen runs before any session, and the logo needs one. So the driver app keeps a copy of the logo as a
  `data:` address in `localStorage` (`frutti-truck-logo`), taken with the driver's session after each login. The login
  screen and the tab icon use that copy. A company without a logo clears it. Blocked storage keeps the default icon.
- Not solved: a phone that has never logged in on a logo-bearing company still shows the default mark on the login
  screen. Showing the logo there too would need a public endpoint (which company's logo, when several share a server?).

**D-155 · The company domain fruttidelmare.com: one name per app, HTTPS in two steps** · accepted · 2026-10-15
- The owner's domain is fruttidelmare.com. The admin app is `app.fruttidelmare.com`, the driver app
  `ch.fruttidelmare.com` (chosen by the owner; D-036 planned one name per app on the real domain). The sslip.io names
  redirect to them.
- Staging stays on the shared OVH VPS (217.182.205.137). The host nginx serves the two names; the certificate is one
  Let's Encrypt certificate for both names, issued with the webroot method (`/var/www/frutti-acme`), so the nginx site
  does not change for certbot. Its renewal reloads nginx (`--deploy-hook`).
- Two steps, because nginx refuses a site that points at certificate files which do not exist yet: phase 1 serves the
  names on plain HTTP (port 80) and the challenge; phase 2, once the certificate exists, adds port 443 and turns on the
  HTTPS settings (`DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_SECURE_COOKIES`, `DJANGO_SECURE_HSTS_SECONDS`) and https origins.
  Supersedes D-027's "no domain" and the sslip.io names of D-036.
- The backend health check sends `X-Forwarded-Proto: https` so Django does not redirect it once HTTPS is on.
- The bare domain `fruttidelmare.com` gets no page and no redirect: the apps live only on their two names (owner, 2026-10-15).
- Not done here: the production server (P4-T02).

**D-156 · The statement PDF of a customer or a supplier, for a period or up to a day (owner request)** · accepted · 2026-10-15
- The customer and supplier pages have a "Relevé (PDF)" button. It asks for one day ("jusqu'au", from the beginning)
  or two days ("du … au …"), then opens a PDF. The PDF has a summary first: balance before, sales or invoices of the
  period, payments, balance at the end, kilos, boxes. Then come the products (kilos, average price, amount), every BL
  or BR with its lines (product, kg, price), the payments, the account with a running balance, and the boxes (at the
  start, added, removed, at the end, with each movement).
- `GET /reports/customer-statement/<id>/pdf` and `/reports/supplier-statement/<id>/pdf` with `date_from` (optional)
  and `date_to` (default today). Office roles (owner, manager, accountant); a driver gets 403. The data comes from
  `sales.selectors.customer_statement`, `purchasing.selectors.supplier_statement` and `boxes.selectors.party_boxes`.
- **Made on the spot, not by the background job of D-071:** the file depends on the dates the person picks, so it is
  not stored (`documents.services.render_pdf`). The API image already has WeasyPrint (the worker uses the same image).
- The customer account is the one of D-062 (`receivables.customer_history`). A sale counts at what it owes **now**
  (its invoice's VAT and stamp, credit notes and withholding taken off), on the sale's day. A statement up to a past
  day therefore already shows a credit note issued after that day. The lines show the BL's prices as charged.
- The supplier account is the trade payable of D-043: posted invoices minus payments. Receipts are listed with
  their kilos and prices but do not move the balance until they are on a posted invoice. The summary shows what is
  received and not yet invoiced. A partner's capital and profit share stay out (three separate balances).
- Boxes: for a client, the boxes they hold; for a supplier, the boxes we owe it. A movement counts on the day it was
  made (the phone's time), else the day it was recorded, as on the truck's day (D-151).
- Not done: the layout has not been checked by eye in a real PDF (no Pango on the dev machine). Open both PDFs on
  staging. Also not done: Arabic, sending by e-mail or WhatsApp.

**D-157 · The browser tests (e2e) run on pull requests only, not on every push** · accepted · 2026-10-15
- The e2e job takes about 6.5 minutes and ran twice for every PR (once for the push, once for the pull request).
  It now runs only for the `pull_request` event: when a PR is opened and again for each new commit on it, so it
  gates the merge.
- Sessions do not run the e2e tests on the machine (owner, 2026-10-15): they take minutes and CI runs them before
  the merge. A session reads the CI result and fixes a failure there. `make e2e` stays for when the owner asks.
- Backend, frontend and API-client checks still run on every push and every PR, except when a push or PR
  changes only docs (`docs/**` and Markdown files): then CI does not run at all and the PR can be merged at once.
  A PR that mixes docs and code runs everything.
- Deploy to staging no longer waits for e2e: it already passed on the PR before the merge. A direct push to
  `main` (no PR) therefore deploys without e2e, so changes go through a PR.
**D-176 · Buying at the port: a purchase is checked by the office before it counts (P3-T12a, Q28)** · accepted · 2026-10-15
- **Owner request (Q28):** a driver buys from a fisherman or at the port, sends it from the phone, and the owner or the
  manager checks it. Only then do the stock, the supplier debt and the payment count. Split in three PRs: T12a office
  side (this one), T12b the phone screen, the "can buy" switch and the purchase float, T12c paying suppliers.
- **A document of its own, not a draft receipt:** `FieldPurchase` (`AT-2026-0001`, yearly) with lines, the sums given
  at the port and revisions, in `purchasing`. A receipt stays what it was (saved = in stock, never edited): a receipt
  line needs its batch, and every receipt selector would otherwise have to skip drafts.
- **Statuses:** `submitted` → `validated` or `refused`, both final. A supplier or a product may be a typed name
  (`proposed_supplier`, `proposed_product`) until the office picks or creates the real one; validation needs real
  ones and a place (`location`, chosen by the office).
- **Revisions:** each save that changes something adds a `FieldPurchaseRevision` (full copy, who, when, the office's
  note given then). The first one is the purchase as sent. A save must name the revision it was based on; an older
  one is refused on `revision` ("modifié entre-temps"). The API lists each revision's changes against the one before
  (`field`, `line`, `before`, `after`); lines and payments are compared by position.
- **What is owed is the kg received (Q28).** The office types the kg received per line; empty means the driver's kg.
  At validation, in one transaction: a BR with the kg received as invoiced and accepted weight and the driver's kg as
  its "ordered" weight (so the difference shows on the BR and in the differences report); a posted FF for that BR,
  due by the deal; an RF per sum given at the port, allocated to that FF, the part beyond it an advance. So the
  supplier balance, the statement (D-156) and the overdue list need no change.
- **The deal is set per purchase:** comptant (due that day), N days, or end of month + N days.
- **Cheques and traites:** `SupplierPayment.cash_on` keeps the day a post-dated cheque or a traite may be cashed (T12c
  will list them by day).
- **Permissions:** owner and manager change, validate and refuse; the accountant reads; drivers 403 here (their own
  endpoints come in T12b). A partner per line is the owner's choice (D-100); a manager may keep one already chosen.
  The office may also type a purchase phoned in (`POST /field-purchases`); its buyer is then the person typing it.
- **Alert:** the dashboard counts purchases to check and those sent more than 24 hours ago (provisional window).
- Screens: Achats › "Achats terrain" (list, to check first), the check page (create the typed supplier or product,
  kg received, prices, place, deal, boxes, note to the driver; save, validate with a summary, refuse with a reason) and
  the history. Demo: `KRK-0917` from Pêcherie Kerkennah with a product named "Pageot", waiting.

**D-158 · Buying at the port from the phone, and the purchase money counted apart (P3-T12b, Q28)** · accepted · 2026-10-16
- **The switch:** `Membership.can_buy`, set by the owner on Paramètres › Utilisateurs (`PATCH /members/<id>/can-buy`),
  sent in the session. Only such a driver sends or changes a purchase, lists suppliers (`/my-suppliers`) or reads the
  last cost paid (`/my-purchase-costs`); any driver reads their own purchases. The server refuses the others (403).
- **From the phone:** `POST /my-field-purchases` with `client_uuid` (a retry answers with the same purchase) and
  `made_at` (checked as a sale's time; its day is the purchase's day). Kept on the phone without network and sent
  later, like an expense. Refused after the day's closing was sent or on an approved day, as an expense. The driver
  sees the last 30 days, the status, the office's note and the kg received; never a supplier's balance nor partners.
- **Changes by the driver** (`PUT /my-field-purchases/<id>`, network needed, with the revision): a new revision; the
  day does not change; what the office set stays (place, boxes, note, and the kg received and partner of a line still
  buying the same product at the same position).
- **Notice (owner, 2026-10-16):** each validated or refused purchase is announced on every screen of the phone until
  the driver taps "J'ai vu" (decisions of the last 3 days; what was read is kept on the phone). Asked every minute.
- **The purchase money is a second cash box (owner, 2026-10-16):** `DriverDay.purchase_float`, typed by the driver at
  the start of the day and again while it runs when the office gives more (`PUT /my-day/purchase-float`). Cash given at
  the port comes out of it first; beyond it, out of the sales cash (owner: allowed). The day's summary gives the
  purchases (count, total, cash, cheques/traites), `purchases_from_sales` and `expected_purchase_cash`; the sales cash
  expected is lowered by `purchases_from_sales`. A refused purchase counts for nothing. At closing the driver counts the
  purchase money left apart (`counted_purchase_cash`, asked only on a day with purchase money or purchases);
  `purchase_difference` is kept, shown to the office, and counts in the cash-difference alert. A send a new load
  undoes keeps its counted purchase money, handed to the office like the sales cash (D-134).
- Not done: the photo of the supplier's paper (moved to T12c); the office cannot type the purchase money for a driver.

**D-159 · Paying suppliers: debts and cheques, a delivery owed at once, the photo of the supplier's paper (P3-T12c)** · accepted · 2026-10-16
- **"Dettes fournisseurs"** (Achats › Dettes, `GET /supplier-debts`, office roles, managers too; the owner's supplier-balances report stays):
  per supplier what is still to pay on posted invoices, of which overdue and due within 7 days, the next due date and
  the advances it holds; biggest first, with a "Payer" button. Below, the cheques and traites given with a cashing
  day (`SupplierPayment.cash_on`, D-176), from a week back on, soonest first; the total counts those still to cash.
- **A delivery owed at once:** the office receipt form has "Dû dès la réception" (checked by default) with the deal
  of D-176 (comptant, N days, end of month + N days; 30 days proposed). Saving makes the BR and a posted FF for it,
  due by the deal, in one transaction (`services.receive_and_invoice`). Unchecked, the receipt waits for the
  supplier's invoice as in D-043. The payment form asks the cashing day of a cheque or a traite.
- **Monthly settlement:** the statement dialog (D-156) gets "Le mois dernier" and "Ce mois-ci": the paper to agree on
  with a supplier paid monthly.
- **Photo of the supplier's paper** on a purchase at the port: optional, from the phone (`PUT
  /my-field-purchases/<id>/paper`, multipart; re-encoded as WebP without metadata, `core.images`). Sent after the
  purchase, also from the phone's queue (same `client_uuid`, so a retry puts it on the same purchase). Replaced while
  the office has not decided; joined only if none once decided. The office sees it on the check page
  (`/field-purchases/<id>/paper`, read by an `<img>`, kept out of the API contract).

**D-160 · A truck load is split by client: one draft BL per client, with its own delivery address (P2-T13)** · accepted · 2026-10-16
Asked by the owner: for a transfer from the cold room to a truck, the client is known from the start, so a BL is printed
for each client with what they will buy, the small/big boxes are tracked, and the delivery address starts from the
client's record but may be changed on this BL only.
- **Load = parts.** `TransferLine.customer` and `TransferBoxLine.customer` (null = kept on the truck, for road sales as
  before) and `TransferDelivery` (transfer, customer, `delivery_address`, one per client). Uniqueness is per client and
  product (two partial constraints). Only a load can have clients; a client appears once; each part needs a product.
  The stock moves for the whole load as before (FIFO per line); the boxes move to the truck added up per type. Errors of
  a client's line come back on `deliveries.<i>.lines.<j>.<field>`.
- **BL = the draft sale of the client.** Validating the load sends `inventory.load_validated`; `sales` answers by
  `create_delivery_drafts`: one draft `Sale` per client at the truck, with the load's prices (source "typed"), the client's
  boxes (`SaleBoxLine`) and `Sale.transfer` pointing at the load. Nothing is sold yet. Confirming the draft at the delivery
  (existing `confirm_sale`) takes the kilos off the truck FIFO, records what the client owes and moves the boxes truck →
  client. Chosen with the owner: draft at the load, real BL (`BL-2026-NNNN`) at the delivery.
- **Address.** `Sale.delivery_address` (copy, 255 chars). Empty at the load takes the client's address and city; a typed
  one stays on that BL only, and the client's record is never changed. The BL PDF prints "Livré à" (this address, or the
  client's when empty) and the boxes left. `update_sale` without `delivery_address` or `boxes` keeps them (the sale form
  does not edit boxes); the sale form has a field for the address.
- **Print before delivery.** `delivery_note_printable` allows a draft that comes from a load (`Sale.transfer`) and stamps it
  "PROVISOIRE" under its draft number `VE-NNNN`; any other draft still has no BL (D-095).
- **Provisional:** the price of a client's line is the load's price of the day, not the client's price list (D-153 shows
  that price on the phone's sale screen only); the office edits the draft BL to change it. A cancelled draft BL is not
  recreated; fix by a new load.
- **Driver phone.** `GET /my-deliveries` (driver only): the draft BL made from a load, for the truck of the day. A driver also
  sees (list, detail, confirm) the sales of a load on their truck, not only the ones they made. "Mes livraisons" confirms with
  `confirmSale`, online only: offline confirmation, a quantity changed on the spot and payment from the card are later.
- The new delivery screen has provisional Arabic translations; native-speaker review remains part of P3-T09.

**D-161 · After a load is validated, the page offers each client's BL and fiche (P2-T13)** · accepted · 2026-10-17
- The validated load page shows a banner and, on each client card, "Imprimer le bon" (the draft BL, D-160) and "Fiche client"
  (the customer statement PDF of D-156 up to today, which includes the BL's sale once the draft exists). No new endpoint.
- **"Tout imprimer"** (`GET /reports/load-print-pack/<transfer>/pdf`): one PDF, for each client their BL (provisional or
  confirmed) then their statement up to today, each document starting on its own page (WeasyPrint pages joined in
  `documents.rendering.htmls_to_pdf`). Made on the spot, not stored.

**D-162 · "Journées des chauffeurs" opens on a live follow-up of each driver's day** · accepted · 2026-10-17
- The page has two tabs: "Suivi des chauffeurs" (default) and "Clôtures à vérifier" (the former page, unchanged). The follow-up
  lists every driver day, running or sent, as a card (money expected in hand, sales, expenses, deliveries done/to do), filtered
  by driver, truck and dates (default today). A card opens the day: money line by line, the load's BL (draft = to deliver,
  confirmed = delivered), road sales, customer payments, expenses and the truck's stock.
- Endpoints (office roles, read-only): `GET /day-overview`, `/day-overview/<day id>`, `/day-overview/drivers`. Figures are
  `day_answer` (as sent once sent, live while it runs). Deliveries are the sales with `transfer` on the truck whose load date
  is the day. `phase` = `running` or the closing status.

**D-163 · Client remarks of 2026-10-17: shares in %, a hard price floor, boxes bought or lost, trucks out of service** · accepted · 2026-10-17
- **Electricity shares.** The owner types each cold room's share in %, all rooms at once; the total must be exactly 100
  (`PUT /cold-room-shares`, `set_cold_room_shares`). A share is stored as the room's weight, so the split stays
  proportional and a new room is added by lowering the others. The single-room weight endpoint stays for now.
- **Price floor.** A quote or sale line is refused when its price after the discount is under the product's minimum
  price (error on the discount field, or on the price when there is no discount). The daily price board still only
  warns. Older lines already flagged `below_minimum` keep their flag.
- **Boxes.** New movement kind `purchase` (boxes bought enter a cold room or a truck; the price is an expense on its own)
  and `POST /boxes/adjustments` (purchase or write-off with reason, owner or manager).
- **Trucks.** `Truck.condition` (`ok`, `maintenance`, `breakdown`): not proposed to drivers, refused by `assign_truck` and
  `open_driver_day`, its coming assignments removed. `TruckAssignment.driver` may be empty: the truck is left free that day,
  also for its usual driver, and a driver may then take it. Trucks out of service are red in the list and the day panel.
- **Partnership terms** (owner capital, partner capital, shares) change until the lot is closed, also after sales; a
  changed partner capital posts a correction. Cancelling is still refused once the lot has sold.
- **UI.** Every table has cell borders and a shaded header (spreadsheet look); `Table frozen` keeps the header in view
  while the table scrolls (price board). The sale, quote and counter-sale grids show, under the product, the places holding
  it and its open partnership (coloured). A transfer goes from a cold room or a truck into a truck, never into itself.
  The lot page no longer shows the stock tabs. The month closing opens on the current month.

**D-170 · Each check of the month closing opens a dialog saying what to do** · accepted · 2026-10-17
- On "Clôture du mois", a check label is a button: the dialog gives the instruction, the number left (and amount), and a link
  to the page where it is fixed (charges, salaires, pertes, ventes, mouvements, journées). Links go to the full list, not
  filtered by month. Texts: `admin.monthClosing.checks.todo.*`.

**D-168 · The truck cards show who really has the truck today, not who usually drives it** · accepted · 2026-10-17
- `GET /trucks` adds `driver_today` (`selectors.drivers_of_day`): the driver who started today's day on the truck, else
  today's assignment. The usual driver is not counted (owner, 2026-10-17: real activity only); `driver` stays the usual
  driver for the truck form. A truck in maintenance or breakdown shows that state, not "Sans chauffeur aujourd'hui".
**D-164 · The driver's phone sends GPS points while the day runs (P3-T13a)** · accepted · 2026-10-17
- Owner asked for live position, route and stop times on a map. The driver app stays a web app (PWA); the native wrapper with
  background tracking (Capacitor, "A2") is skipped for now, so the route has gaps when the screen is off or the app is closed.
- `fleet.LocationPing` (driver day, `client_uuid`, phone time, latitude/longitude 6 decimals, accuracy m). Append-only.
  `POST /my-day/locations` takes up to 200 points; resent points are stored once; points in the future (> 5 min) or after
  the sent closing are dropped. Office read endpoints come with T13b.
- Phone (`tracking.ts`): `watchPosition` only while the day runs; keeps a fix if accuracy <= 100 m, >= 30 s after the last
  and (moved >= 15 m or >= 2 min, a heartbeat that proves a stop); buffer in localStorage (3000 points), sent every minute,
  when back online and when the page hides. A refused permission shows a warning line.

**D-166 · The day dialog of "Journées des chauffeurs" shows the route on a map (P3-T13b)** · accepted · 2026-10-17
- `GET /day-overview/<day id>/route` (office roles): the day's GPS points in time order and the last one. The dialog has a
  "Parcours" section: OpenStreetMap tiles with Leaflet 1.9.4 (no API key), the line of the route, a green start point and a red
  last position; it refreshes every 30 s while the day runs, and warns when the last point is older than 10 minutes.

**D-167 · Stops on the route: 5 minutes within 50 m (P3-T13c)** · accepted · 2026-10-17
- `fleet/trail.py` (pure): a stop starts at a GPS point and takes the next ones within 50 m, with no gap above 15 min; it counts
  from 5 min (first to last point); its place is the average of its points. The route endpoint returns the stops; each lists
  the customers whose sale, delivery or payment was made from 10 min before to 10 min after the stop (`dayclose.day_route`).
- Customer coordinates are not stored yet (T13d): a stop is named by the sales made then, not by distance to a known place.

**D-171 · The driver's phone scrolls less (P3-T14)** · accepted · 2026-10-17
- Ma journée: while the day is not started, the cash form sits right under the truck card; the day's menu is a
  two-column grid of tiles (the history is one of them), not eight full-width buttons. The load and the boxes are
  folding cards (`FoldCard`): the load opens, the boxes stay closed; each shows a summary line (products and kilos,
  or boxes). The four stats are one compact card.
- Header: smaller (one-line title, logo 40 px). "Retour à Ma journée" moved from under each screen's content (the
  rule of D-090's follow-up) into the header, in the logo's place, so it is always in view. The language switch moved
  from the top of every screen to its bottom.
- Notices (offline, price changes, purchase decisions, sending) stay visible until they are acknowledged; only their
  extra margins went. Not folded into one panel: the price and purchase alerts need an answer from the driver.
- The main action stays on screen (`StickyAction`): the sale's total with "Suivant", the purchase's save, the day's
  closing send.
- Sale: one line per product (name, kilos left and price, the kilo input). Customers: the last five sold to come first
  under "Récents", kept only on this phone (localStorage), cleared at logout; the other customers follow, one line each.
- Deliveries: each client folds; the client, the product count and the total show when closed, the lines and the
  confirm button inside.
- Not changed: the API, the stored data and every rule for sales, closings, stock and purchases. New texts have
  French and Arabic keys; the Arabic is provisional (D-103). Whether the folds and tiles read well with a driver's
  hands and in the sun is for the field test (P3-T08).
**D-169 · The monthly closing checks the drivers' days; an out-of-pocket purchase is owed back, not a gap** · accepted · 2026-10-17
- The checks `cash_differences` and `driver_days_closed` were stubs (always OK, "Pas encore suivi"). Now
  `dayclose.selectors.period_days` feeds them: `driver_days_closed` counts past days whose closing was never sent (or
  reopened and not sent again) with the cash they should hold; `cash_differences` counts sent, unapproved days whose
  count differs from the records (sales cash + purchase money). Both are warnings, not blocking.
- **Owner decision (2026-10-17):** cash paid at the port beyond the purchase money and beyond the sales cash in hand was
  paid by the driver out of pocket. `day_summary` has `owed_to_driver` ("à lui rembourser"); `expected_cash` no longer
  goes below zero for it, so counting 0 is no écart. Nothing records the reimbursement yet; it is only shown.

**D-172 · A customer's place on the map, saved from a stop of the route (P3-T13d)** · accepted · 2026-10-17
- `Customer.latitude/longitude` (both or neither). The office (owner or manager) saves them with a button on a stop of the route
  ("Enregistrer ce lieu") for a customer served at that stop: `PUT /customers/<id>/location` (audited, empty values forget it).
  Nothing is learned silently: a wrong sale time could otherwise put a customer at the wrong place.
- A stop within 75 m of a saved place is named after that customer, also when no sale was made there (`dayclose.day_route`); the
  stop's customers are `{id, name, has_place}`.

**D-173 · The "Produits reçus" lines of a receipt are a spreadsheet grid** · accepted · 2026-10-17
- The client's XLS look (D-162) also applies to the new receipt form: the product lines are one table with a shaded
  header row and bordered cells (product, ordered or remaining, invoiced, accepted, cost, amount, use-by, partner, remove),
  not a card per line. Cells are borderless fields filling the cell; the last cost hint sits under the cost. The table
  scrolls sideways on a phone instead of stacking each line.

**D-174 · A transfer is typed like a spreadsheet, leaves from the cold rooms together, and the driver sells to the load's clients (P2-T14)** · accepted · 2026-10-17
Asked by the owner: the transfer screen in the agreed spreadsheet style; "frigo → camion X" without naming a cold room
(the products say where they are, as on a quote); camion X → camion Y; every product of a load for a named client, each
with their BL and fiche; the phone's "Vente" shows only the clients of the load.
- **Form.** The transfer form uses `LinesGrid` (D-139, D-163): one grid per client (client, delivery address, the
  client's price list proposed, else the daily price; boxes) and one grid "Gardé sur le camion, sans client". Each grid's
  "Reste" is the stock less what the other parts take. A transfer that is not a load has no price column (`price` prop).
- **From the cold rooms together.** "Départ" offers "Chambres froides (toutes)" and the trucks; a single cold room is no
  longer offered. `Transfer.from_cold_rooms` (migration 0009): only for a load into a truck; `from_location` is then the
  first active cold room by id (the boxes leave from it). Validation takes each line from the active cold rooms in id
  order, FIFO inside each room (`_post_line_from`, `selectors.held_by_location`), refused on the line when the rooms hold
  too little together. Lines stay in product order, rooms in id order: no deadlock between two validations.
- **Driver phone.** `GET /my-customers`: when today's loads of the driver's truck made BL (D-160), only those clients and
  the walk-in customer are listed, each with `on_load`. In "Vente", a client with a BL still to deliver opens it ("Livré"),
  with "Vendre autre chose à ce client" for the kept stock; "Nouveau client" is hidden. The box pickup keeps picking only.
- **Provisional:** the restriction is a list filter, not a refusal: the server still accepts a sale to another customer
  (an offline sale typed before the load, say). An old draft from one cold room reopens as "from the cold rooms together".

**D-175 · Notifications between the office and the drivers, read from the audit trail, with a tone (P3-T15)** · accepted · 2026-10-17
- New app `apps.notifications` (`Notification`, `NotificationRead`). A `post_save` receiver on `AuditLog` maps the
  audited action (`rules.RULES`) to a notification, in the action's own transaction (a refused action tells nobody)
  but inside its own savepoint: a failing notification is logged and never refuses the action. No service changed.
- Driver → office (owner and managers; the accountant is told nothing): day started, day sent or sent again, sale
  confirmed, credit asked, payment collected, road expense, loss (waiting or not), port purchase sent or changed, new
  customer, refused phone send, stock returned to the cold room. Only when the actor is a driver.
- Office → driver: load validated into the truck the driver has that day (`fleet.selectors.driver_of_location`), day
  approved / justification asked / reopened, port purchase validated / refused / changed, loss and expense decided,
  truck assigned for today or later, refused send dealt with. Only when the actor is not a driver.
- Text is not stored: `kind` + `params` (strings, values as they were), translated in each app (`notifications.kinds`,
  French and provisional Arabic). Shown 14 days, newest 40; each office reader marks read for themselves; nobody is
  told of their own action.
- Both apps poll `GET /me/notifications` every 20 s (also in a background tab). A notification newer than the last one
  this device saw (localStorage, per user) plays a two-note Web Audio tone (no sound file; vibration on a phone) and a
  toast; the first visit on a device rings for nothing old. Tone on by default, switch in the bell's panel. Push
  notifications to a closed app (Web Push) are not done: they would need a service-worker subscription and VAPID keys.

**D-177 · A BL prepared with a truck load prints provisional from its page; validating it there asks "delivered?"** · accepted · 2026-10-17
- Found on staging: the office opened a load's draft BL (D-160) and its page offered only "Valider la vente (BL)" and
  "Valider et imprimer le BL" (D-095). Printing from there confirmed the sale, which is the delivery: the kilos left the
  truck, the client owed the amount and the BL left the driver's "Mes livraisons" ("Aucune livraison à faire").
- Now a draft with `Sale.transfer` shows "Imprimer le bon provisoire" (the PROVISOIRE PDF, nothing changes), a note that
  the driver validates it at the delivery, and "Marquer livré" behind a confirmation dialog for the case the driver
  cannot. "Valider et imprimer le BL" stays for other drafts only. No server change.

**D-178 · The BL of a load is validated at the load and delivered by the driver, in full, in part or not at all (P2-T15)** · accepted · 2026-10-17
Owner's workflow (2026-10-17, all points agreed): the office prints valid BLs, a delivery status follows each one, the
driver may deliver part of it (the rest goes back to stock), the client may change their mind at the door, every change
is a new version and is notified. Replaces D-160's "draft at the load, PROVISOIRE print" and D-177's stop-gap.
- **Issued, not sold.** Validating the load gives each client's BL its BL number (`issued_at`, version 1,
  `delivery_status=to_deliver`, `SaleLine.ordered_quantity` = kg written). The sale stays a draft: no stock moves and
  nothing is owed, so the client owes only what is delivered and an undelivered kilo never left the truck (no return
  movement, the lot stays right for profit per lot, D-040). `confirm_sale` keeps an issued number.
- **Delivery** (`services.deliver_sale`, `POST /my-deliveries/<id>/deliver`): only the lines that changed are sent; zero
  takes a product off (the line is deleted, the version keeps it), less is `partial`, more is the weight at the client
  (up to the truck's stock). The price never changes. Boxes and cash taken at the door are given here. Then the sale is
  confirmed with what was delivered. All zero = not delivered.
- **Not delivered** (`cancel_delivery`, `POST /my-deliveries/<id>/not-delivered`, optional note): the draft is cancelled,
  `delivery_status=cancelled` ("Non livré"); nothing moves. Sending the day closing does this for every BL of the truck
  still to deliver (`cancel_undelivered`), note "Non livré à la fin de la journée".
- **Versions** (`SaleRevision`, immutable): issued, edited (the office changes the BL before delivery: version + 1, the
  driver is notified), delivered (version + 1 only when something differs from the BL), cancelled. Shown on the sale page.
- **Paper (owner's choice):** the driver writes the kg delivered on the paper BL (it has an empty "Livré" column) and the
  client signs; the office reprints the corrected BL ("Commandé / Livré" columns, the products not delivered, the
  version and the driver's note). Printing from the phone waits for P3-T10.
- **Offline:** the phone keeps a delivery or a "non livré" in its queue (`client_uuid` = `Sale.delivery_uuid`, a retry
  answers with what was recorded), shows the BL as done, and counts its kilos as gone from the truck meanwhile.
- **Office:** "Marquer livré" (D-177) confirms it as written (`delivered`); the documents list offers no direct "Valider"
  for a BL to deliver. Ventes filters by delivery status; the load page shows each client's status and version.
- **Notifications** (D-175): `sale.delivered` (driver → office: delivered / delivered in part, with the note),
  `sale.cancelled` of a load BL (driver → office "non livré"; office → driver "bon annulé"), `sale.delivery_changed`
  (office → driver). The plain "sale confirmed" notification is not sent for a load BL.
- **Older BLs** (made before this): migration 0019 sets their status; a draft keeps its VE number, prints PROVISOIRE and
  gets its BL number at the delivery, as before.
- **Provisional:** a credit limit under the "approval" policy can leave a delivered BL waiting (draft, `partial`/`delivered`)
  until the owner approves; a BL loaded for tomorrow is made "non livré" by tonight's closing.

**D-179 · Every action that records money asks "Annuler / Confirmer" first** · accepted · 2026-10-17

- **Owner request (2026-10-17):** a money action never goes out on one tap. `ConfirmButton` (`@frutti/ui`) opens a
  window with the amounts to check (total, cash taken, rest…) and acts only on "Confirmer"; "Annuler" does nothing.
- **Driver app now:** delivering a load BL, a sale, a customer payment, a road expense, a port purchase, starting the
  day (opening cash, purchase float), changing the float, and sending the closing (counted cash).
- **From now on:** any new screen that records money (driver or admin) uses `ConfirmButton`. The admin app's existing
  money forms are not yet converted.

**D-185 · A load's BL counts in the day of the driver who delivered it, at the moment of the delivery** · accepted · 2026-10-17

- **Bug (owner's screenshot, 2026-10-17):** "Suivi des chauffeurs" showed 4 / 4 deliveries done but 0 DT of sales and
  0 DT in hand. The day's figures took only sales `created_by` the driver, and a load's BL is made by the office.
- **Now:** the day counts the confirmed BL of its truck's loads too: those the driver delivered, and those the office
  marked delivered (unless another driver of that truck and date delivered them). Their cash at the door is in hand.
- **Sold at the door:** delivering a load's BL (phone or office "Marquer livré") sets `sold_at` to that moment, so the
  sale, its stock movement and the day it counts in are the delivery's, not the load's (a load validated the evening
  before counts on the delivery day). The prices stay those of the load.
- **Already delivered BLs** keep their `sold_at` (posted movements are not edited); a closing already sent with the
  wrong figures shows the difference and is sent again (D-132).
**D-180 · The route map and the phone's GPS tracking are switched off, not removed** · accepted · 2026-10-18

- **Owner request (2026-10-18):** disable the map feature without deleting it.
- `ROUTE_MAP_ENABLED = false` (`admin/src/dayclose/RouteMap.tsx`) hides the "Parcours" section of a driver's day;
  `TRACKING_ENABLED = false` (`truck/src/tracking.ts`) stops the phone asking for and sending its position, so no GPS warning
  shows either. The backend (points, route, stops, customer places of D-164/D-172) is unchanged; set both flags to `true`
  to bring the feature back.

**D-182 · Port purchases beyond the purchase money: sales cash and the driver's pocket are two parts, never both (fixes D-158)** · accepted · 2026-10-18

- **Owner report (2026-10-18):** a day with 0 sales, 10 000 DT of purchase money and 10 200 DT given in cash showed
  200 DT "Payé avec l'argent des ventes" and the same 200 DT "Avancé de sa poche": the money looked
  counted twice. `purchases_from_sales` held all the cash beyond the purchase money.
- Now `purchases_from_sales` is only what the sales cash really paid (`min(beyond, cash in hand)`) and
  `owed_to_driver` the rest; the two add up to the cash beyond the purchase money. `expected_cash`, the counted cash
  and the gaps do not change.
- Suivi des chauffeurs: "Doit avoir en main" = caisse + ventes + règlements − dépenses − payé avec les ventes − déjà
  remis; the pocket part is shown under it, outside the sum, as what the office owes the driver.
- Migration `dayclose.0006` corrects only that one figure in the kept day figures (closings and undone sends) so days
  already sent read right; no money figure that counts changes.
**D-181 · Buying at the port: the money given may not exceed the purchase (changes D-176)** · accepted · 2026-10-18

- **Owner request (2026-10-18):** a typo in the sums given at the port must be stopped at entry, not turned into an
  advance. `_checked_field_purchase` refuses, on every save (phone, office, validation), sums given above the
  purchase's amount, on `payments.<last>.amount`. The ceiling is Σ max(driver's kg, kg received) × price per line, so a
  lot the office counts lighter keeps what was really given and the part beyond what is owed stays an advance at
  validation (D-176). A real advance beyond the purchase is recorded as an ordinary supplier payment.
- The phone (`purchaseTotals().overpaid`) and the office form check the same before sending, so a purchase kept
  offline is never refused later for this.

**D-183 · The receipt's product cell is typed and searched, not a drop-down (changes D-173)** · accepted · 2026-10-18

- **Owner request (2026-10-18):** "an empty box, and when I start typing I see the products, like in devis or vente".
  The product cell of `ReceiptFormPage` uses the same `Combobox` as `LinesGrid` (D-139): it finds products by code,
  name, Arabic name or category; Enter or a click takes one and moves to the next weight (ordered, or invoiced when
  receiving against an order). Against an order, only the order's products are offered, as before.
- The supplier, place and partner choices stay drop-downs: their lists are short.

**D-184 · An empty truck shows no client in "Vente"** · accepted · 2026-10-18

- **Owner request (2026-10-18):** "when nothing is loaded in the camion the driver should not see clients"; the office
  names the clients when it loads the truck (D-174, D-178), so with nothing on board there is nobody to sell to.
- The "Vente" tab first reads the truck's stock: when every product is gone or already promised to a sale, delivery
  or loss waiting on the phone (`truckIsEmpty`), it shows only "Le camion est vide · Il n'y a plus rien à vendre dans
  ce camion." Phone screen only; the server already refuses a sale beyond the stock.
- Without an answer about the stock (offline and never loaded), the client list still shows, so a sale is not blocked.

**D-186 · A public site with orders and quote requests, and site products with their own web price** · accepted · 2026-10-18

- **Owner request (2026-10-18):** a dynamic, animated public website where a visitor asks for a quote (devis) or
  orders products, the **phone number being required**; then "in the office application, manage the web site
  products: change the price (only on the web site), add and remove products".
- A third front end, `frontend/apps/site` (`@frutti/site`, port 5175, nginx port 8083 in the web image), one page in
  French: video hero, catalogue, "du port à vous", basket and request form. Motion is CSS + IntersectionObserver
  (`motion.ts`), no new package; it stops under "reduce motion". Media made with Artlist (free trial: two Nano Banana 2
  stills, one Kling 2.5 Turbo image-to-video loop), compressed to WebP / H.264 + VP9 (~3.6 MB in all) under
  `apps/site/public/media`. The site imports the generated types only and calls the API through `apiFetch`, to keep
  the office's Zod schemas out of the visitors' download.
- Backend app `storefront`. **No login on the site:** `GET /site/catalog`, `GET /site/products/<id>/photo`,
  `POST /site/requests` have no session, no CSRF, and are throttled per address (120/min, 10 requests/hour) with a
  hidden "website" field for robots. The company served is `PUBLIC_SITE_ORGANIZATION_ID`, else the oldest active one.
- **Every active product of the application is on the site, with its photo** (owner, 2026-10-18: "list all products
  with their photo from the application"); a new product shows at once. The office's choices per product are a
  `SiteProduct` row, made on the first change (`is_published`, `web_price`, description, position), in "Site web →
  Produits du site", which lists every active product with its photo and day's price (owner and manager write,
  accountant reads). Hiding replaces removing. A product without its own photo gets an Artlist picture by name/kind. The **web price is the site's
  alone**: it never changes the day's price (D-020), the price lists or a sale; empty = "prix sur demande". Archived
  products never show. The day's price, costs and stock are never sent to visitors.
- A request (`WebRequest`, number `W-00012`) is a lead, not a sale: nothing moves stock or money. The phone is
  normalised like the server's `normalize_phone` (8 Tunisian digits with or without +216, or an international number);
  an order needs a product, a quote a product or a message; each line keeps the web price shown (snapshot). The office
  is told at once (notification `web_order` / `web_quote`, actor none) and closes it in "Site web → Demandes du site"
  (handled / cancelled / new again, with a note), then makes the quote or sale as usual.
- **Owner request (2026-10-18): the phone is set in the office app.** `SiteSettings` (one row per organization:
  phone, WhatsApp, e-mail, address, hours) in "Site web → Paramètres du site" (owner and manager write, accountant
  reads). Numbers are checked and stored like a visitor's (`normalize_phone`). The catalogue answer carries them as
  `contact`; the site shows the phone in the header, under the hero buttons, after a request, next to a sending error,
  as a round call button on phones, and in the footer with WhatsApp, e-mail, address and hours. An empty field is not
  shown. Not taken from the invoice settings' phone: the site's number may be another line.
- **Domain (owner, 2026-10-18): https://www.fruttidelmare.com**; the bare `fruttidelmare.com` redirects to it. Host
  nginx blocks (port 80 for the challenge and the redirect, 443 to the web container's 8083), `SITE_HOST` in
  `DJANGO_ALLOWED_HOSTS` and the CSRF origins, and the health check of each deploy. The deploy adds both names to the
  `frutti-staging` certificate itself the first time (certbot webroot, `--expand`); a failure only warns.
- The site shows the **company logo** uploaded in Paramètres (D-125) in its header, footer and browser tab, through a
  public `site/logo` (no login), on a white tile so a dark logo stays readable.
- Owner review of the page (2026-10-18): only the "Aube" and "Pro" value cards are kept, and the site says "Sfax"
  instead of "Sakiet Ezzit".
- _Provisional:_ the other marketing texts of the page (story) are generic and must be checked by the owner.
**D-187 · The Caisses page says whose boxes are whose ("Bilan des caisses")** · accepted · 2026-10-18

- **Owner question (2026-10-18):** "how can I know which boxes belong to us, to the supplier, to the client: what we
  own and what we should return". The three lists showed where boxes are, but not whose they are.
- Boxes are alike and are not tracked one by one (D-124), so ownership is a count: **à nous = en main (froid et
  camions) + chez les clients − à rendre aux fournisseurs**. Only the opening stock, a purchase and a write-off change
  it; a receipt or a return moves a location and a supplier by the same count, a load, a delivery or a pickup moves
  boxes between our places and clients.
- A "Bilan des caisses" card above the three lists, one row per box type: in hand, at clients (to collect), owed to
  suppliers (to give back), ours (red when below 0: more boxes owed than we have, e.g. supplier boxes lost). Worked out
  in the browser from the balances the page already loads (`boxSummary` in `boxes/shared.ts`); no API change.
- Each list has a one-line note: locations hold ours or lent ones, clients' boxes are to collect, suppliers' are to
  give back (`kindNotes`, replaces `supplierNote`).

**D-188 · "Créer un devis" on a site request opens the quote in a window, its products already in** · accepted · 2026-10-19
- Asked by Mahmoud (2026-10-19): the office's buttons (Marquer traitée, Annuler la demande, Enregistrer la note,
  Créer un devis) sat at the bottom of the request page. They move to the top: the "Suivi du bureau" card is the
  first card, its buttons come before the note.
- "Créer un devis" does not leave the page. It opens the quote form in the window of D-138 (`NewDocumentDialog`), with
  the request given as `fromRequest`: the products the visitor asked for and their kilos start the quote, to change,
  save or send. Accepting the quote (which creates the BL, D-115) stays on the quote page.
- Not copied: the web price (the price is proposed as for any line: the customer's list, else the day's price).
- Customer: a site request has no customer link, so the window picks the active customer whose phone has the same last
  eight digits, only when exactly one matches; the office can change it.
- "Envoyer" saves and sends, then the window closes. "Accepter et créer le BL" saves, sends and accepts, then opens the
  BL dialog (`DeliverDialog`, D-115) over the window with `stayHere`: the BL is made without navigating to it. Cancel
  there keeps the accepted quote; the BL can be made later from its page.

**D-189 · Units come from the formatter only; empty screens stack on a phone (UI review)** · accepted · 2026-10-19
- `formatMoney` and `formatQuantity` already end with "DT" / "kg": no screen or translation adds the unit again
  (fixed: dashboard figures and alert pills, "dont … en retard", product stock, the driver's "Dans le camion" line).
  A screen that wants the unit smaller splits the formatted text at its last no-break space (dashboard `Kpi`).
- Month names follow the app language (`monthLabel`), never the browser's (the dashboard showed "October 2026").
- `EmptyState`: below the `sm` width the drawing sits above the text, full width, instead of squeezing the text into a
  narrow column (driver phone). On the driver's Vente screen a long product name wraps instead of being cut.
- Left for later (e2e tests click these links): detail pages show both the shell's "Retour" (D-110) and their own
  link ("Toutes les ventes", "Retour au stock"…); keep one.

**D-193 · Price floor: an owner or manager may go under the minimum with a reason; products without a minimum are flagged** · accepted · 2026-10-25
- Question from Mahmoud (2026-10-25): does a "remise" that takes the price under the minimum get stopped on quotes, BL and invoices?
  D-163 already refuses it on every quote and sale line (also on update and on "Convertir en vente"). A BL's lines are those of
  its sale and an invoice's lines are copied from its BLs with no price edit, so they inherit the check; no extra check was added.
- **Override.** `below_minimum_reason` (text, max 255) on `POST/PUT /quotes` and `/sales`. Counted only when the caller is owner or
  manager (the view drops it for anyone else, so a driver's or accountant's line stays refused). With a non-blank reason the line is
  kept, `below_minimum` is set, and the audit logs `quote.price_below_minimum_approved` / `sale.price_below_minimum_approved`
  (actor, reason, each line's price, discount and minimum). The reason is not kept on the document, only in the audit.
- **Quote → BL.** A BL made from a quote takes the quote's prices as agreed (the quote already passed the floor, or an owner let it
  go): its lines are not refused if the minimum was raised since, and anyone who may deliver can do it.
- **Warning.** In the admin line grid, a product with no minimum shows "Aucun prix minimum : la remise n'est pas contrôlée", and a
  row under its minimum shows the price after discount in red while typing; the quote and sale forms then ask the owner or manager
  for the reason, and tell others to correct the row. The server stays the judge.
- Not done: an invoice-level guard (nothing can change an invoice line's price), a reason stored on the document, the driver app.

**D-192 · "Règlements fournisseurs": what is paid, planned or still undefined, per purchase (P3-T16, owner brainstorm 2026-10-20)** · accepted · 2026-10-20
- **Owner request:** when we pay a supplier (office or driver app) the steps must be clear: what is given now, nothing, a part
  or all, and with which method. The driver only records what he gives; the rest is decided in the office. The office needs one
  view of every purchase: settled, planned, or not yet defined.
- **Unit = the supplier invoice (FF).** Every purchase (port, office receipt, opening balance) ends as an FF, so the state is
  computed per FF: `paid` (allocated payments), `planned` (open plan lines), `undefined = total - paid - planned`.
  State of an invoice: `settled` (nothing left), `overdue` (a plan line or the due date passed, not paid), `planned`
  (the whole remainder has plan lines), `undefined` (part of the remainder has no plan; partial plans stay `undefined`
  until the sum is complete).
- **A plan is not a payment (owner):** new `SupplierPaymentPlanLine` (invoice, amount > 0, method, `planned_on`, reference,
  cheque/traite `cash_on`, status `open` | `paid` | `cancelled`, the `SupplierPayment` that settled it). Creating, changing or
  cancelling a plan line never touches the supplier balance. Recording the real payment (existing payment form) can name the
  plan line it settles; then the line becomes `paid`. Several lines per invoice (split across methods and dates, owner: often);
  their sum may not exceed the remainder; a payment is still never edited.
- **Existing invoices start as `undefined`** (owner): no data migration to a plan.
- **View:** Achats › "Règlements fournisseurs", its own sub-view, not Dettes. Summary bar (total dû = payé + planifié + à
  définir), tabs `À définir`, `Planifié`, `En retard`, `Réglé`, a filter by purchase type (port, office receipt, opening),
  per row a "Définir le règlement" button opening a multi-line dialog (method, amount, date, reference, cashing day; lines
  must add up to the remainder). Dettes stays as it is.
- **Driver app (and the office receipt form, same component logic):** first "Qu'avez-vous donné maintenant ?" with
  `Rien / Une partie / Tout`; part or all asks amount and method (a cheque or traite asks number and cashing day); a live
  line "Total · Donné · Reste → à définir par le bureau". The driver never picks the method of the rest. Builds on the
  sums-given lines of D-176/D-181, no new rule for them.
- **Alert:** the dashboard counts invoices left `undefined` for more than 24 hours since they were posted (provisional
  window, as D-176's).
- Not changed: the three balances stay separate (payables, capital, profit share).
- **Built in T16a (backend):** `planned` never exceeds what is left (total - allocated), so a payment made without naming a line cannot make
  the amounts add up to more than the total. A payment naming a plan line must allocate to that line's invoice; the line becomes `paid` whatever
  the amount (a part-payment of a line leaves the rest `undefined`). Replacing a plan marks the old open lines `cancelled` (history kept).
  `overdue` = an open line's date passed, or part undefined with the due date passed. Dashboard `settlements_undefined_late` counts invoices with
  any undefined amount posted 24 h ago or more, whatever their state.
- **Receipt payment (P3-T16d):** `POST /receipts` takes optional `payments` (amount, method, reference, cash_on) only with `invoice_now` ("Dû dès la réception"): recorded with `record_payment` in the same transaction, allocated to the receipt's FF; sums above its total are refused on `payments.<last>.amount` (D-181), without the invoice they are refused on `payments`. The office receipt form has the same Rien / Une partie / Tout step and Total · Donné · Reste line.
- **Built in T16b (office):** the page is a tab "Règlements" of the Achats tabs (the menu has no counters, so counts sit on the page tabs). "Enregistrer le paiement" opens the existing payment form with `ligne`, `montant`, `mode`, `ref`, `encaisse` in the URL, and the form sends `plan_line`. The dialog plans `total - paid` and replaces the open lines.

**D-192 (follow-up, owner 2026-10-20):** "Règlements fournisseurs" is a side-menu entry (Marchandises group, under Achats), not a tab of Achats; the sales entry is renamed "Règlements clients". The menu highlights only the deepest entry matching the path.

**D-191 · A general cost is spread over the calendar days of its month, not monthly / 26 a day (finance review)** · provisional · 2026-10-19
- Found by a finance review of the calculations: the code charged each calendar day monthly / 26, so a lot in stock all month carried
  30/26 or 31/26 of the bill (a year: 14.04 months instead of 12). The month's expense counts the bill once, so the lots did not add up to it.
- Now each calendar day of the month carries its share of the month, split to the millime (`general_day_amounts`), so a lot in stock all
  month carries the bill exactly once. Hours with nothing in stock stay uncharged (D-142), as before.
- **Provisional:** the client's rule "a day is a 26th of the monthly amount" (D-041, Q21) may mean 26 working days a month; the owner
  confirms which. Changing it means changing `general_day_amounts` and its tests only.
- Not changed by this decision, open for the owner: employer CNSS and bonus/overtime in the lot cost of employee days (D-055 vs D-041),
  the settlement of a carried negative balance against the capital (D-031), and the cash-flow basis (approval date vs paid date).
**D-190 · "Convertir en vente" takes the payment on the spot (method, amount, reference)** · accepted · 2026-10-19
- Reported by Mahmoud (2026-10-19): the quote's "Convertir en vente" window had no field for the payment method or
  the amount the client pays. For a "Client de passage" the server refused the BL ("paie toute la vente sur place")
  and the window had nothing to fix it with.
- The window now has the same payment block as the sale form (D-047): "Payé en entier" (on by default for the
  walk-in client), "Montant payé (DT)" (disabled while "Payé en entier" is on), "Mode de paiement" and the reference.
  It is sent with the BL on both "Créer le brouillon" and "Créer et confirmer"; the server checks it against the BL's
  total, as before. A payment error sits on its field, not in the red line at the bottom.
- The quote's customer now says whether it is the walk-in client (`is_walk_in` on `QuoteCustomer`, read-only). The
  payment method has no default: a walk-in BL cannot be confirmed until one is chosen.

**D-194 · Logging out asks first, in both apps (owner list 2026-10-31, item 4)** · accepted · 2026-10-31
- The logout icon of the office and driver apps opens "Se déconnecter ?" (`LogoutDialog` in `@frutti/ui`) with
  Annuler / Se déconnecter; nothing happens until the second button.
- On the phone, logging out erases what is still waiting to be sent, so the window says how many sends are waiting
  instead of the plain question.

**D-195 · "Bon d'achat" is called "Commande d'achat" (owner list 2026-10-31, item 13)** · accepted · 2026-10-31
- Every French label, message and the document-kind choice say "Commande d'achat" (feminine agreement fixed).
- Numbers keep their "BA-" prefix: issued numbers never change, and one series stays readable. Codes, URLs
  (`/achats/commandes`) and the API (`purchase_order`) are unchanged.

**D-196 · "Transferts" is a side-menu entry under the driver's day (owner list 2026-10-31, item 14)** · accepted · 2026-10-31
- Loading a truck belongs to the driver's day, so "Transferts" sits in the Marchandises group right under "Camions du
  jour" and "Journées chauffeurs", and is no longer a tab of Stock. The URLs stay `/stock/transferts…`, so old links work.
**D-197 · Règlements with several means over several invoices, and a Trésorerie that follows every cheque and traite (Phase 9, P9-T01)** · accepted (provisional parts marked) · 2026-10-31
- Owner request (2026-10-31): a customer settles several invoices at once with some cash, three traites and three cheques of
  different due days; the same for what we pay suppliers; and a treasury module that follows the payments. Plan in
  `docs/phases/09-treasury.md` (T01 to T07).
- **Règlement = header + lines + allocations.** `CustomerPayment` stays the règlement (`RG-…`, customer, day, total, void);
  `CustomerPaymentLine` holds each means (method, amount, reference, effet). `amount` is the sum of the lines; `method` is the
  lines' method or `mixed` ("Plusieurs moyens"). Customer methods are `CustomerPaymentMethod` (the sale's four + `bill`
  "Traite" + `mixed`); a sale paid on the spot keeps `SalePaymentMethod`. Allocation is per règlement, not per effet.
- **Allocation by invoice.** An allocation row names a `sale` (BL) or an `invoice`; an invoice's amount is spread over its open
  BLs oldest first (allocations stay per BL in the database, as D-062).
- **New app `treasury`.** `Bank` (the Tunisian banks, seeded per organization, editable), `Instrument` (an effet: received or
  issued, cheque or traite, number, bank, drawer, amount, issued day, due day, status, the customer or supplier, the
  règlement's number) and `InstrumentEvent` (append-only status moves). Sales writes effets only through
  `treasury.services.register_instrument`; treasury never imports sales (it keeps the règlement number as text). The
  statuses and allowed moves are in `services.ALLOWED_MOVES`; T01 writes `portfolio` and `cancelled` only.
- **Checks of an effet:** a cheque needs number and bank (no date: due the day received); a traite needs number, bank and a due
  day not before the day received; a due day at most 365 days ahead (**provisional**); the same paper (kind, bank, number) of
  the same customer is refused twice, also inside one règlement (a cancelled one may be typed again); a bank taken off the
  list is refused.
- **Voiding** a règlement cancels its effets still in the portfolio; refused once one moved on (at the bank, cashed, unpaid,
  endorsed): T04 handles that paper's life (impayé = a new record, never an edit).
- **Retenue à la source** is not a line: the invoice's certificate (D-063) already lowers what is owed.
- **Old payments** (data migration `sales.0020`): each gets its one line; a cheque payment gets its effet with an empty bank
  ("à compléter"), in the portfolio when received in the last 30 days, taken as cashed when older, cancelled when voided
  (**provisional**: the office reviews the portfolio once T04 ships).
- **API.** `POST /customer-payments` takes `lines` (1 to 50; errors on `lines.<i>.<field>`); without it, `amount` + `method` +
  `reference` make the one line (driver app unchanged). With `lines`, an `amount` sent must equal their sum. Payments return
  their `lines` with the effet and its status; search also finds an effet's number. `GET/POST /treasury/banks`,
  `PUT /treasury/banks/<id>`, `GET /treasury/instruments` (direction, kind, statuses, party, due range, search). Office
  roles as everywhere: owner/manager write, accountant reads, drivers 403.
- **Office (T01, minimal):** the existing "Enregistrer un règlement" window asks number, bank, échéance and drawer for a cheque
  or a traite and sends one line. The full multi-line page is T03. Receipt PDF lists the lines when there are several or an
  effet.
- **Defaults chosen without the owner (provisional, Q29):** banks editable in Paramètres › Banques (T03); drivers keep cash only
  on the phone; driver cash moves to the Caisse at the approved day closing (T05); bank charges of an impayé or a deposit go to
  expenses "Frais financiers"; the balance drops when an effet is received, with the encours shown next to it and checked
  against the credit limit (T07).

**D-207 · A driver never sees what a customer owes (owner list 2026-10-31, item 7)** · accepted · 2026-10-31
- Enforced on the server: `GET/POST /my-customers` no longer carries `owes`. The phone's "Encaisser" list shows the
  customer's name and city; the driver types the amount handed over (no pre-filled balance).
- The credit-limit refusal, which named the balance and the limit, reads for a driver "Limite de crédit dépassée pour
  X : faites payer davantage sur place ou appelez le bureau." The office still gets the full message.

**D-198 · Stock products as cards or as a list (owner list 2026-10-31, item 1)** · accepted · 2026-10-31
- "Stock par produit" has a "Cartes / Liste" switch. The list is one table: reference, product, total kg, one column per
  place holding stock, average and last purchase price, state; it sorts by product, total or average price.
- The choice is remembered per browser (`localStorage`, best effort); cards stay the default.

**D-199 · Every amount reads 1 250,000 DT, server messages included (owner list 2026-10-31, item 6)** · accepted · 2026-10-31
- Audit: the two apps, the public site and the PDFs already format every shown amount with 3 decimals and a
  thousands separator (`formatMoney`, `pdf_format.money`). The server's error messages did not ("1250.000 DT").
- `core.money.display_money` gives the same format as the PDFs (narrow no-break space, comma, 3 decimals) and the
  20 messages that name an amount use it (credit limit, payments over what is due, allocations, closing notes…).
- Not changed: what a user types in an amount field stays as typed; the parser already accepts "1 250,5".

**D-200 · Invoices are made from the BL / BR you tick, again and again; a port purchase makes no invoice (owner list 2026-10-31, items 11 and 12)** · accepted · 2026-10-31
- Clients: Factures › "Nouvelle facture" (`/factures/nouvelle`): pick the customer, the page lists their confirmed BL with
  no invoice; tick one or several, "Générer le brouillon" or "Générer et émettre". The page stays on the customer, the
  invoiced BL leave the list, and the invoices made are listed with their links, so the next one is made at once. The
  backend already grouped BLs of one customer (D-096); only the screen is new.
- Suppliers: the existing "Nouvelle facture fournisseur" form (tick the supplier's receipts) gets "Valider et en faire une
  autre" (same supplier, the form empties) and "payer avec l'argent déjà donné" (on by default): `apply_advances` on
  `POST /supplier-invoices` allocates the supplier's unallocated payments to the new posted invoice, oldest first.
- "Achat terrain": validating records the receipt and the money given (as supplier advances), **no invoice**. The
  constraint `field_purchase_validated_has_documents` becomes `…_has_receipt`. The purchase page links "Facturer la
  réception" (the supplier form with that receipt ticked). When an invoice posted later holds the receipt of exactly
  one port purchase, the purchase links it (so "Règlements fournisseurs" still shows it as "Achat terrain").
- Not changed (provisional): a receipt typed at the office as "Dû dès la réception" still makes its invoice at once
  (D-192); the owner said only the port purchase. The deal and due days typed on a port purchase are no longer used;
  the due date is set on the invoice.

**D-201 · Pick the lot on every quote and sale line, FIFO by default (owner list 2026-10-31, item 15)** · accepted · 2026-10-31
- The "Lot" column of the counter sale (D-121) is now on the sale form and the quote form too (`lib/LotPicker`).
  Without a fixed place it lists the product's lots in every cold room (new `GET /inventory/stock/<product>/batches`,
  trucks left out), each with its place, supplier and kg; "Lot le plus ancien (FIFO)" stays the default.
- Sale form: a picked lot fixes the place the sale leaves from; lots picked in two places are refused on the form
  ("une vente part d'un seul endroit"). Without a picked lot the place is found as before (D-144).
- Quote lines keep the lot (`QuoteLine.requested_batch`, migration 0021); the BL made from the quote takes it. If the
  BL leaves from another place, the lot is not there and FIFO applies (the lot is a preference, as in D-121).
- Sale and quote lines now return `requested_batch`, so a draft reopens with its lots.
- Not done: the driver's phone sale (the truck's lots); ask the owner if it is wanted.

**D-202 · Goods bought with VAT are sold with VAT (owner list 2026-10-31, item 10)** · provisional · 2026-10-31
- "Nouvelle réception" has "Achat avec TVA" (`GoodsReceipt.with_vat`); each lot of that receipt keeps it
  (`Batch.bought_with_vat`). A port purchase is without VAT for now.
- Quote and sale forms show "Acheté avec TVA : <produits>…" when a row's product has kilos in stock bought with VAT
  (`GET /inventory/vat-products`). Quotes and BL carry no VAT detail themselves (D-057): the rule bites on the invoice.
- Issuing an invoice without VAT is refused when one of its BL took kilos from a lot bought with VAT
  (`apply_vat` error naming the products). A draft without VAT can still be prepared.
- Provisional: the rule is per lot (what was really sold), not "the product was once bought with VAT"; the owner and
  the accountant confirm, and whether it should only warn instead of refusing.

**D-203 · The office sets the driver's starting cash; the driver accepts it to start the day (owner list 2026-10-31, item 3)** · accepted · 2026-10-31
- New `fleet.DayFund` (driver, date, `opening_cash`, `purchase_float`, `set_by`, `accepted_at`). The office types it in
  "Camions du jour › Fonds de caisse du jour" (`GET/PUT /day-funds`); it changes freely until the driver accepts it.
- The phone's "Ma journée" no longer has amount fields: it shows "Argent remis par le bureau" (`GET /my-day/fund`) and
  "J'ai reçu cet argent : commencer ma journée" (confirm window). `POST /my-day` takes no body any more: it starts the day
  with the fund's amounts and stamps `accepted_at`. With nothing set, it is refused ("appelez le bureau").
- A driver who disagrees calls the office before accepting (no "contester" button, provisional). The purchase money can
  still be raised during the day from the phone (D-158).

**D-204 · At closing the office counts the cash too; the gap with the driver's count is shown (owner list 2026-10-31, item 8)** · provisional · 2026-10-31
- The closing window has "Comptage du bureau": the cash the office counted (and the purchase money, for a day with
  purchases). It shows "Bureau X · chauffeur Y · écart Z" live; "Approuver" needs the office count.
- Stored on the closing (`office_counted_cash`, `office_counted_purchase_cash`, migration); the API adds
  `office_gap` / `office_purchase_gap` (office − driver). A day sent again clears the office count.
- A gap is allowed but needs a note (kept as the review note, audited). Provisional: the owner may prefer a gap to block
  the approval, or a tolerance. The API still approves without an office count (old clients, tests); the screen
  always sends one.

**D-205 · Expense categories the owner edits for both apps; "Payé avec" always offered on the phone (owner list 2026-10-31, items 2 and 5)** · provisional · 2026-10-31
- `ExpenseCategory.for_drivers`: the owner ticks "Sur le téléphone des chauffeurs" per category (fuel, transport,
  handling and miscellaneous are ticked by a data migration, as before). The phone lists exactly those; the server
  refuses another. The owner adds, renames, archives, and now removes a category never used
  (`DELETE /expense-categories/<id>`); a used or default one is refused (archive it instead).
- Provisional reading of "in both apps": the office edits the list, the driver app uses it; drivers do not add
  categories themselves.
- Phone expense: "Payé avec : La caisse / Ma poche / Carte" (`paid_with`), offered whatever the day's cash, also at
  0 DT. "Ma poche" sets `Expense.paid_by_driver` (owed back to the driver); "Carte" records payment method "other".
  Only "La caisse" lowers the cash the driver should hold. The day summary adds `expenses_pocket` and
  `expenses_other`, shown in the office's closing window.

**D-206 · Any document PDF can be e-mailed from the company address (owner list 2026-10-31, item 9)** · provisional · 2026-10-31
- Every "PDF" button of the office app has an "E-mail" button beside it (quote, invoice, credit note, receipt, BL,
  partner statement). The window proposes the customer's (or partner's) address, the subject "<Document> <numéro> -
  <Société>" and a short French message; all three can be changed. The PDF goes as an attachment.
- `GET/POST /documents/<kind>/<id>/email`; the same roles as the PDF read the draft, owner/manager send. Every send is
  kept (`documents.SentEmail`, also a failed one with its reason) and the window lists the last five.
- Sent with Django's SMTP backend from `DEFAULT_FROM_EMAIL` (shown with the company name; replies come back to it).
  Settings come from the environment (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
  `EMAIL_USE_TLS/SSL`, `DEFAULT_FROM_EMAIL`), passed by `deploy/compose.staging.yml`. Without `EMAIL_HOST` a
  production server refuses to send with a clear message; development prints the message in the console.
- **Owner action:** the company mailbox and its SMTP account (provider, user, app password) go into the server's `.env`.
- Not covered yet: the customer and supplier statements of the reports (their PDFs are made by another endpoint).

**D-208 · A supplier règlement with several means; our cheques and traites are effets issued (Phase 9, P9-T02)** · accepted (provisional parts marked) · 2026-10-31
- `SupplierPaymentLine` (method, amount, reference, effet): a règlement fournisseur can be some cash, several of our
  cheques and traites, a transfer... The lines add up to its amount; `SupplierPayment.method` is `mixed` ("Plusieurs
  moyens") when they differ. A line never is `mixed`, nor a plan line or a sum given at the port.
- Each cheque or traite is a `treasury.Instrument` with `direction=issued`, status `issued` (until T04 marks it
  debited), its number, the bank it is drawn on and its échéance. Our cheque number is one paper whoever it went to:
  the same number on the same bank is refused twice (received effets stay per customer, D-197).
- `POST /supplier-payments` takes `lines` (number, bank and due day for an effet; a traite needs its due day) and
  `auto_allocate` (the invoices due first are paid first), `plan_lines` (several D-192 plan lines paid by one
  règlement). Without `lines`, `amount`/`method`/`reference`/`cash_on` make one line as before (the port purchase,
  a receipt paid at once, the current form): its effet may lack its bank and number ("à compléter", the number then
  is the règlement's) and a traite without its day falls due on the payment day (`partial` in the treasury checks).
- `cash_on` stays on the règlement for one cheque or traite; each effet keeps its own échéance. "Chèques et traites à
  venir" (D-159) now lists every effet issued, so a cheque given without a cashing day shows on its payment day.
- Data migration: every old supplier payment gets one line; a cheque or a traite gets its effet, bank empty, due on
  `cash_on` (else the payment day), taken as debited when due more than 30 days ago (provisional, checked in T04).
- API enums: `PaymentMethodEnum` stays the five means (expenses, plan lines, lines); the règlement's own method is
  `SupplierPaymentMethodEnum` (adds `mixed`).
- Supplier règlements still cannot be voided (no void before D-208 either); a void with its effets comes with T03.

**D-209 · Staging also deploys from the organisation repo SmartToolsAgro/SmartFeesh, on request (owner, 2026-10-31)** · accepted · 2026-10-31
- PRs and CI stay on `mahmoudnjeh95/Seafood_distrubion`, which keeps deploying staging after every green merge.
- SmartFeesh follows its `main` by fast-forward pushes, made only when the owner asks; it has its own key
  (`frutti-ci-deploy-smartfeesh`, `restrict`) and secrets, so each such push tests and deploys again.
- Push only once the personal repo's deploy of that commit is done: two builds at once overload the shared server
  (#216). See `docs/runbook.md` › Deploy.

**D-210 · The "Nouveau règlement" pages: lines, "Répartir", live totals and a last look (Phase 9, P9-T03a)** · accepted (provisional parts marked) · 2026-10-31
- Customer règlements get a full page, `/reglements/nouveau` ("Règlement détaillé" on the customer card, "Nouveau
  règlement" on Règlements clients). The quick window "Enregistrer un règlement" stays for one means.
- One lines editor serves both forms: a line per means; cheque and traite ask number, bank (Paramètres › Banques),
  échéance, and for a customer the drawer (empty: the customer). "Répartir" makes N cheques or traites of equal
  amounts every 1 to 12 months from a first échéance, numbers counted on from the first ("004401" → "004402"); the
  millimes that do not divide go on the last one.
- What a customer règlement can settle: each open invoice as one row (the server spreads it over its BLs, oldest
  first) and each BL on no invoice. "Affecter automatiquement" fills the one due first first; nothing typed keeps it
  all as the customer's credit (the confirm window shows it).
- The customer règlement page shows the encours next to the balance: solde + effets received still in portfolio or at the
  bank, red when over the credit limit (Q29's recommendation, provisional until the owner answers; the server's
  credit check still reads the balance only).
- Every règlement goes through a confirm window (D-179) with the total, the affecté, what is left, and one line per
  means. The supplier form moved to the same editor: its single "Montant / Mode" fields are gone.
- Banques: a page under Finance (`/tresorerie/banques`), where T04 adds the Portefeuille. Owner and manager write.
- The list and detail pages, the supplier void and paying several plan lines at once moved to P9-T03b.

**D-212 · Several lots picked by hand on a counter-sale line (owner request, 2026-10-31)** · accepted · 2026-10-31
- A counter-sale line may name several lots, each with the kilos to take from it: `SaleLinePick` (one row per line
  and lot), written as `picks: [{batch, quantity}]` on `SaleLineWrite`. Picks take their kilos in the order given,
  each up to what it holds; what they leave over comes from the other lots, oldest first (FIFO), and a picked lot
  short is topped up the same way. Stock never goes negative.
- A single `batch` (D-121, quote and sale forms) stays as it was: it is one pick of the line's whole weight.
  `picks` take precedence when both are sent.
- Refused on the line: picks asking more kilos than the line's weight, a lot picked twice, a lot of another product
  or organization, a pick without kilos above zero.
- Migration `0022_sale_line_picks` creates the table and copies each draft's single lot into one pick of the line's
  whole weight, so a draft confirmed after the deploy still takes its lot. A confirmed sale keeps `SaleLineBatch`.
- The till opens a dialog from the lot cell to choose the lots and their kilos; the cell shows the picks and warns
  when a picked lot is short. Regular sale and BL screens still use the single lot picker (D-201).
- Provisional: the kilos the picks leave over come from the oldest lots only; the seller cannot pick the lot for that
  rest.

**D-211 · A supplier règlement can be voided; the règlements lists filter, add up and export (Phase 9, P9-T03b)** · accepted · 2026-10-31
- `SupplierPayment.voided_at/voided_by/void_reason`, `POST /supplier-payments/<id>/void` (owner, manager) with a
  reason. Like the customer void: the règlement stays in the list, marked; its allocations stop counting (its
  invoices go back to "validée" or "partiellement payée"), the D-192 plan lines it paid are planned again, its
  cheques and traites are cancelled (their numbers are free again). Refused once one of them was debited or rejected,
  and for money given at the port with a purchase (corrected on the purchase).
- Every reader leaves voided règlements out: supplier balance, invoice paid amount and status, open invoices,
  advances (and their automatic use), debts and "chèques à venir", statement, payments per day (cash flow report),
  partner trade payable. An advance of a voided règlement is 0.
- Both lists filter by days, means (a line of that means, or `mixed`) and state (`active`, `voided`,
  `unallocated`); `GET …/totals` adds up the same filter (voided left out, counted apart) with what each means paid;
  `GET …/export` gives the same rows as an Excel file. The Excel builder moved to `apps/core/xlsx.py` (the reports
  use it too).
- Each règlement has its page (`/reglements/<id>`, `/achats/paiements/<id>`): its means with each effet's state and
  history, what it settled, the credit or advance left ("Affecter"), "Annuler" with a reason; the PDF receipt for a
  customer. The supplier receipt PDF and paying several plan lines from "Règlements fournisseurs" move to P9-T03c.

**D-213 · Only the office counts the driver's cash; the driver sees what they should hold (owner request 2026-10-31)** · accepted, provisional points marked · 2026-10-31
- The owner's rule: the cash the driver hands over is counted at the office, not on the phone. The driver's closing
  (`POST my-day-closing`, `my-past-day-closing`) takes only an optional `note`; the phone shows "Argent attendu dans
  la caisse" and the purchase money expected, and never a count field, a gap or a difference. The send still closes
  the day (D-134).
- The office counts in the closing window (`POST /day-closings/<id>/count`, owner or manager, `record_office_count`,
  while the day is sent and not approved): the sales cash, and the purchase money when some is expected. The gap is
  `office − expected` (`office_difference`, `office_purchase_difference`, stored; 0 until counted). "Enregistrer le
  comptage" saves it before the review; "Approuver" needs the sales count (and the purchase count when purchase money is
  expected), and a gap needs a note (the review note). The approval may still send the counts, as before.
- `DayClosing.counted_cash`, `counted_purchase_cash`, `difference` and `purchase_difference` are empty for every send
  since this change (migration 0008 makes them nullable); the sends made before keep the driver's figures, and the API
  no longer shows them. `DayReopening` keeps the cash the office counted at the send a new load undid (the driver's own
  count for an older send), so `handed_over` stays the cash that went to the office.
- The office notification for a sent day no longer carries a gap; the admin's day overview shows the office count and
  its gap once counted; `unexplained_cash_differences` and the monthly check read the office gap of counted days.
- Provisional: a day can be reopened before the office counted it, and then nothing counts as handed over (the driver
  still holds the cash until the next count); the owner may prefer the count to be required at the send instead.
  Purchase money is counted only when expected (no purchase money = no purchase count needed).

**D-214 · A port purchase by a driver goes on the driver's truck, and shows on the day until the office checks it (changes D-176, D-158)** · accepted · 2026-10-31
- **Owner report (2026-10-31):** "when the driver pays for a product it should be in his stock", and the purchase did
  not appear in "Journées des chauffeurs" in the office app, although it needs the office's validation.
- **Where the goods go:** the office form defaulted the place to the first cold room, and the driver never chose one.
  `POST /my-field-purchases` now sets the place to the driver's truck of the purchase's day (`fleet.truck_of_driver`),
  so it is the place on the purchase when the office checks it, and the validated receipt goes into that truck's stock.
  A driver with no truck that day keeps no place: the office chooses, as before. The office may still change the place
  before validating. Goods still do not count in stock before the office validates (D-176, Q28).
- **Purchases on the day:** `purchasing.purchases_made_between` (the same span as the day's money, refused ones
  included). `day_activity` lists them as `purchases` (number, supplier, status submitted / validated / refused, total,
  cash given, time); the page's day dialog shows a "Achats au port" table linked to each purchase, and the day card shows
  the purchases' total and count (refused ones excluded from the count, as in the money).
- Provisional: the card shows no "to check" count yet; the status in the dialog is the only sign.
- Existing purchases sent before this change keep no place (the form still defaults them to the first cold room).
**D-215 · Supplier payment receipt PDF; several plan lines paid by one règlement (Phase 9, P9-T03c)** · accepted · 2026-10-31
- A new document kind `supplier_receipt` ("Paiement fournisseur N° RF-…"): the shared header with the supplier as
  the party, the means (number, bank, échéance of each effet), the invoices settled and the advance left; "ANNULÉ"
  on a voided one. PDF and e-mail buttons on the règlement's page. Rendered by `apps/purchasing/printing.py`.
- "Règlements fournisseurs": open plan lines get a tick box (one supplier at a time) and a bar "N lignes choisies ·
  total — Payer la sélection". The payment form then shows one means per plan line (its method, amount, reference,
  cashing day) and each amount on its invoice, and sends `plan_lines`; each line becomes `paid` (D-208).

**D-216 · The portfolio: remise en banque with a bordereau, encaissé, retirer, débité (Phase 9, P9-T04a)** · accepted (provisional parts marked) · 2026-10-31
- Trésorerie › Portefeuille (`/tresorerie/portefeuille`, side menu Finance › Portefeuille): every cheque and traite by
  where it stands, in tabs; filters (search, kind, bank, due days), totals of the filter with those late (échéance
  passed while in portfolio, at the bank or issued), a tick box per effet and the steps of the tab.
- A remise en banque is a `treasury.Deposit` "RB-2026-0001" (per organization and year, `TreasuryCounter`): the bank
  and the day, the effets in portfolio it takes ("Remis en banque", `Instrument.deposit`), a PDF bordereau (document
  kind `bank_deposit`) listing them with their total, opened right after. Provisional: the bank is picked from the
  banks list until T05 adds our bank accounts.
- Encaissé: from the bank, or straight from the portfolio (cashed at the bank's counter). Retirer de la banque brings
  an effet back to the portfolio; its bordereau keeps it listed and its history shows the step. Our effets: Débité.
  No balance moves on these steps (the règlement already counted, Q29); the impayé and the rejet come with P9-T04b.
- API: `GET/POST /treasury/deposits`, `GET /treasury/deposits/<id>`, `POST /treasury/instruments/cash|withdraw|debit`
  (`instruments`, `day`), `GET /treasury/instruments/totals`; filters `bank` and `deposit` on the list. Owner and
  manager write, the accountant reads. Each step is an `InstrumentEvent` and an audit entry; at most 200 effets at once.

**D-217 · An impayé is a new record: the customer owes again, the sales owe again beyond the credit (Phase 9, P9-T04b)** · accepted (provisional parts marked) · 2026-10-31
- "Impayé" on a customer cheque or traite at the bank, or already credited (the bank may take it back): the effet
  becomes "Impayé" and `sales.UnpaidEffet` (day, reason, amount, bank charges) is written. The règlement is never
  edited: it keeps its amount and lines.
- The customer balance adds the impayé back. Its règlement's credit left (not allocated) absorbs it first; the rest is
  taken back from the sales it settled, newest allocation first (`UnpaidRelease` rows), so those sales owe again
  (`amount_due` refreshed). The règlement then has less to allocate, and it can no longer be voided.
- The bank's charges, when given, become an approved expense "Frais financiers" paid by transfer on the impayé's day
  (provisional, Q29: re-invoicing them to the customer is not done). The office gets a notification `effet_unpaid`;
  the account history, the customer page and the statement PDF show the line "Effet impayé".
- After an impayé the paper is "Restitué" to the customer (`POST /treasury/instruments/return`); the customer pays
  with a new règlement. Re-presenting the same paper to the bank is not offered (it would need the impayé undone).
- API: `POST /customer-effets/<instrument_id>/unpaid` (`unpaid_on`, `reason`, `bank_charges`), owner or manager; the
  règlement's detail shows each line's `unpaid`. Endorsing to a supplier and our effets rejected move to P9-T04c.

**D-218 · Our rejected effet is a new record: the supplier is owed again, its invoices owe again beyond the advance (Phase 9, P9-T04c)** · accepted · 2026-10-31
- "Rejeté par la banque" on one of our cheques or traites still issued: the effet becomes "Rejeté" and
  `purchasing.RejectedEffet` (day, reason, amount) is written; the règlement is never edited.
- What was paid to the supplier leaves out the rejected amount: the règlement's advance left absorbs it first, then what
  it settled on invoices is taken back, newest allocation first (`RejectedRelease`), and those invoices go back to
  "partiellement payée" or "validée". The supplier balance, the invoice paid amount, advances and their automatic use,
  the règlements list and totals, and the supplier statement ("Effet rejeté") all read it. "Chèques et traites à venir"
  leaves rejected effets out. A règlement with a rejected effet can no longer be voided.
- We pay the supplier again with a new règlement. Re-presenting the same paper is not offered.
- API `POST /supplier-effets/<instrument_id>/reject` (`rejected_on`, `reason`), owner or manager; the règlement's
  detail shows each line's `rejected`.
- Endorsing a customer effet to a supplier is not built: it waits for the owner's answer (Q29).

**D-227 · Cold-room electricity: the month's estimate is typed, the real invoice counts as the month's expense (owner point 11, provisional parts marked)** · accepted (provisional parts marked) · 2026-10-31
- **Why:** the owner wants the month's cold-room estimate editable, and the real invoice entered in its own section; the
  real amount counts as the month's expense and the difference with the estimate is shown and booked as before (D-058).
- **Estimate:** new `expenses.ColdRoomEstimate` (one per organization and month, `amount` for all rooms). Typed by the owner or
  manager (`PUT /cold-room-estimate`, `set_cold_room_estimate`) for the current or an earlier month, positive, to the millime.
  While the month is not billed it replaces the copied daily rate: the rooms share it by weight (as a bill), each day's rate
  is its room's part / days. It is changed freely until the month's bill is approved, then frozen (the rates keep the daily
  amount used). Every change is audited (`cold_room_estimate.set`, before/after, optional reason).
- **Real invoice:** the existing electricity bill (one expense of category cold storage + its month). Its section is "Facture
  chambre froide réelle"; a draft is edited there; "Enregistrer et compter en dépense" approves it at once, so it counts in the
  month's expenses. Only approved bills count (unchanged).
- **Month view:** the estimate (typed or copied), the real total, and the difference (real minus estimate, `estimate_total`,
  `difference`, `estimate_typed`, `typed_amount`) are shown; the lots keep the correction line `cold_room_adjustment` = real
  minus the estimate in force at approval (unchanged mechanism, D-041/D-058).
- **Provisional:** (1) the real bill's approval is now the default button (drafts still possible), so a wrong approved bill is
  corrected by a new record, as before, not edited. (2) **Gap, open for the owner:** an estimate changed after a lot of that
  month was already closed (its cost frozen in the closing) leaves the closed lot on the old estimate, while the correction at
  approval uses the estimate in force then; the month's total can then differ by that change. Options: lock the estimate once a
  lot of the month is closed, or accept. (3) Not built: the bill's date and an invoice reference (the bill is dated the last day
  of the month, the reference goes in notes, as before). (4) Rounding: each room's daily rate is rounded to the millime, so the
  estimate charged to the lots can differ from the typed amount by a few millimes until approval (the correction absorbs it).
- Not touched: per-room weights and shares, the hour-by-hour split (D-142), treasury (no treasury posting in this change).

**D-221 · Every amount field shows thousands separators while the person types (owner point 3, 2026-10-31)** · accepted (provisional parts marked) · 2026-10-31
- Typing 1250 shows "1 250", 1250,5 shows "1 250,5", 1250000 shows "1 250 000" (the `formatMoney` French format).
  `MoneyInput` (`packages/ui`, on the `Input` element) does it; `typeMoney` does the same on a plain cell (the
  LinesGrid unit price, the receipt unit cost). Pure helpers `formatMoneyInput` and `moneyInputCaret` live in
  `packages/i18n/src/format.ts`, with vitest tests.
- The form state keeps the shown text, so `parseDecimalInput` reads it unchanged (spaces ignored, dot or comma). The API
  still gets the plain decimal string ("1250.500"). This replaces the D-199 note "what a user types stays as typed".
- The caret stays after the same digits and comma while the separators move. Backspace or Delete on a separator
  removes the digit beside it too.
- Changed: the money fields only (DT amounts and unit prices per kg). Kilos, percentages (VAT, CNSS, withholding,
  discounts, partner shares), temperatures, counts, days and months are not money and keep their inputs. The public
  site has no money field.
- The one place that rewrote a typed amount before sending it (the bank charges of an unpaid effet) removes the
  spaces first, so the API receives what it did before.
- Provisional: Arabic typing uses the French format too (the Arabic separators are not typed yet).
- Provisional: a second decimal separator is ignored ("1.250.000" shows "1,250000"); decimals are not cut, so a
  fourth decimal is still shown and refused by the parser as before.

**D-220 · Only the office corrects a driver's day, every correction is a revision; "La caisse" is off on a 0 DT day (owner list 2026-10-31, points 1 and 2; changes D-134's re-send, D-132, D-205)** · accepted, provisional parts marked · 2026-10-31
- **The driver never sends a sent day again when its records moved.** `submit_day_closing` raises 403 "Le bureau corrige
  la journée. Vous ne pouvez plus l'envoyer." for a submitted or justification day whose `changed_since_sent` is true.
  The re-send with no change (after a justification) and a reopened day (a new load, D-134) stay as they were. The phone
  shows the sent figures (`day_answer`: as sent unless the day reopened) and "Le bureau corrige la journée" in place of
  the send button.
- **The office corrects it, with a revision.** `POST /day-closings/<id>/correct` (owner or manager; `reason` required,
  optional `office_counted_cash` / `office_counted_purchase_cash`; an empty count stays) takes the day's records as they
  are now (`summary`, `expected_cash`, `expected_purchase_cash`), sets the counts and the gaps, and writes a
  `DayClosingRevision` (number per day, actor, reason, `before` and `after` as strings: the day's figures and the
  office's counts) plus the audit `day_closing.corrected`. A correction changing nothing is refused. The day's detail
  lists `revisions` (who, when, why, before and after) for the office's day window. Refused on a reopened day.
- **A saved count changes only by a correction** (`_refuse_recount`): counting, approving with counts, and recounting
  refuse a different figure than the one saved. The count inputs are disabled once counted.
- **Provisional:** a correction keeps the status: an approved day stays approved (the revision stands, no new
  approval), a day to check stays to check. The owner may prefer a correction to send the day back to the review.
- **Provisional:** the correction takes the records as they are now rather than typed figures: only the counts are typed.
- **"La caisse" on the phone and the server (owner point 2).** The day's accepted starting cash (`DriverDay.opening_cash`)
  of 0 DT, or no day started, turns "La caisse" off: the phone's expense "Payé avec" disables it and falls back to "Ma
  poche" (`cashOffOn`, `paidWithOn`), and `expenses.services.submit_road_expense` refuses a cash expense not paid by the
  driver with "« La caisse » n'est pas possible : …" on `paid_with` (400). This reverses the "always offered" part of
  D-205 for the expense only.
- **Provisional scope:** "La caisse" is the expense choice, the only one labelled so. Customer receipts (sales, payments,
  delivery cash) and purchases paid in cash from the purchase money (D-158) stay open: they bring money in, or are paid
  from the purchase float, not from the box. The owner may want the purchase cash and the receipts blocked too.
- **Provisional:** no day started counts as 0 DT (the office has not handed any cash yet), though D-133 accepts a sale
  with no day; a driver with no day pays with "Ma poche" or "Carte".
- Migration `dayclose/0009_dayclosingrevision`. API `correctDayClosing` (generated client). Tests:
  `dayclose/tests/test_day_correction.py`, `expenses/tests/test_road_expense_cash.py`, the phone's `expensePaid.test.ts`.

**D-228 · A salary is approved when it is generated; adjust it, then pay it (owner point 12, provisional parts marked)** · accepted (provisional parts marked) · 2026-11-01
- "Générer le mois" creates **approved** salary records (`approved_at`, `approved_by` set): no draft step any more.
  Drafts made before this change stay drafts and keep their edit, approve and delete actions (nothing creates new ones).
- An approved salary is corrected only by a `SalaryAdjustment` (signed amount, reason), then paid as before. The
  record never changes (ARCHITECTURE §4.5).
- The month's expense, the unpaid badges and the demo seed read approved records as before. The demo's night hours are
  now an adjustment "Heures de nuit" (the record is approved).
- **Not in this PR (waits for PR #246, treasury ledger, D-219, `ec` session):** the payment writing its treasury
  movement (`salary` kind, source `hr.salary_payment`) and the screen line "Débité de la trésorerie : N DT (compte, date)".
  No second ledger is built here; that line follows once `post_movement` is on `origin/main` (see D-229).
**D-219 · Treasury accounts and an append-only movement ledger; règlements and effets post to it (Phase 9, P9-T05a)** · accepted (provisional parts marked) · 2026-10-31
- `treasury.TreasuryAccount`: Caisse, bank account (bank, 20-digit RIB), a driver's cash (one per driver, made when
  first needed). Its balance is the opening balance plus its movements from the opening day on; older movements stay
  listed in the database but are not counted, so the office may set the real opening after the backfill.
  Provisional: every organization starts with "Caisse" and "Banque principale" (the owner's list of accounts is Q29).
- `treasury.TreasuryMovement`: (account, day, signed amount, kind, label, reference, source, source_id, role), never
  edited; unique per (source, source_id, role), so writing a record's movements again is a no-op. A correction is an
  opposite movement (role `void`).
- Who writes: customer règlement lines in cash, transfer, card (+; a line may name its account, else the Caisse for
  cash, the main bank account otherwise; cash a driver took on the phone goes to that driver's cash); supplier lines
  (−, same rule; our cheque or traite keeps the account the bank will debit). Effets: cashed (+ on the remise's
  account; cashed from the portfolio at the drawer's counter: the Caisse), impayé after cashing (− on the account
  credited), ours debited (− on its account, else the account of its bank, else the main one). A voided règlement
  undoes its movements on the day it is voided. Port purchases are left to P9-T05b (the driver's money).
- `AccountTransfer` "MT-YYYY-NNNN": versement (cash → bank), retrait (bank → cash), virement (any other pair), kind
  from the two accounts; annulé with a reason writes the two opposite movements.
- `CashCount` (arrêté de caisse) on a Caisse or a driver's cash: expected = balance at the end of the day, gap =
  counted − expected; a gap needs its reason and is written as a movement "Écart de caisse".
- `manage.py backfill_treasury` writes the history; the staging backend runs it at each start (idempotent).
- API under `treasury/accounts`, `treasury/accounts/<id>/movements` (+ `/export`), `treasury/transfers`,
  `treasury/cash-counts`; `account` on règlement lines and on `treasury/deposits`. Owner and manager write, the
  accountant reads.

**D-224 · A BL shows the VAT of the lines sold with VAT from the moment it is prepared (owner point 6)** · accepted, provisional parts marked · 2026-10-31
- **Snapshot on the lines:** `SaleLine.vat_rate` (empty = no VAT on that line) is set when the line is written: a draft
  created or changed, and the BL of a truck load at the load. It is the product's own rate, else the settings' rate in
  force on the sale's day, and only when the product is sold with VAT (`inventory.selectors.vat_product_ids`, D-202:
  kilos in stock bought with VAT). Later rate or price changes never move it.
- **One VAT computation:** each line's `amount_excl_tax`, `vat_amount`, `amount_incl_tax` come from `invoicing.compute`,
  the invoice's own arithmetic (`_apply_bl_vat`). The sale has `vat_total`, `total_incl_tax` and `prices_include_vat`
  (the settings' flag on its day); `Sale.amount_excl_tax` is total with VAT minus VAT. `Sale.total` and
  `total_excl_tax` keep their meaning (charged, without VAT).
- **Delivery (D-178):** the kept lines keep their rate and get their VAT recomputed on the kilos left.
- **Screens and PDF:** the BL PDF and the sale page show "TVA %" and "Montant TVA" per line, then "Total HT", "Total TVA",
  "Total TTC". A BL with no VAT line looks as before. The API sale and line carry the new fields as strings.
- **Existing sales:** no rate on their lines, so their BL shows no VAT; `total_incl_tax` is backfilled to `total`.
- **Provisional, the owner confirms:** the rule is D-202 (product of a lot bought with VAT, the stock at the moment the
  line is written), not per lot. The invoice is not changed: it still applies VAT to every line when "Facture avec TVA"
  is ticked (its default), so a mixed BL (VAT and non-VAT products) can invoice more VAT than its BL shows. Whether the
  invoice should follow the BL's lines is open.
- **Provisional:** "Reste dû" and the customer balance stay without VAT until the invoice (D-062): a BL with VAT shows
  its total with VAT but what is still owed is not yet computed with it.
- **Provisional:** with prices including VAT, the BL's unit price column still shows the price charged (with VAT) next to
  the amounts without VAT; the invoice shows the unit price without VAT. This setting is rarely used.
- Not changed: the sale form's live preview (no VAT computed in the browser; the VAT appears on the sale page after saving).

**D-223 · One numbering for every kind of number; the prefixes are set on Paramètres (owner point 5)** · accepted (provisional parts marked) · 2026-10-31
- One counter for all: `core.NumberSeries` (organization, kind, year; year 0 for kinds not restarted each year). Taken by
  `core.numbering.next_number` under the row lock, inside the transaction that saves the record, after every check: gap-free
  as before. The eight counter tables (sales, purchasing ×2, inventory ×2, expenses, hr, treasury) are dropped; their
  migrations (`sales/0026`, `purchasing/0017`, `inventory/0012`, `expenses/0007`, `hr/0004`, `treasury/0004`) copy each
  last number into `NumberSeries`, so no number is reused. The treasury account transfers' counter (`MT`, D-219, kind
  "transfer" in the old table) becomes the kind `account_transfer`, since `transfer` is the stock transfer.
- Kinds (`numbering.NUMBER_KINDS`): customer, supplier, employee, product, and every document (quote, sale, delivery note,
  invoice, credit note, customer payment, opening receivable, purchase order, receipt, supplier invoice, supplier payment,
  field purchase, batch, transfer, loss, count, expense, deposit, account transfer, salary payment). Default prefixes are the
  ones already printed (DV, VE, BL, FA, AV, RG, OUV, BA, BR, FF, RF, AT, L, TR, PE, INV, DP, RB, MT, PS; C, F, E), so nothing changes
  until the owner edits them (provisional: the partners stay C-001 / F-001 / E-001, not CL / FO).
- Yearly kinds restart at 1 each year (D-120): `FA-2026-0001`. The others: `BR-0001`, `C-001`.
- Product references are `ART0001`, four digits, no hyphen: the owner's article codes (D-126) use that shape. Provisional:
  the default prefix is ART, and the counter starts after the highest `ART` code in use (ART0060 gives ART0061).
- Paramètres › Numérotation (`/parametres/numerotation`, `GET`/`PUT /numbering`): one line per kind with its prefix, the
  default and the next number. A prefix is 1 to 6 capitals or digits, and no two kinds share one in the organization.
  Owner or manager writes, the accountant reads, drivers get 403. A changed prefix applies to the next number; the counter
  goes on. Audit `numbering.prefixes_changed`.
- Customers, suppliers, employees and products: the reference is generated on create when left blank
  (`numbering.next_free_reference`). The counter starts after the highest reference already in use under the current prefix
  (lazily at first use, and in the migrations `partners/0004`, `catalog/0006`, `hr/0005` for existing data). A reference
  typed by hand is skipped, never reused. A typed reference is kept: imports, the demo seed and the owner's codes
  (`set_product_codes`) are unchanged. The forms show the reference read-only (provisional: the API still accepts a
  corrected reference on update, for the owner's clean-up).
- Not converted: the public site's request numbers (`W-00012`, derived from the request id). The effets' own numbers are
  typed by hand (D-197).

**D-230 · The treasury screens take the Perfaxis layout: a ribbon of icon buttons on every treasury screen, a bordereau de versement with three columns, états des factures grouped by party; the process stays ours (Phase 9, P9-T08)** · accepted · 2026-11-01
- Owner request: the trésorerie module should look like the Perfaxis one (the ribbon, the grids, the bordereau de
  versement, the états des factures). The flow and the rules stay ours: effets, bordereaux, impayés and the ledger of
  P9-T01 to T04 are not changed, and no migration is added.
- `TresorerieRibbon` sits at the top of the screens Encaissement (`/reglements`), Décaissement (`/achats/paiements`),
  Banque, Portefeuille, Ordre de paiement (`/achats/reglements`), Bordereau de versement and the two états.
- Bordereau de versement (`/tresorerie/bordereau`): En attente (at the bank) · Encaissé · Impayé, with the same steps
  and dialogs as the Portefeuille. Facture de vente and Facture d'achat (`/tresorerie/etats/ventes`, `/achats`): the
  invoices grouped by customer or supplier, net à payer, réglé, restant, state, with totals.
- Not on the ribbon yet: Agence bancaire, Caisse liquide and the journals (journal des banques, journal des caisses).
  They need the treasury accounts of P9-T05, which are not merged. Excel export of the états is later.
- The sidebar is unchanged: the e2e spec lists the modules by name. The treasury is reached from Règlements clients,
  Règlements fournisseurs, Portefeuille and Banques.
**D-222 · The e-mail window sends to every address the party has, and the office can drop or add some for one send (owner point 4, 2026-10-31)** · accepted (provisional parts marked) · 2026-10-31
- The party's own address and each of its contacts' addresses are offered (`Customer.email_addresses()`,
  `Supplier.email_addresses()`: the party's first, then the contacts' in order; blank and repeated ones, case ignored,
  are dropped). Every provider of a PDF (sales, purchasing, the partner statement) fills `Printable.email_to` with them.
- The window ticks all of them. Unticking one or typing an extra one (several at once, separated by commas, spaces or
  semicolons) changes this send only; the party, its contacts and the stored addresses are not touched. An added
  address can be removed again before sending.
- One message goes to the ticked addresses in its `to` (no copy per address). The send accepts 1 to 10 addresses
  (the server refuses more, the window says so); the same address twice is sent once. The draft returns `to` as a list.
- Provisional: the list is shown with a checkbox row even when the party has one address (no separate one-address
  layout); the party's own page is not changed (its e-mail field and contacts feed the list). A party with one address
  works as before.
- Sent addresses are still kept as one text on `documents.SentEmail` (the history row).

**D-232 · Treasury forms take the Perfaxis panels; the états export as a CSV that Excel opens (Phase 9, P9-T08)** · accepted · 2026-11-01
- The Encaissement and Décaissement forms show a toolbar (Enregistrer, Retour) and two titled panels: the payment
  information (the date) beside the customer or supplier, the lines and the open items below. The logic is unchanged.
- "Exporter (Excel)" on the états writes the rows on screen as a CSV: `;` between cells, French decimal commas, a
  byte-order mark, so Excel opens it with accents right. Provisional: a real `.xlsx` would need a backend endpoint and
  a regenerated client; the CSV covers the need until the accountant asks for `.xlsx`.
- Export covers the invoices loaded on the page (the 200 most recent), as the screen does.
**D-231 · Several lots picked by hand on a load to a truck, and on any transfer from one place (owner request, 2026-10-31)** · accepted · 2026-10-31
- A transfer line may name lots, each with the kilos to take from it, as a counter-sale line does (D-212): `TransferLinePick`
  (one row per line and lot), written as `picks: [{batch, quantity}]` on `TransferLineWrite`, in the kept part and in each
  client's part of a load. Picks take their kilos in the order given, each up to what it holds; what they leave over
  comes from the other lots, oldest first (FIFO), and a picked lot short is topped up the same way. Stock never goes
  negative. Validation posts the line's picks first, then FIFO, through `inventory.services.post_fifo_movements`.
- It replaces the rule of D-009 that nobody picks batches by hand, for transfers too, as D-212 did for sales.
- Refused on the line: picks above the line's weight, a lot picked twice, a lot of another product or organization,
  a pick without kilos above zero, and any pick on a load from several cold rooms (D-174): the kg there come from
  whichever rooms hold them, so there is no one place to pick a lot from.
- The check is one function, `inventory.services.checked_lot_picks`, used by the counter sale and by transfers.
- Migration `inventory.0011_transfer_line_picks` creates the table. A draft's picks go with its lines when it is
  changed; a validated transfer keeps the movements that really moved.
- The transfer form shows the lot column on every line grid, lots of the place the kg leave from; with several cold
  rooms the column shows the oldest lots and cannot be picked.
- Provisional: the kilos the picks leave over come from the oldest lots only, as for a sale.

**D-233 · The bank and cash accounts and their journals are screens of the treasury: Agence bancaire, Caisse liquide, Journal des banques, Journal des caisses (Phase 9, P9-T08 follow-up to P9-T05a)** · accepted · 2026-11-01
- Agence bancaire and Caisse liquide list the accounts of their kind (`bank`, `cash`; the driver accounts stay on the
  phone and the expenses side). Add and rename, take off (not deleted: its movements stay). A bank account keeps its
  bank and RIB; a cash box can be counted (arrêté de caisse): the counted cash goes against the expected balance and
  the gap is kept with its reason.
- Journal des banques and Journal des caisses show one account's statement: the movements in order with the running
  balance, the opening and closing balances, a date range and a search. The Excel link is the server's statement file.
- Provisional: the screens use the P9-T05 API as it is; no backend change.


**D-225 · Motif on a supplier règlement; Motif and Payé par on a customer règlement (owner points 7 and 8, reglement-fields)** · accepted (provisional parts marked) · 2026-11-01
- Owner request: "in règlement fournisseur we need to have motif (optionnel)"; "in règlement client we need to have motif + payé par (optionnels)".
- `SupplierPayment.reason` and `CustomerPayment.reason` ("Motif", optional, max 200 characters); `CustomerPayment.paid_by`
  ("Payé par", optional, the person who handed the money over, max 120). Empty by default, nothing pre-filled. They are kept
  apart from `notes` (the existing "Note"), which stays as it was.
- Migrations `purchasing/0016_supplierpayment_reason` and `sales/0024_customerpayment_paid_by_customerpayment_reason` (add columns only).
- Written by `record_payment` and `record_customer_payment` (`reason`, `paid_by`, stripped), read back by the règlement
  serializers (lists, details, `POST` bodies: optional, `reason`/`paid_by` refused above their length). Audit snapshots carry them.
- Shown: a Motif column on both lists (hidden on a phone), a line on each detail page, and a line in the receipt PDF header
  (`sales/pdf/receipt.html`, `purchasing/pdf/supplier_receipt.html`). The driver app is unchanged (both fields default to empty).
- Provisional: the Motif is free text on the règlement only, not on its effets; the lists do not filter or export by it yet.
- Not touched: the règlement lists' filters and totals, the effets logic and the treasury app (D-210, D-211, D-215).

**D-236 · Bank details: SWIFT and address on the bank; RIB and IBAN kept once per organization; a Caisse is principale or secondaire (Phase 9, P9-T09a)** · accepted · 2026-11-01
- A bank has its SWIFT code (8 or 11 characters, spaces dropped) and its branch address; both optional.
- A bank account keeps its RIB (20 digits, as before) and its IBAN, written as the office's spec gives it: two letters,
  two digits, four characters, four digits, three digits (spaces allowed, dropped when saved). Neither the RIB nor the
  IBAN can belong to two accounts of the organization.
- A Caisse is principale or secondaire; the existing Caisses become principale. A bank account has no type.
- Provisional: the IBAN format is the one the office's spec shows (15 characters), not the 24-character Tunisian IBAN;
  to confirm with the accountant.
**D-226 · "Total à régler" on the party cards and in the règlement forms; a customer payment is the règlement page (owner points 9 and 10, reglement-fields)** · accepted (provisional parts marked) · 2026-11-01
- Owner request: "totale montant à régler in client/fournisseur"; "add payment for facture client should look like payment fournisseur".
- **Total à régler** = the balance still owed: customer `balance` (positive part), supplier `balance` (positive part). A credit
  (a customer's credit, a supplier's advance) shows as "Crédit du client" / "Avance chez le fournisseur" with its amount, and
  "Total à régler" stays 0. No fourth balance: supplier payables, partner capital and profit shares stay separate (D-040, D-197).
- **Same number on both screens:** `payments/toPay.ts` (`amountToPay`, `creditHeld`) reads the same endpoints (the customer
  balance and the supplier balance) on the party card and in the règlement form (a strip above the invoices: total, overdue,
  advance). The customer's "Encours" stays solde + effets received not cashed (D-210) and reads the same instruments query.
- Breakdown on the customer card (provisional): "Factures à régler", "BL sans facture à régler" (from the open items), "Crédit
  non affecté" when some credit is not yet allocated, effets en portefeuille and the encours. On the supplier card the
  breakdown is the existing one (outstanding, unallocated advance, overdue). Our effets issued are not added: they count as paid
  when given (D-208), so the supplier total needs no effets line (provisional; the "chèques à venir" list stays on Dettes).
- **Customer payment entry = the règlement page.** The quick window "Enregistrer un règlement" (`PaymentDialog`, one means, no
  lines, no "Répartir", no bar) is removed. "Enregistrer un règlement" on the customer card and the "Encaisser" button of
  the ageing table open `/reglements/nouveau?client=<id>`, the page the supplier payment uses: the same lines editor, the
  same "Répartir sur les plus anciennes échéances" button (the old "Affecter automatiquement" and "Tout effacer" are
  replaced by it), the same bar and the same confirm window. The customer rules stay: affectation to invoices and BL, the
  encours and credit-limit figures, advance as credit.
- Where this touches the other sessions' code: `payments/PaymentsPage.tsx` (the ageing button only; the règlements list, its
  filters and totals are unchanged), `customers/BalanceCard.tsx`, `purchasing/SupplierBalanceCard.tsx` and
  `purchasing/SupplierPaymentFormPage.tsx` (a figures strip added above the Motif field; the lines, Répartir and the
  confirm window unchanged), `payments/CustomerPaymentFormPage.tsx` (figures moved to `payments/Figure.tsx`). The treasury app,
  the effets logic and the lists' order are not touched.
- Provisional: the customer "Total à régler" keeps the old balance semantics (unchanged server side); the owner may want the
  encours shown as the headline instead.

**D-234 · Salary payments and primes/advances post to the treasury (owner points 12–13, provisional parts marked)** · accepted (provisional parts marked) · 2026-11-01
- **Why:** D-228 left the treasury movement of a salary payment and its "Débité de la trésorerie" line for later. The
  owner wants every salary paid to leave the treasury, and primes and advances on the salary record (points 12 and 13).
- **Treasury:** each `SalaryPayment` writes one outgoing movement in the same transaction as the payment
  (`treasury.post_movement`, kind `salary`, source `hr.salary_payment`, source id = the payment, day = `paid_on`, label
  "Salaire : <name>" or "Avance : <name>", reference = the PS number). Account: the Caisse for cash (`line_account`),
  the main bank account for a transfer, a cheque or another means. A payment is never edited or voided, so nothing
  reverses it.
- **Backfill:** `hr.services.post_treasury_history` writes the payments made before, skipping the ids already posted;
  `backfill_treasury` runs it, so running it again counts nothing twice.
- **On screen:** the payment and each payment line of a salary show "Débité de la trésorerie : N DT (compte <name>,
  <date>)", read from the movement (`treasury.selectors.movement_of_source`). A payment with no movement shows nothing.
- **Primes (point 13):** a prime is a `SalaryAdjustment` of kind `prime`: positive, with a reason. It raises what is due
  and needs no payment of its own. It is added to an approved salary only (the approved-record rule holds); drafts,
  which only remain from before D-228, keep their bonus field. The payroll list shows each adjustment and prime as a line
  (kind, amount, reason).
- **Advances:** a `SalaryPayment` of kind `advance` (code `advance`, label "Avance sur salaire") is allocated in full
  to the salary of its own month, in one allocation of the same amount. It reduces what is still due and writes its
  movement like any payment. Above what is still due it is refused with a French message unless `confirm_overpay` is
  set (refused by default). A payment with no allocation is still an advance in the old sense, allocated later.
- **Expense side unchanged:** the month's expense is still the approved salary (gross, employer CNSS, adjustments). An
  advance is a payment against that salary, not an extra expense.
- **Provisional:** (1) an advance paid in cash goes to the Caisse; (2) a prime needs no separate payment; (3) an advance
  above the month's due needs the confirmation flag; (4) a prime does not recompute the CNSS, as an adjustment does
  (D-228): the accountant to confirm whether primes are subject to CNSS; (5) the code `advance` (not `avance`) is a
  naming choice.
- **Built with:** migration `hr.0006_salary_payment_kinds_and_primes` (`kind` on payments and adjustments); API
  `POST salary-records/<id>/primes` (`addSalaryPrime`), `kind` and `confirm_overpay` on `POST salary-payments`, and
  `kind`, `treasury_debit` on payments and salary lines. The only change to the treasury app is one read selector,
  `movement_of_source`; no model or service changed.

**D-235 · The règlement lists show each customer's and supplier's documents: BL or BR, invoices and total (owner request, 2026-11-01)** · accepted (total provisional) · 2026-11-01
- "Nouveau règlement client" (client list) and "Nouveau paiement fournisseur" (supplier list) show, beside each name,
  how many BL (customers) or BR (suppliers), how many invoices, and their total. Zeros are shown too. The owner's
  "in bank" was read as these règlement pages, where the lists are.
- Counted: a customer's confirmed BL and issued invoices; a supplier's goods receipts (all) and its invoices (not
  drafts). Cancelled documents and drafts are not counted.
- Total (provisional): a customer's invoices' net to pay, as on the Documents page; a supplier's invoices' total. The
  BL are not added on top, since they are invoiced. What is owed stays on the balance and the encours.
- `GET /api/v1/treasury/party-documents` (`listPartyDocuments`): owner, manager and accountant; a party with no document
  is not listed (the screens show zeros). The counts do not move with payments, only with new BL, receipts or invoices.

**D-237 · The mandatory fields of the payment forms show a red outline (Phase 9, P9-T09b)** · accepted · 2026-11-01
- The date and the party of an encaissement or a décaissement are outlined in red, as the Perfaxis forms mark them
  (`required` on the input, the outline class on the field). The lines' fields are not outlined yet.
- Provisional: the outline shows from the start, not after a failed save.

**D-238 · Every approved expense is a treasury movement the day it was spent (Phase 9, P9-T05b)** · accepted · 2026-11-01
- An approved expense leaves an account on its spent-on day: the driver's cash when the driver paid in cash, else the
  Caisse for cash, else the main bank account. Nothing is written before approval; a refused or waiting expense moves
  no money.
- The approved expenses from before the ledger are written by `backfill_treasury` (once; safe to run again).
- Provisional: a cheque or a traite paid as an expense is counted at the main bank account on approval, not when the
  bank debits it, until the office decides how expense cheques are followed.

**D-239 · The money paid at the sale is a treasury movement the day of the sale (Phase 9, P9-T05b)** · accepted · 2026-11-02
- When a sale is confirmed, the amount paid at it goes in: the driver's cash when the delivering user is a driver and
  paid in cash, else the Caisse for cash, else the main bank account for a transfer or a card. Written once, dated the
  sale's day; a sale with nothing paid moves no money.
- A sale cancelled later keeps its money: what was paid becomes the customer's credit (the P2-T06 hook), so nothing is
  reversed. The customer's credit itself is not a movement yet.
- The sales confirmed before the ledger are written by `backfill_treasury`.
- Provisional: a cheque paid at the sale is counted at the main bank account on the sale's day; it is not followed as
  an effet until the office decides how cheques given at the door are tracked.

**D-240 · The money paid to a partner at a settlement leaves our accounts the day it is paid (Phase 9, P9-T05b)** · accepted · 2026-11-02
- Each payment of a partner settlement is a treasury movement, out of the account its method goes to: the Caisse for
  cash, the main bank account for a transfer, a cheque, a traite or another way. The three balances (capital, profit
  share, payables) are unchanged: only the money moves here.
- The settlements paid before the ledger are written by `backfill_treasury`.
- Provisional: a cheque or traite given to a partner is counted at the main bank account on its day, not followed as an
  effet issued (the office decides how these are tracked, as for supplier cheques).
- Not covered by a test yet: building a closed partnership lot in the test set-up is still to do.

**D-252 · Clearing a balance to zero: the rest is given up, as a loss on a customer or a gain on a supplier** · accepted · 2026-11-02
- Owner request: a customer owed 10 080 DT, paid 10 000 and the 80 DT left are never coming. The owner clears the
  customer's balance to zero; the amount is recorded as a loss on that customer (a `CustomerBalanceWriteOff`, shown on
  the customer's account with its reason and who did it). The same for a supplier we owe: the rest we no longer pay is
  a gain on that supplier.
- Two steps before anything is written: the reason (required), then the exact balance typed again. The server checks
  the typed amount against the balance at that moment and refuses a balance that moved, a balance that is not positive
  (nothing to clear, or credit held) and an empty reason.
- The amount is spread over the open sales (customers) or invoices (suppliers), oldest first, so those read as settled
  by it, and the balance (customer or supplier) falls by it. Records are never edited or deleted: a wrong clearance is
  to be corrected by a new record, not undone (not built yet).
- Owner only, enforced on the server (customers and suppliers).
- Provisional: the loss is kept on the customer and the gain on the supplier, but does NOT yet change the profit per lot
  or the profit shares (open question for the owner: should an uncollected balance reduce the lot's profit?). The
  supplier gain is not a treasury movement (no money moves).
- Provisional: the customer's clearance counts toward the credit-limit and encours figures as a settled amount (the
  balance falls, so the room to sell goes back up).

**D-251 · Each payment, sale and expense shows the account its money went through, linked to that account's journal (Phase 9, P9-T09c)** · accepted · 2026-11-02
- The payment, sale, expense and partner-payout screens show "Où est passé l'argent": one line per treasury movement the
  record wrote, with the account (Caisse, bank account or a driver's cash) and the day, linked to that account's journal.
  The journal opens on that account (`?compte=`).
- The account is read from the ledger (the movements of the record), not stored on the payment line: a line does not
  say which account it went through, the movement does.
- Provisional: the driver's cash has no journal page yet, so it is shown without a link.
**D-241 · One "Trésorier" entry in the side menu; the règlement and portfolio entries go into the treasury ribbon (Phase 9, P9-T08)** · accepted · 2026-11-02

- The side menu no longer lists Règlements clients, Règlements fournisseurs, Portefeuille or Banques. A single **Trésorier** entry (Finance group, where Banques was) opens the treasury at its first screen, Encaissement (`/reglements`); the treasury ribbon links every other screen (Décaissement, Portefeuille, Banque, Bordereau, Ordre de paiement, …).

- Only the menu entries move: the routes and pages stay, and the ribbon and the links in the pages still reach them. The Banks page keeps its name, "Banques", since it lists the banks; the ribbon button stays "Banque".

- Provisional: Trésorier lands on Encaissement; the menu item is lit on `/reglements` pages only (the menu lights the longest entry the path is under). If the owner wants a treasury landing page or the item lit on every treasury screen, that is a follow-up.

**D-242 · Sending the closing resets that driver's "Fonds de caisse" and "Argent pour les achats" to zero (owner request, 2026-11-02)** · provisional · 2026-11-02
- Sending the closing ends the day (D-134). At that moment the office's `DayFund` for that driver and date is set to 0
  for both amounts, audited as `day_fund.reset`. The row stays with its `accepted_at`, so the office still sees the day
  was started. Only that driver's row is touched.
- The day's own figures (`DriverDay.opening_cash`, `purchase_float`) and the sent closing are not changed: the closing
  keeps the start the driver had.
- A new load that reopens the sent day (D-134) does not bring the amounts back; the day runs on its own figures.
- Provisional: "day ends" is read as the closing being sent. If the owner means the office's approval, which comes
  later, the reset moves to `approve_day_closing`. The owner's peer PM confirmed this reading on 2026-11-02 (take the
  recommended option); the provisional status stays so the owner can move it.
**D-247 · Stock adjustment by hand: add or remove kilos of a lot; the average price is worked out again (owner request, 2026-11-02)** · accepted (provisional parts marked) · 2026-11-02
- An office adjustment is an `adjustment` movement (the existing kind, reason required) posted by `services.adjust_stock`:
  `POST /api/v1/stock/adjustments` (`adjustStock`) with a place, a lot, `add` or `remove`, kilos and the reason. Owners and
  managers only; the answer is the product's stock with its new average price. Screen: "Ajuster le stock" on the product
  page (`/stock/produits/:id`).
- The kilos added keep the lot's cost. The average purchase price is not stored: it is weighted by the kilos on hand, so it
  is worked out again from the ledger as soon as the adjustment is saved (no step to run). A removal is refused past what
  the place holds, like any movement.
- Provisional: the lots offered are those still on hand (a sold-out lot cannot be topped up: a receipt does that); no new
  cost is typed on an addition (the lot's cost is used, a different cost is a receipt); no owner approval step (unlike a
  loss above the threshold, D-045); the monthly closing counts an adjustment as spoilage, like a count correction.


**D-243 · An advance to the partner from the capital they put in a lot (owner request, 2026-11-02)** · accepted (provisional parts marked) · 2026-11-02
- The owner pays the partner an advance from the capital they put in a lot, from the lot's "Partenariat" section ("Donner une avance"). The request says "beneficiary": read as the partner, not the free-text payee of an expense.
- A `CapitalEntryKind.ADVANCE` entry (−) on the partner's capital ledger, with the means of payment and a reference (`method`, `reference`, the entry's date = the day paid). `services.advance_capital`, `POST /partnerships/{id}/advances` (`advancePartnerCapital`). Owner only, like every partnership write.
- Up to the capital still in: an advance never takes the capital below zero (D-031). Allowed while the lot is open or closed; refused once settled or cancelled.
- The settlement pays what is left: its `capital_returned` is the capital balance, already net of the advances, so the total paid is unchanged. The partner's period flows count an advance as capital returned.
- A capital correction (`update_partnership`) cannot take the capital below what was already advanced.
- Provisional: an advance on an open lot leaves less capital to cover a loss; the uncovered part is then owed by the partner (D-031). To confirm with the client.
- The money leaves our accounts the day it is paid, as a settlement payment does (D-240): a treasury movement out of the account its means goes to, kind `partner_settlement`, labelled "Avance". Provisional: the kind is shared with the settlements.

**D-253 · The bank's statement is imported from Excel as a copy, line by line, each line given to a customer or a supplier (Phase 9, P9-T09d)** · accepted · 2026-11-02
- On the Journal des banques, a bank account takes the bank's Excel file (columns DATE, LIBELLE, DEBIT, CREDIT and,
  optionally, SOLDE; a date is an Excel date or text like "03-janv-24"; amounts may have a decimal comma). All or
  nothing: one unreadable row, listed with its row number, and nothing is saved.
- A line already on the account (same day, label, debit, credit and balance) is skipped, so the same file twice adds
  nothing; two identical lines inside one new file are both kept.
- The lines are a copy of what the bank says (`BankStatementLine`): they move no money and change no balance of ours.
  The matching of a line with our own movements (rapprochement bancaire) is still to be decided with the accountant.
- A line at the debit takes a customer, a line at the credit a supplier (Perfaxis' "Tiers"); both can be cleared. A
  wrong import is fixed by removing lines (audited).
- Limits: 5 MB and 5 000 rows a file, as for the other imports.
**D-248 · The purchase money is set by the office only; the driver approves it when starting the day (owner request, 2026-11-02)** · accepted · 2026-11-02
- The money for purchases at the port (`DriverDay.purchase_float`) is typed by the office in "Camions du jour › Fonds de caisse"
  (`PUT /day-funds`). The driver approves it with the cash when starting the day (D-203, `POST /my-day`), then cannot change it.
- Removed: the driver's `PUT /my-day/purchase-float` (D-158's "typed again while the day runs"). The phone shows the amount
  with "Seul le bureau peut le modifier." and no edit control.
- The office changes the purchase money of a running day with `PUT /day-funds`. **Changed by D-260:** the change is a
  proposal the driver approves on the phone; it no longer takes effect at once. The accepted opening cash stays locked.
- Once the driver's closing is sent, the purchase money is locked for the office too (the day is kept as sent, D-134).
  The fund list reports `ended` for each row so the office screen locks the field.
- Provisional, superseded by D-260: the driver did not approve a change of the office during the day. D-260 now requires it.

**D-244 · A prime is paid when it is added, and its payment is a treasury movement (owner request, 2026-11-02)** · accepted (provisional parts marked) · 2026-11-02
- **Why:** a prime (D-234) raised what is due but was never paid by itself, so the treasurer's journal did not show it.
  The owner wants a payment method on the prime, and the money to leave the treasury like any salary payment.
- **Supersedes** D-234 provisional (2) "a prime needs no separate payment".
- **On the screen:** "Ajouter une prime" asks for the amount, the reason, the payment method (espèces, chèque, virement,
  autre; default espèces) and the payment date (default today). Saving adds the prime and pays it at once, in full.
- **Treasury:** the prime's payment is a `SalaryPayment` of kind `prime` (migration `hr.0007`), allocated in full to the
  salary the prime was added to, and writes one outgoing movement the same day: the Caisse for cash, the main bank
  account for a transfer, a cheque or another means. Label "Prime : <name>", kind "salary", reference = the PS number.
  The journal and the cash-flow report count it through the salary payment.
- **API:** `POST salary-records/<id>/primes` now takes `method` and `paid_on` (`PrimeWrite`, `addSalaryPrime`). A refused
  method, date or amount adds nothing: the prime and its payment are one transaction.
- **Treasury screens** refresh with the payroll screens after a prime or a salary payment.
- **Provisional:** (1) a prime paid by cheque or traite is counted at the main bank account on its day, not followed as
  an effet (as for salary cheques); (2) primes added before this change have no payment and stay out of the treasury:
  the office pays them through a salary payment, or the owner decides how to record them; (3) the prime does not change
  the CNSS (D-234, the accountant to confirm).

**D-250 · The withholding is taken on every invoice of 1 000 DT and more, and on none below (owner rule, 2026-11-02)** · provisional · 2026-11-02
- The server decides: an invoice whose **total TTC** (HT + VAT + stamp + fees) reaches 1 000,000 DT carries the
  retenue à la source at the rate in force; below it, none, whatever the rate typed. The "withholding" checkbox is
  gone from the invoice form (the API input `withholding_applied` too; the output still says whether one applies).
- The withholding base is unchanged: (HT + VAT) × rate, stamp and fees left out (D-057). The fees can take an invoice
  over 1 000 DT without entering the base.
- Provisional: the base of the threshold is the total with tax as printed (stamp and fees in). The accountant confirms
  whether the threshold is on the total with VAT only, which would exclude the stamp and fees.
- The rate stays in Paramètres financiers (0 by default): with a rate at 0, a 1 000 DT invoice shows no line. The
  owner sets the rate.
- Issued invoices keep what they had (D-057); a draft takes the rule when it is next saved.

**D-249 · The office checks a driver's day before approving it: expenses, purchases, the truck's stock and boxes (owner list 2026-11-02, items 1 to 4)** · provisional · 2026-11-02
- **Where:** the day's check sits in the closing window ("Clôtures à vérifier") and in "Suivi des chauffeurs", as the
  component `DayReview`. It reads `GET /day-overview/<id>` (new `owns_truck`, `stock`, `boxes`, `review_blockers`).
- **Expenses (item 1):** each driver expense of the day is approved or refused from there
  (`POST /day-overview/<id>/expenses/<expense>/decide`, a refusal needs its reason). Only the day's own expenses (typed by
  its driver, dated in its window).
- **Purchases (item 3):** a purchase made on the day is counted on the truck as bought ("Acheté, à valider" kilos in the
  stock table). The office validates it with one button (`POST …/purchases/<purchase>/validate`, the same validation as
  the purchase page: its kilos enter the truck's stock). A purchase missing its supplier, product or place is refused
  with the reason; the office completes it on the purchase page.
- **Stock and boxes back to the cold room (items 2 and 4):** one button, "Remettre le camion en stock", posts a return
  transfer of everything the truck holds (kilos and boxes) to the first active cold room, validated at once
  (`POST …/return-to-stock`). It works whether or not the driver sent the day. Provisional: the cold room is the first
  active one by id (no choice on the button yet).
- **Only the truck's latest day owns its stock:** `fleet.latest_day_on_truck`. On an earlier day the stock and boxes are
  not shown and cannot be returned (they belong to a later day), and they do not block its approval.
- **Approval is refused** while the day still has an expense to approve or refuse, a purchase to validate or refuse, or
  (on the truck's latest day) kilos or boxes in the truck. The reason shows on the closing (`review_blockers`).
- **A sent day moved by the office's decision is corrected, not re-sent:** refusing an expense or validating/refusing a
  purchase that changes the figures calls the existing correction (D-220) with the reason, so the revision shows who and
  why. A return changes no figure of the day (it happens after the send), so it creates no revision.
- Also: a transfer may carry only boxes (no product line), needed for the truck that gives back its boxes alone.
- Not done: the "Caisses" supplier side is the boxes the day's purchases brought (a count, not an owed balance per supplier);
  choosing the cold room for the return; the owner may prefer approval to ask for a reason instead of blocking.
- Migration: none. Tests: `dayclose/tests/test_day_review.py`.
**D-246 · The invoice's "Facture avec TVA" is checked only for goods bought with VAT (owner request 2026-11-02)** · provisional · 2026-11-02
- A new invoice from BL takes VAT only when one of its BL took kilos from a lot bought with VAT (D-202); for every other
  product the box starts unchecked. Before, every invoice started with VAT.
- The default is decided by the server (`apply_vat` left empty on `POST /invoices`; the same rule when a draft is changed
  without the box sent keeps the draft's own choice). The box can still be checked or unchecked by hand on the draft.
- The refusal of an invoice without VAT on VAT-bought goods (D-202) is unchanged.
- The "Achat avec TVA" box on a receipt (D-202) already starts unchecked and is not changed.
- Provisional: the rule is read from the lots, so a mixed BL with one VAT-bought product is invoiced with VAT as a whole.

**D-256 · A BL paid before it is invoiced: the VAT and timbre still to come are shown, then collected or given up (owner request 2026-11-02, P9-T10)** · provisional · 2026-11-02
- Problem: a BL holds only its goods (HT); the VAT, timbre and withholding live on the invoice (D-057), shared back over the BL when
  it is issued (D-101). A BL paid at HT therefore turned unpaid again for the VAT and timbre, and nothing said so.
- **Estimate before invoicing.** A BL's règlement line shows "Reste estimé à l'émission": VAT per line and the timbre. It uses the
  invoice's own engine in a no-save simulation, so it follows the same rules (the VAT only on goods bought with VAT, D-202/D-246;
  a product or lot without VAT gives a timbre-only estimate; each rate on its own row). The timbre is once per invoice, so on a BL
  it reads "une seule fois par facture" and is never added once per BL.
- **"Régler TTC"** box on the règlement line (off by default): sizes the amount on HT + estimated VAT + timbre.
- **At issue.** The invoice is "Payée" only when what is allocated on all its BL equals its net to pay. Otherwise it reads "Payée
  en partie: reste X DT (TVA a, timbre b)". Several BL: one comparison per invoice; an overpayment on one BL covers a shortfall on
  another, and the gap is shown once. A mixed group (some BL paid, some not) only warns, it is never refused.
- **The gap is collected by default**: one new règlement for the difference, allocated by BL share. **Giving it up** reuses D-252
  (the rest cleared to zero as a loss), owner only, with a reason; it is recorded, nothing is edited.
- **Seen afterwards**: "Écart de facturation" on the invoice and BL (goods, VAT, timbre paid or missing); a "BL payé, facture non
  soldée" filter on Ventes and a line on the customer statement. All in the audit trail.
- **Not done / open**: a "no timbre" flag per customer (no rule known; ask the accountant); the BL's own receivable stays HT.
- Provisional: collect by default, give up only by the owner; warn, never refuse, a mixed group.

**D-260 · A change of the purchase money during the day waits for the driver's approval on the phone (owner answer, 2026-11-02; changes D-248)** · accepted (provisional parts marked) · 2026-11-02
- The office changes the money for purchases of a running day in "Camions du jour › Fonds de caisse" as before. It becomes a
  proposal (`fleet.PurchaseFloatChange`, pending) and does not change the amount in force. The office list shows
  "En attente du chauffeur : X".
- The driver sees the proposal on the phone's day, with the amount in force and the new amount, and approves it with
  "J'accepte ce montant" (`POST /my-day/purchase-change/approve`). Only approval; the driver cannot edit the amount
  (no PUT, no field). A driver who disagrees calls the office, as before (D-203).
- **The record:** the proposal keeps the amount before and the amount proposed, who proposed it, and, once approved, who
  agreed and when (`decided_by`, `decided_at`), with its status: pending, approved, replaced, or expired. The audit log keeps
  `driver_day.purchase_float_proposed`, `…_withdrawn` and `…_approved`.
- A new proposal replaces the pending one, which stays as "replaced". Proposing the amount in force again withdraws the
  pending proposal. One pending proposal per day (database constraint).
- **What the driver can spend until they approve (recommended, provisional):** the amount in force. A raised amount cannot
  be spent until approved, and a lowered amount does not apply until approved either, so the driver is never cut off in the
  middle of the day without agreeing. Purchases and the cash split (D-158, D-182) use the amount in force only.
- Sending the closing before the driver approves expires the proposal ("Non approuvé avant la clôture"); the day keeps the
  amount in force, as sent (D-134). After the closing, the office cannot change the money for purchases of that day.
- Approval changes the amount in force and the day's fund figure at once. The phone refreshes the proposal every minute,
  and only on the day screen; the purchase notice on every screen (D-158) is for validated purchases only.
  Provisional: the owner may want a notice on every screen, or a refusal button.
