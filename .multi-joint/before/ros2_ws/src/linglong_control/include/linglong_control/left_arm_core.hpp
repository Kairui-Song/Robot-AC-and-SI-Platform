#pragma once

#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>

namespace linglong_control
{
// Deployed EYOU left arm, not the JE single-drive test at slave 0.
constexpr std::array<unsigned, 4> left_arm_slaves{1, 2, 3, 5};
constexpr std::array<const char *, 4> left_arm_names{"joint_1", "joint_2", "joint_3", "joint_5"};
struct ArmCalibration
{
  double counts_per_radian{}, zero_counts{}, velocity_scale{};
  double lower{}, upper{}, max_step{}, following_error{}, max_velocity{};
};
struct ArmFeedback
{
  std::int32_t position{}, velocity{};
  std::uint16_t status{};
  std::int8_t mode{};
  bool operational{};
};
struct ArmOutput
{
  std::int32_t target{};
  std::uint16_t control{};
};
using ArmFrame = std::array<ArmFeedback, 4>;
using ArmTargets = std::array<double, 4>;

// No ROS/IgH, allocation or subprocesses in the cycle path. Every command is
// validated before any of the four targets is committed to the process image.
class LeftArmCore
{
public:
  explicit LeftArmCore(std::array<ArmCalibration, 4> calibration) : cal_(calibration)
  {
    for (const auto & c : cal_) {
      for (double n : {c.counts_per_radian, c.zero_counts, c.velocity_scale,
          c.lower, c.upper, c.max_step, c.following_error, c.max_velocity}) {
        if (!std::isfinite(n)) {throw std::invalid_argument("Nonfinite left-arm calibration");}
      }
      if (c.counts_per_radian == 0 || c.velocity_scale == 0 || c.lower >= c.upper ||
        c.max_step <= 0 || c.following_error <= 0 || c.max_velocity <= 0 ||
        !encodable(c, c.lower) || !encodable(c, c.upper)) {
        throw std::invalid_argument("Invalid left-arm calibration/limits");
      }
    }
  }

  bool feedback(const ArmFrame & frame, bool complete)
  {
    if (fault_) {return false;}
    if (!complete) {return fail(6);}
    for (std::size_t i = 0; i < 4; ++i) {
      const auto & f = frame[i];
      if (!f.operational) {return fail(9);}
      if (f.status & 0x0008) {return fail(10);}
      const double p = (static_cast<double>(f.position) - cal_[i].zero_counts) /
        cal_[i].counts_per_radian;
      if (!std::isfinite(p) || p < cal_[i].lower || p > cal_[i].upper) {return fail(2);}
      // Once activated, loss of enable/mode on ANY joint stops the whole arm.
      if (active_ && ((f.status & 0x006f) != 0x0027 || f.mode != 8)) {return fail(10);}
      if (active_ && std::abs(targets_[i] - p) > cal_[i].following_error) {return fail(4);}
    }
    frame_ = frame;
    valid_ = true;
    for (std::size_t i = 0; i < 4; ++i) {
      positions_[i] = (static_cast<double>(frame[i].position) - cal_[i].zero_counts) /
        cal_[i].counts_per_radian;
      velocities_[i] = static_cast<double>(frame[i].velocity) / cal_[i].velocity_scale;
    }
    if (!active_) {hold();}
    return true;
  }

  bool activate()
  {
    if (fault_ || !valid_) {return false;}
    for (const auto & f : frame_) {
      if ((f.status & 0x006f) != 0x0027 || f.mode != 8) {return false;}
    }
    hold();
    active_ = true;
    return true;
  }
  void deactivate() {active_ = false; hold();}
  void hold() {targets_ = positions_;}
  bool command(const ArmTargets & next, double elapsed)
  {
    if (!active_ || fault_) {return false;}
    if (!std::isfinite(elapsed) || elapsed <= 0) {return fail(5);}
    for (std::size_t i = 0; i < 4; ++i) {
      if (!std::isfinite(next[i])) {return fail(1);}
      if (next[i] < cal_[i].lower || next[i] > cal_[i].upper || !encodable(cal_[i], next[i])) {
        return fail(2);
      }
      if (std::abs(next[i] - targets_[i]) > cal_[i].max_step) {return fail(3);}
      if (std::abs(next[i] - targets_[i]) > cal_[i].max_velocity * elapsed + 1e-9) {return fail(12);}
      if (std::abs(next[i] - positions_[i]) > cal_[i].following_error) {return fail(4);}
    }
    targets_ = next;
    return true;
  }
  std::array<ArmOutput, 4> output(bool enabling = false) const
  {
    std::array<ArmOutput, 4> out{};
    bool modes_ok = true;
    for (const auto & f : frame_) {modes_ok = modes_ok && f.mode == 8;}
    for (std::size_t i = 0; i < 4; ++i) {
      out[i].target = active_ && !fault_ ? encode(cal_[i], targets_[i]) : frame_[i].position;
      if (!fault_ && valid_ && modes_ok && (active_ || enabling)) {
        const auto sw = frame_[i].status & 0x006f;
        // No automatic fault reset. Align target to feedback throughout startup.
        if ((frame_[i].status & 0x004f) == 0x0040) {out[i].control = 0x0006;}
        else if (sw == 0x0021) {out[i].control = 0x0007;}
        else if (sw == 0x0023 || sw == 0x0027) {out[i].control = 0x000f;}
      }
    }
    return out;
  }
  bool fail(int code) {if (!fault_) {fault_ = code;} active_ = false; return false;}
  int fault() const {return fault_;}
  bool active() const {return active_;}
  const ArmTargets & positions() const {return positions_;}
  const ArmTargets & velocities() const {return velocities_;}
  const ArmTargets & targets() const {return targets_;}

private:
  static bool encodable(const ArmCalibration & c, double p)
  {
    const double n = std::round(c.zero_counts + c.counts_per_radian * p);
    return std::isfinite(n) && n >= std::numeric_limits<std::int32_t>::min() &&
      n <= std::numeric_limits<std::int32_t>::max();
  }
  static std::int32_t encode(const ArmCalibration & c, double p)
  {return static_cast<std::int32_t>(std::llround(c.zero_counts + c.counts_per_radian * p));}
  std::array<ArmCalibration, 4> cal_;
  ArmFrame frame_{};
  ArmTargets positions_{}, velocities_{}, targets_{};
  bool valid_{false}, active_{false};
  int fault_{0};
};
}  // namespace linglong_control
