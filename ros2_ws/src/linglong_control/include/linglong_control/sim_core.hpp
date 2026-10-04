#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

namespace linglong_control
{
// Pure C++ control boundary: no ROS, subprocesses, sleeps or allocations in read/write.
enum class Fault : int
{
  none = 0, invalid_command = 1, position_limit = 2, command_step = 3,
  following_error = 4, cycle_timeout = 5, feedback_timeout = 6,
  injected = 7, lifecycle_error = 8
};

struct JointConfig
{
  double lower, upper, initial, max_velocity, max_command_step, max_following_error;
};

struct SimConfig
{
  double nominal_period{0.01};
  double cycle_timeout{0.5};
  double feedback_timeout{0.1};
  std::uint64_t fault_after_cycles{0};
  std::uint64_t dropout_after_cycles{0};
};

class SimCore
{
public:
  SimCore(std::vector<JointConfig> joints, SimConfig config)
  : joints_(std::move(joints)), config_(config), positions_(joints_.size()),
    velocities_(joints_.size()), targets_(joints_.size())
  {
    if (joints_.empty() || !positive(config.nominal_period) ||
      !positive(config.cycle_timeout) || !positive(config.feedback_timeout) ||
      config.cycle_timeout <= config.nominal_period ||
      config.feedback_timeout <= config.nominal_period)
    {
      throw std::invalid_argument("Invalid cycle/feedback timing configuration");
    }
    for (const auto & j : joints_) {
      if (!std::isfinite(j.lower) || !std::isfinite(j.upper) || j.lower >= j.upper ||
        !std::isfinite(j.initial) || j.initial < j.lower || j.initial > j.upper ||
        !positive(j.max_velocity) || !positive(j.max_command_step) ||
        !positive(j.max_following_error))
      {
        throw std::invalid_argument("Invalid joint limits or initial position");
      }
    }
  }

  bool configure()
  {
    if (active_ || fault_ != Fault::none) {return false;}
    for (std::size_t i = 0; i < joints_.size(); ++i) {
      positions_[i] = targets_[i] = joints_[i].initial;
      velocities_[i] = 0.0;
    }
    configured_ = true;
    cycles_ = deadline_misses_ = 0;
    feedback_age_ = last_period_ = max_period_ = 0.0;
    return true;
  }

  bool activate()
  {
    if (!configured_ || active_ || fault_ != Fault::none) {return false;}
    // Reactivation holds the last measured position, never a default zero target.
    std::copy(positions_.begin(), positions_.end(), targets_.begin());
    std::fill(velocities_.begin(), velocities_.end(), 0.0);
    feedback_age_ = 0.0;
    active_ = true;
    return true;
  }

  void deactivate()
  {
    active_ = false;
    hold();
  }

  void hold()
  {
    std::copy(positions_.begin(), positions_.end(), targets_.begin());
    std::fill(velocities_.begin(), velocities_.end(), 0.0);
  }

  void cleanup()
  {
    deactivate();
    configured_ = false;
    fault_ = Fault::none;  // Explicit lifecycle cleanup is required to reset a fault.
  }

  bool latch(Fault fault)
  {
    if (fault_ == Fault::none) {fault_ = fault;}
    deactivate();
    return false;
  }

  bool read(double elapsed)
  {
    if (fault_ != Fault::none) {return false;}
    if (!active_) {return true;}
    ++cycles_;
    if (!positive(elapsed)) {return latch(Fault::cycle_timeout);}
    last_period_ = elapsed;
    max_period_ = std::max(max_period_, elapsed);
    // An observed interval > 1.5 nominal periods; not a hard real-time guarantee.
    if (elapsed > 1.5 * config_.nominal_period) {++deadline_misses_;}
    if (elapsed > config_.cycle_timeout) {return latch(Fault::cycle_timeout);}
    if (config_.fault_after_cycles && cycles_ >= config_.fault_after_cycles) {
      return latch(Fault::injected);
    }
    if (config_.dropout_after_cycles && cycles_ >= config_.dropout_after_cycles) {
      feedback_age_ += elapsed;
      if (feedback_age_ >= config_.feedback_timeout) {return latch(Fault::feedback_timeout);}
      return true;  // Hold last sample, expose its age; do not fabricate a new measurement.
    }
    feedback_age_ = 0.0;
    for (std::size_t i = 0; i < joints_.size(); ++i) {
      const double max_delta = joints_[i].max_velocity * elapsed;
      const double delta = std::clamp(targets_[i] - positions_[i], -max_delta, max_delta);
      positions_[i] += delta;
      velocities_[i] = delta / elapsed;
    }
    return true;
  }

  bool write(const std::vector<double> & command)
  {
    if (fault_ != Fault::none) {return false;}
    if (!active_) {return true;}  // INACTIVE cannot move, even if framework calls write().
    if (command.size() != joints_.size()) {return latch(Fault::invalid_command);}
    // Validate the whole multi-axis sample before committing any target.
    for (std::size_t i = 0; i < joints_.size(); ++i) {
      const auto & j = joints_[i];
      if (!std::isfinite(command[i])) {return latch(Fault::invalid_command);}
      if (command[i] < j.lower || command[i] > j.upper) {return latch(Fault::position_limit);}
      if (std::abs(command[i] - targets_[i]) > j.max_command_step) {
        return latch(Fault::command_step);
      }
      if (std::abs(command[i] - positions_[i]) > j.max_following_error) {
        return latch(Fault::following_error);
      }
    }
    std::copy(command.begin(), command.end(), targets_.begin());
    return true;
  }

  const std::vector<double> & positions() const {return positions_;}
  const std::vector<double> & velocities() const {return velocities_;}
  bool active() const {return active_;}
  Fault fault() const {return fault_;}
  std::uint64_t cycles() const {return cycles_;}
  std::uint64_t deadline_misses() const {return deadline_misses_;}
  double feedback_age() const {return feedback_age_;}
  double last_period() const {return last_period_;}
  double max_period() const {return max_period_;}

private:
  static bool positive(double v) {return std::isfinite(v) && v > 0.0;}
  std::vector<JointConfig> joints_;
  SimConfig config_;
  std::vector<double> positions_, velocities_, targets_;
  bool configured_{false}, active_{false};
  Fault fault_{Fault::none};
  std::uint64_t cycles_{0}, deadline_misses_{0};
  double feedback_age_{0.0}, last_period_{0.0}, max_period_{0.0};
};
}  // namespace linglong_control
