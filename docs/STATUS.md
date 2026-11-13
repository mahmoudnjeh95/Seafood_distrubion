# Project status

_Last updated: 2026-11-13 (P6-T08 PR 1, partnership result, D-325; next free decision D-325)_

## Where we are

- **P6-T08 PR 1 · Partnership result (D-325, migrations `closing 0003`, `0004`, `partnerships 0006`):**
  `closing.PartnershipResult` freezes each partnership's rate on the sum of its lines when its last line closes;
  reopen, late drift, book and settle work per partnership; ledgers carry `partnership_result_id`; old results
  migrated one line each. Existing closing tests pass unchanged; golden tests in
  `closing/tests/test_partnership_result.py` (950 on shrimp +2 400 / squid −500 at 50 %; Ali 400, Salah 300, owner 300
  at engine level). No API or screen change.
- **Next: PR 2** (plan in `docs/phases/06-profit-sharing.md` under T08c2, item 2): `create_partnership(lot, lines)`,
  checks on rates and capital per line, drop `one_live_partnership_per_lot`, transformation joins the partnerships,
  API `lot` + `lines`, `make gen-api`; then the two-partner golden test on real records. Then PR 3 (screens, PDF).

- **Integration branch (owner 2026-11-11, "stage all of them"):** PRs #343 to #350 are merged into
  `claude/confident-mayer-8rb73t`, not into `main`. Conflicts were "keep both" entries in `access.py`,
  `SettingsPage.tsx`, `DECISIONS.md` and `STATUS.md`. Two migrations numbered `sales 0037` met: the public-buyers one
  is now `sales 0038_vat_withholding`. Checks run locally: `makemigrations --check` clean, ruff, format, import-linter,
  mypy, eslint, prettier, typecheck, vitest all pass, and the full backend pytest suite passes (1 881 tests).
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
0. **Lot page (P6-T08):** PR 2 (several lines and partners, API), then PR 3 (receipt form, lot page, statement PDF).
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
