#include "linglong_control/sim_system.hpp"

#include <set>
#include <string>
#include "pluginlib/class_list_macros.hpp"
#include "rclcpp/rclcpp.hpp"

namespace linglong_control
{
namespace
{
template<class Map>
double number(const Map & params, const std::string & key)
{
  const auto & text = params.at(key);
  std::size_t used = 0;
  const double value = std::stod(text, &used);
  if (used != text.size() || !std::isfinite(value)) {
    throw std::invalid_argument("Invalid numeric parameter: " + key);
  }
  return value;
}
template<class Map>
std::uint64_t cycles(const Map & params, const std::string & key)
{
  const double value = number(params, key);
  if (value < 0.0 || value > 1000000000.0 || std::floor(value) != value) {
    throw std::invalid_argument("Expected cycle count in [0, 1000000000]: " + key);
  }
  return static_cast<std::uint64_t>(value);
}
}  // namespace

hardware_interface::CallbackReturn SimSystem::on_init(const hardware_interface::HardwareInfo & info)
{
  if (machine_.state() != HardwareState::UNINITIALIZED) {
    return hardware_interface::CallbackReturn::FAILURE;
  }
  if (SystemInterface::on_init(info) != hardware_interface::CallbackReturn::SUCCESS) {
    return hardware_interface::CallbackReturn::ERROR;
  }
  try {
    // Intentionally supports only mock. A hardware value must never silently fall back to mock.
    if (info_.hardware_parameters.at("backend") != "mock") {
      throw std::invalid_argument("SimSystem only supports backend=mock; no EtherCAT driver installed");
    }
    if (info_.is_async) {
      throw std::invalid_argument("SimSystem requires the synchronous controller_manager loop");
    }
    std::vector<JointConfig> joints;
    std::set<std::string> names;
    for (const auto & joint : info_.joints) {
      if (!names.insert(joint.name).second || joint.command_interfaces.size() != 1 ||
        joint.command_interfaces[0].name != "position" || joint.state_interfaces.size() != 2)
      {
        throw std::invalid_argument("Expected unique joints with position command and position/velocity state");
      }
      std::set<std::string> states;
      for (const auto & state : joint.state_interfaces) {states.insert(state.name);}
      if (states != std::set<std::string>{"position", "velocity"}) {
        throw std::invalid_argument("Invalid state interface names");
      }
      const auto & p = joint.parameters;
      command_keys_.push_back(joint.name + "/position");
      joints.push_back({number(p, "lower"), number(p, "upper"), number(p, "initial_position"),
        number(p, "max_velocity"), number(p, "max_command_step"), number(p, "max_following_error")});
    }
    if (info_.sensors.size() != 1 || info_.sensors[0].name != "control_health" ||
      info_.sensors[0].state_interfaces.size() != health_names_.size())
    {
      throw std::invalid_argument("Expected control_health sensor interfaces");
    }
    std::set<std::string> actual_health;
    for (const auto & state : info_.sensors[0].state_interfaces) {actual_health.insert(state.name);}
    if (actual_health != std::set<std::string>(health_names_.begin(), health_names_.end())) {
      throw std::invalid_argument("Invalid control_health interface names");
    }
    const auto & p = info_.hardware_parameters;
    const auto supervised = p.find("supervised_fault_stop");
    if (supervised != p.end()) {
      if (supervised->second != "true" && supervised->second != "false") {
        throw std::invalid_argument("supervised_fault_stop must be true or false");
      }
      supervised_fault_stop_ = supervised->second == "true";
    }
    SimConfig config;
    config.nominal_period = number(p, "nominal_period");
    config.cycle_timeout = number(p, "cycle_timeout");
    config.feedback_timeout = number(p, "feedback_timeout");
    config.fault_after_cycles = cycles(p, "fault_after_cycles");
    config.dropout_after_cycles = cycles(p, "dropout_after_cycles");
    core_ = std::make_unique<SimCore>(std::move(joints), config);
    positions_.assign(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
    velocities_ = positions_;
    commands_ = positions_;
    health_[0] = 1.0;
  } catch (const std::exception & error) {
    machine_.transition(HardwareState::FAULT);
    RCLCPP_ERROR(rclcpp::get_logger("linglong_control"), "Configuration rejected: %s", error.what());
    return hardware_interface::CallbackReturn::ERROR;
  }
  machine_.transition(HardwareState::INIT);
  update_states();
  return hardware_interface::CallbackReturn::SUCCESS;
}

std::vector<hardware_interface::StateInterface> SimSystem::export_state_interfaces()
{
  std::vector<hardware_interface::StateInterface> interfaces;
  for (std::size_t i = 0; i < info_.joints.size(); ++i) {
    interfaces.emplace_back(info_.joints[i].name, "position", &positions_[i]);
    interfaces.emplace_back(info_.joints[i].name, "velocity", &velocities_[i]);
  }
  for (std::size_t i = 0; i < health_.size(); ++i) {
    interfaces.emplace_back("control_health", health_names_[i], &health_[i]);
  }
  return interfaces;
}

std::vector<hardware_interface::CommandInterface> SimSystem::export_command_interfaces()
{
  std::vector<hardware_interface::CommandInterface> interfaces;
  for (std::size_t i = 0; i < info_.joints.size(); ++i) {
    interfaces.emplace_back(info_.joints[i].name, "position", &commands_[i]);
  }
  return interfaces;
}

void SimSystem::update_states()
{
  if (core_->fault() != Fault::none) {
    machine_.transition(HardwareState::FAULT);
    commands_enabled_ = false;
  }
  if (core_->fault() == Fault::none) {
    std::copy(core_->positions().begin(), core_->positions().end(), positions_.begin());
    std::copy(core_->velocities().begin(), core_->velocities().end(), velocities_.begin());
  } else {
    // Never publish old measurements as healthy feedback after a latched error.
    std::fill(positions_.begin(), positions_.end(), std::numeric_limits<double>::quiet_NaN());
    std::fill(velocities_.begin(), velocities_.end(), std::numeric_limits<double>::quiet_NaN());
  }
  health_ = {1.0, core_->active() ? 1.0 : 0.0, static_cast<double>(core_->fault()),
    static_cast<double>(core_->cycles()), core_->last_period(), core_->max_period(),
    static_cast<double>(core_->deadline_misses()), core_->feedback_age(),
    static_cast<double>(machine_.state()), static_cast<double>(machine_.sequence()),
    commands_enabled_ ? 1.0 : 0.0};
}

hardware_interface::CallbackReturn SimSystem::on_configure(const rclcpp_lifecycle::State &)
{
  // After on_error the framework may already be UNCONFIGURED, so another
  // cleanup callback is not guaranteed. Explicit configure is also a MOCK-only
  // recovery request. Activation alone can never reset a fault.
  if (core_ && machine_.state() == HardwareState::FAULT) {
    machine_.transition(HardwareState::RECOVERING);
    core_->cleanup();
    machine_.transition(HardwareState::INIT);
  }
  if (!core_ || !machine_.transition(HardwareState::DISCOVERING)) {
    return hardware_interface::CallbackReturn::FAILURE;
  }
  machine_.transition(HardwareState::CONFIGURING);
  if (!core_->configure()) {
    machine_.transition(HardwareState::FAULT);
    update_states();
    return hardware_interface::CallbackReturn::FAILURE;
  }
  machine_.transition(HardwareState::INACTIVE);
  fault_reported_ = false;
  update_states();
  std::copy(positions_.begin(), positions_.end(), commands_.begin());
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn SimSystem::on_activate(const rclcpp_lifecycle::State &)
{
  if (!core_ || !machine_.transition(HardwareState::ACTIVATING)) {
    return hardware_interface::CallbackReturn::FAILURE;
  }
  if (!core_->activate()) {
    machine_.transition(HardwareState::FAULT);
    update_states();
    return hardware_interface::CallbackReturn::FAILURE;
  }
  machine_.transition(HardwareState::ACTIVE);
  update_states();
  std::copy(positions_.begin(), positions_.end(), commands_.begin());
  last_read_ = std::chrono::steady_clock::now();
  commands_enabled_ = false;
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn SimSystem::on_deactivate(const rclcpp_lifecycle::State &)
{
  if (!core_ || (machine_.state() != HardwareState::ACTIVE &&
    machine_.state() != HardwareState::FAULT && machine_.state() != HardwareState::INACTIVE)) {
    return hardware_interface::CallbackReturn::FAILURE;
  }
  commands_enabled_ = false;
  core_->deactivate();
  if (machine_.state() == HardwareState::ACTIVE) {machine_.transition(HardwareState::INACTIVE);}
  update_states();
  std::copy(core_->positions().begin(), core_->positions().end(), commands_.begin());
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn SimSystem::on_cleanup(const rclcpp_lifecycle::State &)
{
  if (!core_ || machine_.state() == HardwareState::SHUTDOWN || core_->active()) {
    return hardware_interface::CallbackReturn::FAILURE;
  }
  // Explicit MOCK cleanup is a fault-reset path; configure also handles a
  // framework that already transitioned to UNCONFIGURED after on_error.
  if (machine_.state() == HardwareState::FAULT) {machine_.transition(HardwareState::RECOVERING);}
  commands_enabled_ = false;
  core_->cleanup();
  machine_.transition(HardwareState::INIT);
  update_states();
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn SimSystem::on_shutdown(const rclcpp_lifecycle::State &)
{
  commands_enabled_ = false;
  machine_.transition(HardwareState::SHUTDOWN);
  if (core_) {core_->deactivate(); update_states();}
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn SimSystem::on_error(const rclcpp_lifecycle::State &)
{
  commands_enabled_ = false;
  machine_.transition(HardwareState::FAULT);
  if (!core_) {return hardware_interface::CallbackReturn::ERROR;}
  core_->latch(Fault::lifecycle_error);
  update_states();
  RCLCPP_ERROR(rclcpp::get_logger("linglong_control"),
    "MOCK fault latched, code=%d; restart after correcting the cause",
    static_cast<int>(core_->fault()));
  // Latch survives framework error handling. Explicit recovery is required.
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::return_type SimSystem::read(const rclcpp::Time &, const rclcpp::Duration &)
{
  if (core_ && machine_.state() == HardwareState::FAULT) {return fault_result();}
  if (!core_ || (machine_.state() != HardwareState::INACTIVE &&
    machine_.state() != HardwareState::ACTIVE)) {return hardware_interface::return_type::ERROR;}
  const auto now = std::chrono::steady_clock::now();
  const double elapsed = std::chrono::duration<double>(now - last_read_).count();
  last_read_ = now;
  const bool ok = core_->read(elapsed);
  update_states();
  return ok ? hardware_interface::return_type::OK : fault_result();
}

hardware_interface::return_type SimSystem::fault_result()
{
  update_states();  // Fault is latched; commands disabled; feedback is invalid, never extrapolated.
  if (!fault_reported_) {
    RCLCPP_ERROR(rclcpp::get_logger("linglong_control"),
      "MOCK fault latched, code=%d; motion blocked; explicit recovery required",
      static_cast<int>(core_->fault()));
    fault_reported_ = true;
  }
  // Keep transport/interfaces alive ONLY for the supervised mock. This lets
  // joint_state_broadcaster deliver the fault and the supervisor release claimed
  // command interfaces BEFORE removing the hardware from the resource manager.
  // It does not clear a fault, advance motion/cycles or authorize new commands.
  return supervised_fault_stop_ ? hardware_interface::return_type::OK :
         hardware_interface::return_type::ERROR;
}

hardware_interface::return_type SimSystem::write(const rclcpp::Time &, const rclcpp::Duration &)
{
  if (!core_ || machine_.state() == HardwareState::SHUTDOWN) {
    return hardware_interface::return_type::ERROR;
  }
  if (machine_.state() == HardwareState::FAULT || core_->fault() != Fault::none) {
    return fault_result();
  }
  if (!commands_enabled_) {return hardware_interface::return_type::OK;}
  const bool ok = core_->write(commands_);
  if (!ok) {update_states();}
  return ok ? hardware_interface::return_type::OK : fault_result();
}

hardware_interface::return_type SimSystem::prepare_command_mode_switch(
  const std::vector<std::string> & start, const std::vector<std::string> & stop)
{
  for (const auto * keys : {&start, &stop}) {
    std::size_t count = 0;
    for (const auto & key : command_keys_) {
      const auto occurrences = std::count(keys->begin(), keys->end(), key);
      if (occurrences > 1) {return hardware_interface::return_type::ERROR;}
      count += static_cast<std::size_t>(occurrences);
    }
    if (count != 0 && count != command_keys_.size()) {
      return hardware_interface::return_type::ERROR;
    }
  }
  return hardware_interface::return_type::OK;
}

hardware_interface::return_type SimSystem::perform_command_mode_switch(
  const std::vector<std::string> & start, const std::vector<std::string> & stop)
{
  if (prepare_command_mode_switch(start, stop) != hardware_interface::return_type::OK || !core_) {
    return hardware_interface::return_type::ERROR;
  }
  const auto owns = [this](const auto & keys) {
      return std::any_of(keys.begin(), keys.end(), [this](const auto & key) {
        return std::find(command_keys_.begin(), command_keys_.end(), key) != command_keys_.end();
      });
    };
  if (owns(start) && (machine_.state() != HardwareState::ACTIVE || !core_->active() ||
    core_->fault() != Fault::none)) {return hardware_interface::return_type::ERROR;}
  if (owns(stop) || owns(start)) {
    core_->hold();
    std::copy(core_->positions().begin(), core_->positions().end(), commands_.begin());
    commands_enabled_ = owns(start) && core_->active() && core_->fault() == Fault::none;
    update_states();
  }
  return hardware_interface::return_type::OK;
}
}  // namespace linglong_control

PLUGINLIB_EXPORT_CLASS(linglong_control::SimSystem, hardware_interface::SystemInterface)
