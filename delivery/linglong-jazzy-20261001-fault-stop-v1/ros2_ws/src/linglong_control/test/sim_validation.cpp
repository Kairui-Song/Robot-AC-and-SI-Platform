// Standalone validation of the same SimCore used by SimSystem. No ROS or hardware I/O.
#include "linglong_control/sim_core.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <string>
#include <thread>
#include <sys/resource.h>

using namespace linglong_control;
using Clock = std::chrono::steady_clock;
constexpr double period = .01;
constexpr std::array<double, 4> initial{.15, -.10, .05, .02};

SimCore make_core(SimConfig config = {})
{
  std::vector<JointConfig> joints;
  for (const auto p : initial) {joints.push_back({-1.57, 1.57, p, .1, .05, .15});}
  return SimCore(std::move(joints), config);
}

void start(SimCore & core)
{
  if (!core.configure() || !core.activate()) {throw std::runtime_error("Cannot start mock core");}
}

void target(std::vector<double> & command, double t)
{
  for (std::size_t i = 0; i < command.size(); ++i) {
    command[i] = initial[i] + .03 * std::sin(2.0 * 3.141592653589793 * .1 * t + i * .2)
      - .03 * std::sin(i * .2);
  }
}

double us(Clock::duration value)
{
  return std::chrono::duration<double, std::micro>(value).count();
}

long peak_rss_kib()
{
  rusage usage{};
  return getrusage(RUSAGE_SELF, &usage) == 0 ? usage.ru_maxrss : -1;
}

struct Errors
{
  std::uint64_t samples{0};
  long double sum_square{0};
  double maximum{0};
  void add(double error)
  {
    if (!std::isfinite(error)) {throw std::runtime_error("Nonfinite tracking error");}
    ++samples;
    sum_square += error * error;
    maximum = std::max(maximum, std::abs(error));
  }
  double rms() const {return samples ? std::sqrt(static_cast<double>(sum_square / samples)) : 0;}
};

bool endurance(std::uint64_t cycles)
{
  auto core = make_core(); start(core);
  std::vector<double> command(initial.begin(), initial.end());
  Errors errors;
  std::uint64_t failures = 0, actual_cycles = 0;
  const auto begin = Clock::now();
  const auto rss_before = peak_rss_kib();
  for (std::uint64_t cycle = 1; cycle <= cycles; ++cycle) {
    // Match the real read -> controller update -> write order. Read sees last target.
    if (!core.read(period)) {++failures; break;}
    target(command, cycle * period);
    for (std::size_t i = 0; i < command.size(); ++i) {
      errors.add(command[i] - core.positions()[i]);
    }
    if (!core.write(command)) {++failures; break;}
    actual_cycles = cycle;
  }
  const auto elapsed = std::chrono::duration<double>(Clock::now() - begin).count();
  const bool passed = failures == 0 && actual_cycles == cycles && errors.maximum <= .002;
  std::cout << "{\"scenario\":\"accelerated_endurance\",\"passed\":" << (passed ? "true" : "false")
    << ",\"cycles_requested\":" << cycles << ",\"cycles_completed\":" << actual_cycles
    << ",\"simulated_seconds\":" << actual_cycles * period << ",\"wall_seconds\":" << elapsed
    << ",\"unexpected_faults\":" << failures << ",\"fault_code\":" << static_cast<int>(core.fault())
    << ",\"tracking_rmse_rad\":" << errors.rms() << ",\"tracking_max_rad\":" << errors.maximum
    << ",\"peak_rss_before_kib\":" << rss_before << ",\"peak_rss_after_kib\":" << peak_rss_kib()
    << ",\"criteria\":{\"unexpected_faults\":0,\"max_tracking_error_rad\":0.002}"
    << ",\"scope\":\"virtual time, deterministic rate-limited mock; not physical uptime or real-time scheduling\"}\n";
  return passed;
}

