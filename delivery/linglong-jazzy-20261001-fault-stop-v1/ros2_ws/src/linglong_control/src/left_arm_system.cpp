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
  if (machine_.state() != HardwareState::UNINITIALIZED) {return Callback::FAILURE;}
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
    if (info_.sensors.size() != 1 || info_.sensors[0].name != "control_health") {
      throw std::invalid_argument("Missing control_health");
    }
    std::set<std::string> health;
    for (const auto & s : info_.sensors[0].state_interfaces) {health.insert(s.name);}
    if (info_.sensors[0].state_interfaces.size() != health_names_.size() ||
      health != std::set<std::string>(health_names_.begin(), health_names_.end())) {
      throw std::invalid_argument("Invalid health interfaces");
    }
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
    machine_.transition(HardwareState::FAULT);
    RCLCPP_ERROR(rclcpp::get_logger("left_arm"), "Configuration rejected: %s", e.what());
    return Callback::ERROR;
  }
  machine_.transition(HardwareState::INIT);
  states();
  publish_states();
  return Callback::SUCCESS;
}

std::vector<hardware_interface::StateInterface> LeftArmSystem::export_state_interfaces()
{
  std::vector<hardware_interface::StateInterface> result;
  for (std::size_t i = 0; i < 4; ++i) {
    result.emplace_back(left_arm_names[i], "position", &exported_positions_[i]);
    result.emplace_back(left_arm_names[i], "velocity", &exported_velocities_[i]);
  }
  for (std::size_t i = 0; i < health_.size(); ++i) {result.emplace_back("control_health", health_names_[i], &exported_health_[i]);}
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
  if (core_->fault()) {machine_.transition(HardwareState::FAULT); commands_enabled_ = false;}
  health_[0] = 0;  // Physical PDO feedback; never labelled mock.
  health_[1] = core_->active() ? 1 : 0;
  health_[2] = core_->fault();
  health_[8] = static_cast<double>(machine_.state());
  health_[9] = static_cast<double>(machine_.sequence());
  health_[10] = commands_enabled_ ? 1 : 0;
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
    const bool sent = bus_.send(core_->output());
    if (configured_ && !sent) {core_->fail(9);}
    states();
  }
}
void LeftArmSystem::publish_states()
{
  exported_positions_ = positions_;
  exported_velocities_ = velocities_;
  exported_health_ = health_;
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
      if (enable ? core_->activate() : core_->disabled()) {
        if (!bus_.send(core_->output())) {core_->fail(9); stop(); return false;}
        last_read_ = std::chrono::steady_clock::now();
        states();
        return true;
      }
    } else if (seen_complete) {
      core_->fail(6);
      stop();
      return false;
    }
    if (!bus_.send(core_->output(enable && complete))) {core_->fail(9); stop(); return false;}
    next += std::chrono::nanoseconds(bus_config_.period_ns);
    std::this_thread::sleep_until(next);  // lifecycle startup only, never read/write
  }
  core_->fail(11);
  stop();
  return false;
}
Callback LeftArmSystem::on_configure(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (!core_ || core_->fault() || configured_) {return Callback::FAILURE;}
  if (!machine_.transition(HardwareState::DISCOVERING)) {return Callback::FAILURE;}
  try {
    bus_.discover(bus_config_);
    machine_.transition(HardwareState::CONFIGURING);
    bus_.configure();
    if (!startup(false)) {bus_.close(); return Callback::FAILURE;}
    configured_ = true;
    machine_.transition(HardwareState::INACTIVE);
    states();
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
  if (!configured_ || core_->fault() ||
    !machine_.transition(HardwareState::ACTIVATING)) {return Callback::FAILURE;}
  commands_enabled_ = false;
  if (!startup(true)) {return Callback::FAILURE;}
  machine_.transition(HardwareState::ACTIVE);
  states();
  return Callback::SUCCESS;
}
Callback LeftArmSystem::on_deactivate(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (!core_ || (machine_.state() != HardwareState::ACTIVE &&
    machine_.state() != HardwareState::INACTIVE && machine_.state() != HardwareState::FAULT)) {
    return Callback::FAILURE;
  }
  stop();
  // Sending controlword 0 alone is not evidence of drive disable. Poll the
  // four actual status words within the bounded lifecycle transition.
  if (core_->fault() || !startup(false)) {return Callback::FAILURE;}
  if (machine_.state() == HardwareState::ACTIVE) {machine_.transition(HardwareState::INACTIVE);}
  states();
  return core_->fault() ? Callback::FAILURE : Callback::SUCCESS;
}
Callback LeftArmSystem::on_cleanup(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  if (!core_ || core_->active() || machine_.state() == HardwareState::SHUTDOWN) {
    return Callback::FAILURE;
  }
  stop(); bus_.close(); configured_ = false;
  // Fault remains latched even through cleanup. Correct cause and restart.
  if (!core_->fault()) {machine_.transition(HardwareState::INIT);}
  states();
  return Callback::SUCCESS;
}
Callback LeftArmSystem::on_shutdown(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  stop(); bus_.close(); configured_ = false;
  machine_.transition(HardwareState::SHUTDOWN);
  if (core_) {states();}
  return Callback::SUCCESS;
}
Callback LeftArmSystem::on_error(const rclcpp_lifecycle::State &)
{
  std::lock_guard<std::mutex> lock(mutex_);
  machine_.transition(HardwareState::FAULT);
  if (core_) {core_->fail(8); stop();}
  bus_.close(); configured_ = false;
  return Callback::SUCCESS;
}
Result LeftArmSystem::read(const rclcpp::Time &, const rclcpp::Duration &)
{
  // Lifecycle startup owns PDO exchange while it waits for drive states.
  // Never wait behind that loop on the controller's periodic thread. Keep
  // the previous snapshot/cycle counter; no fresh feedback is fabricated.
  std::unique_lock<std::mutex> lock(mutex_, std::try_to_lock);
  if (!lock.owns_lock()) {return Result::OK;}
  const auto result = read_locked();
  publish_states();
  return result;
}
Result LeftArmSystem::read_locked()
{
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
  if (!core_->feedback(frame, complete)) {stop(); return Result::ERROR;}
  if (machine_.state() == HardwareState::INACTIVE && !core_->disabled()) {
    core_->fail(10); stop(); return Result::ERROR;
  }
  states();
  // INACTIVE components may not receive write() calls from controller_manager.
  if (!core_->active() && !bus_.send(core_->output())) {core_->fail(9); stop(); return Result::ERROR;}
  return Result::OK;
}
Result LeftArmSystem::write(const rclcpp::Time &, const rclcpp::Duration &)
{
  // The lifecycle owner sends aligned/disabled targets during transitions.
  // Skipped writes must not replay controller targets after activation.
  std::unique_lock<std::mutex> lock(mutex_, std::try_to_lock);
  if (!lock.owns_lock()) {return Result::OK;}
  if (!configured_ || core_->fault()) {return Result::ERROR;}
  if (commands_enabled_ && !core_->command(commands_, health_[4])) {
    stop(); publish_states(); return Result::ERROR;
  }
  if (!bus_.send(core_->output())) {core_->fail(9); stop(); publish_states(); return Result::ERROR;}
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
  std::unique_lock<std::mutex> lock(mutex_, std::try_to_lock);
  if (!lock.owns_lock()) {return Result::ERROR;}
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
    states();
    publish_states();
  }
  return Result::OK;
}
}  // namespace linglong_control

PLUGINLIB_EXPORT_CLASS(linglong_control::LeftArmSystem, hardware_interface::SystemInterface)
