---
name: ros-control-integration
description: Connects and verifies this project's Web platform, system state machine and ROS Jazzy ros2_control stack. Use when explicitly requested to integrate ROS control, lifecycle supervision or four-joint feedback.
disable-model-invocation: true
---

# ROS control integration

User objective: 全部接入打通

Work in the source project, not `delivery`, `.ros-system`, `build-*` or `install-*` copies.

1. Follow the chain: `app.py` → `ros_control_bridge.py` → `linglong_control_tools/web_gateway.py` → `/system/*` or FollowJointTrajectory → controller manager → hardware plugin → `/dynamic_joint_states` → supervisor and Web feedback.
2. Keep `system_manager` the sole normal lifecycle owner. Start hardware and trajectory controller inactive; require READY and explicit enable. Never bypass the supervisor by activating controllers directly from the Web API.
3. Export `hardware_state`, `transition_sequence` and `commands_enabled` consistently in both plugins and the xacro. Keep Python and C++ wire IDs aligned.
4. Check stale feedback, frozen cycle counters, lifecycle timeouts, rejected Actions, cancel results, fault stop, recovery and terminal shutdown. Request acceptance is not completion.
5. Use fresh measured radians and validated limits for trajectories. Physical configuration must pass the existing commissioning checks; physical faults require cause correction and stack restart. Never execute physical motion for an integration test without explicit authorization.
6. Keep direct EtherCAT motion tests disabled whenever `LINGLONG_ROS_URL` is configured. Do not silently fall back from ROS to direct writes.
7. Run Python tests, ROS-independent C++ tests and `ros2_ws/tools/verify_web_integration.py` in ROS Jazzy. State clearly which layers ran and which remain unverified. Do not cite old delivery records as evidence for new code.

See `ros2_ws/WEB_CONTROL.md` for deployment and the API contract.
