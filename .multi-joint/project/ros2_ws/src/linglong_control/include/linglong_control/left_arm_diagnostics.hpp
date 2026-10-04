#pragma once
#include <array>
#include <cstdint>

namespace linglong_control
{
constexpr std::array<const char *, 4> arm_sensor_names{
  "ethercat_slave_1", "ethercat_slave_2", "ethercat_slave_3", "ethercat_slave_5"};
constexpr std::array<const char *, 7> arm_slave_fields{
  "al_state", "online", "operational", "status_word", "mode_display", "state_valid", "sample_valid"};
constexpr std::array<const char *, 9> arm_bus_fields{
  "link_up", "working_counter", "wc_state", "feedback_valid", "dc_enabled",
  "first_fault_slave", "first_fault_cycle", "last_good_cycle", "state_valid"};
struct ArmSlaveDiagnostic
{
  unsigned al_state{};
  bool online{}, operational{}, state_valid{}, sample_valid{};
  std::uint16_t status{};
  std::int8_t mode{};
};
struct ArmBusDiagnostic
{
  bool link_up{}, valid{}, state_valid{};
  unsigned working_counter{}, wc_state{};
  std::array<ArmSlaveDiagnostic, 4> slaves{};
};
}  // namespace linglong_control
