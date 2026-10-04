#!/usr/bin/env bash
set -euo pipefail
root=/var/lib/linglong-jazzy-24.04
stage=/mnt/c/Users/Administrator/Desktop/linglong_1025_2
# Every invocation uses a private mount namespace; mounts disappear on exit.
if [[ ${LINGLONG_PRIVATE_MOUNTS:-0} != 1 ]]; then
  exec unshare --mount --propagation private env LINGLONG_PRIVATE_MOUNTS=1 bash "$0" "$@"
fi
mount --rbind /dev "$root/dev"
mount -t proc proc "$root/proc"
mount --bind "$stage" "$root/workspace"
exec chroot "$root" /usr/bin/env LANG=C.UTF-8 LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive "$@"
