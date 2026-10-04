// Actual ROS hardware plugin with a fake IgH transport: never opens a device.
#include "fake_left_arm_bus.hpp"
#include "linglong_control/left_arm_system.hpp"
#include <future>

hardware_interface::HardwareInfo description()
{
  hardware_interface::HardwareInfo info{};
  info.name = "TestLeftArm";
  info.type = "system";
  info.is_async = false;
  info.hardware_parameters = {{"backend", "ethercat_left_arm"}, {"commissioning_confirmed", "true"},
    {"nominal_period", "0.01"}, {"cycle_timeout", "0.1"}, {"startup_timeout", "1"},
    {"master_index", "0"}, {"vendor_id", "4247"}, {"product_code", "9222"},
    {"dc_assign_activate", "0"}, {"watchdog_divider", "0"}, {"watchdog_intervals", "1000"}};
  for (std::size_t i=0; i<4; ++i) {
    hardware_interface::ComponentInfo joint{};
    joint.name = left_arm_names[i];
    joint.type = "joint";
    joint.parameters = {{"slave_position", std::to_string(left_arm_slaves[i])},
      {"counts_per_radian", "100000"}, {"zero_counts", "1000"},
      {"velocity_counts_per_rad_s", "100000"}, {"lower", "-1"}, {"upper", "1"},
      {"max_command_step", ".05"}, {"max_following_error", ".15"}, {"max_velocity", "1"}};
    hardware_interface::InterfaceInfo position{}, velocity{};
    position.name = "position";
    velocity.name = "velocity";
    joint.command_interfaces = {position};
    joint.state_interfaces = {position, velocity};
    info.joints.push_back(joint);
  }
  hardware_interface::ComponentInfo sensor{};
  sensor.name = "control_health";
  sensor.type = "sensor";
  for (auto name : control_health_names) {
    hardware_interface::InterfaceInfo interface{};
    interface.name = name;
    sensor.state_interfaces.push_back(interface);
  }
  info.sensors.push_back(sensor);
  return info;
}

