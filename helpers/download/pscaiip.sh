#!/usr/bin/env bash
# Optional client refresh commands are supplied as JSON argv in a separate wrapper
# if needed. This adapter reads the standard client's published full snapshots.
set -euo pipefail
(( $# == 3 )) || { echo 'Usage: pscaiip.sh FQDN IPv4 IPv6' >&2; exit 1; }
for file in "$@"; do cat -- "$file"; printf '\n'; done
