#pragma once

#include <array>
#include <chrono>
#include <memory>
#include <vector>
#include "hardware_interface/system_interface.hpp"
#include "linglong_control/sim_core.hpp"

namespace linglong_control
{
class SimSystem : public hardware_interface::SystemInterface
{
public:
  hardware_interface::CallbackReturn on_init(const hardware_interface::HardwareInfo &) override;
  std::vector<hardware_interface::StateInterface> export_state_interfaces() override;
  std::vector<hardware_interface::CommandInterface> export_command_interfaces() override;
  hardware_interface::CallbackReturn on_configure(const rclcpp_lifecycle::State &) override;
  hardware_interface::CallbackReturn on_activate(const rclcpp_lifecycle::State &) override;
  hardware_interface::CallbackReturn on_deactivate(const rclcpp_lifecycle::State &) override;
  hardware_interface::CallbackReturn on_cleanup(const rclcpp_lifecycle::State &) override;
  hardware_interface::CallbackReturn on_shutdown(const rclcpp_lifecycle::State &) override;
  hardware_interface::CallbackReturn on_error(const rclcpp_lifecycle::State &) override;
  hardware_interface::return_type read(const rclcpp::Time &, const rclcpp::Duration &) override;
  hardware_interface::return_type write(const rclcpp::Time &, const rclcpp::Duration &) override;
  hardware_interface::return_type prepare_command_mode_switch(
    const std::vector<std::string> &, const std::vector<std::string> &) override;
  hardware_interface::return_type perform_command_mode_switch(
    const std::vector<std::string> &, const std::vector<std::string> &) override;

private:
  void update_states();
  std::unique_ptr<SimCore> core_;
  std::vector<double> positions_, velocities_, commands_;
  std::vector<std::string> command_keys_;
  bool commands_enabled_{false};
  static constexpr std::array<const char *, 8> health_names_{
    "mock", "active", "fault_code", "cycles", "period_seconds", "max_period_seconds",
    "deadline_misses", "feedback_age_seconds"};
  std::array<double, 8> health_{};
  std::chrono::steady_clock::time_point last_read_;
};
}  // namespace linglong_control
