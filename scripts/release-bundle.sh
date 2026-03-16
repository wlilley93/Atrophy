#!/bin/bash
# Build and publish a hot bundle to GitHub Releases.
#
# Usage: ./scripts/release-bundle.sh [patch|minor|major]
#
#   patch  (default) - bump 1.2.3 -> 1.2.4
#   minor            - bump 1.2.3 -> 1.3.0
#   major            - bump 1.2.3 -> 2.0.0
#
# Does everything:
#   1. Bumps the version in package.json
#   2. Commits the version bump
#   3. Builds the hot bundle (app.js + preload + renderer)
#   4. Creates or updates a GitHub Release tagged bundle-vX.Y.Z
#   5. Uploads bundle.tar.gz + bundle-manifest.json
#
# Users' apps pick it up automatically on next restart.

set -euo pipefail

cd "$(dirname "$0")/.."

# --- Version bump ---

BUMP="${1:-patch}"

case "$BUMP" in
  patch|minor|major) ;;
  *)
    echo "Usage: $0 [patch|minor|major]"
    echo "  patch (default) - bump 1.2.3 -> 1.2.4"
    echo "  minor           - bump 1.2.3 -> 1.3.0"
    echo "  major           - bump 1.2.3 -> 2.0.0"
    exit 1
    ;;
esac

OLD_VERSION=$(node -p "require('./package.json').version")

# Bump version in package.json (node one-liner to avoid jq dependency)
NEW_VERSION=$(node -e "
  const fs = require('fs');
  const pkg = JSON.parse(fs.readFileSync('package.json', 'utf-8'));
  const [major, minor, patch] = pkg.version.split('.').map(Number);
  const bump = '${BUMP}';
  if (bump === 'major') pkg.version = (major + 1) + '.0.0';
  else if (bump === 'minor') pkg.version = major + '.' + (minor + 1) + '.0';
  else pkg.version = major + '.' + minor + '.' + (patch + 1);
  fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2) + '\n');
  process.stdout.write(pkg.version);
")

VERSION="${NEW_VERSION}"
TAG="bundle-v${VERSION}"

echo "=== Release hot bundle v${VERSION} (${BUMP} bump from ${OLD_VERSION}) ==="
echo ""

# Commit the version bump
git add package.json
git commit -m "Bump version to ${VERSION}"

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
