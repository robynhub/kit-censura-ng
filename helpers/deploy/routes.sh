#!/usr/bin/env bash
# Reconcile only routes owned by the configured protocol/table. Linux + iproute2.
set -euo pipefail
file=${1:?}; table=${2:?}; protocol=${3:?}; via4=${4-}; via6=${5-}
[[ $table =~ ^[0-9]+$ && $protocol =~ ^[0-9]+$ ]]
(( table > 0 && table < 4294967296 && protocol > 4 && protocol < 256 ))
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
for family in 4 6; do
    if [[ $family == 4 ]]; then
        awk 'NF && !/:/' "$file" | sort -u > "$work/want"
        via=$via4
    else
        awk '/:/' "$file" | sort -u > "$work/want"
        via=$via6
    fi
    ip -"$family" -o route show table "$table" proto "$protocol" > "$work/observed"
    # Normalize the textual route prefix (ip prints host routes without /32 or /128).
    awk -v family="$family" '{ p=($1=="blackhole" ? $2 : $1); if (p=="default") p=(family==4?"0.0.0.0/0":"::/0"); else if (p !~ /\//) p=p (family==4?"/32":"/128"); print p }' \
        "$work/observed" | sort -u > "$work/have"
    while IFS= read -r prefix; do
        [[ -n $prefix ]] || continue
        action=add
        if grep -Fxq -- "$prefix" "$work/have"; then action=replace; fi
        if [[ -n $via ]]; then
            ip -"$family" route "$action" "$prefix" via "$via" table "$table" proto "$protocol"
        else
            ip -"$family" route "$action" blackhole "$prefix" table "$table" proto "$protocol"
        fi
    done < "$work/want"
    # Delete obsolete owned routes only after every requested addition succeeded.
    comm -23 "$work/have" "$work/want" > "$work/remove"
    while IFS= read -r prefix; do
        [[ -n $prefix ]] || continue
        ip -"$family" route del "$prefix" table "$table" proto "$protocol"
    done < "$work/remove"
done
