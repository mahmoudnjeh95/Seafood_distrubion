#!/usr/bin/env bash
# Nightly backup of one compose project (D-139). Runs ON the server from the debian user's crontab:
#   ~/frutti-staging/bin/backup.sh [project]          (project defaults to frutti-staging)
# remote-deploy.sh installs this file and the public key on every deploy; the cron entry is in docs/runbook.md.
#
# 1. pg_dump (custom format) from the project's db container, and a tar.gz of its media volume (photos, logos,
#    avatars, receipts, generated PDFs).
# 2. Both are encrypted with gpg to the public key while they stream: nothing readable is written to disk, and the
#    server never holds the private key needed to read a backup (it stays with the owner).
# 3. Kept in ~/<project>/backups/<UTC time>/: every backup for 30 days, then the first of each month for 10 years.
# 4. Copied off the server with rclone (from a container) when BACKUP_S3_BUCKET is set in ~/<project>/.env.
#
# Prints one line "BACKUP OK ..." on success, or "BACKUP FAILED ..." and exits non-zero, for monitoring.
set -euo pipefail
umask 077

PROJECT="${1:-frutti-staging}"
BASE="$HOME/$PROJECT"
ENV_FILE="$BASE/.env"
BACKUPS="$BASE/backups"
KEEP_DAYS=30
KEEP_YEARS=10
# Images already used by the project, or official ones pinned to an exact version.
TOOLS_IMAGE="postgres:16-alpine"
RCLONE_IMAGE="rclone/rclone:1.68.2"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STEP="start"
PARTIAL="$BACKUPS/.partial-$STAMP"
GNUPGHOME=""

fail() {
  echo "$(date -u +%FT%TZ) BACKUP FAILED $PROJECT $STAMP: $*" >&2
  STEP="reported"
  exit 1
}
on_exit() {
  local status=$?
  [ -z "$GNUPGHOME" ] || rm -rf "$GNUPGHOME"
  if [ "$status" -ne 0 ]; then
    rm -rf "$PARTIAL"
    # fail() already printed its line; an unexpected error names the step it stopped in.
    [ "$STEP" = "reported" ] || echo "$(date -u +%FT%TZ) BACKUP FAILED $PROJECT $STAMP: step '$STEP' exited $status" >&2
  fi
}
trap on_exit EXIT

# A value from the environment wins, else the line NAME=value of the project's .env, else empty.
setting() {
  if [ -n "${!1:-}" ]; then printf '%s' "${!1}"; return; fi
  if [ -f "$ENV_FILE" ]; then grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- || true; fi
}
human() { numfmt --to=iec --suffix=B "$1"; }

STEP="checks"
[ -d "$BASE" ] || fail "no folder $BASE"
command -v docker > /dev/null || fail "docker not found"
command -v gpg > /dev/null || fail "gpg not found"
KEY_FILE="$(setting BACKUP_PUBLIC_KEY_FILE)"
KEY_FILE="${KEY_FILE:-$BASE/backup-public-key.asc}"
[ -s "$KEY_FILE" ] || fail "public key $KEY_FILE missing"
mkdir -p "$BACKUPS"
chmod 700 "$BACKUPS"

# One run at a time.
exec 9> "$BACKUPS/.lock"
flock -n 9 || fail "another backup of $PROJECT is running"

DB_CONTAINER="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.service=db")"
if [ -z "$DB_CONTAINER" ] || [ "$(wc -l <<< "$DB_CONTAINER")" -ne 1 ]; then
  fail "no single running db container in project $PROJECT"
fi
MEDIA_VOLUME="${PROJECT}_media"
docker volume inspect "$MEDIA_VOLUME" > /dev/null 2>&1 || fail "no volume $MEDIA_VOLUME"

# gpg with a throwaway home: the debian user's own keyring is never touched.
GNUPGHOME="$(mktemp -d)"
export GNUPGHOME
encrypt() {
  # --rfc4880: classic OpenPGP packets (AES-256 with MDC) that any OpenPGP tool can read for years.
  gpg --batch --no-tty --quiet --rfc4880 --cipher-algo AES256 --compress-algo none \
    --trust-model always --recipient-file "$KEY_FILE" --encrypt --output "$1"
}
KEY_ID="$(gpg --batch --quiet --with-colons --show-keys "$KEY_FILE" | awk -F: '/^fpr/{print $10; exit}')"
[ -n "$KEY_ID" ] || fail "cannot read the public key $KEY_FILE"

mkdir -m 700 "$PARTIAL"

STEP="database dump"
docker exec "$DB_CONTAINER" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  | encrypt "$PARTIAL/db.dump.gpg" || fail "pg_dump or its encryption failed"

