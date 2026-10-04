#!/usr/bin/env bash
set -eo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ${LINGLONG_CLEAN_BUILD:-} != "$root" ]]; then
  exec env -i HOME="$HOME" USER="${USER:-}" LANG=C.UTF-8 \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LINGLONG_CLEAN_BUILD="$root" bash "$0" "$@"
fi
cd "$root"
source /opt/ros/jazzy/setup.bash
python3 tools/check_release.py
if [[ ${1:-} == --install-deps ]]; then
  rosdep install --from-paths src --ignore-src -r -y --rosdistro jazzy
fi
# Plain install avoids executable-bit loss through Windows symlinks.
chmod +x src/linglong_control/scripts/*
colcon --log-base log-release build --build-base build-release --install-base install-release \
  --packages-up-to linglong_control --cmake-args -DLINGLONG_CORE_ONLY=OFF -DCMAKE_BUILD_TYPE=Debug
bash tools/ros_release.sh --record-install
bash tools/ros_release.sh --verify
bash tools/ros_release.sh --build-test
