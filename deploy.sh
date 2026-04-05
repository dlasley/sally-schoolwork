#!/usr/bin/env bash
# Deploy to LiveKit Cloud, including config.local.json in the build context.
# config.local.json is gitignored to protect PII; this script temporarily
# removes that exclusion so lk agent deploy can package it.
set -euo pipefail

GITIGNORE=".gitignore"
PATTERN="personas/config.local.json"
BACKUP=$(mktemp)

cleanup() {
    cp "$BACKUP" "$GITIGNORE"
    rm -f "$BACKUP"
}
trap cleanup EXIT

cp "$GITIGNORE" "$BACKUP"
sed -i '' "/^${PATTERN//\//\\/}$/d" "$GITIGNORE"

lk agent deploy "$@"
