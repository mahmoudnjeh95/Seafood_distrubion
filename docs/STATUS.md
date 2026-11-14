# Project status

_Last updated: 2026-11-14 (P6-T08 PR 1, partnership result, D-325; next free decision D-326; D-330 is taken by global search)_

## Where we are

- **Phase 13 usability (owner 2026-11-13, `docs/phases/13-usability.md`):** P13-T01 global search (Ctrl+K, D-330)
  merged (#355). Next: P13-T02 standing orders. The multi-product lot (P6-T08 PR 1
  to 3) is being built by the session "P6-T08 PR 1: partnership result (netted)".

- **Main has the integration of #343 to #350** (#351, D-322). PRs #344, #346 and #348 are still open but their work is
  in `main` through #351.
- **P6-T08c1 merged (#352, D-323, migration `partnerships 0005`):** a partnership points to its lot and lists the
  products it shares (today its one batch). No change in results. Next: T08c2 + T08d in three PRs, plan written in
  `docs/phases/06-profit-sharing.md` under T08c2 (#353).
- **P6-T08 PR 1 · Partnership result (D-325, migrations `closing 0003`, `0004`, `partnerships 0006`):**
  `closing.PartnershipResult` freezes each partnership's rate on the sum of its lines when its last line closes;
  reopen, late drift, book and settle work per partnership; ledgers carry `partnership_result_id`; old results
  migrated one line each. Existing closing tests pass unchanged; golden tests in
  `closing/tests/test_partnership_result.py` (950 on shrimp +2 400 / squid −500 at 50 %; Ali 400, Salah 300, owner 300
  at engine level). No API or screen change.
- **Next: PR 2** (plan in `docs/phases/06-profit-sharing.md` under T08c2, item 2): `create_partnership(lot, lines)`,
  checks on rates and capital per line, drop `one_live_partnership_per_lot`, transformation joins the partnerships,
  API `lot` + `lines`, `make gen-api`; then the two-partner golden test on real records. Then PR 3 (screens, PDF).
- **P12-T06b (D-324):** the owner's Tunisian was not understood by the browser's dictation. With `AZURE_SPEECH_KEY`
  and `AZURE_SPEECH_REGION`, the micro records and Azure recognises the question (`POST assistant/chat/dictation`,
  `ar-TN`/`fr-FR`) in every browser. Without the key the browser's recognition stays. `manage.py check_speech`
  checks a new key. No live Azure call was made (no key in the session), no browser test run.
- **Owner:** create the Azure Speech resource (free tier F0), put the key and region in the staging `.env`,
  redeploy, run `check_speech`, then "Check on staging (T06)" step 2b in the phase 12 file.

## Next step

0. **Owner:** the Azure key (above), and a PR for `claude/vigilant-dirac-wnt3pw` when wanted. Fix GitHub billing so CI
   runs on the PRs (D-297).
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
