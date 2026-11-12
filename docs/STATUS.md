# Project status

_Last updated: 2026-11-11 (integration of the eight open PRs #343 to #350 on `claude/confident-mayer-8rb73t`, D-322; next free decision D-324)_

## Where we are

- **P6-T08c1 merged (#352, D-323, migration `partnerships 0005`):** a partnership points to its lot and lists the
  products it shares (today its one batch). No change in results. Next: T08c2 + T08d in three PRs, plan written in
  `docs/phases/06-profit-sharing.md` under T08c2 (partnership result, then several lines and partners, then screens).

- **Integration branch (owner 2026-11-11, "stage all of them"):** PRs #343 to #350 are merged into
  `claude/confident-mayer-8rb73t`, not into `main`. Conflicts were "keep both" entries in `access.py`,
  `SettingsPage.tsx`, `DECISIONS.md` and `STATUS.md`. Two migrations numbered `sales 0037` met: the public-buyers one
  is now `sales 0038_vat_withholding`. Checks run locally: `makemigrations --check` clean, ruff, format, import-linter,
  mypy, eslint, prettier, typecheck, vitest all pass, and the full backend pytest suite passes (1 881 tests).
- **Checks on this branch:** the security test found two access gaps, fixed in D-322: the lot page is owner and
  accountant only, and the e-invoicing settings are owner-only writes in the test list. The mypy error in
  `sales/services.py` (public buyers, withholding) is fixed by an explicit `is not None` check.
- **Not done:** CI cannot start jobs (GitHub billing; PR bodies say so), so none of these have a CI result. The
  Smartfeesh repo `mahmoudnjeh95/smartfeesh` is not visible to this session's GitHub access; D-321 names
  `SmartToolsAgro/SmartFeesh` for deploys, which this session also cannot reach.

## Open PRs and the decision numbers in their files

| PR | Task | Decision | Migration |
|---|---|---|---|
| #343 | Period lock (P11-T16) | D-315 | `core 0009` |
| #344 | Cash limit on expenses (P11-T11) | D-316 | — |
| #345 | Assistant IA screen, voice (P12-T06) | D-314 | `assistant 0002` to `0004` |
| #346 | Supplier tax regime (P11-T10) | D-319 | `partners 0009` |
| #347 | One purchase is one lot (P6-T08a) | D-320 | `inventory 0017` |
| #348 | Public buyers keep VAT (P11-T09) | D-313 | `partners 0010`, `sales 0038` |
| #349 | Lot page (P6-T08b) | D-320 | — |
| #350 | E-invoicing settings (P11-T05a) | D-310 | `sales 0037` |

The PR bodies still show the numbers they were written with (D-310 to D-313, D-320, D-321); the table is right.

## Next step

0. **Owner:** decide whether this integration branch goes to `main`. Merge order if so: #350, #343, #344, #346, #348,
   #345, #347, #349. Also fix GitHub billing so CI runs on the PRs (D-297).
0. **P11-T05b to d (e-invoicing):** blocked on the owner's documents (Q18): TTN enrolment, sandbox access, the TEIF
   specification and XSD, the TunTrust certificate (password only in the server's `.env`).
0. **Phase 11 next, in order:** T02, T08, T07, T13, T12, T17, T21, T20, T03, T04, T05 (provisional values in per-company
   settings, marked "à confirmer"). T06 is the accountant's session.
0. **Phase 12:** P12-T02 (write tools with confirmation), then T05 (section `assistant` in the roles matrix).
0. **Lot page (P6-T08c to e):** partnerships on the lot, the netted shared result, closing and statements.
0. **Staging checks** for the merged work are in each phase file under "Check on staging".

## Open owner decisions

- Q18 (e-invoicing documents), Q29 (invoice paid on effet receipt or cashed), the accountant's "à confirmer" points
  (D-313, D-316, D-319).
- D-234 (provisional): an advance above the month's due needs a confirmation.
- Backups off-site and the private key (D-139); D-206 SMTP account in the server `.env`.

## Blockers

- GitHub Actions starts no job (billing), so no PR can go green.
- Smartfeesh (`mahmoudnjeh95/smartfeesh`) is not reachable from this session.
- DNS and certificate for `app.` and `ch.`, and the Sentry DSN, remain owner actions (D-155, D-140).
- Staging VPS is shared: touch only `frutti-staging`; `sudo nginx -t` before reload; never prune Docker.
- Keep generated API files in sync (`make gen-api`); preserve each branch's i18n keys when merging.
