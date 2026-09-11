#!/usr/bin/env bash
# Runs on a Linux DNS server. The current symlink is the single activation point.
set -euo pipefail
backend=${1:?}; root=${2:?}; id=${3:?}; main_config=${4:?}
stage="$root/releases/$id"
mkdir "$root/.activate-lock" || { echo 'Another deployment is active' >&2; exit 1; }
old=''; switched=false
cleanup() {
    rc=$?
    trap - EXIT
    if (( rc != 0 )) && $switched; then
        if [[ -n $old ]]; then
            ln -s -- "$old" "$root/.rollback-$id"
            mv -Tf -- "$root/.rollback-$id" "$root/current"
        else
            rm -- "$root/current"
        fi
        # Reload the previous configuration; preserve failure status if rollback fails.
        if [[ $backend == bind ]]; then rndc reconfig || echo 'ROLLBACK RELOAD FAILED' >&2
        else unbound-control reload || echo 'ROLLBACK RELOAD FAILED' >&2; fi
    fi
    rmdir "$root/.activate-lock"
    exit "$rc"
}
trap cleanup EXIT
[[ ! -e $root/current || -L $root/current ]] || { echo 'current must be a symlink' >&2; exit 1; }
if [[ -L $root/current ]]; then old=$(readlink -- "$root/current"); fi
if [[ $backend == bind ]]; then
    # Each domain must validate with its category zone before activation.
    while read -r domain zone; do
        named-checkzone "$domain" "$stage/zones/$zone" >/dev/null
    done < <(awk -F '"' '/^zone / { n=split($4,p,"/"); print $2,p[n] }' "$stage/named.conf")
else
    unbound-checkconf "$stage/unbound.conf"
fi
ln -s -- "releases/$id" "$root/.next-$id"
mv -Tf -- "$root/.next-$id" "$root/current"
switched=true
if [[ $backend == bind ]]; then
    named-checkconf "$main_config"
    rndc reconfig
else
    unbound-checkconf "$main_config"
    unbound-control reload
fi
switched=false
