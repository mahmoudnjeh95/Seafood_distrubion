# Production images. Built from the repository root:
#   docker build --target backend -t frutti-backend .
#   docker build --target web -t frutti-web .
# deploy/compose.staging.yml builds both.

# ---- front ends: the three apps built once ----
FROM node:22-bookworm-slim AS frontend
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /app/frontend
RUN corepack enable
COPY frontend/ ./
RUN pnpm install --frozen-lockfile
# Sentry in the two apps (D-140): built in when SENTRY_DSN_FRONTEND is set in the server's .env, off when empty.
# The release changes on every deploy, so only the build step below runs again, not the install.
ARG SENTRY_DSN_FRONTEND=""
ARG SENTRY_ENVIRONMENT=""
ARG RELEASE=""
ENV VITE_SENTRY_DSN=$SENTRY_DSN_FRONTEND \
    VITE_SENTRY_ENVIRONMENT=$SENTRY_ENVIRONMENT \
    VITE_RELEASE=$RELEASE
# One app at a time, with a capped Node heap: building the three together (tsc + vite each) took the shared
# staging VPS down on CPU and RAM. Slower, but the server stays up.
ENV NODE_OPTIONS=--max-old-space-size=1024
RUN pnpm --filter @frutti/admin run build \
    && pnpm --filter @frutti/truck run build \
    && pnpm --filter @frutti/site run build

# ---- backend: Django + gunicorn ----
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS backend
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/venv \
    PATH=/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod
# WeasyPrint draws PDFs with Pango; DejaVu is the font of the printed documents (D-071).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
# Placeholder values: collectstatic needs settings to load, not the real secrets (nothing connects to the cache).
RUN DJANGO_SECRET_KEY=build-only DJANGO_ALLOWED_HOSTS=build DJANGO_CACHE_URL=redis://build-only:6379/0 \
    python manage.py collectstatic --noinput
RUN useradd --system --no-create-home app  && mkdir -p /app/media && chown app /app/media
# Uploaded photos; a named volume mounted here starts with this owner (deploy/compose.staging.yml).
VOLUME /app/media
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]

# ---- web: nginx serving the apps and the public site, and passing the API to the backend ----
FROM nginx:1.28-alpine AS web
COPY deploy/nginx-web.conf /etc/nginx/conf.d/default.conf
COPY deploy/frutti-app.inc /etc/nginx/conf.d/frutti-app.inc
COPY --from=frontend /app/frontend/apps/admin/dist /srv/admin
COPY --from=frontend /app/frontend/apps/truck/dist /srv/truck
COPY --from=frontend /app/frontend/apps/site/dist /srv/site
EXPOSE 8081 8082 8083
