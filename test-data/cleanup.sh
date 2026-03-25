#!/usr/bin/env bash
# Remove downloaded datasets and generated reports.
# Re-run setup.py to re-download.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

rm -rf "$SCRIPT_DIR/corpora/"
rm -rf "$SCRIPT_DIR/reports/"

echo "Cleaned: corpora/ and reports/ removed"
echo "Run 'python test-data/setup.py' to re-download datasets"
