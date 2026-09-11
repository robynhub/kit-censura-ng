#!/usr/bin/env bash
# Transfer only generated DNS artifacts. No raw lists, credentials or audit logs.
set -euo pipefail
backend=${1:?}; server=${2:?}; remote_root=${3:?}; generation=${4:?}
main_config=${5:?}; connect_timeout=${6:?}; port=${7:?}
[[ $backend == bind || $backend == unbound ]]
[[ $server =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$ ]]
[[ $remote_root =~ ^/[a-zA-Z0-9_/-]+$ && $remote_root != / && $remote_root != *'/../'* ]]
[[ $main_config =~ ^/[a-zA-Z0-9_./-]+$ && $main_config != *'/../'* ]]
[[ $connect_timeout =~ ^[0-9]+$ && $port =~ ^[0-9]+$ ]]
id=$(basename -- "$generation")
[[ $id =~ ^[a-zA-Z0-9_-]+$ ]]
ssh_args=(-p "$port" -o BatchMode=yes -o "ConnectTimeout=$connect_timeout" -o StrictHostKeyChecking=yes)
stage="$remote_root/releases/$id"
ssh "${ssh_args[@]}" "$server" "mkdir -p -- '$stage/zones'"
transport="ssh -p $port -o BatchMode=yes -o ConnectTimeout=$connect_timeout -o StrictHostKeyChecking=yes"
rsync -rt --chmod=D755,F644 --timeout=60 -e "$transport" \
    "$generation/named.conf" "$generation/unbound.conf" "$server:$stage/"
rsync -rt --chmod=D755,F644 --timeout=60 -e "$transport" "$generation/zones/" "$server:$stage/zones/"
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ssh "${ssh_args[@]}" "$server" "bash -s -- '$backend' '$remote_root' '$id' '$main_config'" < "$ROOT/activate.sh"
