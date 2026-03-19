#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

load_env_defaults() {
  local env_file="$1"
  local line=""
  local trimmed=""
  local key=""

  [[ -f "$env_file" ]] || return 0

  while IFS= read -r line || [[ -n "$line" ]]; do
    trimmed="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$trimmed" || "$trimmed" == \#* ]] && continue
    [[ "$trimmed" == export\ * ]] && trimmed="${trimmed#export }"
    [[ "$trimmed" == *=* ]] || continue

    key="${trimmed%%=*}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ -n "$key" ]] || continue
    [[ -z "${!key:-}" ]] || continue

    eval "export ${trimmed}"
  done < "$env_file"
}

# Prefer explicit shell env, then admin-local config, then fall back to the app env
# so local runs use the same Firebase project unless overridden.
load_env_defaults "$ROOT_DIR/.env"
load_env_defaults "$ROOT_DIR/../uisurf-app/.env"

uv run fastapi dev src/uisurf_admin/main.py --port "${PORT:-8082}"
