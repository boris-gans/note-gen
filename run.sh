#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run.sh  —  Start the note-gen backend
#
# Usage:  ./run.sh
#
# First run: copies .env.example -> .env so you can set GROQ_API_KEY.
# Subsequent runs: installs/syncs deps with uv, then launches uvicorn.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- 1. Guard: ensure .env exists (copy template on first run) ---
if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        cp .env.example .env
        echo "[run.sh] Created .env from .env.example"
        echo "         Set GROQ_API_KEY in .env, then re-run ./run.sh"
        exit 1
    fi
fi

# --- 2. Install / sync deps ---
uv sync

# --- 3. Launch uvicorn with reload (watches app/ only) ---
uv run uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --reload \
    --reload-dir app
