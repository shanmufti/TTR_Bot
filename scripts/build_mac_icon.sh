#!/usr/bin/env bash
# Rebuild packaging/macos/AppIcon.icns from app_icon_source_1024.png (macOS only).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/packaging/macos/app_icon_source_1024.png"
SET="$(mktemp -d "${TMPDIR:-/tmp}/ttr-iconset.XXXXXX")"
OUT="$ROOT/packaging/macos/AppIcon.icns"
cleanup() { rm -rf "$SET"; }
trap cleanup EXIT

if [[ ! -f "$SRC" ]]; then
  echo "Missing $SRC"
  exit 1
fi

sips -z 16 16     "$SRC" --out "$SET/icon_16x16.png"
sips -z 32 32     "$SRC" --out "$SET/icon_16x16@2x.png"
sips -z 32 32     "$SRC" --out "$SET/icon_32x32.png"
sips -z 64 64     "$SRC" --out "$SET/icon_32x32@2x.png"
sips -z 128 128   "$SRC" --out "$SET/icon_128x128.png"
sips -z 256 256   "$SRC" --out "$SET/icon_128x128@2x.png"
sips -z 256 256   "$SRC" --out "$SET/icon_256x256.png"
sips -z 512 512   "$SRC" --out "$SET/icon_256x256@2x.png"
sips -z 512 512   "$SRC" --out "$SET/icon_512x512.png"
sips -z 1024 1024 "$SRC" --out "$SET/icon_512x512@2x.png"

iconutil -c icns "$SET" -o "$OUT"
echo "Wrote $OUT"
