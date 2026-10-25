#!/usr/bin/env bash
# Runs ON the staging server, from an unpacked release: deploy/remote-deploy.sh <release-id>
# Called by deploy/deploy.sh. Starts the stack, installs the nginx site, checks health. Never seeds data.
set -euo pipefail

RELEASE="$1"
BASE="$HOME/frutti-staging"
RELEASE_DIR="$BASE/releases/$RELEASE"
ENV_FILE="$BASE/.env"
# One host name per app, so their login cookies stay apart (D-036, D-155). Must match nginx-host-staging.conf.
ADMIN_HOST="app.fruttidelmare.com"
DRIVER_HOST="ch.fruttidelmare.com"
# The public site (D-186); the bare name only redirects to it (nginx-host-staging.conf).
SITE_HOST="www.fruttidelmare.com"
SITE_BARE_HOST="fruttidelmare.com"
ACME_WEBROOT=/var/www/frutti-acme # Let's Encrypt challenge files, served by the host nginx (D-155)
NGINX_SITE=/etc/nginx/sites-available/frutti-staging

# 0. Phase 2 (D-155): the certificate must exist before the HTTPS settings change, or nginx would fail after them
#    and leave the apps refusing plain HTTP. Nothing is changed when it is missing.
CERT_DIR=/etc/letsencrypt/live/frutti-staging
if ! sudo test -f "$CERT_DIR/fullchain.pem" || ! sudo test -f "$CERT_DIR/privkey.pem"; then
  echo "No certificate in $CERT_DIR: issue it first (docs/runbook.md, Domain and HTTPS). Nothing was changed." >&2
  exit 1
fi

# 1. Secrets: created once on the server, never in the repository.
if [ ! -f "$ENV_FILE" ]; then
  echo "Creating $ENV_FILE with new random secrets"
  umask 077
  cat > "$ENV_FILE" <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 24)
DJANGO_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n')
SENTRY_DSN=
SENTRY_DSN_FRONTEND=
EOF
fi
chmod 600 "$ENV_FILE"

# Host names are not secrets: written on every deploy, so a change here reaches servers set up earlier.
set_env() {
  if grep -q "^$1=" "$ENV_FILE"; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi
}
set_env DJANGO_ALLOWED_HOSTS "$ADMIN_HOST,$DRIVER_HOST,$SITE_HOST"
set_env DJANGO_CSRF_TRUSTED_ORIGINS "https://$ADMIN_HOST,https://$DRIVER_HOST,https://$SITE_HOST"
export RELEASE

# 2. Build and start. Only Frutti's own containers are touched.
cd "$RELEASE_DIR/deploy"
# The VPS is shared with other clients' production: build one image at a time, at low CPU priority.
export COMPOSE_PARALLEL_LIMIT=1
sudo -E nice -n 19 ionice -c3 docker compose --project-name frutti-staging --env-file "$ENV_FILE" -f compose.staging.yml build
sudo -E docker compose --project-name frutti-staging --env-file "$ENV_FILE" -f compose.staging.yml up -d --remove-orphans

# 3. Host nginx: install our site only if it changed, test, then reload. On a failed test, put back the old file.
sudo install -d -m 755 "$ACME_WEBROOT"
if ! sudo cmp -s "$RELEASE_DIR/deploy/nginx-host-staging.conf" "$NGINX_SITE" 2>/dev/null; then
  sudo cp -a "$NGINX_SITE" "$NGINX_SITE.previous" 2>/dev/null || true
  sudo install -m 644 "$RELEASE_DIR/deploy/nginx-host-staging.conf" "$NGINX_SITE"
  sudo ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/frutti-staging
  if sudo nginx -t; then
    sudo systemctl reload nginx
  else
    echo "nginx test failed: restoring the previous Frutti site, other sites untouched" >&2
    if [ -f "$NGINX_SITE.previous" ]; then sudo mv "$NGINX_SITE.previous" "$NGINX_SITE"
    else sudo rm -f "$NGINX_SITE" /etc/nginx/sites-enabled/frutti-staging; fi
    exit 1
  fi
fi

# 3b. The public site's names in the certificate (D-186), once: the port-80 block above answers the challenge.
#     A failure (DNS not there yet, Let's Encrypt limit) does not stop the deploy; the next deploy tries again.
if ! sudo openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -ext subjectAltName 2>/dev/null | grep -q "DNS:$SITE_HOST"; then
  if sudo certbot certonly --webroot -w "$ACME_WEBROOT" --cert-name frutti-staging --expand \
    -d "$ADMIN_HOST" -d "$DRIVER_HOST" -d "$SITE_HOST" -d "$SITE_BARE_HOST" \
    --deploy-hook "/usr/sbin/nginx -t && /bin/systemctl reload nginx" --non-interactive --agree-tos; then
    sudo nginx -t && sudo systemctl reload nginx
    echo "Certificate now holds $SITE_HOST and $SITE_BARE_HOST"
  else
    echo "WARNING: could not add $SITE_HOST to the certificate; see docs/runbook.md (Domain and HTTPS)" >&2
  fi
fi

# 4. Health: each app's web container, with the host name and the https scheme the host nginx sends for it
#    (so Django does not redirect the check; the nginx sites above are checked by the uptime watch).
for pair in "$ADMIN_HOST:18081" "$DRIVER_HOST:18082" "$SITE_HOST:18083"; do
  host="${pair%:*}"
  port="${pair##*:}"
  for _ in $(seq 1 30); do
    if curl -fsS -H "Host: $host" -H "X-Forwarded-Proto: https" "http://127.0.0.1:$port/api/v1/health" > /dev/null 2>&1; then echo "$host healthy"; break; fi
    sleep 2
  done
  curl -fsS -H "Host: $host" -H "X-Forwarded-Proto: https" "http://127.0.0.1:$port/api/v1/health" > /dev/null || { echo "$host not healthy" >&2; exit 1; }
done

# 5. Nightly backup (D-139): the script the debian user's crontab calls, and the public key it encrypts to.
#    The cron entry itself is installed once by hand (docs/runbook.md, "Backups").
install -d -m 700 "$BASE/bin"
install -m 755 "$RELEASE_DIR/deploy/backup.sh" "$BASE/bin/backup.sh"
install -m 644 "$RELEASE_DIR/deploy/backup-public-key.asc" "$BASE/backup-public-key.asc"

# 6. Keep the last 3 releases and their images; remove only Frutti's older ones.
cd "$BASE/releases"
for old in $(ls -1t | tail -n +4); do
  rm -rf "$old"
  sudo docker image rm "frutti-backend:$old" "frutti-web:$old" > /dev/null 2>&1 || true
done

echo "Deployed $RELEASE: admin https://$ADMIN_HOST  driver https://$DRIVER_HOST  site https://$SITE_HOST"
