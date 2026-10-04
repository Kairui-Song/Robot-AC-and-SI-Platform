#include <gtest/gtest.h>
#include "linglong_control/sim_system.hpp"
#include "pluginlib/class_loader.hpp"

namespace
{
hardware_interface::HardwareInfo description()
{
  hardware_interface::HardwareInfo info{};
  info.is_async = false;
  info.name = "TestMock";
  info.type = "system";
  info.hardware_parameters = {{"backend", "mock"}, {"nominal_period", "0.01"},
    {"cycle_timeout", "0.5"}, {"feedback_timeout", "0.1"},
    {"fault_after_cycles", "0"}, {"dropout_after_cycles", "0"}};
  for (const auto & name : {"joint_1", "joint_2", "joint_3", "joint_5"}) {
    hardware_interface::ComponentInfo joint;
    joint.name = name;
    joint.type = "joint";
    joint.parameters = {{"lower", "-1.57"}, {"upper", "1.57"}, {"initial_position", "0.2"},
      {"max_velocity", "0.1"}, {"max_command_step", "0.05"}, {"max_following_error", "0.15"}};
    hardware_interface::InterfaceInfo position;
    position.name = "position";
    hardware_interface::InterfaceInfo velocity;
    velocity.name = "velocity";
    joint.command_interfaces = {position};
    joint.state_interfaces = {position, velocity};
    info.joints.push_back(joint);
  }
  hardware_interface::ComponentInfo sensor;
  sensor.name = "control_health";
  sensor.type = "sensor";
  for (const auto & name : {"mock", "active", "fault_code", "cycles", "period_seconds",
    "max_period_seconds", "deadline_misses", "feedback_age_seconds", "hardware_state",
    "transition_sequence", "commands_enabled"})
  {
    hardware_interface::InterfaceInfo state;
    state.name = name;
    sensor.state_interfaces.push_back(state);
  }
  info.sensors.push_back(sensor);
  return info;
}
}  // namespace

TEST(SimPlugin, DiscoveredViaPluginlib)
{
  pluginlib::ClassLoader<hardware_interface::SystemInterface> loader(
    "hardware_interface", "hardware_interface::SystemInterface");
  EXPECT_NE(loader.createSharedInstance("linglong_control/SimSystem"), nullptr);
}

TEST(SimPlugin, HardwareBackendNeverFallsBackToMock)
{
  auto info = description();
  info.hardware_parameters["backend"] = "ethercat";
  linglong_control::SimSystem system;
  EXPECT_EQ(system.on_init(info), hardware_interface::CallbackReturn::ERROR);
}

