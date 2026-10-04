#pragma once

#include <ecrt.h>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <type_traits>
#include "linglong_control/left_arm_core.hpp"

namespace linglong_control
{
struct ArmBusConfig
{
  unsigned master{0};
  std::uint32_t vendor{0x1097}, product{0x2406}, period_ns{10000000};
  std::uint16_t dc_assign{}, watchdog_divider{}, watchdog_intervals{};
};

// IgH owns one domain containing all four deployed left-arm slaves. The SII
// mapping is retained; absent required entries reject configuration. Never copy
// the unrelated JE slave-0 mapping from je_single_motor_test_v2.cpp.
class LeftArmBus
{
public:
  ~LeftArmBus() {close();}
  LeftArmBus() = default;
  LeftArmBus(const LeftArmBus &) = delete;
  LeftArmBus & operator=(const LeftArmBus &) = delete;
  void open(const ArmBusConfig & config)
  {
    discover(config);
    configure();
  }
  void discover(const ArmBusConfig & config)
  {
    close();
    config_ = config;
    try {
      master_ = ecrt_request_master(config.master);
      if (!master_) {throw std::runtime_error("Cannot exclusively request IgH master");}
      domain_ = ecrt_master_create_domain(master_);
      if (!domain_) {throw std::runtime_error("Cannot create left-arm PDO domain");}
      for (std::size_t i = 0; i < 4; ++i) {
        slaves_[i] = ecrt_master_slave_config(master_, 0, left_arm_slaves[i], config.vendor, config.product);
        if (!slaves_[i]) {throw std::runtime_error("Left-arm slave identity/configuration mismatch");}
        verify_mapping(i);
      }
    } catch (...) {close(); throw;}
  }
  void configure()
  {
    if (!master_ || !domain_) {throw std::runtime_error("Discover left arm before configuration");}
    const auto & config = config_;
    try {
      for (std::size_t i = 0; i < 4; ++i) {
        // Existing left-arm code selects CSP via 0x6060. Require mode display
        // in TxPDO so mode verification never uses blocking SDOs in the loop.
        auto & o = offsets_[i];
        o.target = reg(i, 0x607a);
        o.control = reg(i, 0x6040);
        o.position = reg(i, 0x6064);
        o.velocity = reg(i, 0x606c);
        o.status = reg(i, 0x6041);
        o.mode = reg(i, 0x6061);
        if (ecrt_slave_config_sdo8(slaves_[i], 0x6060, 0, 8)) {
          throw std::runtime_error("Cannot configure CSP mode");
        }
        if (offsets_[i].has_mode_command) {offsets_[i].mode_command = reg(i, 0x6060);}
        if (!ok([&] {return ecrt_slave_config_sync_manager(slaves_[i], 2, EC_DIR_OUTPUT, EC_WD_ENABLE);}) ||
          !ok([&] {return ecrt_slave_config_watchdog(slaves_[i], config.watchdog_divider, config.watchdog_intervals);}) ||
          !ok([&] {return ecrt_slave_config_dc(slaves_[i], config.dc_assign, config.period_ns, 0, 0, 0);})) {
          throw std::runtime_error("Cannot configure left-arm watchdog/DC");
        }
      }
      if (ecrt_master_activate(master_)) {throw std::runtime_error("Cannot activate IgH master");}
      data_ = ecrt_domain_data(domain_);
      if (!data_) {throw std::runtime_error("Cannot get left-arm process image");}
      std::memset(data_, 0, ecrt_domain_size(domain_));
      // Start disabled; no movement until a complete feedback frame is received.
      if (!send({})) {throw std::runtime_error("Initial PDO send failed");}
    } catch (...) {close(); throw;}
  }
  bool receive(ArmFrame & frame)
  {
    if (!data_) {return false;}
    if (!ok([&] {return ecrt_master_receive(master_);}) ||
      !ok([&] {return ecrt_domain_process(domain_);})) {return false;}
    ec_domain_state_t ds{};
    ec_master_state_t ms{};
    if (!ok([&] {return ecrt_domain_state(domain_, &ds);}) ||
      !ok([&] {return ecrt_master_state(master_, &ms);})) {return false;}
    bool complete = ms.link_up && ds.wc_state == EC_WC_COMPLETE;
    for (std::size_t i = 0; i < 4; ++i) {
      ec_slave_config_state_t ss{};
      if (!ok([&] {return ecrt_slave_config_state(slaves_[i], &ss);})) {return false;}
      const auto & o = offsets_[i];
      frame[i] = {EC_READ_S32(data_ + o.position), EC_READ_S32(data_ + o.velocity),
        EC_READ_U16(data_ + o.status), EC_READ_S8(data_ + o.mode),
        static_cast<bool>(ss.online && ss.operational)};
      complete = complete && frame[i].operational;
    }
    return complete;
  }
  bool send(const std::array<ArmOutput, 4> & output)
  {
    if (!data_) {return false;}
    for (std::size_t i = 0; i < 4; ++i) {
      EC_WRITE_S32(data_ + offsets_[i].target, output[i].target);
      EC_WRITE_U16(data_ + offsets_[i].control, output[i].control);
      if (offsets_[i].has_mode_command) {EC_WRITE_S8(data_ + offsets_[i].mode_command, 8);}
    }
    // A steady epoch provides monotonically increasing DC application time,
    // unaffected by ROS simulation time or wall-clock adjustments.
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
    bool success = ok([&] {return ecrt_master_application_time(master_, static_cast<std::uint64_t>(ns));});
    if (config_.dc_assign) {
      success = ok([&] {return ecrt_master_sync_reference_clock(master_);}) && success;
      success = ok([&] {return ecrt_master_sync_slave_clocks(master_);}) && success;
    }
    success = ok([&] {return ecrt_domain_queue(domain_);}) && success;
    return ok([&] {return ecrt_master_send(master_);}) && success;
  }
  void close()
  {
    // Best effort only: physical stopping on a dead bus is the commissioned
    // drive watchdog/brake responsibility, not an acknowledgement from send().
    if (data_) {send({});}
    data_ = nullptr;
    if (master_) {ecrt_release_master(master_);}
    master_ = nullptr;
    domain_ = nullptr;
    slaves_.fill(nullptr);
  }
private:
  // IgH 1.5 has some void APIs which return status in 1.6. Check errors where
  // available and always validate WKC/slave state on the following receive.
  template<class F> static bool ok(F call)
  {
    if constexpr (std::is_void_v<decltype(call())>) {call(); return true;}
    else {return call() >= 0;}
  }
  void verify_mapping(std::size_t i)
  {
    ec_slave_info_t slave{};
    if (ecrt_master_get_slave(master_, left_arm_slaves[i], &slave) ||
      slave.vendor_id != config_.vendor || slave.product_code != config_.product) {
      throw std::runtime_error("Connected device is not the configured EYOU left-arm servo");
    }
    std::array<unsigned, 6> found{};
    const std::array<std::uint16_t, 6> indices{0x607a, 0x6040, 0x6064, 0x606c, 0x6041, 0x6061};
    const std::array<unsigned, 6> widths{32, 16, 32, 32, 16, 8};
    offsets_[i].has_mode_command = false;
    for (unsigned sm = 2; sm < slave.sync_count; ++sm) {
      ec_sync_info_t sync{};
      if (ecrt_master_get_sync_manager(master_, left_arm_slaves[i], sm, &sync)) {
        throw std::runtime_error("Cannot inspect left-arm sync manager");
      }
      for (unsigned p = 0; p < sync.n_pdos; ++p) {
        ec_pdo_info_t pdo{};
        if (ecrt_master_get_pdo(master_, left_arm_slaves[i], sm, p, &pdo)) {
          throw std::runtime_error("Cannot inspect left-arm PDO");
        }
        for (unsigned e = 0; e < pdo.n_entries; ++e) {
          ec_pdo_entry_info_t entry{};
          if (ecrt_master_get_pdo_entry(master_, left_arm_slaves[i], sm, p, e, &entry)) {
            throw std::runtime_error("Cannot inspect left-arm PDO entry");
          }
          for (std::size_t k = 0; k < indices.size(); ++k) {
            if (entry.index == indices[k] && entry.subindex == 0) {
              if (entry.bit_length != widths[k] || sm != (k < 2 ? 2u : 3u) ||
                sync.dir != (k < 2 ? EC_DIR_OUTPUT : EC_DIR_INPUT) || ++found[k] != 1) {
                throw std::runtime_error("Wrong PDO width/direction or duplicate left-arm entry");
              }
            }
          }
          if (sync.dir == EC_DIR_OUTPUT && entry.index != 0) {
            // Known feed-forward/offset outputs remain zero. Unknown output
            // objects require a reviewed adapter, never silently write zeros.
            unsigned expected = 0;
            switch (entry.index) {
              case 0x6040: case 0x6071: case 0x60b2: expected = 16; break;
              case 0x607a: case 0x60ff: case 0x60b0: case 0x60b1: expected = 32; break;
              case 0x6060:
                if (offsets_[i].has_mode_command) {throw std::runtime_error("Duplicate mode output");}
                offsets_[i].has_mode_command = true; expected = 8; break;
              default: throw std::runtime_error("Unsupported left-arm RxPDO output object");
            }
            if (sm != 2 || entry.subindex != 0 || entry.bit_length != expected) {
              throw std::runtime_error("Unsupported left-arm RxPDO layout");
            }
          }
        }
      }
    }
    for (unsigned count : found) {
      if (count != 1) {throw std::runtime_error("Required left-arm PDO entry missing; verify SII mapping");}
    }
  }
  unsigned reg(std::size_t i, std::uint16_t index)
  {
    unsigned bit = 0;
    const int offset = ecrt_slave_config_reg_pdo_entry(slaves_[i], index, 0, domain_, &bit);
    if (offset < 0 || bit) {throw std::runtime_error("Required byte-aligned left-arm PDO entry missing");}
    return static_cast<unsigned>(offset);
  }
  struct Offsets {
    unsigned target{}, control{}, position{}, velocity{}, status{}, mode{}, mode_command{};
    bool has_mode_command{false};
  };
  ArmBusConfig config_{};
  ec_master_t * master_{nullptr};
  ec_domain_t * domain_{nullptr};
  std::uint8_t * data_{nullptr};
  std::array<ec_slave_config_t *, 4> slaves_{};
  std::array<Offsets, 4> offsets_{};
};
}  // namespace linglong_control
