#!/usr/bin/env bash
# Thin wrapper so the spec's `scripts/bootstrap-mongo.*` name exists.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python scripts/bootstrap_mongo.py "$@"