TEST(SimPlugin, InterfacesActivationAndFaultLatch)
{
  linglong_control::SimSystem system;
  ASSERT_EQ(system.on_init(description()), hardware_interface::CallbackReturn::SUCCESS);
  auto states = system.export_state_interfaces();
  auto commands = system.export_command_interfaces();
  ASSERT_EQ(states.size(), 19u);
  ASSERT_EQ(commands.size(), 4u);
  const rclcpp_lifecycle::State previous;
  ASSERT_EQ(system.on_configure(previous), hardware_interface::CallbackReturn::SUCCESS);
  ASSERT_EQ(system.on_activate(previous), hardware_interface::CallbackReturn::SUCCESS);
  for (auto & command : commands) {EXPECT_DOUBLE_EQ(command.get_value(), 0.2);}
  const std::vector<std::string> keys{
    "joint_1/position", "joint_2/position", "joint_3/position", "joint_5/position"};
  EXPECT_EQ(system.prepare_command_mode_switch({keys[0]}, {}), hardware_interface::return_type::ERROR);
  EXPECT_EQ(system.prepare_command_mode_switch({keys[0], keys[0], keys[0], keys[0]}, {}),
    hardware_interface::return_type::ERROR);
  ASSERT_EQ(system.prepare_command_mode_switch(keys, {}), hardware_interface::return_type::OK);
  ASSERT_EQ(system.perform_command_mode_switch(keys, {}), hardware_interface::return_type::OK);
  (void)commands[3].set_value(2.0);
  EXPECT_EQ(system.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)),
    hardware_interface::return_type::ERROR);
  EXPECT_TRUE(std::isnan(states[0].get_value()));
  EXPECT_EQ(system.on_error(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(system.on_activate(previous), hardware_interface::CallbackReturn::FAILURE);
  // Explicit configure also recovers MOCK after framework error handling has
  // already moved the lifecycle to UNCONFIGURED (cleanup would be a no-op).
  EXPECT_EQ(system.on_configure(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(system.on_cleanup(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(system.on_configure(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(system.on_activate(previous), hardware_interface::CallbackReturn::SUCCESS);
}

TEST(SimPlugin, StateGuardsOwnershipAndTerminalShutdown)
{
  linglong_control::SimSystem system;
  ASSERT_EQ(system.on_init(description()), hardware_interface::CallbackReturn::SUCCESS);
  auto states = system.export_state_interfaces();
  const auto phase = [&states]() {return states[16].get_value();};
  const rclcpp_lifecycle::State previous;
  EXPECT_EQ(phase(), 1);  // INIT
  EXPECT_EQ(system.on_activate(previous), hardware_interface::CallbackReturn::FAILURE);
  EXPECT_EQ(phase(), 1);
  ASSERT_EQ(system.on_configure(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(phase(), 4);  // INACTIVE
  const std::vector<std::string> keys{
    "joint_1/position", "joint_2/position", "joint_3/position", "joint_5/position"};
  EXPECT_EQ(system.perform_command_mode_switch(keys, {}), hardware_interface::return_type::ERROR);
  ASSERT_EQ(system.on_activate(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(phase(), 6);
  EXPECT_EQ(system.on_cleanup(previous), hardware_interface::CallbackReturn::FAILURE);
  EXPECT_EQ(system.perform_command_mode_switch({keys[0]}, {}), hardware_interface::return_type::ERROR);
  EXPECT_EQ(system.perform_command_mode_switch(keys, {}), hardware_interface::return_type::OK);
  EXPECT_EQ(states[18].get_value(), 1);
  EXPECT_EQ(system.on_deactivate(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(phase(), 4);
  EXPECT_EQ(states[18].get_value(), 0);
  EXPECT_EQ(system.on_shutdown(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(phase(), 9);
  EXPECT_EQ(system.on_configure(previous), hardware_interface::CallbackReturn::FAILURE);
  EXPECT_EQ(system.on_activate(previous), hardware_interface::CallbackReturn::FAILURE);
}

TEST(SimPlugin, SupervisedFaultPublishesLatchUntilOrderedRelease)
{
  auto info = description();
  info.hardware_parameters["supervised_fault_stop"] = "true";
  info.hardware_parameters["fault_after_cycles"] = "2";
  linglong_control::SimSystem system;
  ASSERT_EQ(system.on_init(info), hardware_interface::CallbackReturn::SUCCESS);
  auto states = system.export_state_interfaces();
  auto commands = system.export_command_interfaces();
  const rclcpp_lifecycle::State previous;
  ASSERT_EQ(system.on_configure(previous), hardware_interface::CallbackReturn::SUCCESS);
  ASSERT_EQ(system.on_activate(previous), hardware_interface::CallbackReturn::SUCCESS);
  const std::vector<std::string> keys{
    "joint_1/position", "joint_2/position", "joint_3/position", "joint_5/position"};
  ASSERT_EQ(system.perform_command_mode_switch(keys, {}), hardware_interface::return_type::OK);
  const auto tick = [&]() {return system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));};
  EXPECT_EQ(tick(), hardware_interface::return_type::OK);
  EXPECT_EQ(tick(), hardware_interface::return_type::OK);
  EXPECT_EQ(states[9].get_value(), 0);  // active
  EXPECT_EQ(states[10].get_value(), 7);  // injected fault
  EXPECT_EQ(states[18].get_value(), 0);  // commands disabled
  const double cycles = states[11].get_value();
  for (int i = 0; i < 10; ++i) {
    (void)commands[0].set_value(.3);
    EXPECT_EQ(system.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)),
      hardware_interface::return_type::OK);
    EXPECT_EQ(tick(), hardware_interface::return_type::OK);
    EXPECT_EQ(states[11].get_value(), cycles);  // No fabricated progress while faulted.
    EXPECT_TRUE(std::isnan(states[0].get_value()));
    EXPECT_EQ(states[10].get_value(), 7);
  }
  EXPECT_EQ(system.perform_command_mode_switch(keys, {}), hardware_interface::return_type::ERROR);
  EXPECT_EQ(system.perform_command_mode_switch({}, keys), hardware_interface::return_type::OK);
  EXPECT_EQ(system.on_deactivate(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(system.on_activate(previous), hardware_interface::CallbackReturn::FAILURE);
  EXPECT_EQ(states[10].get_value(), 7);
  EXPECT_EQ(system.on_cleanup(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(system.on_configure(previous), hardware_interface::CallbackReturn::SUCCESS);
  EXPECT_EQ(states[9].get_value(), 0);
}
