# Runbook

How to operate the running system. Keep it short and true; update it when a procedure changes.

## Staging (OVH VPS 217.182.205.137)

| What | Where |
|---|---|
| Admin app | https://app.fruttidelmare.com (D-155) |
| Driver app | https://ch.fruttidelmare.com (D-155) |
| Public site | https://www.fruttidelmare.com (D-186); https://fruttidelmare.com redirects to it |
| Logins | `owner`, `driver`. Created by hand, never by a deploy: a deploy does not seed data. After the client start below, new passwords and no demo data |
| Server login | `ssh debian@217.182.205.137` (key `~/.ssh/id_ed25519_erp_prod` on Mahmoud's machine) |

**Shared server.** The VPS also runs other clients' production sites (Sonalim, TRT, dossipv, smartgreen)
behind one nginx. Frutti only owns: the Docker project `frutti-staging` (containers `frutti-staging-*`,
volumes `frutti-staging_pgdata` and `frutti-staging_media` (product photos)), the folder `~/frutti-staging`, and the nginx site
`/etc/nginx/sites-available/frutti-staging` (ports 8095 and 8096; the bare address redirects to the app's host name, D-036),
and the backup line of the `debian` user's crontab (see "Backups"). Never edit, prune or restart anything
else there. Always run `sudo nginx -t` before reloading nginx.

### Deploy

From a clone with SSH access: commit, then `make deploy-staging` (or `bash deploy/deploy.sh`). It sends
the committed code (never uncommitted changes) to `~/frutti-staging/releases/<time>-<commit>`, builds the
images on the server, starts the stack (migrations run at backend start), installs the nginx site if it
changed (test, reload, roll back on failure), checks health on both ports. A deploy never seeds or changes data.
The last 3 releases and their images are kept.

CI deploys automatically after every green push to `main`, once these GitHub secrets exist
(Settings → Secrets and variables → Actions):

- `STAGING_KNOWN_HOSTS`: output of `ssh-keyscan -t ed25519 217.182.205.137`.
- `STAGING_SSH_KEY`: a private key **made only for this** (`ssh-keygen -t ed25519 -f frutti_ci_deploy -N ""`),
  whose public key is added to `~debian/.ssh/authorized_keys` on the server.

**Where the deploy runs (D-209, 2026-10-31).** Work happens on `mahmoudnjeh95/Seafood_distrubion` (PRs, CI).
The organisation copy `SmartToolsAgro/SmartFeesh` follows it and is **the only repo that deploys**: after every
merge, push `main` there as a fast-forward (`git remote add org https://github.com/SmartToolsAgro/SmartFeesh.git`
once, then `git push org origin/main:refs/heads/main`); its CI tests again and deploys. Staging does not change
until that push. Only one repo may hold the secrets: two deploys at once overload the shared server (#216).

The SmartFeesh key (`frutti-ci-deploy-smartfeesh`) is in `~debian/.ssh/authorized_keys` with the `restrict`
option (no tunnels, no terminal); the file before it is `authorized_keys.bak-before-smartfeesh`. The first key
(`frutti-ci-deploy`, 2026-10-10, previous file `authorized_keys.bak-before-frutti-ci`) belongs to the personal
repo; it is revoked by deleting its line on the server and the two secrets of the personal repo.
To revoke a key, delete its line and the GitHub secret. Limit to keep in mind: the deploy runs uploaded code
with sudo, so whoever holds the secret is effectively root on a server shared with other clients. The real
fix is a separate server, or a server that pulls only code already on `main` from GitHub.

### Domain and HTTPS (D-155)

The names are `app.fruttidelmare.com` (admin app) and `ch.fruttidelmare.com` (driver app), both pointing at 217.182.205.137.
Phase 1 (plain HTTP, the names, the challenge webroot) and phase 2 (certificates, HTTPS) are separate deploys.
Phase 2 is merged only after the certificate exists: the deploy stops before it changes anything when the
certificate is missing.

**Owner, at the domain registrar (DNS for fruttidelmare.com):**

1. Add an `A` record: name `app`, value `217.182.205.137`, TTL 3600 (or the default).
2. Add an `A` record: name `ch`, value `217.182.205.137`, TTL 3600.
3. Do not change existing `MX` or `TXT` records (e-mail); only add these two.
4. Wait until both names answer: `nslookup app.fruttidelmare.com` and `nslookup ch.fruttidelmare.com` show
   217.182.205.137 (can take up to a few hours).

**Phase 1, from the repo (after the DNS answers):**

1. Commit and merge the phase 1 change to `main`; CI deploys it. Check `gh run list` for the deploy, then
   `curl -sS http://app.fruttidelmare.com/api/v1/health` and the same for `ch.`.
2. Still on the server: `sudo nginx -t`.

**Phase 2, on the server (one time, as `debian`; only Frutti's names are touched):**

1. Check the tool: `certbot --version`. If missing: `sudo apt install -y certbot`.
2. Issue both certificates through the webroot (nginx itself is not changed by certbot):
   ```bash
   sudo certbot certonly --webroot -w /var/www/frutti-acme \
     -d app.fruttidelmare.com -d ch.fruttidelmare.com \
     --cert-name frutti-staging --deploy-hook "/usr/sbin/nginx -t && /bin/systemctl reload nginx" \
     -m <owner e-mail> --agree-tos --non-interactive
   ```
   One certificate with both names, under `/etc/letsencrypt/live/frutti-staging/`. The deploy hook is stored with the
   renewal, so the automatic renewal reloads nginx. Check: `sudo certbot renew --dry-run`.
3. Then the phase 2 PR is merged (nginx 443 blocks with these certificate files, port 80 redirects to https,
   HTTPS settings on in `compose.staging.yml` with HSTS at 300 seconds, https origins in `remote-deploy.sh`). CI deploys.
4. Check: `curl -sS https://app.fruttidelmare.com/api/v1/health` and the same for `ch.`; log in on a phone.
5. After a week on https without trouble, raise `DJANGO_SECURE_HSTS_SECONDS` in `compose.staging.yml` to 2592000
   (30 days) in a small PR.

**Public site names (D-186).** `www.fruttidelmare.com` and the bare `fruttidelmare.com` point at the same server.
The deploy adds both to the `frutti-staging` certificate by itself the first time (`remote-deploy.sh`, step 3b,
webroot through the port-80 block of the host nginx site). If it printed a warning, run it by hand:
```bash
sudo certbot certonly --webroot -w /var/www/frutti-acme --cert-name frutti-staging --expand \
  -d app.fruttidelmare.com -d ch.fruttidelmare.com -d www.fruttidelmare.com -d fruttidelmare.com \
  --deploy-hook "/usr/sbin/nginx -t && /bin/systemctl reload nginx" --non-interactive --agree-tos
sudo nginx -t && sudo systemctl reload nginx
```
Check: `curl -sS https://www.fruttidelmare.com/api/v1/site/catalog | head -c 200`.

Do not run `certbot --nginx`: it rewrites the Frutti site file, which the next deploy replaces.

### Look at it

```bash
ssh debian@217.182.205.137
sudo docker ps --filter name=frutti-staging
sudo docker logs --tail 100 frutti-staging-backend-1
cd ~/frutti-staging/releases/$(ls -1t ~/frutti-staging/releases | head -1)/deploy
sudo docker compose --project-name frutti-staging --env-file ~/frutti-staging/.env -f compose.staging.yml exec backend python manage.py shell
```

### Stock check

Every night just after 03:00 UTC the `frutti-staging-nightly-1` container compares the stock on hand
with the movement ledger (D-038); see `sudo docker logs frutti-staging-nightly-1`. A difference is
logged as an error. After understanding it, repair from the ledger with
`... exec backend python manage.py rebuild_on_hand` (same folder as above); `--check` only reports.
Every `--check` records its result, which the uptime watch reads (see "Monitoring").

### Roll back

Redeploy an older commit: `git checkout <commit> && make deploy-staging`, then come back to your branch.
Migrations are not reversed automatically.

### Secrets

`~/frutti-staging/.env` (mode 600) is created on the first deploy with random values: database password,
Django secret key, allowed host and CSRF origins, and an empty `SENTRY_DSN`. Edit it on the
server, then redeploy. It is never in the repository. Deleting it would change the database password and
break the existing database.

### Monitoring

What is watched (D-140):

| What | How | Alert |
|---|---|---|
| Admin app, driver app, public site, API | `.github/workflows/uptime.yml`, every 15 minutes | the run fails, GitHub e-mails |
| Nightly stock check | `/api/v1/health/stock-check` read by the same workflow | same |
| Errors in the API and both apps | Sentry, once a DSN is set | Sentry e-mails |

**How the e-mail reaches the owner.** A failed scheduled run is e-mailed by GitHub to the account that owns the
schedule: the one that merged the workflow to `main`, or that last changed its `cron` line (if the workflow is
turned off and on again, the one that turned it on). That account must keep e-mail on for Actions (GitHub →
Settings → Notifications → Actions: e-mail, failed workflows only). While something stays down, every run (every
15 minutes) e-mails again: fix it, or pause the watch with `gh workflow disable uptime.yml` (and `enable` after).
GitHub **turns scheduled workflows off after 60 days without activity in the repository**; it e-mails a warning
first. To turn it back on: Actions → Uptime → "Enable workflow", or `gh workflow enable uptime.yml`. Run it by hand
any time: Actions → Uptime → "Run workflow", or `gh workflow run uptime.yml`.

**When the alert fires.** Open the failed run (Actions → Uptime): each failed check is an error line.

- *Admin app / Driver app / API is down:* `curl -sS https://app.fruttidelmare.com/api/v1/health` from
  any machine. If it does not answer, log in (see "Look at it"): `sudo docker ps --filter name=frutti-staging`
  (a container restarting?), `sudo docker logs --tail 100 frutti-staging-backend-1`, then
  `sudo systemctl status nginx` (read only: nginx is shared, never restart it for us; `sudo nginx -t` before any
  reload). A failed deploy shows in `gh run list --workflow ci.yml`; roll back as below. A single failed run that
  passes on the next one is usually a network blip: watch the next run.
- *Nightly stock check failed:* the check found a difference between the stock on hand and the ledger (or
  crashed). Read `sudo docker logs frutti-staging-nightly-1` for the lines, understand them (see "Stock check"),
  repair with `rebuild_on_hand`, then run `rebuild_on_hand --check` once: that run clears the state.
- *Nightly stock check late or never:* no check for 26 hours. The `frutti-staging-nightly-1` container is probably
  stopped or looping on an error: `sudo docker ps -a --filter name=frutti-staging-nightly` and its logs. A redeploy
  restarts it, and it checks once at start.

**Sentry (errors).** No Sentry project exists yet; until there is one, nothing is sent. To turn it on:

1. Create a free Sentry project (platform "React" for the two apps; one more, "Django", for the API, or use the
   same project for all three: every report carries the tag `app` = `api`, `admin` or `truck`).
2. On the server, in `~/frutti-staging/.env`: `SENTRY_DSN=<DSN of the API project>` and
   `SENTRY_DSN_FRONTEND=<DSN of the apps project>`.
3. Redeploy. The apps read their DSN **when the image is built**, so a change needs a redeploy, not only a restart.

Reports carry the release (`<time>-<commit>` of the deploy) and the environment (`staging`), and name a user by id
only. Variables: `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE` (API, set by the compose file from the
deploy), `SENTRY_DSN_FRONTEND` (build argument, becomes `VITE_SENTRY_DSN`; `VITE_SENTRY_ENVIRONMENT` and
`VITE_RELEASE` likewise). A local `pnpm build` with `VITE_SENTRY_DSN` set builds the apps with Sentry on.

### Backups (D-139)

**What runs.** Every night at 02:30 UTC (03:30 in Tunisia), from the `debian` user's crontab (`crontab -l`):

```
30 2 * * * $HOME/frutti-staging/bin/backup.sh frutti-staging >> $HOME/frutti-staging/backup.log 2>&1
```

`deploy/backup.sh` (installed to `~/frutti-staging/bin/` on every deploy, with the public key
`deploy/backup-public-key.asc` → `~/frutti-staging/backup-public-key.asc`) writes
`~/frutti-staging/backups/<UTC time>/` with:

- `db.dump.gpg`: `pg_dump --format=custom` of the database, from the db container;
- `media.tar.gz.gpg`: the volume `frutti-staging_media` (product photos, logo, avatars, expense receipts, loss photos,
  payment files, generated PDFs);
- `manifest.txt` (not secret): time, key fingerprint, PostgreSQL version, SHA-256 of both files.

Both files are encrypted with gpg to the backup public key while they stream: nothing readable is written to disk
and the server cannot read its own backups. Folders older than 30 days are deleted. Each run adds one line to
`~/frutti-staging/backup.log`: `... BACKUP OK frutti-staging <time> db=541KB media=916KB duration=2s kept=.. removed=..
offsite=..` or `... BACKUP FAILED frutti-staging <time>: <reason>` (exit code 1). To run one by hand:
`~/frutti-staging/bin/backup.sh`. Not backed up: `.env` (recreated by a deploy; keep its off-site credentials in the
password manager), Redis (holds nothing), code, images and nginx site (in git).

**The key.** Public key fingerprint `8C69 CE47 FE72 6683 B373 2261 C5D2 D8A9 82D4 3BCF` (RSA 4096, encryption subkey
`D0FF5AC57C467C81159A72D06A497EF2DC5C2F40`). The **private key** is the file `frutti-backup-PRIVATE-key.asc`, made on
2026-10-14 on Mahmoud's machine, in `C:\Users\ITDT\frutti-backup-key\`, with no passphrase. To do: the owner moves it
into a password manager and onto a USB key, then it is deleted from that folder. It is never on the server or in git.
**Without it no backup can be read.**

**Off-site copy (still to set up by the owner).** When `BACKUP_S3_BUCKET` is set in `~/frutti-staging/.env`, each backup
is copied with rclone (container `rclone/rclone:1.68.2`) to `<bucket>/<prefix>/<time>/`. The variables (empty lines
are already in `.env`):

| Variable | Example (OVHcloud Object Storage) |
|---|---|
| `BACKUP_S3_ENDPOINT` | `https://s3.gra.io.cloud.ovh.net` |
| `BACKUP_S3_REGION` | `gra` |
| `BACKUP_S3_BUCKET` | `frutti-backups` (empty = local copy only, said in the log line) |
| `BACKUP_S3_PREFIX` | `frutti-staging` (the default) |
| `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` | keys of a user allowed to write that bucket |

Create the bucket yourself (the script does not), in another provider or region than this VPS, with a lifecycle rule
that deletes objects after 30 to 60 days: the script never deletes anything off-site, so give its keys write access
only. Then run `~/frutti-staging/bin/backup.sh` once and check the line says `offsite=<bucket>/...`. Tested on
2026-10-14 against a throwaway S3 server: upload OK; an unreachable endpoint fails in about 20 s with a clear line.

**Restore drill (2026-10-14, done for real).** From a clone, on the machine that holds the private key (Git Bash):

```bash
scp -r debian@217.182.205.137:frutti-staging/backups/20261014T122410Z ./drill/
RESTORE_SSH=debian@217.182.205.137 RESTORE_BACKEND_IMAGE=frutti-backend:20261014113217-a398d51 \
  bash deploy/restore.sh ./drill/20261014T122410Z ~/frutti-backup-key/frutti-backup-PRIVATE-key.asc
bash deploy/restore.sh --remove frutti-restore-20261014T122502Z   # with the same RESTORE_SSH
```

`deploy/restore.sh` checks the SHA-256 against the manifest, decrypts **on this machine** (the key never leaves it),
streams the dump into a new throwaway container `frutti-restore-<time>` (`postgres:16-alpine`, own network, no port),
the media into a new volume `frutti-restore-<time>-media`, prints the exact row count of every table and runs
`rebuild_on_hand --check` with the backend image. It never touches the running database. Without `RESTORE_SSH`
it uses the local Docker. Result, against the live database counted right after the backup:

| Check | Live | Restored |
|---|---|---|
| Tables, all compared row by row count | 99 (1 551 rows) | 99, identical |
| `sales_sale` / `inventory_stockmovement` / `inventory_stockonhand` | 18 / 76 / 29 | 18 / 76 / 29 |
| `catalog_product` / `core_user` / `sales_invoice` / `expenses_expense` | 50 / 3 / 8 / 17 | 50 / 3 / 8 / 17 |
| Media files | 24 | 24 |
| `rebuild_on_hand --check` | | "0 difference(s) found" |

Backup took 2 s (db 541 KB, media 916 KB encrypted); the whole restore 45 s. Afterwards the container, network and
volume were removed. Do this again every few months and after a large change to the data model.

**Emergency restore (the live data is lost or broken).** Not drilled yet in place; the drill above proves the files.

1. Take a backup of what is there now, if the server still runs (`~/frutti-staging/bin/backup.sh`), so the
   restore can be undone. Pick the backup to restore (`~/frutti-staging/backups/`, or the off-site bucket) and copy it
   to the machine with the private key. Check it first with `restore.sh` as in the drill.
2. On a new server, deploy first (`make deploy-staging`): it creates `.env`, an empty database and the volumes.
   Put the `BACKUP_S3_*` lines back into `.env`. Then stop the app, keep the database running:
   ```bash
   cd ~/frutti-staging/releases/$(ls -1t ~/frutti-staging/releases | head -1)/deploy
   export RELEASE=$(ls -1t ~/frutti-staging/releases | head -1)
   sudo -E docker compose --project-name frutti-staging --env-file ~/frutti-staging/.env -f compose.staging.yml stop backend worker nightly web
   docker exec frutti-staging-db-1 dropdb -U frutti --force frutti
   docker exec frutti-staging-db-1 createdb -U frutti frutti
   ```
3. From the machine with the key (Git Bash, in the backup folder):
   ```bash
   gpg --import frutti-backup-PRIVATE-key.asc   # once; or use a throwaway GNUPGHOME as restore.sh does
   gpg --decrypt db.dump.gpg | ssh debian@<server> docker exec -i frutti-staging-db-1 pg_restore -U frutti -d frutti --no-owner --exit-on-error
   gpg --decrypt media.tar.gz.gpg | ssh debian@<server> docker run --rm -i -v frutti-staging_media:/media postgres:16-alpine tar -xzf - -C /media
   ```
4. Start again (`... compose.staging.yml up -d`, same folder and `RELEASE`), check both health URLs, run
   `... exec backend python manage.py rebuild_on_hand --check`, and log in. A new `.env` means a new secret key: everyone
   logs in again.

### Client start: empty the demo data (D-146)

Run once, before the client uses the staging database, after the backup. The command keeps the organization and
its settings, the logins, the cold rooms and trucks, the expense categories, the products whose code starts with
`ART`, and the employees named with `--keep-employee`; everything else of the organization is deleted (stock,
boxes, purchases, sales, invoices, customers, suppliers, costs, payroll, closings, documents, prices, counters, audit log).

```bash
cd ~/frutti-staging/releases/$(ls -1t ~/frutti-staging/releases | head -1)/deploy
# 1. A backup first (the nightly one is not enough right before this):
~/frutti-staging/bin/backup.sh
# 2. Dry run: prints what would go and what stays, then rolls back (nothing changes):
sudo docker compose --project-name frutti-staging --env-file ~/frutti-staging/.env -f compose.staging.yml \
  exec backend python manage.py prepare_client_start --keep-employee "Dhaker" --keep-employee "Manel" \
  --keep-employee "Sabra" --keep-employee "Ghassen" --keep-employee "Wajdi"
# 3. The same command with --apply: deletes, sets the marker, prints the new passwords once.
# 4. Check: `... exec backend python manage.py rebuild_on_hand --check` ("0 difference(s) found").
```

Each `--keep-employee` is a part of a name and must match exactly one employee, or the command stops. The
deletion runs in one transaction and checks every foreign key before it commits: a problem rolls everything back.
Once `real_data_since` is set, `seed_dev` adds nothing. To undo, restore the backup
(Emergency restore above).

## Production

Not set up yet (P4-T02). It needs a domain and HTTPS: staging runs on plain HTTP (D-027).
