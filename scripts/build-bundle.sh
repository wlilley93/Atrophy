#!/bin/bash
# Build a hot bundle tarball for release.
#
# Usage: ./scripts/build-bundle.sh [version]
#   version: optional override, defaults to package.json version
#
# Output:
#   dist/bundle.tar.gz          - the hot bundle (app.js + preload + renderer)
#   dist/bundle-manifest.json   - metadata with version + sha256
#
# The tarball contains the out/ directory EXCLUDING out/main/index.js
# (the bootstrap), since bootstrap stays frozen in the asar.

set -euo pipefail

cd "$(dirname "$0")/.."

# Get version
VERSION="${1:-$(node -p "require('./package.json').version")}"

echo "Building hot bundle v${VERSION}..."

# Build
pnpm build

# Also build renderer if vite.renderer.config.ts exists
if [ -f vite.renderer.config.ts ]; then
  npx vite build --config vite.renderer.config.ts
fi

# Create dist dir
mkdir -p dist

# Create tarball excluding the bootstrap (out/main/index.js)
# Include: out/main/app.js, out/preload/*, out/renderer/*
cd out
tar czf ../dist/bundle.tar.gz \
  --exclude='main/index.js' \
  --exclude='main/index.js.map' \
  main/ preload/ renderer/
cd ..

# Calculate SHA-256
SHA256=$(shasum -a 256 dist/bundle.tar.gz | cut -d' ' -f1)

# Write manifest
cat > dist/bundle-manifest.json << EOF
{
  "version": "${VERSION}",
  "sha256": "${SHA256}",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo ""
echo "Hot bundle built:"
echo "  dist/bundle.tar.gz ($(du -h dist/bundle.tar.gz | cut -f1))"
echo "  dist/bundle-manifest.json"
echo "  Version: ${VERSION}"
echo "  SHA-256: ${SHA256}"
echo ""
echo "To release: create a GitHub Release and attach both files."
