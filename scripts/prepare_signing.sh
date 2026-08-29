#!/usr/bin/env bash
set -euo pipefail

EXPECTED_CERTIFICATE='82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC'

for variable in \
  ANDROID_KEYSTORE_BASE64 \
  ANDROID_KEYSTORE_PASSWORD \
  ANDROID_KEY_ALIAS \
  ANDROID_KEY_PASSWORD \
  RUNNER_TEMP
do
  if [[ -z ${!variable:-} ]]; then
    echo "missing required environment variable: $variable" >&2
    exit 1
  fi
done

umask 077
KEYSTORE_PATH="$RUNNER_TEMP/userland-apps-release.jks"
printf '%s' "$ANDROID_KEYSTORE_BASE64" | base64 --decode > "$KEYSTORE_PATH"
test -s "$KEYSTORE_PATH"

export LC_ALL=C
KEYSTORE_INFO=$(keytool \
  -list \
  -v \
  -keystore "$KEYSTORE_PATH" \
  -alias "$ANDROID_KEY_ALIAS" \
  -storepass:env ANDROID_KEYSTORE_PASSWORD)

if ! grep -q '^Entry type: PrivateKeyEntry$' <<< "$KEYSTORE_INFO"; then
  echo "signing alias is not a PrivateKeyEntry" >&2
  exit 1
fi
CERTIFICATE_SHA256=$(awk -F': ' '/SHA256:/{print $2; exit}' <<< "$KEYSTORE_INFO")
if [[ "$CERTIFICATE_SHA256" != "$EXPECTED_CERTIFICATE" ]]; then
  echo "signing certificate SHA-256 does not match repository contract" >&2
  exit 1
fi

if [[ -n ${GITHUB_ENV:-} ]]; then
  printf 'ANDROID_KEYSTORE_FILE=%s\n' "$KEYSTORE_PATH" >> "$GITHUB_ENV"
fi
if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  printf 'keystore_path=%s\n' "$KEYSTORE_PATH" >> "$GITHUB_OUTPUT"
  printf 'certificate_sha256=%s\n' "$CERTIFICATE_SHA256" >> "$GITHUB_OUTPUT"
fi
printf 'Signing certificate verified: %s\n' "$CERTIFICATE_SHA256"
