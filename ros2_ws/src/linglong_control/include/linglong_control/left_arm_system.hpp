#pragma once

#include <array>
#include <chrono>
#include <memory>
#include <mutex>
#include <vector>
#include "hardware_interface/system_interface.hpp"
#include "linglong_control/left_arm_bus.hpp"
#include "linglong_control/hardware_state.hpp"

namespace linglong_control
{
class LeftArmSystem : public hardware_interface::SystemInterface
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
  bool startup(bool enable);
  void states();
  void stop();
  std::mutex mutex_;
  LeftArmBus bus_;
  ArmBusConfig bus_config_;
  std::unique_ptr<LeftArmCore> core_;
  ArmTargets positions_{}, velocities_{}, commands_{};
  std::vector<std::string> keys_;
  HardwareStateMachine state_;
  static constexpr auto health_names_ = control_health_names;
  std::array<double, control_health_names.size()> health_{};
  std::array<double, 9> bus_health_{};
  std::array<std::array<double, 7>, 4> slave_health_{};
  bool first_fault_recorded_{false};
  double period_{0.01}, cycle_timeout_{0.1}, startup_timeout_{5.0};
  bool configured_{false}, commands_enabled_{false};
  std::chrono::steady_clock::time_point last_read_;
};
}  // namespace linglong_control
