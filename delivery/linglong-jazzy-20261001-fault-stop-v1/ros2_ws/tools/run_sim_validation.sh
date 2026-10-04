#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
cmake -S src/linglong_control -B build-validation \
  -DLINGLONG_CORE_ONLY=ON -DCMAKE_BUILD_TYPE=Release
touch build-validation/COLCON_IGNORE
cmake --build build-validation --parallel 2
ctest --test-dir build-validation --output-on-failure
python3 tools/run_sim_validation.py --binary build-validation/sim_validation "$@"
