# baotuo-teacher-video: one container with the web app, the Frametell engine, Chromium and ffmpeg.
#
# Build args (all optional; see .env.example for mainland-China mirrors):
#   BASE_IMAGE      node image (default node:22-bookworm-slim)
#   APT_MIRROR      e.g. http://mirrors.tuna.tsinghua.edu.cn   (replaces deb.debian.org)
#   NPM_REGISTRY    e.g. https://registry.npmmirror.com
#   PIP_INDEX       e.g. https://pypi.tuna.tsinghua.edu.cn/simple
#   FRAMETELL_REPO / FRAMETELL_REF   where to fetch the engine when vendor/engine is not in the build context
ARG BASE_IMAGE=node:22-bookworm-slim

# Stages 1–3 make only platform-independent files (JS bundles, JS packages, the engine's sources), so a multi-arch
# build runs them once, natively on the build machine; only the runtime stage is per architecture.

# ── 1. the frontend ──
FROM --platform=$BUILDPLATFORM ${BASE_IMAGE} AS web
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --registry "$NPM_REGISTRY"
COPY frontend/ ./
RUN npm run build

# ── 2. the engine's browser libraries and fonts (ffmpeg comes from apt, so no binary download) ──
FROM --platform=$BUILDPLATFORM ${BASE_IMAGE} AS deps
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /opt/frametell/deps
COPY engine/package.json engine/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund --registry "$NPM_REGISTRY"

# ── 3. the engine itself: from vendor/ when present (scripts/fetch-engine.sh vendor), else from git ──
FROM --platform=$BUILDPLATFORM ${BASE_IMAGE} AS engine
ARG APT_MIRROR=
ARG FRAMETELL_REPO=https://github.com/sitor-ai/frametell.git
ARG FRAMETELL_REF=683b3e5e8cfae5062bea8f3317783cf845fe1c9f
COPY vendor/ /src/vendor/
COPY scripts/fetch-engine.sh /src/fetch-engine.sh
RUN set -e; \
    if [ -d /src/vendor/engine ] && [ -d /src/vendor/prompts ]; then \
      mkdir -p /opt/frametell && cp -R /src/vendor/engine /src/vendor/prompts /opt/frametell/ && \
      cp /src/vendor/REF /src/vendor/FRAMETELL-LICENSE /opt/frametell/ 2>/dev/null || true; \
      rm -rf /opt/frametell/engine/node_modules; \
    else \
      if [ -n "$APT_MIRROR" ]; then sed -i "s|http://deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; fi; \
      apt-get update && apt-get install -y --no-install-recommends git ca-certificates && \
      FRAMETELL_REPO="$FRAMETELL_REPO" FRAMETELL_REF="$FRAMETELL_REF" DEPS_DIR=/nonexistent bash /src/fetch-engine.sh /opt/frametell; \
    fi; \
    test -f /opt/frametell/engine/tools/render.mjs && test -f /opt/frametell/prompts/PAGE.md

# ── 4. runtime ──
FROM ${BASE_IMAGE}
ARG APT_MIRROR=
ARG PIP_INDEX=https://pypi.org/simple
RUN set -e; \
    if [ -n "$APT_MIRROR" ]; then sed -i "s|http://deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; fi; \
    apt-get update; \
    for i in 1 2 3 4; do \
      apt-get install -y -o Acquire::Retries=5 --fix-missing --no-install-recommends \
        chromium ffmpeg python3 python3-venv ca-certificates fonts-noto-color-emoji tini && break; \
      [ "$i" = 4 ] && exit 1; echo "apt retry $i"; sleep 5; \
    done; \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -i "$PIP_INDEX" -r /app/backend/requirements.txt

COPY --from=deps /opt/frametell/deps /opt/frametell/deps
COPY --from=engine /opt/frametell/ /opt/frametell/
RUN ln -sfn /opt/frametell/deps/node_modules /opt/frametell/engine/node_modules
COPY backend/ /app/backend/
COPY --from=web /web/dist /app/frontend/dist

ENV BTV_DATA_DIR=/data \
    BTV_ENGINE_DIR=/opt/frametell/engine \
    BTV_PROMPTS_DIR=/opt/frametell/prompts \
    BTV_FRONTEND_DIR=/app/frontend/dist \
    BTV_EXAMPLES_DIR=/app/backend/examples \
    BTV_IN_DOCKER=1 \
    CHROME_PATH=/usr/bin/chromium \
    FFMPEG_PATH=/usr/bin/ffmpeg \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

# runs as root inside the container: a bind-mounted ./data is then writable on any host (Chromium runs --no-sandbox;
# the container is the boundary)
RUN mkdir -p /data
WORKDIR /app/backend
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/auth/status', timeout=4)" || exit 1
# one worker: jobs and their logs live in this process
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
