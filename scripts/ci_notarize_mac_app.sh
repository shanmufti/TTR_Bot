#!/usr/bin/env bash
# Notarize and staple a signed .app (run after ci_codesign_mac_app.sh).
# Env: APPLE_ID, APPLE_TEAM_ID, APPLE_APP_SPECIFIC_PASSWORD
set -euo pipefail

APP_PATH="${1:?Usage: $0 <path/to/App.app>}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "::error::App bundle not found: $APP_PATH"
  exit 1
fi

for v in APPLE_ID APPLE_TEAM_ID APPLE_APP_SPECIFIC_PASSWORD; do
  if [[ -z "${!v:-}" ]]; then
    echo "::error::$v is not set"
    exit 1
  fi
done

RUNNER_TEMP="${RUNNER_TEMP:-$(mktemp -d)}"
ZIP_PATH="${RUNNER_TEMP}/notarize-submit.zip"

ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

xcrun notarytool submit "$ZIP_PATH" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_SPECIFIC_PASSWORD" \
  --wait

xcrun stapler staple "$APP_PATH"
xcrun stapler validate "$APP_PATH"
echo "Notarize + staple OK: $APP_PATH"
