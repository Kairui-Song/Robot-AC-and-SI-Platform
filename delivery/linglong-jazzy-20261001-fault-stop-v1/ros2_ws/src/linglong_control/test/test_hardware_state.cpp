#include "linglong_control/hardware_state.hpp"
#include <stdexcept>
#include <iostream>
using namespace linglong_control;
void check(bool value) {if (!value) {throw std::runtime_error("hardware transition contract failed");}}
int main()
{
  using S = HardwareState;
  HardwareStateMachine m;
  check(!m.transition(S::ACTIVE));
  check(m.sequence() == 0);
  for (auto state : {S::INIT, S::DISCOVERING, S::CONFIGURING, S::INACTIVE, S::ACTIVATING, S::ACTIVE}) {
    check(m.transition(state));
  }
  check(!m.transition(S::ACTIVE));
  check(!m.transition(S::INIT));  // cleanup cannot bypass deactivation
  check(m.transition(S::FAULT));
  check(!m.transition(S::ACTIVATING));
  check(!m.transition(S::INACTIVE));
  check(m.transition(S::RECOVERING));
  check(!m.transition(S::ACTIVE));  // recovery does not enable
  check(m.transition(S::INIT));
  check(m.transition(S::SHUTDOWN));
  for (int i = 0; i <= 9; ++i) {check(!m.transition(static_cast<S>(i)));}
  for (auto target : {S::FAULT, S::SHUTDOWN}) {
    HardwareStateMachine interrupted;
    check(interrupted.transition(S::INIT));
    check(interrupted.transition(S::DISCOVERING));
    check(interrupted.transition(target));
  }
  std::cout << "Hardware state guards, recovery and terminal shutdown passed\n";
}
