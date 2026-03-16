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
#   4. Extracts release notes from docs/CHANGELOG.md
#   5. Creates or updates a GitHub Release tagged bundle-vX.Y.Z
#   6. Uploads bundle.tar.gz + bundle-manifest.json
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

# --- Build ---

bash scripts/build-bundle.sh "${VERSION}"

# --- Extract release notes from CHANGELOG.md ---

CHANGELOG="docs/CHANGELOG.md"
NOTES=""

if [ -f "${CHANGELOG}" ]; then
  # Extract the section for this version: everything between "## X.Y.Z" and the next "## " or "---"
  NOTES=$(node -e "
    const fs = require('fs');
    const text = fs.readFileSync('${CHANGELOG}', 'utf-8');
    const ver = '${VERSION}';
    // Match the version header (with or without date)
    const re = new RegExp('## ' + ver.replace(/\\./g, '\\\\.') + '[^\\n]*\\n');
    const match = re.exec(text);
    if (!match) { process.exit(0); }
    const start = match.index + match[0].length;
    // Find the next version header or horizontal rule
    const rest = text.slice(start);
    const end = rest.search(/^---\$/m);
    let section = end >= 0 ? rest.slice(0, end).trim() : rest.trim();
    // Append download note
    section += '\n\nDownloaded automatically by the app on next restart.';
    process.stdout.write(section);
  " 2>/dev/null || true)
fi

# Fallback if no changelog entry found
if [ -z "${NOTES}" ]; then
  echo "Warning: no changelog entry found for v${VERSION} in ${CHANGELOG}"
  echo "Using default release notes. Update ${CHANGELOG} and run:"
  echo "  gh release edit ${TAG} --notes-file <file>"
  echo ""
  NOTES="v${VERSION} hot bundle update. Downloaded automatically by the app on next restart."
fi

# --- Extract title from first line of changelog section ---

TITLE=$(node -e "
  const fs = require('fs');
  const text = fs.readFileSync('${CHANGELOG}', 'utf-8');
  const ver = '${VERSION}';
  const re = new RegExp('## ' + ver.replace(/\\./g, '\\\\.') + '[^\\n]*\\n');
  const match = re.exec(text);
  if (!match) { process.stdout.write('v' + ver); process.exit(0); }
  const start = match.index + match[0].length;
  const rest = text.slice(start);
  // First non-empty line is the summary
  const firstLine = rest.split('\\n').find(l => l.trim() && !l.startsWith('#'));
  if (firstLine) {
    // Strip markdown formatting for the title
    const clean = firstLine.trim().replace(/[*_\`]/g, '').slice(0, 60);
    process.stdout.write('v' + ver + ' - ' + clean);
  } else {
    process.stdout.write('v' + ver);
  }
" 2>/dev/null || echo "v${VERSION}")

# --- Publish ---

if gh release view "${TAG}" &>/dev/null; then
  echo "Release ${TAG} exists - updating assets and notes..."
  gh release edit "${TAG}" --title "${TITLE}" --notes "${NOTES}"
  gh release delete-asset "${TAG}" bundle.tar.gz --yes 2>/dev/null || true
  gh release delete-asset "${TAG}" bundle-manifest.json --yes 2>/dev/null || true
  gh release upload "${TAG}" \
    dist/bundle.tar.gz \
    dist/bundle-manifest.json
else
  echo "Creating release ${TAG}..."
  gh release create "${TAG}" \
    --title "${TITLE}" \
    --notes "${NOTES}" \
    dist/bundle.tar.gz \
    dist/bundle-manifest.json
fi

echo ""
echo "Done. Release ${TAG} is live."
echo "Users will get v${VERSION} on their next app restart."
