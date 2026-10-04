#include "linglong_control/sim_core.hpp"

#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

using linglong_control::Fault;
using linglong_control::JointConfig;
using linglong_control::SimConfig;
using linglong_control::SimCore;

void require(bool value, const char * message)
{
  if (!value) {throw std::runtime_error(message);}
}
void near(double actual, double expected)
{
  require(std::abs(actual - expected) < 1e-10, "numeric mismatch");
}
SimCore make(SimConfig config = {})
{
  return SimCore({{-1, 1, 0.3, 0.1, 0.05, 0.08}, {-1, 1, -0.2, 0.1, 0.05, 0.08}}, config);
}
void start(SimCore & core)
{
  require(core.configure() && core.activate(), "start failed");
}

int main()
{
  int passed = 0;
  const auto test = [&passed](const char * name, const auto & body) {
      body();
      ++passed;
      std::cout << "PASS " << name << '\n';
    };
  try {
    test("invalid configuration rejected", [] {
      for (double value : {0.0, -1.0, std::numeric_limits<double>::infinity()}) {
        SimConfig config;
        config.nominal_period = value;
        bool rejected = false;
        try {auto core = make(config); (void)core;} catch (const std::invalid_argument &) {rejected = true;}
        require(rejected, "invalid timing accepted");
      }
      bool rejected = false;
      try {SimCore core({{-1, 1, 2, 0.1, 0.05, 0.1}}, {});}
      catch (const std::invalid_argument &) {rejected = true;}
      require(rejected, "out-of-range initial position accepted");
    });
    test("activate requires configure", [] {
      auto core = make();
      require(!core.activate(), "unconfigured activation accepted");
    });
    test("activation holds nonzero feedback", [] {
      auto core = make(); start(core);
      require(core.read(0.01), "read failed");
      near(core.positions()[0], 0.3); near(core.positions()[1], -0.2);
    });
    test("finite-rate simulated feedback", [] {
      auto core = make(); start(core);
      require(core.write({0.33, -0.17}), "valid command rejected");
      core.read(0.01);
      near(core.positions()[0], 0.301); near(core.velocities()[0], 0.1);
      for (int i = 0; i < 40; ++i) {require(core.read(0.01), "read failed");}
      near(core.positions()[0], 0.33); near(core.velocities()[0], 0.0);
    });
    test("inactive ignores commands and motion", [] {
      auto core = make(); start(core);
      core.write({0.33, -0.17}); core.deactivate();
      core.write({0.4, -0.1}); core.read(0.01);
      near(core.positions()[0], 0.3);
    });
    test("reactivation discards stale target", [] {
      auto core = make(); start(core);
      core.write({0.33, -0.17}); core.read(0.01); core.deactivate();
      require(core.activate(), "reactivation failed"); core.read(0.01);
      near(core.positions()[0], 0.301);
    });
    test("NaN and infinity latch fault", [] {
      for (double v : {std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::infinity()}) {
        auto core = make(); start(core);
        require(!core.write({0.31, v}), "nonfinite accepted");
        require(core.fault() == Fault::invalid_command && !core.active(), "not latched");
        require(!core.write({0.3, -0.2}) && !core.activate(), "fault bypassed");
      }
    });
    test("whole batch rejected before any motion", [] {
      auto core = make(); start(core);
      require(!core.write({0.31, 2.0}), "limit accepted");
      require(core.fault() == Fault::position_limit, "wrong fault");
      core.read(0.01); near(core.positions()[0], 0.3);
    });
    test("command step bounded", [] {
      auto core = make(); start(core);
      require(!core.write({0.4, -0.2}) && core.fault() == Fault::command_step, "step accepted");
    });
    test("following error bounded", [] {
      auto core = make(); start(core);
      require(core.write({0.335, -0.2}), "first bounded step failed");
      require(core.write({0.37, -0.2}), "second bounded step failed");
      require(!core.write({0.405, -0.2}) && core.fault() == Fault::following_error, "lag accepted");
    });
    test("missed interval counted then timeout latched", [] {
      auto core = make(); start(core);
      core.read(0.02);
      require(core.deadline_misses() == 1, "missed interval not counted");
      require(!core.read(0.6) && core.fault() == Fault::cycle_timeout, "timeout accepted");
      near(core.max_period(), 0.6);
    });
    test("invalid elapsed time rejected", [] {
      auto core = make(); start(core);
      require(!core.read(std::numeric_limits<double>::quiet_NaN()), "NaN time accepted");
    });
    test("dropout reports age and faults without synthetic feedback", [] {
      SimConfig config; config.dropout_after_cycles = 2; config.feedback_timeout = 0.025;
      auto core = make(config); start(core);
      core.write({0.33, -0.17}); core.read(0.01);
      core.read(0.01); near(core.feedback_age(), 0.01); near(core.positions()[0], 0.301);
      core.read(0.01);
      require(!core.read(0.01) && core.fault() == Fault::feedback_timeout, "dropout not latched");
    });
    test("injected fault survives framework error handling", [] {
      SimConfig config; config.fault_after_cycles = 2;
      auto core = make(config); start(core); core.read(0.01);
      require(!core.read(0.01), "fault not injected");
      core.latch(Fault::lifecycle_error);
      require(core.fault() == Fault::injected && !core.configure(), "fault overwritten or cleared");
      core.cleanup(); require(core.configure() && core.activate(), "explicit reset failed");
    });
    test("controller stop holds feedback", [] {
      auto core = make(); start(core);
      core.write({0.33, -0.17}); core.read(0.01); core.hold(); core.read(0.01);
      near(core.positions()[0], 0.301); near(core.velocities()[0], 0.0);
    });
    test("long trajectory needs no repeated topic heartbeat", [] {
      auto core = make(); start(core);
      for (int i = 1; i <= 1000; ++i) {
        require(core.write({0.3 + 0.02 * std::sin(i * 0.01), -0.2}), "trajectory rejected");
        require(core.read(0.01), "trajectory read failed");
      }
      require(core.active() && core.fault() == Fault::none, "spurious command timeout");
    });
  } catch (const std::exception & error) {
    std::cerr << "FAIL after " << passed << " tests: " << error.what() << '\n';
    return 1;
  }
  std::cout << passed << " control-core scenarios passed\n";
  return 0;
}
