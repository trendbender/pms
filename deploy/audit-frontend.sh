#!/usr/bin/env bash
# Fail the deploy if the frontend has HIGH/CRITICAL advisories in prod deps.
# Run before `docker compose build frontend` to catch vulnerable Next.js/deps early.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
docker run --rm -v "$PWD":/app -w /app node:22-alpine \
  sh -c "npm audit --omit=dev --audit-level=high"
echo "✅ npm audit (prod, level=high) clean"