STEP="media archive"
docker run --rm --name "$PROJECT-backup-media-$STAMP" --network none -v "$MEDIA_VOLUME:/media:ro" \
  "$TOOLS_IMAGE" tar -C /media -czf - . \
  | encrypt "$PARTIAL/media.tar.gz.gpg" || fail "media archive or its encryption failed"

STEP="manifest"
DB_SIZE="$(stat -c %s "$PARTIAL/db.dump.gpg")"
MEDIA_SIZE="$(stat -c %s "$PARTIAL/media.tar.gz.gpg")"
[ "$DB_SIZE" -gt 1000 ] || fail "database dump is suspiciously small ($DB_SIZE bytes)"
{
  echo "project=$PROJECT"
  echo "time=$STAMP"
  echo "encrypted_to=$KEY_ID"
  echo "postgres=$(docker exec "$DB_CONTAINER" postgres --version)"
  (cd "$PARTIAL" && sha256sum db.dump.gpg media.tar.gz.gpg)
} > "$PARTIAL/manifest.txt"
mv "$PARTIAL" "$BACKUPS/$STAMP"
DIR="$BACKUPS/$STAMP"

STEP="retention"
# Every backup of the last KEEP_DAYS days; before that, the first backup of each month for KEEP_YEARS years
# (accounting records are kept 10 years, D-324). The folders sort by time, so a month's first one comes first.
CUTOFF="$(date -u -d "$KEEP_DAYS days ago" +%Y%m%dT%H%M%SZ)"
YEARS_CUTOFF="$(date -u -d "$KEEP_YEARS years ago" +%Y%m%dT%H%M%SZ)"
removed=0
month_seen=""
for old in "$BACKUPS"/20*; do
  [ -d "$old" ] || continue
  name="$(basename "$old")"
  month="${name:0:6}"
  first_of_month=0
  if [ "$month" != "$month_seen" ]; then first_of_month=1; month_seen="$month"; fi
  [[ "$name" < "$CUTOFF" ]] || continue
  if [ "$first_of_month" = 1 ] && ! [[ "$name" < "$YEARS_CUTOFF" ]]; then continue; fi
  rm -rf "$old"
  removed=$((removed + 1))
done
KEPT="$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name '20*' | wc -l)"

STEP="off-site copy"
BUCKET="$(setting BACKUP_S3_BUCKET)"
if [ -z "$BUCKET" ]; then
  OFFSITE="none (BACKUP_S3_BUCKET not set in $ENV_FILE: local copy only)"
else
  PREFIX="$(setting BACKUP_S3_PREFIX)"
  PREFIX="${PREFIX:-$PROJECT}"
  RCLONE_CONFIG_OFFSITE_ENDPOINT="$(setting BACKUP_S3_ENDPOINT)"
  RCLONE_CONFIG_OFFSITE_REGION="$(setting BACKUP_S3_REGION)"
  RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID="$(setting BACKUP_S3_ACCESS_KEY_ID)"
  RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY="$(setting BACKUP_S3_SECRET_ACCESS_KEY)"
  for name in ENDPOINT ACCESS_KEY_ID SECRET_ACCESS_KEY; do
    var="RCLONE_CONFIG_OFFSITE_$name"
    [ -n "${!var}" ] || fail "BACKUP_S3_BUCKET is set but BACKUP_S3_$name is empty in $ENV_FILE (local copy kept in $DIR)"
  done
  export RCLONE_CONFIG_OFFSITE_ENDPOINT RCLONE_CONFIG_OFFSITE_REGION \
    RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY
  # Values pass by name (-e NAME), so the secrets never appear in the process list.
  # Short timeouts: an unreachable destination fails in a few minutes instead of hanging the night.
  docker run --rm --name "$PROJECT-backup-offsite-$STAMP" -v "$DIR:/backup:ro" \
    -e RCLONE_CONFIG_OFFSITE_TYPE=s3 -e RCLONE_CONFIG_OFFSITE_PROVIDER=Other \
    -e RCLONE_CONFIG_OFFSITE_ENDPOINT -e RCLONE_CONFIG_OFFSITE_REGION \
    -e RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID -e RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY \
    "$RCLONE_IMAGE" copy /backup "offsite:$BUCKET/$PREFIX/$STAMP" \
    --s3-no-check-bucket --contimeout 15s --timeout 2m --retries 2 --low-level-retries 3 --quiet \
    || fail "off-site copy to $BUCKET/$PREFIX/$STAMP failed (local copy kept in $DIR)"
  OFFSITE="$BUCKET/$PREFIX/$STAMP"
fi

STEP="done"
echo "$(date -u +%FT%TZ) BACKUP OK $PROJECT $STAMP db=$(human "$DB_SIZE") media=$(human "$MEDIA_SIZE")" \
  "duration=${SECONDS}s kept=$KEPT removed=$removed offsite=$OFFSITE dir=$DIR"
