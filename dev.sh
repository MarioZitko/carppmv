#!/usr/bin/env bash
# One-command local dev startup: Postgres (docker), FastAPI backend, Next.js frontend.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Starting Postgres..."
docker compose up -d db

echo "==> Waiting for Postgres to be healthy..."
until [ "$(docker compose ps -q db | xargs docker inspect -f '{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; do
  sleep 1
done

cleanup() {
  echo
  echo "==> Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Starting backend (http://localhost:8000)..."
uv run uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!

echo "==> Starting frontend (http://localhost:3000)..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

wait "$BACKEND_PID" "$FRONTEND_PID"
