#!/bin/bash
# Rebuilds this fork's Madeira source tree: upstream Madeira at the commit in
# UPSTREAM, its submodules (Wine, FEX, DXMT, Madeira Dock), then the patches in
# patches/ applied as commits on a branch named "iwls".
#
#   madeira/prepare.sh [DEST]        (default: madeira/work/Madeira)
#
# To change the fork: edit DEST, commit there, then export the series again:
#   git -C DEST format-patch --no-numbered --zero-commit -o madeira/patches "$(cat madeira/UPSTREAM)"..iwls
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HERE/work/Madeira}"
COMMIT="$(tr -d '[:space:]' < "$HERE/UPSTREAM")"
URL=https://github.com/willfaust/Madeira.git

if [ ! -d "$DEST/.git" ]; then
    mkdir -p "$DEST"
    git -C "$DEST" init -q
    git -C "$DEST" remote add origin "$URL"
fi
git -C "$DEST" fetch -q --depth 1 origin "$COMMIT"
git -C "$DEST" checkout -q --detach "$COMMIT"
git -C "$DEST" submodule update --init --recursive --depth 1 --jobs 4
git -C "$DEST" checkout -q -B iwls "$COMMIT"
shopt -s nullglob
patches=("$HERE"/patches/*.patch)
if [ ${#patches[@]} -gt 0 ]; then
    git -C "$DEST" -c user.name=iwls -c user.email=iwls@localhost am -q --3way "${patches[@]}"
fi
echo "Madeira $COMMIT + ${#patches[@]} patch(es) -> $DEST"
