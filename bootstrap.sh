#!/usr/bin/env bash
# Check first. Never install packages without an interactive confirmation.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mode=${1:---check}
case "$mode" in --check|--init|--install-ivass) ;; *) echo 'Usage: bootstrap.sh [--check|--init|--install-ivass]' >&2; exit 1 ;; esac
PYTHON=${KIT_PYTHON:-python3}
command -v "$PYTHON" >/dev/null || { echo 'Install Python >= 3.8.10 using your OS package manager.' >&2; exit 1; }
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8,10) else "Python >= 3.8.10 required")'
for tool in bash; do command -v "$tool" >/dev/null || exit 1; done
if [[ $mode == --install-ivass ]]; then
    [[ -t 0 ]] || { echo 'Interactive confirmation required; no packages installed.' >&2; exit 1; }
    printf 'Create .venv and download pypdf from PyPI for IVASS? [y/N] '
    read -r answer
    case "$answer" in y|Y|yes|YES)
        "$PYTHON" -m venv "$ROOT/.venv"
        "$ROOT/.venv/bin/python3" -m pip install -r "$ROOT/requirements-ivass.txt"
        ;; *) echo 'Installation cancelled.'; exit 0 ;; esac
fi
if [[ $mode == --init ]]; then
    umask 077
    for name in kit.ini manuale.txt whitelist-domains.txt whitelist-ips.txt; do
        if [[ ! -e "$ROOT/config/$name" ]]; then cp "$ROOT/config/$name.example" "$ROOT/config/$name"; fi
    done
fi
if [[ -f "$ROOT/config/kit.ini" ]]; then
    "$ROOT/bin/kit-censura-ng" -c "$ROOT/config/kit.ini" doctor
else
    echo 'Core prerequisites OK. Run ./bootstrap.sh --init to create local configuration.'
fi