bool faults(std::uint64_t seed, int trials)
{
  std::mt19937_64 random(seed);
  std::uniform_real_distribution<double> jitter(.005, .015);
  constexpr std::array<const char *, 9> names{
    "nan_command", "infinite_command", "position_limit", "command_step", "following_error",
    "cycle_timeout", "invalid_period", "feedback_dropout", "injected_fault"};
  constexpr std::array<Fault, 9> expected{Fault::invalid_command, Fault::invalid_command,
    Fault::position_limit, Fault::command_step, Fault::following_error, Fault::cycle_timeout,
    Fault::cycle_timeout, Fault::feedback_timeout, Fault::injected};
  std::array<int, 9> detected{}, latched{}, recovered{};
  double max_dropout_age = 0;
  double max_recovery_cpu_us = 0;
  int lifecycle_failures = 0;
  for (std::size_t kind = 0; kind < names.size(); ++kind) {
    for (int trial = 0; trial < trials; ++trial) {
      const auto trigger = 5 + random() % 96;
      SimConfig config;
      if (kind == 7) {config.dropout_after_cycles = trigger;}
      if (kind == 8) {config.fault_after_cycles = trigger;}
      auto core = make_core(config); start(core);
      std::vector<double> command(initial.begin(), initial.end());
      // Inject while following a trajectory, with randomized healthy-cycle jitter.
      double simulation_time = 0;
      for (std::uint64_t i = 1; i < trigger; ++i) {
        const double elapsed = jitter(random);
        simulation_time += elapsed;
        const bool read_ok = core.read(elapsed);
        target(command, simulation_time);
        if (!core.write(command) || !read_ok) {++lifecycle_failures;}
      }
      command = core.positions();
      const auto axis = random() % command.size();
      switch (kind) {
        case 0: command[axis] = std::numeric_limits<double>::quiet_NaN(); core.write(command); break;
        case 1: command[axis] = std::numeric_limits<double>::infinity(); core.write(command); break;
        case 2: command[axis] = 2.; core.write(command); break;
        case 3: command[axis] += .06; core.write(command); break;
        case 4:
          for (int step = 0; step < 4; ++step) {command[axis] += .04; core.write(command);}
          break;
        case 5: core.read(.501 + jitter(random)); break;
        case 6: core.read(trial % 2 ? 0.0 : -period); break;
        case 7:
          for (int i = 0; i < 32 && core.fault() == Fault::none; ++i) {core.read(jitter(random));}
          max_dropout_age = std::max(max_dropout_age, core.feedback_age());
          break;
        case 8: core.read(period); break;
      }
      if (core.fault() == expected[kind] && !core.active()) {++detected[kind];}
      const auto stopped = core.positions();
      bool retained = true;
      command.assign(initial.begin(), initial.end());
      for (int i = 0; i < 20; ++i) {
        if (core.activate() || core.configure() || core.write(command) || core.read(period) ||
          core.fault() != expected[kind] || core.positions() != stopped)
        {retained = false;}
      }
      if (retained) {++latched[kind];}
      // Software-input faults recover on this same object. Persistent injected sources
      // require a new fault-free mock configuration; report the distinction per case.
      const auto recovery_begin = Clock::now();
      core.cleanup();
      bool reset_ok = core.configure() && core.activate() && core.fault() == Fault::none;
      auto repaired = make_core(); start(repaired);
      auto & recovery_core = kind < 7 ? core : repaired;
      for (int i = 1; i <= 100; ++i) {
        reset_ok = recovery_core.read(period) && reset_ok;
        target(command, i * period);
        reset_ok = recovery_core.write(command) && reset_ok;
      }
      max_recovery_cpu_us = std::max(max_recovery_cpu_us, us(Clock::now() - recovery_begin));
      if (reset_ok && recovery_core.active() && recovery_core.fault() == Fault::none) {++recovered[kind];}
    }
  }
  // Repeated stop/start preserves the measured position (not the configured initial zero).
  auto lifecycle = make_core(); start(lifecycle);
  std::vector<double> command(initial.begin(), initial.end());
  for (int i = 0; i < trials * 10; ++i) {
    command = lifecycle.positions();
    command[0] += (i % 2 ? -.001 : .001);
    if (!lifecycle.write(command) || !lifecycle.read(period)) {++lifecycle_failures;}
    const auto before = lifecycle.positions();
    lifecycle.deactivate();
    if (!lifecycle.activate() || !lifecycle.read(period) || lifecycle.positions() != before) {++lifecycle_failures;}
  }
  bool passed = lifecycle_failures == 0 && max_dropout_age >= .1 && max_dropout_age < .115000001;
  for (std::size_t i = 0; i < names.size(); ++i) {
    passed = passed && detected[i] == trials && latched[i] == trials && recovered[i] == trials;
  }
  std::cout << "{\"scenario\":\"randomized_fault_recovery\",\"passed\":" << (passed ? "true" : "false")
    << ",\"seed\":" << seed << ",\"trials_per_fault\":" << trials << ",\"cases\":[";
  for (std::size_t i = 0; i < names.size(); ++i) {
    if (i) {std::cout << ',';}
    std::cout << "{\"name\":\"" << names[i] << "\",\"expected_code\":" << static_cast<int>(expected[i])
      << ",\"injected\":" << trials << ",\"detected\":" << detected[i]
      << ",\"latch_verified\":" << latched[i] << ",\"recovery_verified\":" << recovered[i]
      << ",\"recovery_mode\":\"" << (i < 7 ? "same_instance_explicit_reset" : "recreated_fault_free_configuration") << "\"}";
  }
  std::cout << "],\"lifecycle_iterations\":" << trials * 10 << ",\"lifecycle_failures\":" << lifecycle_failures
    << ",\"max_dropout_detection_sim_sec\":" << max_dropout_age
    << ",\"max_recovery_cpu_us\":" << max_recovery_cpu_us
    << ",\"criteria\":{\"all_faults_detected_and_latched\":true,\"all_explicit_recoveries\":true,"
    << "\"lifecycle_failures\":0,\"dropout_sim_latency_upper_sec\":0.115}"
    << ",\"scope\":\"mock reset and recreated fault-free configuration plus 100 healthy cycles; recovery CPU time is not robot MTTR\"}\n";
  return passed;
}

