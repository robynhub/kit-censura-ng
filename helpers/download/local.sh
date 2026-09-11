#!/usr/bin/env bash
# Concatenate explicitly configured sources. A missing file is an error.
set -euo pipefail
(( $# > 0 )) || { echo 'Usage: local.sh FILE...' >&2; exit 1; }
for file in "$@"; do
    cat -- "$file"
    printf '\n'
done
