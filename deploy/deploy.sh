#!/usr/bin/env bash
# Deploys the committed HEAD to staging: `make deploy-staging` (or the CI job on main).
# Builds the two images HERE (the CI runner, or this machine), sends them and a copy of the code (git archive, so
# nothing uncommitted) to the server, then runs remote-deploy.sh there.
#
# Never build on the server (D-308): the VPS is shared with other clients' production, and building the images there
# (three front ends with Vite, then the Python image) took all its memory and CPU and took the whole server down.
# The server now only loads finished images and starts them.
set -euo pipefail

TARGET="${DEPLOY_TARGET:-debian@217.182.205.137}"
SSH_OPTS=(${DEPLOY_SSH_OPTS:-})
RELEASE="$(date -u +%Y%m%d%H%M%S)-$(git rev-parse --short HEAD)"
REMOTE_DIR="frutti-staging/releases/$RELEASE"

if ! docker info > /dev/null 2>&1; then
  echo "Docker is needed here to build the images: they are never built on the shared server (D-308)." >&2
  exit 1
fi

echo "Deploying $RELEASE to $TARGET"

# 1. Build from the committed code only, with the same build arguments as compose.staging.yml. The front-end Sentry
#    DSN lives in the server's .env (it ends up in the public JavaScript anyway, so reading it is fine).
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
git archive --format=tar HEAD | tar -x -C "$BUILD_DIR"
SENTRY_DSN_FRONTEND="$(ssh "${SSH_OPTS[@]}" "$TARGET" \
  "grep -s '^SENTRY_DSN_FRONTEND=' frutti-staging/.env | head -n 1 | cut -d= -f2-" || true)"
docker build --target backend --tag "frutti-backend:$RELEASE" "$BUILD_DIR"
docker build --target web --tag "frutti-web:$RELEASE" \
  --build-arg "SENTRY_DSN_FRONTEND=$SENTRY_DSN_FRONTEND" \
  --build-arg SENTRY_ENVIRONMENT=staging \
  --build-arg "RELEASE=$RELEASE" \
  "$BUILD_DIR"

# 2. The code (compose file, nginx site, scripts) and the images. Loading runs at the lowest CPU and disk priority.
git archive --format=tar HEAD | ssh "${SSH_OPTS[@]}" "$TARGET" "mkdir -p $REMOTE_DIR && tar -x -C $REMOTE_DIR"
docker save "frutti-backend:$RELEASE" "frutti-web:$RELEASE" | gzip -1 \
  | ssh "${SSH_OPTS[@]}" "$TARGET" "gunzip | sudo nice -n 19 ionice -c3 docker load"
docker image rm "frutti-backend:$RELEASE" "frutti-web:$RELEASE" > /dev/null 2>&1 || true

# 3. Start them.
ssh "${SSH_OPTS[@]}" "$TARGET" "bash $REMOTE_DIR/deploy/remote-deploy.sh $RELEASE"
