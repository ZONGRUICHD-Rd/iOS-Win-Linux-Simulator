#!/bin/bash
# Signs a Madeira.app built with CODE_SIGNING_ALLOWED=NO ad-hoc, with its
# entitlements embedded, and zips it into an IPA:
#
#   madeira/ci/package-ipa.sh Madeira.app MADEIRA_DIR OUT.ipa
#
# Sideloaders (SideStore, AltStore, Sideloadly) re-sign with the user's own
# certificate, and read the embedded entitlements to decide which App ID
# capabilities to request: get-task-allow (JIT through a debugger) and the
# increased memory limit.
set -euo pipefail
APP="$(cd "$1" && pwd)"
M="$(cd "$2" && pwd)"
OUT="$3"
WORK="$(mktemp -d)"
cp -R "$APP" "$WORK/"
A="$WORK/$(basename "$APP")"

sign() { codesign --force --sign - --timestamp=none "$@"; }

# The fork's interface is Chinese for everyone: with en.lproj gone, zh-Hans is
# the app's only localization (and its development region), whatever the
# iPhone's language. English stays the fallback for any string not translated.
rm -rf "$A/en.lproj"

find "$A" -name '*.dylib' -print0 | while IFS= read -r -d '' f; do sign "$f"; done
for fw in "$A"/Frameworks/*.framework; do [ -d "$fw" ] && sign "$fw"; done
for ext in "$A"/PlugIns/*.appex; do [ -d "$ext" ] && sign "$ext"; done
sign --entitlements "$M/app/Madeira/Madeira.entitlements" --generate-entitlement-der "$A"
codesign -d --entitlements - "$A"

mkdir -p "$WORK/Payload"
mv "$A" "$WORK/Payload/"
(cd "$WORK" && zip -qry "$OLDPWD/$OUT" Payload)
ls -la "$OUT"
rm -rf "$WORK"
