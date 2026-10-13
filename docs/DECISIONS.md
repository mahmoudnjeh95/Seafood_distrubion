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
  each day's amount split over the lots in stock that day by kg held (provisional: our reading).
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
- Charge to lots (**Q21 provisional**): each month part / 26 per day, each day split over the lots in stock
  anywhere that day by kg held (end-of-day ledger balance); days with nothing in stock charge nobody. Only
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
