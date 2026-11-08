#!/usr/bin/env bash
# Empties the training copy (D-283) and starts it again from today's production master data. Run by hand ON the
# server, never by a deploy: ~/frutti-training/bin/reset-training.sh          (shows what it would do)
#                                ~/frutti-training/bin/reset-training.sh --apply
# The training copy runs in the production stack, on the same PostgreSQL server, with its own database
# `frutti_training`. Production's database `frutti` is only read (pg_dump); every write names frutti_training, the
# training-* services or the training_media volume. The trainees' logins are kept: saved first to
# ~/frutti-training/logins/, put back after.
set -euo pipefail

STAGING="$HOME/frutti-staging"
TRAINING="$HOME/frutti-training"
TRAINING_DB=frutti_training
RELEASE="$(ls -1t "$STAGING/releases" | head -1)"
DEPLOY_DIR="$STAGING/releases/$RELEASE/deploy"
export RELEASE

stack() { sudo -E docker compose --project-name frutti-staging --env-file "$STAGING/.env" -f "$DEPLOY_DIR/compose.staging.yml" "$@"; }

echo "Training logins kept through the reset:"
LOGINS="$(stack exec -T training-backend python manage.py prepare_training --export-logins)"
echo "$LOGINS" | grep '"username"' | sed 's/.*"username": "\(.*\)".*/  \1/' || echo "  (none: a 'formation' owner login will be created)"

if [ "${1:-}" != "--apply" ]; then
  echo
  echo "Would: copy production's database into $TRAINING_DB, delete the work there (stock, sales, invoices, payments,"
  echo "closings, payroll, expenses, lots, documents, history), keep the master data and the logins above."
  echo "Production is only read. Nothing was changed. Run again with --apply."
  exit 0
fi

# 1. The logins, kept on disk in case a later step fails (running this script again puts them back).
install -d -m 700 "$TRAINING/logins"
SAVED="$TRAINING/logins/$(date -u +%Y%m%d%H%M%S).json"
(umask 077 && printf '%s\n' "$LOGINS" > "$SAVED")
ls -1t "$TRAINING/logins"/*.json | tail -n +11 | xargs -r rm -f # keep the last 10
echo "Logins saved to $SAVED"

# 2. Stop the training copy only, then replace its database with a copy of production's.
stack stop training-worker training-backend
stack exec -T db psql -q -U frutti -d postgres -c "DROP DATABASE IF EXISTS $TRAINING_DB WITH (FORCE)"
stack exec -T db createdb -U frutti "$TRAINING_DB"
stack exec -T db sh -c "pg_dump -U frutti -d frutti --format=custom | pg_restore -U frutti -d $TRAINING_DB --no-owner --no-privileges"
echo "Production database copied into $TRAINING_DB"

# 3. The pictures the master data and the documents need: product photos and the company logo.
sudo docker run --rm --user root --entrypoint sh \
  -v frutti-staging_media:/from:ro -v frutti-staging_training_media:/to "frutti-backend:$RELEASE" -c '
    for d in products organizations; do rm -rf "/to/$d"; [ -d "/from/$d" ] && cp -a "/from/$d" /to/; done; true'

# 4. In the training database: keep the master data, delete the work, lock production's accounts, put the
#    trainees back. prepare_training refuses to run anywhere FRUTTI_TRAINING is not true.
stack run --rm -T --no-deps training-backend sh -c \
  "python manage.py migrate --noinput && python manage.py prepare_training --logins - --apply" < "$SAVED"

# 5. Start the training copy again and check it.
stack up -d training-backend training-worker
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
