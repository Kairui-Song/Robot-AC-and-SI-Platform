#include "linglong_control/left_arm_core.hpp"
#include <iostream>
#include <stdexcept>

using namespace linglong_control;
void check(bool ok) {if (!ok) {throw std::runtime_error("left-arm core check failed");}}
std::array<ArmCalibration, 4> calibration()
{
  std::array<ArmCalibration, 4> cal{};
  for (std::size_t i = 0; i < 4; ++i) {
    cal[i] = {i == 1 ? -100000.0 : 100000.0, 1000, 100000, -1, 1, .05, .15, 1};
  }
  return cal;
}
ArmFrame frame()
{
  ArmFrame f{};
  for (auto & j : f) {j = {11000, 200, 0x27, 8, true};}
  return f;
}
int main()
{
  check(left_arm_slaves == std::array<unsigned, 4>{1, 2, 3, 5});
  {
    LeftArmCore c(calibration());
    check(!c.activate());
    auto f = frame();
    for (auto & j : f) {j.status = 0x40;}
    check(c.feedback(f, true));
    for (auto & o : c.output(true)) {check(o.control == 6 && o.target == 11000);}
    f[3].mode = 1;
    check(c.feedback(f, true));
    for (auto & o : c.output(true)) {check(o.control == 0);}
    check(!c.activate());
    f[3].mode = 8;
    for (auto & j : f) {j.status = 0x21;}
    check(c.feedback(f, true));
    for (auto & o : c.output(true)) {check(o.control == 7);}
    for (auto & j : f) {j.status = 0x23;}
    check(c.feedback(f, true));
    for (auto & o : c.output(true)) {check(o.control == 15);}
    check(c.feedback(frame(), true) && c.activate());
    check(c.positions()[1] == -.1 && c.velocities()[0] == .002);
    check(c.command({.11, -.11, .11, .11}, .02));
    const auto out = c.output();
    check(out[0].target == 12000 && out[1].target == 12000);
    auto bad = c.targets(); bad[3] = 2;
    check(!c.command(bad, .02));
    check(c.targets()[0] == .11 && c.fault() == 2);
    for (auto & o : c.output()) {check(o.control == 0);}
    check(!c.activate());
  }
  for (int scenario = 0; scenario < 8; ++scenario) {
    LeftArmCore c(calibration());
    auto f = frame();
    check(c.feedback(f, true) && c.activate());
    if (scenario == 0) {check(!c.feedback(f, false) && c.fault() == 6);}
    if (scenario == 1) {f[2].operational = false; check(!c.feedback(f, true) && c.fault() == 9);}
    if (scenario == 2) {f[3].status = 8; check(!c.feedback(f, true) && c.fault() == 10);}
    if (scenario == 3) {f[1].mode = 1; check(!c.feedback(f, true) && c.fault() == 10);}
    if (scenario == 4) {f[0].position = 50000; check(!c.feedback(f, true) && c.fault() == 4);}
    if (scenario == 5) {auto t=c.targets(); t[3]=NAN; check(!c.command(t, .01) && c.fault() == 1);}
    if (scenario == 6) {auto t=c.targets(); t[3]+=.04; check(!c.command(t, .01) && c.fault() == 12);}
    if (scenario == 7) {f[3].status = 0x21; check(!c.feedback(f, true) && c.fault() == 10);}
    const std::array<int, 8> expected_slave{{-1, 3, 5, 2, 1, 5, 5, 5}};
    check(c.fault_slave() == expected_slave[scenario]);
    const auto first_fault = c.fault();
    c.fail(8);
    check(c.fault() == first_fault && c.fault_slave() == expected_slave[scenario]);
    for (auto & o : c.output(true)) {check(o.control == 0);}
    c.deactivate(); check(!c.activate());
  }
  {
    LeftArmCore c(calibration());
    check(c.feedback(frame(), true) && c.activate());
    check(c.command({.11, -.11, .11, .11}, .02));
    c.hold(); check(c.targets() == c.positions());
    c.deactivate();
    for (auto & o : c.output()) {check(o.control == 0 && o.target == 11000);}
    check(c.activate() && c.targets() == c.positions());
  }
  for (int scenario = 0; scenario < 4; ++scenario) {
    auto cal = calibration();
    if (scenario == 0) {cal[3].counts_per_radian = 0;}
    if (scenario == 1) {cal[0].upper = NAN;}
    if (scenario == 2) {cal[1].counts_per_radian = 1e20;}
    if (scenario == 3) {cal[2].velocity_scale = 0;}
    bool rejected = false;
    try {LeftArmCore invalid(cal);} catch (const std::invalid_argument &) {rejected = true;}
    check(rejected);
  }
  std::cout << "Left arm: group validation, enable, calibration, feedback faults and latching passed\n";
}
