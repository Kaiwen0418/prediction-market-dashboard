#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ssh_host="${1:-frodo@192.168.1.131}"
ssh_key="${PMI_SSH_KEY:-$HOME/.ssh/agentbench_codex_ed25519}"
ssh -i "$ssh_key" "$ssh_host" 'mkdir -p ~/prediction-market-dashboard/public/data'
rsync -az -e "ssh -i $ssh_key" \
  --exclude='/deploy/.env' --exclude='/deploy/tunnel.yml' --exclude='**/__pycache__/***' --exclude='*.pyc' \
  --include='/deploy/***' --include='/surveillance/***' \
  --include='/backend/' --include='/backend/app/***' --include='/backend/tests/***' \
  --include='/backend/requirements.txt' --include='/public/' --include='/public/data/***' \
  --include='/.dockerignore' --exclude='*' \
  "$repo_root/" "$ssh_host:prediction-market-dashboard/"
ssh -i "$ssh_key" "$ssh_host" 'cd ~/prediction-market-dashboard
python3 - <<'"'"'PY'"'"'
from pathlib import Path
import secrets
p=Path("deploy/.env")
if not p.exists():
    p.write_text("POSTGRES_PASSWORD="+secrets.token_hex(24)+"\nSURVEILLANCE_API_TOKEN="+secrets.token_hex(32)+"\nSURVEILLANCE_CONTRACTS=100\n")
    p.chmod(0o600)
PY
docker compose --env-file deploy/.env -f deploy/local.compose.yml build backend
docker compose --env-file deploy/.env -f deploy/local.compose.yml up -d --wait postgres
docker compose --env-file deploy/.env -f deploy/local.compose.yml stop surveillance-worker
docker compose --env-file deploy/.env -f deploy/local.compose.yml run --rm --no-deps surveillance-worker python -m surveillance.cli recover-worker
docker compose --env-file deploy/.env -f deploy/local.compose.yml up -d --no-build
docker compose --env-file deploy/.env -f deploy/local.compose.yml ps'
