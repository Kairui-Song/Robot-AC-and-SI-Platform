# Changelog

## Unreleased

- ethercat_bridge.py
  - 为每个状态样本添加时间戳 `ts`，在返回结果中新增 `status_fresh` 和 `status_age_seconds` 字段。
  - 状态新鲜度阈值改为可配置：通过环境变量 `LINGLONG_STATUS_FRESH_SECONDS`（默认 2.0 秒）。
  - 若状态被判为过期，关键 telemetry 字段（`actual_position`/`actual_velocity`/`actual_torque`/等）将置为 `null`，避免向前端展示陈旧数据。

- adapter.py
  - 增加环境开关 `LINGLONG_ENABLE_CAN_MASK`：仅当其值为 `'1'` 时启用 CAN 屏蔽/接口切换，默认禁用以避免故障停用时的意外切换。
  - 在调用 `can_mask.disable_all_except` 时增加异常捕获与 `logger.exception`，记录完整堆栈信息并在失败时安全回退。

- tools/simulate_benchmark_run.py
  - 新增本地模拟脚本，用于验证 `ethercat_bridge.run_controller_benchmark` 的解析与新鲜度逻辑。
