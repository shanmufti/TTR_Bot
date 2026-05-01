#!/usr/bin/env bash
# Build "TTR Bot.app" with PyInstaller (requires: uv sync --group dev).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec .venv/bin/pyinstaller --noconfirm "$ROOT/TTR Bot.spec"