double percentile(std::vector<double> samples, double quantile)
{
  if (samples.empty()) {return 0;}
  std::sort(samples.begin(), samples.end());
  const auto index = static_cast<std::size_t>(std::ceil(quantile * samples.size())) - 1;
  return samples[std::min(index, samples.size() - 1)];
}

bool scheduler(int seconds, int workers, const std::string & csv_path)
{
  auto core = make_core(); start(core);
  std::vector<double> command(initial.begin(), initial.end());
  struct Sample {double scheduled, actual, interval, late, execution;};
  std::vector<Sample> samples;
  samples.reserve(seconds * 100 + 1);
  std::atomic<bool> running{true};
  std::vector<std::thread> load;
  // Bound background load and stop all workers with RAII, even on exceptions.
  struct Stop {
    std::atomic<bool> & running;
    std::vector<std::thread> & threads;
    ~Stop() {running.store(false); for (auto & thread : threads) {thread.join();}}
  } stop{running, load};
  for (int i = 0; i < workers; ++i) {
    load.emplace_back([&running, i] {
      volatile double sink = i + 1.0;
      while (running.load(std::memory_order_relaxed)) {
        for (int j = 1; j < 10000; ++j) {sink = std::sin(sink + j * .001);}
      }
    });
  }
  const auto tick = std::chrono::milliseconds(10);
  const auto begin = Clock::now();
  auto previous = begin;
  auto deadline = begin + tick;
  const auto end = begin + std::chrono::seconds(seconds);
  std::uint64_t missed_slots = 0, interval_overruns = 0;
  bool healthy = true;
  while (deadline <= end) {
    std::this_thread::sleep_until(deadline);
    const auto wake = Clock::now();
    const double elapsed = std::chrono::duration<double>(wake - previous).count();
    const auto execution_begin = Clock::now();
    healthy = core.read(elapsed);
    target(command, std::chrono::duration<double>(wake - begin).count());
    healthy = core.write(command) && healthy;
    const auto done = Clock::now();
    samples.push_back({us(deadline - begin), us(wake - begin), us(wake - previous),
                       std::max(0.0, us(wake - deadline)), us(done - execution_begin)});
    if (elapsed > .015) {++interval_overruns;}
    previous = wake;
    deadline += tick;
    // Skip missed schedule slots; do not hide lateness with a catch-up burst.
    if (deadline <= done) {
      const auto skipped = (done - deadline) / tick + 1;
      const auto remaining = deadline <= end ? (end - deadline) / tick + 1 : 0;
      missed_slots += static_cast<std::uint64_t>(std::min(skipped, remaining));
      deadline += tick * skipped;
    }
    if (!healthy) {break;}
  }
  const auto actual_seconds = std::chrono::duration<double>(Clock::now() - begin).count();
  running.store(false);
  std::vector<double> late, execution, intervals;
  late.reserve(samples.size()); execution.reserve(samples.size()); intervals.reserve(samples.size());
  for (const auto & s : samples) {late.push_back(s.late); execution.push_back(s.execution); intervals.push_back(s.interval);}
  const double miss_ratio = static_cast<double>(missed_slots) / (seconds * 100);
  const bool passed = healthy && samples.size() >= static_cast<std::size_t>(seconds * 90) &&
    percentile(late, .99) <= 5000.0 && percentile(execution, .99) <= 2000.0 && miss_ratio <= .01;
  if (!csv_path.empty()) {
    std::ofstream csv(csv_path);
    if (!csv) {throw std::runtime_error("Cannot create scheduler CSV");}
    csv << "scheduled_us,actual_us,interval_us,wake_lateness_us,execution_us\n" << std::setprecision(12);
    for (const auto & s : samples) {csv << s.scheduled << ',' << s.actual << ',' << s.interval << ',' << s.late << ',' << s.execution << '\n';}
    if (!csv) {throw std::runtime_error("Scheduler CSV write failed");}
  }
  std::cout << "{\"scenario\":\"wall_clock_scheduler\",\"passed\":" << (passed ? "true" : "false")
    << ",\"load_threads\":" << workers << ",\"duration_requested_sec\":" << seconds
    << ",\"wall_seconds\":" << actual_seconds << ",\"samples\":" << samples.size()
    << ",\"missed_slots\":" << missed_slots << ",\"missed_slot_ratio\":" << miss_ratio
    << ",\"intervals_over_15ms\":" << interval_overruns
    << ",\"wake_lateness_p50_us\":" << percentile(late, .5)
    << ",\"wake_lateness_p95_us\":" << percentile(late, .95)
    << ",\"wake_lateness_p99_us\":" << percentile(late, .99)
    << ",\"wake_lateness_max_us\":" << percentile(late, 1.)
    << ",\"execution_p99_us\":" << percentile(execution, .99)
    << ",\"execution_max_us\":" << percentile(execution, 1.)
    << ",\"interval_p99_us\":" << percentile(intervals, .99)
    << ",\"fault_code\":" << static_cast<int>(core.fault())
    << ",\"criteria\":{\"p99_wake_lateness_us\":5000,\"p99_execution_us\":2000,\"max_missed_slot_ratio\":0.01}"
    << ",\"scope\":\"WSL/Linux ordinary scheduler + mock core and target generation, not ROS/DDS/PDO or hard real-time\"}\n";
  return passed;
}

