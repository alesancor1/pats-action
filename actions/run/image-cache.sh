#!/usr/bin/env bash
# carries the lxd images `pats init` builds from one runner to the next, through
# a directory init reads with --image-cache. the cache itself is actions/cache's.
#
#   image-cache.sh prepare   the directory and the cache key prefix, to
#                            $GITHUB_OUTPUT as dir / prefix
#   image-cache.sh export    after an init: the server's pats-img-* images into
#                            IMAGE_CACHE_DIR, files of no such image out of it,
#                            and key / changed to $GITHUB_OUTPUT
#
# the prefix scopes a cache to a pats version and an INIT_ARGS (the sandboxes a
# job makes). the key adds the set of images, so a cache is saved only when the
# set differs from the restored one's, and the run, since a cache key can't be
# saved twice: a set seen before still becomes the newest under the prefix.
# pats checks each file's key itself: a stale one is not used.
# the images are the cli's default remote's, in pats' lxd project.
set -euo pipefail

: "${GITHUB_OUTPUT:?}"

ALIAS_RE='^pats-img-[0-9a-f]{24}$'

_hash() {
  sha256sum | cut -c1-12
}

_prepare() {
  local dir="${IMAGE_CACHE_DIR:-$HOME/pats-image-cache}" version scope
  version="$(pats --version | head -n1 | _hash)"
  scope="$(printf '%s' "${INIT_ARGS:-}" | _hash)"
  mkdir -p "$dir"
  {
    echo "dir=$dir"
    echo "prefix=pats-images-$version-$scope-"
  } >> "$GITHUB_OUTPUT"
}

# _aliases: the pats-img-* aliases on the server, one per line, sorted. a failed
# list fails the export before it touches the directory. no pats project: init
# made no lxd sandbox, so no images.
_aliases() {
  local projects
  projects="$(lxc project list --format json)" || return 1
  jq -e 'any(.[]; .name == "pats")' <<< "$projects" > /dev/null || return 0
  lxc image list --project pats --format json |
    jq -r '.[].aliases[]?.name' | { grep -E "$ALIAS_RE" || true; } | sort -u
}

_export() {
  : "${IMAGE_CACHE_DIR:?}" "${IMAGE_CACHE_PREFIX:?}"
  local dir="$IMAGE_CACHE_DIR" aliases a f name stem key changed
  aliases="$(_aliases)"
  while read -r a; do
    [ -n "$a" ] || continue
    if ! compgen -G "$dir/$a.tar*" > /dev/null; then
      echo "exporting $a"
      lxc image export "$a" "$dir/$a" --project pats
    fi
  done <<< "$aliases"
  # an image this job's server lacks was not one its init wanted.
  for f in "$dir"/*; do
    [ -e "$f" ] || continue
    name="$(basename "$f")"
    name="${name%%.tar*}"
    if ! grep -qx -- "$name" <<< "$aliases"; then
      echo "dropping $(basename "$f")"
      rm -f -- "$f"
    fi
  done
  stem="$IMAGE_CACHE_PREFIX$(printf '%s\n' "$aliases" | _hash)-"
  key="$stem${GITHUB_RUN_ID:-0}-${GITHUB_RUN_ATTEMPT:-1}"
  changed=true
  if [ -z "$aliases" ] || [[ "${IMAGE_CACHE_MATCHED_KEY:-}" == "$stem"* ]]; then
    changed=false
  fi
  {
    echo "key=$key"
    echo "changed=$changed"
  } >> "$GITHUB_OUTPUT"
}

main() {
  case "${1:-}" in
    prepare) _prepare ;;
    export) _export ;;
    *) echo "usage: image-cache.sh prepare|export" >&2; exit 2 ;;
  esac
}

main "$@"
