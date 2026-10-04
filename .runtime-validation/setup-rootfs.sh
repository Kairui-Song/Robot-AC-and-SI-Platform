#!/usr/bin/env bash
set -euo pipefail
stage=/mnt/c/Users/Administrator/Desktop/linglong_1025_2
root=/var/lib/linglong-jazzy-24.04
mkdir -p "$root"
if [[ ! -f "$root/etc/os-release" ]]; then
  tar -xpf "$stage/.runtime-validation/ubuntu-base.tar.gz" -C "$root"
fi
mkdir -p "$root/workspace" "$root/usr/share/keyrings"
cp --remove-destination /etc/resolv.conf "$root/etc/resolv.conf"
cp "$stage/.runtime-validation/ros.key" "$root/usr/share/keyrings/ros-archive-keyring.gpg"
printf '%s\n' 'deb [arch=amd64 signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu noble main' > "$root/etc/apt/sources.list.d/ros2.list"
printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod +x "$root/usr/sbin/policy-rc.d"
cat "$root/etc/os-release"
