#!/usr/bin/env bash
# TLS verification remains enabled. URL/timeout are configuration arguments.
set -euo pipefail
url=${1:?URL required}
timeout=${2:-60}
exec curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 10 --max-time "$timeout" --retry 2 "$url"
