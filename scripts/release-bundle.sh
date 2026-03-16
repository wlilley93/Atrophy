#!/bin/bash
# Build and publish a hot bundle to GitHub Releases.
#
# Usage: ./scripts/release-bundle.sh
#
# Does everything:
#   1. Reads version from package.json
#   2. Builds the hot bundle (app.js + preload + renderer)
#   3. Creates or updates a GitHub Release tagged bundle-vX.Y.Z
#   4. Uploads bundle.tar.gz + bundle-manifest.json
#
# Users' apps pick it up automatically on next restart.

set -euo pipefail

cd "$(dirname "$0")/.."

VERSION=$(node -p "require('./package.json').version")
TAG="bundle-v${VERSION}"

echo "=== Release hot bundle v${VERSION} ==="
echo ""

# 1. Build
bash scripts/build-bundle.sh "${VERSION}"

# 2. Check if release already exists
if gh release view "${TAG}" &>/dev/null; then
  echo "Release ${TAG} exists - updating assets..."
  # Delete old assets then re-upload
  gh release delete-asset "${TAG}" bundle.tar.gz --yes 2>/dev/null || true
  gh release delete-asset "${TAG}" bundle-manifest.json --yes 2>/dev/null || true
  gh release upload "${TAG}" \
    dist/bundle.tar.gz \
    dist/bundle-manifest.json
else
  echo "Creating release ${TAG}..."
  gh release create "${TAG}" \
    --title "Bundle v${VERSION}" \
    --notes "Hot bundle update v${VERSION}. Downloaded automatically by the app on next restart." \
    dist/bundle.tar.gz \
    dist/bundle-manifest.json
fi

echo ""
echo "Done. Release ${TAG} is live."
echo "Users will get v${VERSION} on their next app restart."
