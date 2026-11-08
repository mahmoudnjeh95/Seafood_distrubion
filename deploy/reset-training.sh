#!/usr/bin/env bash
# Empties the training copy (D-283) and starts it again from today's production master data. Run by hand ON the
# server, never by a deploy: ~/frutti-training/bin/reset-training.sh          (shows what it would do)
#                                ~/frutti-training/bin/reset-training.sh --apply
# Production is only read (pg_dump, and a copy of the product photos and the logo); every write goes to the
# frutti-training project. The trainees' logins are kept: saved first to ~/frutti-training/logins/, put back after.
set -euo pipefail

TRAINING="$HOME/frutti-training"
STAGING="$HOME/frutti-staging"
RELEASE="$(ls -1t "$STAGING/releases" | head -1)"
DEPLOY_DIR="$STAGING/releases/$RELEASE/deploy"
export RELEASE

prod() { sudo -E docker compose --project-name frutti-staging --env-file "$STAGING/.env" -f "$DEPLOY_DIR/compose.staging.yml" "$@"; }
train() { sudo -E docker compose --project-name frutti-training --env-file "$TRAINING/.env" -f "$DEPLOY_DIR/compose.training.yml" "$@"; }

[ -f "$TRAINING/.env" ] || { echo "No $TRAINING/.env: deploy once first (it creates the training stack)." >&2; exit 1; }

echo "Training logins kept through the reset:"
LOGINS="$(train exec -T backend python manage.py prepare_training --export-logins)"
echo "$LOGINS" | grep '"username"' | sed 's/.*"username": "\(.*\)".*/  \1/' || echo "  (none: a 'formation' owner login will be created)"

if [ "${1:-}" != "--apply" ]; then
  echo
  echo "Would: copy production's database into the training one, delete the work (stock, sales, invoices, payments,"
  echo "closings, payroll, expenses, lots, documents, history), keep the master data and the logins above."
  echo "Nothing was changed. Run again with --apply."
  exit 0
fi

# 1. The logins, kept on disk in case a later step fails (put them back with: prepare_training --logins - --apply).
install -d -m 700 "$TRAINING/logins"
SAVED="$TRAINING/logins/$(date -u +%Y%m%d%H%M%S).json"
(umask 077 && printf '%s\n' "$LOGINS" > "$SAVED")
ls -1t "$TRAINING/logins"/*.json | tail -n +11 | xargs -r rm -f # keep the last 10
echo "Logins saved to $SAVED"

# 2. Stop the training apps, then replace their database with a copy of production's.
train stop web worker backend
train exec -T db sh -c 'psql -q -U frutti -d postgres -c "DROP DATABASE IF EXISTS frutti WITH (FORCE)" && createdb -U frutti frutti'
prod exec -T db pg_dump -U frutti -d frutti --format=custom \
  | train exec -T db pg_restore -U frutti -d frutti --no-owner --no-privileges
echo "Production database copied"

# 3. The pictures the master data and the documents need: product photos and the company logo.
sudo docker run --rm --user root --entrypoint sh \
  -v frutti-staging_media:/from:ro -v frutti-training_media:/to "frutti-backend:$RELEASE" -c '
    for d in products organizations; do rm -rf "/to/$d"; [ -d "/from/$d" ] && cp -a "/from/$d" /to/; done; true'

# 4. Keep the master data, delete the work, lock production's accounts, put the trainees back.
train run --rm -T --no-deps backend sh -c \
  "python manage.py migrate --noinput && python manage.py prepare_training --logins - --apply" < "$SAVED"

# 5. Start again and check.
train up -d
for pair in "app1.fruttidelmare.com:18091" "ch1.fruttidelmare.com:18092"; do
  for _ in $(seq 1 30); do
    if curl -fsS -H "Host: ${pair%:*}" -H "X-Forwarded-Proto: https" "http://127.0.0.1:${pair##*:}/api/v1/health" > /dev/null 2>&1; then
      echo "${pair%:*} healthy"
      break
    fi
    sleep 2
  done
done
echo "Training copy reset from production of $(date -u '+%Y-%m-%d %H:%M') UTC."
