#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE_NAME="${SERVICE_NAME:-app}"
BRANCH="${BRANCH:-main}"

echo "[update] project: $ROOT_DIR"
echo "[update] compose file: $COMPOSE_FILE"
echo "[update] branch: $BRANCH"

if ! command -v git >/dev/null 2>&1; then
  echo "[update] git is required" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[update] docker is required" >&2
  exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "[update] missing $COMPOSE_FILE" >&2
  echo "[update] create it from docs/deploy-docker-compose.md first" >&2
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "[update] missing .env" >&2
  echo "[update] create .env first; the update script will not generate or modify secrets" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[update] tracked files have local changes; aborting to avoid overwriting local edits" >&2
  git status --short
  exit 1
fi

echo "[update] fetching latest code"
git fetch origin "$BRANCH"

LOCAL_REV="$(git rev-parse HEAD)"
REMOTE_REV="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL_REV" = "$REMOTE_REV" ]; then
  echo "[update] already up to date: $LOCAL_REV"
else
  echo "[update] updating $LOCAL_REV -> $REMOTE_REV"
  git pull --ff-only origin "$BRANCH"
fi

echo "[update] building image"
docker compose -f "$COMPOSE_FILE" build "$SERVICE_NAME"

echo "[update] restarting service"
docker compose -f "$COMPOSE_FILE" up -d "$SERVICE_NAME"

echo "[update] status"
docker compose -f "$COMPOSE_FILE" ps

echo "[update] done"
