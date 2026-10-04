#include "linglong_control/left_arm_system.hpp"

#include <algorithm>
#include <set>
#include <thread>
#include "pluginlib/class_list_macros.hpp"
#include "rclcpp/rclcpp.hpp"

namespace linglong_control
{
namespace
{
using Callback = hardware_interface::CallbackReturn;
using Result = hardware_interface::return_type;
template<class Map> double number(const Map & p, const std::string & key)
{
  std::size_t used = 0;
  const auto & text = p.at(key);
  const double value = std::stod(text, &used);
  if (used != text.size() || !std::isfinite(value)) {throw std::invalid_argument(key);}
  return value;
}
template<class Map> unsigned integer(const Map & p, const std::string & key, double maximum)
{
  const double value = number(p, key);
  if (value < 0 || value > maximum || value != std::floor(value)) {throw std::invalid_argument(key);}
  return static_cast<unsigned>(value);
}
}  // namespace

Callback LeftArmSystem::on_init(const hardware_interface::HardwareInfo & info)
{
  if (SystemInterface::on_init(info) != Callback::SUCCESS) {return Callback::ERROR;}
  try {
    const auto & p = info_.hardware_parameters;
    if (p.at("backend") != "ethercat_left_arm" || p.at("commissioning_confirmed") != "true" ||
      info_.is_async || info_.joints.size() != 4) {
      throw std::invalid_argument("Require commissioned synchronous four-joint left arm");
    }
    std::array<ArmCalibration, 4> calibration{};
    for (std::size_t i = 0; i < 4; ++i) {
      const auto & j = info_.joints[i];
      if (j.name != left_arm_names[i] || j.command_interfaces.size() != 1 ||
        j.command_interfaces[0].name != "position" || j.state_interfaces.size() != 2) {
        throw std::invalid_argument("Require joint_1/2/3/5 in deployed order");
      }
      std::set<std::string> states;
      for (const auto & s : j.state_interfaces) {states.insert(s.name);}
      if (states != std::set<std::string>{"position", "velocity"} ||
        integer(j.parameters, "slave_position", 65535) != left_arm_slaves[i]) {
        throw std::invalid_argument("Invalid left-arm interfaces/slave mapping");
      }
      const auto & q = j.parameters;
      calibration[i] = {number(q, "counts_per_radian"), number(q, "zero_counts"),
        number(q, "velocity_counts_per_rad_s"), number(q, "lower"), number(q, "upper"),
        number(q, "max_command_step"), number(q, "max_following_error"), number(q, "max_velocity")};
      keys_.push_back(j.name + "/position");
    }
    if (info_.sensors.size() != 6 || info_.sensors[0].name != "control_health") {
      throw std::invalid_argument("Missing control_health");
    }
    std::set<std::string> health;
    for (const auto & s : info_.sensors[0].state_interfaces) {health.insert(s.name);}
    if (info_.sensors[0].state_interfaces.size() != 8 ||
      health != std::set<std::string>(health_names_.begin(), health_names_.end())) {
      throw std::invalid_argument("Invalid health interfaces");
    }
    const auto verify_sensor = [this](std::size_t i, const std::string & name, const auto & fields) {
        const auto & sensor = info_.sensors[i];
        std::set<std::string> actual;
        for (const auto & entry : sensor.state_interfaces) {actual.insert(entry.name);}
        if (sensor.name != name || sensor.state_interfaces.size() != fields.size() ||
          actual != std::set<std::string>(fields.begin(), fields.end())) {
          throw std::invalid_argument("Invalid EtherCAT diagnostic sensor: " + name);
        }
      };
    verify_sensor(1, "ethercat_bus", arm_bus_fields);
    for (std::size_t i = 0; i < 4; ++i) {verify_sensor(i + 2, arm_sensor_names[i], arm_slave_fields);}
    bus_health_[5] = -1;
    period_ = number(p, "nominal_period");
    cycle_timeout_ = number(p, "cycle_timeout");
    startup_timeout_ = number(p, "startup_timeout");
    if (period_ < 0.001 || period_ > 0.02 || cycle_timeout_ <= period_ ||
      cycle_timeout_ > 0.5 || startup_timeout_ < 1 || startup_timeout_ > 30) {
      throw std::invalid_argument("Invalid left-arm cycle/startup timing");
    }
    bus_config_.master = integer(p, "master_index", 255);
    bus_config_.vendor = integer(p, "vendor_id", 4294967295.0);
    bus_config_.product = integer(p, "product_code", 4294967295.0);
    if (bus_config_.vendor != 0x1097 || bus_config_.product != 0x2406) {
      throw std::invalid_argument("This plugin is for the existing EYOU left arm only");
    }
    bus_config_.period_ns = static_cast<std::uint32_t>(std::llround(period_ * 1e9));
    bus_config_.dc_assign = integer(p, "dc_assign_activate", 65535);
    bus_config_.watchdog_divider = integer(p, "watchdog_divider", 65535);
    bus_config_.watchdog_intervals = integer(p, "watchdog_intervals", 65535);
    if (!bus_config_.watchdog_intervals) {throw std::invalid_argument("Drive watchdog must be configured");}
    core_ = std::make_unique<LeftArmCore>(calibration);
    positions_.fill(std::numeric_limits<double>::quiet_NaN());
    velocities_ = commands_ = positions_;
  } catch (const std::exception & e) {
    RCLCPP_ERROR(rclcpp::get_logger("left_arm"), "Configuration rejected: %s", e.what());
    return Callback::ERROR;
  }
  return Callback::SUCCESS;
}

std::vector<hardware_interface::StateInterface> LeftArmSystem::export_state_interfaces()
{
  std::vector<hardware_interface::StateInterface> result;
  for (std::size_t i = 0; i < 4; ++i) {
    result.emplace_back(left_arm_names[i], "position", &positions_[i]);
    result.emplace_back(left_arm_names[i], "velocity", &velocities_[i]);
  }
  for (std::size_t i = 0; i < 8; ++i) {result.emplace_back("control_health", health_names_[i], &health_[i]);}
  for (std::size_t i = 0; i < arm_bus_fields.size(); ++i) {
    result.emplace_back("ethercat_bus", arm_bus_fields[i], &bus_health_[i]);
  }
  for (std::size_t joint = 0; joint < 4; ++joint) {
    for (std::size_t i = 0; i < arm_slave_fields.size(); ++i) {
      result.emplace_back(arm_sensor_names[joint], arm_slave_fields[i], &slave_health_[joint][i]);
    }
  }
  return result;
}
std::vector<hardware_interface::CommandInterface> LeftArmSystem::export_command_interfaces()
{
  std::vector<hardware_interface::CommandInterface> result;
  for (std::size_t i = 0; i < 4; ++i) {result.emplace_back(left_arm_names[i], "position", &commands_[i]);}
  return result;
}
void LeftArmSystem::states()
{
  health_[0] = 0;  // Physical PDO feedback; never labelled mock.
  health_[1] = core_->active() ? 1 : 0;
  health_[2] = core_->fault();
  const auto & d = bus_.diagnostic();
  bus_health_[0] = d.link_up;
  bus_health_[1] = d.working_counter;
  bus_health_[2] = d.wc_state;
  bus_health_[3] = d.valid;
  bus_health_[4] = bus_config_.dc_assign != 0;
  bus_health_[8] = d.state_valid;
  if (d.valid && !core_->fault()) {bus_health_[7] = health_[3];}
  if (core_->fault() && !first_fault_recorded_) {
    bus_health_[5] = core_->fault_slave();
    bus_health_[6] = health_[3];
    first_fault_recorded_ = true;
  }
  for (std::size_t i = 0; i < 4; ++i) {
    const auto & s = d.slaves[i];
    slave_health_[i] = {static_cast<double>(s.al_state), static_cast<double>(s.online),
      static_cast<double>(s.operational), static_cast<double>(s.status), static_cast<double>(s.mode),
      static_cast<double>(s.state_valid), static_cast<double>(s.sample_valid)};
  }
  if (core_->fault()) {
    positions_.fill(std::numeric_limits<double>::quiet_NaN());
    velocities_ = positions_;
  } else {positions_ = core_->positions(); velocities_ = core_->velocities();}
}
void LeftArmSystem::stop()
{
  commands_enabled_ = false;
  if (core_) {
    core_->deactivate();
    bus_.send(core_->output());
    states();
  }
}
bool LeftArmSystem::startup(bool enable)
{
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::duration<double>(startup_timeout_);
  auto next = std::chrono::steady_clock::now();
  bool seen_complete = false;
  while (std::chrono::steady_clock::now() < deadline) {
    ArmFrame frame{};
    const bool complete = bus_.receive(frame);
    if (complete) {
      seen_complete = true;
      if (!core_->feedback(frame, true)) {stop(); return false;}
      if (!enable || core_->activate()) {
        if (!bus_.send(core_->output())) {core_->fail(9); stop(); return false;}
        last_read_ = std::chrono::steady_clock::now();
        states();
        commands_ = positions_;
        return true;
      }
    } else if (seen_complete) {
      core_->fail(6, bus_.failed_joint());
      stop();
      return false;
    }
    if (!bus_.send(core_->output(enable && complete))) {core_->fail(9); stop(); return false;}
    next += std::chrono::nanoseconds(bus_config_.period_ns);
    std::this_thread::sleep_until(next);  // lifecycle startup only, never read/write
  }
  core_->fail(11, bus_.failed_joint());
  stop();
  return false;
}
Callback LeftArmSystem::on_configure(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (!core_ || core_->fault() || configured_) {return Callback::FAILURE;}
  try {
    bus_.open(bus_config_);
    if (!startup(false)) {bus_.close(); return Callback::FAILURE;}
    configured_ = true;
    return Callback::SUCCESS;
  } catch (const std::exception & e) {
    core_->fail(9);
    stop(); bus_.close();
    RCLCPP_ERROR(rclcpp::get_logger("left_arm"), "EtherCAT configuration failed: %s", e.what());
    return Callback::FAILURE;
  }
}
Callback LeftArmSystem::on_activate(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (!configured_ || core_->fault()) {return Callback::FAILURE;}
  commands_enabled_ = false;
  return startup(true) ? Callback::SUCCESS : Callback::FAILURE;
}
Callback LeftArmSystem::on_deactivate(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  stop();
  return Callback::SUCCESS;
}
Callback LeftArmSystem::on_cleanup(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  stop(); bus_.close(); configured_ = false;
  // Fault remains latched even through cleanup. Correct cause and restart.
  return Callback::SUCCESS;
}
Callback LeftArmSystem::on_shutdown(const rclcpp_lifecycle::State & s) {return on_cleanup(s);}
Callback LeftArmSystem::on_error(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (core_) {core_->fail(8); stop();}
  if (core_) {
    RCLCPP_ERROR(rclcpp::get_logger("left_arm"),
      "Left-arm fault latched: code=%d slave=%d cycle=%.0f WKC=%.0f wc_state=%.0f; no automatic recovery",
      core_->fault(), core_->fault_slave(), bus_health_[6], bus_health_[1], bus_health_[2]);
  }
  bus_.close(); configured_ = false;
  return Callback::SUCCESS;
}
Result LeftArmSystem::read(const rclcpp::Time &, const rclcpp::Duration &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (!configured_ || core_->fault()) {return Result::ERROR;}
  const auto now = std::chrono::steady_clock::now();
  const double elapsed = std::chrono::duration<double>(now - last_read_).count();
  last_read_ = now;
  health_[3] += 1;
  health_[4] = elapsed;
  health_[5] = std::max(health_[5], elapsed);
  if (elapsed > period_ * 1.5) {health_[6] += 1;}
  ArmFrame frame{};
  const bool complete = bus_.receive(frame);
  health_[7] = complete ? 0 : health_[7] + elapsed;
  if (core_->active() && elapsed > cycle_timeout_) {core_->fail(5);}
  if (!complete) {core_->fail(6, bus_.failed_joint());}
  if (!core_->feedback(frame, complete)) {stop(); return Result::ERROR;}
  states();
  // INACTIVE components may not receive write() calls from controller_manager.
  if (!core_->active() && !bus_.send(core_->output())) {core_->fail(9); stop(); return Result::ERROR;}
  return Result::OK;
}
Result LeftArmSystem::write(const rclcpp::Time &, const rclcpp::Duration &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (!configured_ || core_->fault()) {return Result::ERROR;}
  if (commands_enabled_ && !core_->command(commands_, health_[4])) {stop(); return Result::ERROR;}
  if (!bus_.send(core_->output())) {core_->fail(9); stop(); return Result::ERROR;}
  return Result::OK;
}
Result LeftArmSystem::prepare_command_mode_switch(
  const std::vector<std::string> & start, const std::vector<std::string> & stop_keys)
{
  for (const auto * group : {&start, &stop_keys}) {
    std::size_t count = 0;
    for (const auto & key : keys_) {
      const auto n = std::count(group->begin(), group->end(), key);
      if (n > 1) {return Result::ERROR;}
      count += static_cast<std::size_t>(n);
    }
    if (count != 0 && count != 4) {return Result::ERROR;}
  }
  return Result::OK;
}
Result LeftArmSystem::perform_command_mode_switch(
  const std::vector<std::string> & start, const std::vector<std::string> & stop_keys)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (prepare_command_mode_switch(start, stop_keys) != Result::OK) {return Result::ERROR;}
  const auto owns = [this](const auto & group) {
    return std::any_of(group.begin(), group.end(), [this](const auto & key) {
      return std::find(keys_.begin(), keys_.end(), key) != keys_.end();
    });
  };
  if (owns(start) && (!core_->active() || core_->fault())) {return Result::ERROR;}
  if (owns(start) || owns(stop_keys)) {
    core_->hold();
    commands_ = core_->positions();
    commands_enabled_ = owns(start);
  }
  return Result::OK;
}
}  // namespace linglong_control

PLUGINLIB_EXPORT_CLASS(linglong_control::LeftArmSystem, hardware_interface::SystemInterface)