int main(int argc, char ** argv)
{
  std::cout << std::setprecision(12);
  try {
    std::string mode, csv_path;
    std::uint64_t cycles = 8640000, seed = 20260925;
    int trials = 200, seconds = 20, workers = 0;
    for (int i = 1; i < argc; i += 2) {
      if (i + 1 >= argc) {throw std::invalid_argument("Every option requires a value");}
      const std::string key = argv[i], value = argv[i + 1];
      if (key == "--mode") {mode = value; continue;}
      if (key == "--csv") {csv_path = value; continue;}
      if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos) {
        throw std::invalid_argument("Numeric arguments must be nonnegative integers");
      }
      const auto number = std::stoull(value);
      if (number > 100000000) {throw std::invalid_argument("Argument exceeds bounded test range");}
      if (key == "--cycles") {cycles = number;}
      else if (key == "--seed") {seed = number;}
      else if (key == "--trials") {trials = static_cast<int>(number);}
      else if (key == "--seconds") {seconds = static_cast<int>(number);}
      else if (key == "--workers") {workers = static_cast<int>(number);}
      else {throw std::invalid_argument("Unknown option: " + key);}
    }
    if (cycles < 1 || trials < 1 || trials > 10000 || seconds < 1 || seconds > 300 || workers > 8) {
      throw std::invalid_argument("Test size outside supported bounds");
    }
    if (mode == "build_info") {
      std::cout << "{\"compiler\":\"" << __VERSION__ << "\",\"cplusplus\":" << __cplusplus
#ifdef NDEBUG
        << ",\"ndebug\":true}"
#else
        << ",\"ndebug\":false}"
#endif
        << '\n';
      return 0;
    }
    if (mode == "endurance") {return endurance(cycles) ? 0 : 1;}
    if (mode == "faults") {return faults(seed, trials) ? 0 : 1;}
    if (mode == "scheduler") {return scheduler(seconds, workers, csv_path) ? 0 : 1;}
    throw std::invalid_argument("mode must be endurance, faults or scheduler");
  } catch (const std::exception & error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
}
