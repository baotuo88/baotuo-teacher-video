#!/usr/bin/env bash
# Fetch the Frametell engine (packages/engine) and its agent prompts (packages/agent/prompts) at a pinned commit,
# then link the engine to the dependencies installed from engine/package.json.
#
#   scripts/fetch-engine.sh <dest>          e.g. vendor (local dev) or /opt/frametell (Docker)
#
# Env:
#   FRAMETELL_REPO    git URL (default https://github.com/sitor-ai/frametell.git; set a mirror if GitHub is slow)
#   FRAMETELL_REF     commit to pin (default below)
#   DEPS_DIR          where engine/package.json's node_modules lives (default <dest>/deps)
set -euo pipefail

DEST="${1:?usage: fetch-engine.sh <dest>}"
REPO="${FRAMETELL_REPO:-https://github.com/sitor-ai/frametell.git}"
REF="${FRAMETELL_REF:-683b3e5e8cfae5062bea8f3317783cf845fe1c9f}"
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
DEPS_DIR="${DEPS_DIR:-$DEST/deps}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -n "${FRAMETELL_SRC:-}" ]; then
  # an existing checkout of the repo (e.g. one cloned through a proxy)
  echo "→ frametell from local checkout $FRAMETELL_SRC"
  SRC="$FRAMETELL_SRC"
  REF="$(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo "$REF")"
else
  echo "→ frametell $REF from $REPO"
  git -C "$TMP" init -q
  git -C "$TMP" remote add origin "$REPO"
  git -C "$TMP" config core.sparseCheckout true
  printf 'packages/engine/\npackages/agent/prompts/\nLICENSE\n' > "$TMP/.git/info/sparse-checkout"
  git -C "$TMP" fetch -q --depth 1 --filter=blob:none origin "$REF"
  git -C "$TMP" checkout -q FETCH_HEAD
  SRC="$TMP"
fi

rm -rf "$DEST/engine" "$DEST/prompts"
cp -R "$SRC/packages/engine" "$DEST/engine"
cp -R "$SRC/packages/agent/prompts" "$DEST/prompts"
rm -rf "$DEST/engine/node_modules"
cp "$SRC/LICENSE" "$DEST/FRAMETELL-LICENSE"
echo "$REF" > "$DEST/REF"

# the engine finds roughjs, fonts, playwright-core and ffmpeg-static through engine/node_modules
if [ -d "$DEPS_DIR/node_modules" ]; then
  ln -sfn "$(cd "$DEPS_DIR" && pwd)/node_modules" "$DEST/engine/node_modules"
  echo "✓ engine/node_modules → $DEPS_DIR/node_modules"
else
  echo "! $DEPS_DIR/node_modules not found: run npm ci in engine/ and link it as engine/node_modules"
fi
echo "✓ engine at $DEST/engine, prompts at $DEST/prompts"
