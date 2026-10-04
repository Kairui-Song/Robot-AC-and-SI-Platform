#pragma once

#include <array>
#include <cstdint>

namespace linglong_control
{
// Stable wire values shared with system_state.py. ACTIVE means enabled cyclic
// hardware, never proof that a trajectory is executing or that a stop completed.
enum class HardwareState : int
{
  UNINITIALIZED = 0, INIT = 1, DISCOVERING = 2, CONFIGURING = 3,
  INACTIVE = 4, ACTIVATING = 5, ACTIVE = 6, FAULT = 7,
  RECOVERING = 8, SHUTDOWN = 9
};

class HardwareStateMachine
{
public:
  HardwareState state() const {return state_;}
  std::uint64_t sequence() const {return sequence_;}
  bool transition(HardwareState next)
  {
    using S = HardwareState;
    if (state_ == S::SHUTDOWN || next == state_) {return false;}
    bool allowed = next == S::FAULT || next == S::SHUTDOWN;
    switch (state_) {
      case S::UNINITIALIZED: allowed |= next == S::INIT; break;
      case S::INIT: allowed |= next == S::DISCOVERING; break;
      case S::DISCOVERING: allowed |= next == S::CONFIGURING; break;
      case S::CONFIGURING: allowed |= next == S::INACTIVE; break;
      case S::INACTIVE: allowed |= next == S::ACTIVATING || next == S::INIT; break;
      case S::ACTIVATING: allowed |= next == S::ACTIVE; break;
      case S::ACTIVE: allowed |= next == S::INACTIVE; break;
      case S::FAULT: allowed |= next == S::RECOVERING; break;
      case S::RECOVERING: allowed |= next == S::INIT; break;
      case S::SHUTDOWN: break;
    }
    if (!allowed) {return false;}
    state_ = next;
    ++sequence_;
    return true;
  }
private:
  HardwareState state_{HardwareState::UNINITIALIZED};
  std::uint64_t sequence_{0};
};

inline constexpr std::array<const char *, 11> control_health_names{
  "mock", "active", "fault_code", "cycles", "period_seconds", "max_period_seconds",
  "deadline_misses", "feedback_age_seconds", "hardware_state", "transition_sequence",
  "commands_enabled"};
}  // namespace linglong_control