int main()
{
  using C = hardware_interface::CallbackReturn;
  using R = hardware_interface::return_type;
  const rclcpp_lifecycle::State previous;
  const std::vector<std::string> keys{
    "joint_1/position", "joint_2/position", "joint_3/position", "joint_5/position"};
  emulate_drives = true;
  {
    // Hold the lifecycle thread inside real plugin startup. Periodic calls
    // must return before it is released, without entering the fake bus.
    LeftArmSystem system;
    check(system.on_init(description()) == C::SUCCESS);
    check(system.on_configure(previous) == C::SUCCESS);
    auto states = system.export_state_interfaces();
    auto commands = system.export_command_interfaces();
    for (auto & command : commands) {check(command.set_value(.9));}
    const auto cycles_before = states[11].get_value();
    const auto phase_before = states[16].get_value();
    const auto position_before = states[0].get_value();
    std::promise<void> entered, release;
    auto entered_future = entered.get_future();
    auto released = release.get_future().share();
    bool first = true;
    receive_hook = [&] {
        if (first) {
          first = false;
          entered.set_value();
          released.wait_for(std::chrono::seconds(2));
        }
      };
    auto activation = std::async(std::launch::async, [&] {return system.on_activate(previous);});
    const bool started = entered_future.wait_for(std::chrono::seconds(1)) == std::future_status::ready;
    auto periodic = std::async(std::launch::async, [&] {
        const auto start = std::chrono::steady_clock::now();
        const auto read = system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
        const auto write = system.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
        const auto mode = system.perform_command_mode_switch(keys, {});
        return std::make_tuple(read, write, mode,
          std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count());
      });
    const bool bounded = periodic.wait_for(std::chrono::milliseconds(100)) == std::future_status::ready;
    release.set_value();
    const auto activated = activation.get();
    const auto result = periodic.get();
    receive_hook = {};
    check(started && bounded && activated == C::SUCCESS);
    check(std::get<0>(result) == R::OK && std::get<1>(result) == R::OK);
    check(std::get<2>(result) == R::ERROR);
    check(states[11].get_value() == cycles_before);  // no fabricated read
    check(states[16].get_value() == phase_before && states[0].get_value() == position_before);
    for (auto & command : commands) {check(command.get_value() == .9);}
    check(system.perform_command_mode_switch(keys, {}) == R::OK);
    for (auto & command : commands) {check(command.get_value() == .1);}
    check(system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == R::OK);
    check(system.write(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == R::OK);
    for (unsigned i=0; i<4; ++i) {check(EC_READ_S32(image.data()+i*24) == 11000);}
    std::cout << "Contended read/write/mode-switch duration: " << std::get<3>(result) << " s\n";
    check(system.on_shutdown(previous) == C::SUCCESS);
  }
  for (int failure = 0; failure < 4; ++failure) {
    LeftArmSystem system;
    check(system.on_init(description()) == C::SUCCESS);
    auto states = system.export_state_interfaces();
    check(states.size() == 19);
    check(system.on_activate(previous) == C::FAILURE);
    check(system.on_configure(previous) == C::SUCCESS);
    (void)system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
    check(states[16].get_value() == 4);
    for (unsigned i=0; i<4; ++i) {check(EC_READ_U16(image.data()+i*24+4) == 0);}
    check(system.perform_command_mode_switch(keys, {}) == R::ERROR);
    check(system.on_activate(previous) == C::SUCCESS);
    (void)system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
    check(states[16].get_value() == 6);
    check(system.perform_command_mode_switch(keys, {}) == R::OK);
    check(states[18].get_value() == 1);
    check(system.on_cleanup(previous) == C::FAILURE);
    if (failure == 0) {
      check(system.perform_command_mode_switch({}, keys) == R::OK);
      check(system.on_deactivate(previous) == C::SUCCESS);
      (void)system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
      check(states[16].get_value() == 4 && states[18].get_value() == 0);
      check(system.on_cleanup(previous) == C::SUCCESS);
      (void)system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
      check(states[16].get_value() == 1);
      check(system.on_configure(previous) == C::SUCCESS);
    } else {
      if (failure == 1) {
        incomplete = true;
        check(system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == R::ERROR);
        incomplete = false;
      } else if (failure == 2) {
        send_error = true;
        check(system.on_deactivate(previous) == C::FAILURE);
        send_error = false;
      } else {
        stuck_enabled = true;
        check(system.on_deactivate(previous) == C::FAILURE);
        (void)system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
        check(states[10].get_value() == 11);
        stuck_enabled = false;
      }
      (void)system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
      check(states[16].get_value() == 7 && states[18].get_value() == 0);
      check(system.on_error(previous) == C::SUCCESS);
      check(system.on_cleanup(previous) == C::SUCCESS);
      check(system.on_configure(previous) == C::FAILURE);  // physical fault remains latched
      check(system.on_activate(previous) == C::FAILURE);
    }
    check(system.on_shutdown(previous) == C::SUCCESS);
    (void)system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01));
    check(states[16].get_value() == 9);
    check(system.on_configure(previous) == C::FAILURE);
  }
  {
    LeftArmSystem system;
    check(system.on_init(description()) == C::SUCCESS);
    check(system.on_configure(previous) == C::SUCCESS);
    auto states = system.export_state_interfaces();
    stuck_enabled = true;  // an external actor enables a drive while system is READY
    check(system.read(rclcpp::Time(0), rclcpp::Duration::from_seconds(.01)) == R::ERROR);
    check(states[10].get_value() == 10 && states[16].get_value() == 7);
    stuck_enabled = false;
    check(system.on_shutdown(previous) == C::SUCCESS);
  }
  std::cout << "Physical plugin: guarded lifecycle, drive enable, confirmed disable, stop failure, fault latch and shutdown passed\n";
}
