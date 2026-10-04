#!/usr/bin/env bash
set -eo pipefail
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg build-essential cmake git \
  python3-colcon-common-extensions python3-pytest python3-yaml \
  ros-jazzy-ros-base ros-jazzy-ros2-control ros-jazzy-ros2-controllers \
  ros-jazzy-xacro ros-jazzy-robot-state-publisher ros-jazzy-rviz2 \
  ros-jazzy-ament-cmake-pytest ros-jazzy-ament-cmake-gtest
