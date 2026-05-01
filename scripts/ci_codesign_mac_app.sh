#!/usr/bin/env bash
# Import a Developer ID Application .p12 (base64) and codesign a .app for distribution.
# Env: MACOS_CODESIGN_P12, MACOS_CODESIGN_P12_PASSWORD, MACOS_CODESIGN_IDENTITY
# Optional: ENTITLEMENTS_FILE (defaults to packaging/macos/Entitlements.plist if present)
set -euo pipefail

APP_PATH="${1:?Usage: $0 <path/to/App.app>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d "$APP_PATH" ]]; then
  echo "::error::App bundle not found: $APP_PATH"
  exit 1
fi

if [[ -z "${MACOS_CODESIGN_P12:-}" ]]; then
  echo "::error::MACOS_CODESIGN_P12 is empty"
  exit 1
fi
if [[ -z "${MACOS_CODESIGN_P12_PASSWORD:-}" ]]; then
  echo "::error::MACOS_CODESIGN_P12_PASSWORD is empty"
  exit 1
fi
if [[ -z "${MACOS_CODESIGN_IDENTITY:-}" ]]; then
  echo "::error::MACOS_CODESIGN_IDENTITY is empty"
  exit 1
fi

RUNNER_TEMP="${RUNNER_TEMP:-$(mktemp -d)}"
KEYCHAIN_PATH="${RUNNER_TEMP}/build-signing.keychain-db"
KEYCHAIN_PASSWORD="$(openssl rand -base64 32)"
P12_PATH="${RUNNER_TEMP}/codesign.p12"

cleanup() {
  security delete-keychain "$KEYCHAIN_PATH" &>/dev/null || true
  rm -f "$P12_PATH"
}
trap cleanup EXIT

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

echo "$MACOS_CODESIGN_P12" | base64 --decode >"$P12_PATH"
security import "$P12_PATH" -k "$KEYCHAIN_PATH" -P "$MACOS_CODESIGN_P12_PASSWORD" \
  -T /usr/bin/codesign -T /usr/bin/security -T /usr/bin/productbuild
security list-keychain -d user -s "$KEYCHAIN_PATH"
security default-keychain -s "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

ENT_ARGS=()
ENT_FILE="${ENTITLEMENTS_FILE:-$ROOT/packaging/macos/Entitlements.plist}"
if [[ -f "$ENT_FILE" ]]; then
  ENT_ARGS=(--entitlements "$ENT_FILE")
  echo "Using entitlements: $ENT_FILE"
fi

codesign --deep --force --options runtime --timestamp \
  "${ENT_ARGS[@]}" \
  --sign "$MACOS_CODESIGN_IDENTITY" \
  "$APP_PATH"

codesign --verify --verbose=4 "$APP_PATH"
echo "Codesign OK: $APP_PATH"
