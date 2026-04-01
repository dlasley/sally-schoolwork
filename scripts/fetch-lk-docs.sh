#!/usr/bin/env bash
# Download LiveKit documentation for offline reference.
#
# Files:
#   docs/llms.txt      — Table of contents / summary index (~65 KB)
#   docs/llms-full.txt — Full documentation content (~2.4 MB)

set -euo pipefail

DOCS_DIR="$(cd "$(dirname "$0")/.." && pwd)/docs"
mkdir -p "$DOCS_DIR"

echo "Downloading LiveKit docs to $DOCS_DIR ..."
curl -sS -o "$DOCS_DIR/llms.txt" https://docs.livekit.io/llms.txt
curl -sS -o "$DOCS_DIR/llms-full.txt" https://docs.livekit.io/llms-full.txt

echo "Done."
ls -lh "$DOCS_DIR"/llms*.txt
