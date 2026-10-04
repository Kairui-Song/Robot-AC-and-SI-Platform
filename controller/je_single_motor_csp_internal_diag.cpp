#include <ecrt.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <limits>
#include <numeric>
#include <set>
#include <unistd.h>
#include <vector>

namespace {

constexpr uint32_t JE_VENDOR_ID = 0x03456789;
constexpr uint32_t JE_PRODUCT_CODE = 0x00000000;

constexpr long PERIOD_NS = 1000000L;
constexpr uint16_t SDK_ASSIGN_ACTIVATE = 0x0300;
constexpr uint32_t SDK_SYNC0_CYCLE_NS = 1000000U;
constexpr int32_t SDK_SYNC0_SHIFT_NS = 500000;
constexpr uint32_t SDK_SYNC1_CYCLE_NS = 0U;
constexpr int32_t SDK_SYNC1_SHIFT_NS = 0;

constexpr int32_t MAX_DELTA_COUNTS = 1000;
constexpr uint64_t PRE_ENABLE_STABLE_CYCLES = 1000;
constexpr uint64_t PRE_ENABLE_MAX_WAIT_CYCLES = 10000;
constexpr uint64_t PREFLIGHT_OBSERVE_CYCLES = 5000;
constexpr uint64_t PHASE_TIMEOUT_CYCLES = 2000;
constexpr uint64_t ENABLE_HOLD_CYCLES = 1000;
constexpr uint64_t RAMP_CYCLES = 2000;
constexpr uint64_t HOLD_CYCLES = 3000;
constexpr uint64_t RETURN_CYCLES = 2000;
constexpr uint64_t DISABLE_FLUSH_CYCLES = 32;
constexpr uint64_t STARTUP_ABORT_CYCLES = 10000;
constexpr uint64_t DIAG_INTERVAL_CYCLES = 20;
constexpr size_t LOG_CAPACITY = 20000;

constexpr int8_t MODE_CSP = 8;

ec_master_t *master = nullptr;
ec_domain_t *domain = nullptr;
ec_slave_config_t *slave_config = nullptr;
uint8_t *domain_pd = nullptr;

std::atomic<bool> running(true);

unsigned int off_607a = 0;
unsigned int off_60ff = 0;
unsigned int off_6071 = 0;
unsigned int off_6040 = 0;
unsigned int off_6060 = 0;
unsigned int off_2000 = 0;
unsigned int off_60b2 = 0;
unsigned int off_60b1 = 0;
unsigned int off_6064 = 0;
unsigned int off_606c = 0;
unsigned int off_6077 = 0;
unsigned int off_6041 = 0;

ec_pdo_entry_info_t slave_0_pdo_entries[] = {
    {0x607a, 0x00, 32},
    {0x60ff, 0x00, 32},
    {0x6071, 0x00, 16},
    {0x6040, 0x00, 16},
    {0x6060, 0x00, 8},
    {0x2000, 0x00, 8},
    {0x60b2, 0x00, 16},
    {0x60b1, 0x00, 32},
    {0x6064, 0x00, 32},
    {0x606c, 0x00, 32},
    {0x6077, 0x00, 16},
    {0x6041, 0x00, 16},
};

ec_pdo_info_t slave_0_pdos[] = {
    {0x1600, 8, slave_0_pdo_entries + 0},
    {0x1a00, 4, slave_0_pdo_entries + 8},
};

ec_sync_info_t slave_0_syncs[] = {
    {0, EC_DIR_OUTPUT, 0, nullptr, EC_WD_DISABLE},
    {1, EC_DIR_INPUT, 0, nullptr, EC_WD_DISABLE},
    {2, EC_DIR_OUTPUT, 1, slave_0_pdos + 0, EC_WD_ENABLE},
    {3, EC_DIR_INPUT, 1, slave_0_pdos + 1, EC_WD_DISABLE},
    {0xff},
};

ec_pdo_entry_reg_t domain_regs[] = {
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x607a, 0x00, &off_607a},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x60ff, 0x00, &off_60ff},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x6071, 0x00, &off_6071},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x6040, 0x00, &off_6040},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x6060, 0x00, &off_6060},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x2000, 0x00, &off_2000},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x60b2, 0x00, &off_60b2},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x60b1, 0x00, &off_60b1},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x6064, 0x00, &off_6064},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x606c, 0x00, &off_606c},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x6077, 0x00, &off_6077},
    {0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE, 0x6041, 0x00, &off_6041},
    {},
};

enum class Phase : uint8_t {
    Startup = 0,
    PreEnableStable,
    PreflightObserve,
    WaitReadyToSwitchOn,
    WaitSwitchedOn,
    WaitOperationEnabled,
    EnableHold,
    RampOut,
    HoldOut,
    RampBack,
    DisableFlush,
    Complete,
    Abort,
};

enum class DiagType : uint8_t {
    U8,
    U16,
    U32,
};

struct DiagSignal {
    const char *name;
    uint16_t index;
    uint8_t subindex;
    DiagType type;
    ec_sdo_request_t *request;
    uint64_t value;
    bool valid;
    uint64_t last_success_cycle;
    uint64_t success_count;
    uint64_t error_count;
};

struct LogRow {
    uint64_t cycle;
    int64_t timestamp_ns;
    int64_t deadline_ns;
    int64_t lateness_ns;
    uint32_t missed_cycles;
    uint16_t statusword_raw;
    uint16_t statusword_masked;
    uint16_t controlword;
    int8_t mode_command;
    int32_t target_position;
    int32_t actual_position;
    int32_t actual_velocity;
    int16_t actual_torque;
    uint32_t working_counter;
    uint32_t wc_state;
    uint8_t slave_online;
    uint8_t slave_operational;
    uint8_t master_link_up;
    uint8_t phase;
    uint32_t motor_int_pos_3005;
    uint8_t motor_int_pos_3005_valid;
    uint64_t motor_int_pos_3005_age_cycles;
    uint16_t current_a_ad_3006;
    uint8_t current_a_ad_3006_valid;
    uint64_t current_a_ad_3006_age_cycles;
    uint16_t current_b_ad_3007;
    uint8_t current_b_ad_3007_valid;
    uint64_t current_b_ad_3007_age_cycles;
    uint16_t current_c_ad_3008;
    uint8_t current_c_ad_3008_valid;
    uint64_t current_c_ad_3008_age_cycles;
    uint16_t current_oos_ad_3009;
    uint8_t current_oos_ad_3009_valid;
    uint64_t current_oos_ad_3009_age_cycles;
    uint8_t control_mode_300a;
    uint8_t control_mode_300a_valid;
    uint64_t control_mode_300a_age_cycles;
};

struct SummaryStats {
    const char *name;
    size_t samples;
    double pos_err_min;
    double pos_err_max;
    double pos_err_median;
    double torque_mean;
    double torque_abs_mean;
    int16_t torque_min;
    int16_t torque_max;
    double current_a_mean;
    uint16_t current_a_min;
    uint16_t current_a_max;
    double current_b_mean;
    uint16_t current_b_min;
    uint16_t current_b_max;
    double current_c_mean;
    uint16_t current_c_min;
    uint16_t current_c_max;
    double current_oos_mean;
    uint16_t current_oos_min;
    uint16_t current_oos_max;
    uint32_t motor_int_pos_min;
    uint32_t motor_int_pos_max;
    std::set<uint32_t> control_mode_values;
    bool complete;
};

LogRow log_rows[LOG_CAPACITY];
size_t log_count = 0;

std::array<DiagSignal, 6> diag_signals = {{
    {"motor_int_pos_3005", 0x3005, 0x00, DiagType::U32, nullptr, 0, false, 0, 0, 0},
    {"current_a_ad_3006", 0x3006, 0x00, DiagType::U16, nullptr, 0, false, 0, 0, 0},
    {"current_b_ad_3007", 0x3007, 0x00, DiagType::U16, nullptr, 0, false, 0, 0, 0},
    {"current_c_ad_3008", 0x3008, 0x00, DiagType::U16, nullptr, 0, false, 0, 0, 0},
    {"current_oos_ad_3009", 0x3009, 0x00, DiagType::U16, nullptr, 0, false, 0, 0, 0},
    {"control_mode_300a", 0x300A, 0x00, DiagType::U8, nullptr, 0, false, 0, 0, 0},
}};

size_t active_diag_index = diag_signals.size();
size_t next_diag_index = 0;
uint64_t next_diag_cycle = 0;

void signal_handler(int) {
    running = false;
}

int64_t timespec_to_ns(const timespec &ts) {
    return static_cast<int64_t>(ts.tv_sec) * 1000000000LL + static_cast<int64_t>(ts.tv_nsec);
}

void add_ns(timespec &ts, long ns) {
    ts.tv_nsec += ns;
    while (ts.tv_nsec >= 1000000000L) {
        ts.tv_nsec -= 1000000000L;
        ++ts.tv_sec;
    }
}

bool timespec_is_past(const timespec &lhs, const timespec &rhs) {
    if (lhs.tv_sec != rhs.tv_sec) {
        return lhs.tv_sec > rhs.tv_sec;
    }
    return lhs.tv_nsec > rhs.tv_nsec;
}

const char *phase_name(Phase phase) {
    switch (phase) {
        case Phase::Startup: return "startup";
        case Phase::PreEnableStable: return "pre_enable_stable";
        case Phase::PreflightObserve: return "preflight_observe";
        case Phase::WaitReadyToSwitchOn: return "wait_ready_to_switch_on";
        case Phase::WaitSwitchedOn: return "wait_switched_on";
        case Phase::WaitOperationEnabled: return "wait_operation_enabled";
        case Phase::EnableHold: return "enable_hold";
        case Phase::RampOut: return "ramp_out";
        case Phase::HoldOut: return "hold_out";
        case Phase::RampBack: return "ramp_back";
        case Phase::DisableFlush: return "disable_flush";
        case Phase::Complete: return "complete";
        case Phase::Abort: return "abort";
    }
    return "unknown";
}

uint16_t statusword_state(uint16_t statusword) {
    return statusword & 0x006F;
}

bool is_fault(uint16_t statusword) {
    return statusword & 0x0008;
}

bool state_is_ready_to_switch_on(uint16_t statusword) {
    return statusword_state(statusword) == 0x0021;
}

bool state_is_switched_on(uint16_t statusword) {
    return statusword_state(statusword) == 0x0023;
}

bool state_is_operation_enabled(uint16_t statusword) {
    return statusword_state(statusword) == 0x0027;
}

void write_safe_outputs(uint16_t controlword, int8_t mode, int32_t target_position) {
    EC_WRITE_S32(domain_pd + off_607a, target_position);
    EC_WRITE_S32(domain_pd + off_60ff, 0);
    EC_WRITE_S16(domain_pd + off_6071, 0);
    EC_WRITE_U16(domain_pd + off_6040, controlword);
    EC_WRITE_U8(domain_pd + off_6060, static_cast<uint8_t>(mode));
    EC_WRITE_U8(domain_pd + off_2000, 0);
    EC_WRITE_S16(domain_pd + off_60b2, 0);
    EC_WRITE_S32(domain_pd + off_60b1, 0);
}

bool configure_slave() {
    if (ecrt_slave_config_pdos(slave_config, EC_END, slave_0_syncs)) {
        std::fprintf(stderr, "Failed to configure PDOs\n");
        return false;
    }
    if (ecrt_domain_reg_pdo_entry_list(domain, domain_regs)) {
        std::fprintf(stderr, "Failed to register PDO entries\n");
        return false;
    }
    if (ecrt_slave_config_sdo8(slave_config, 0x60C2, 0x01, 0x01)) {
        std::fprintf(stderr, "Failed to configure 0x60C2:01\n");
        return false;
    }
    if (ecrt_slave_config_sdo8(slave_config, 0x60C2, 0x02, 0xFD)) {
        std::fprintf(stderr, "Failed to configure 0x60C2:02\n");
        return false;
    }
    if (ecrt_slave_config_dc(
            slave_config,
            SDK_ASSIGN_ACTIVATE,
            SDK_SYNC0_CYCLE_NS,
            SDK_SYNC0_SHIFT_NS,
            SDK_SYNC1_CYCLE_NS,
            SDK_SYNC1_SHIFT_NS) != 0) {
        std::fprintf(stderr, "Failed to configure DC sync\n");
        return false;
    }
    return true;
}

bool create_diag_requests() {
    for (DiagSignal &signal : diag_signals) {
        size_t size = 0;
        switch (signal.type) {
            case DiagType::U8: size = sizeof(uint8_t); break;
            case DiagType::U16: size = sizeof(uint16_t); break;
            case DiagType::U32: size = sizeof(uint32_t); break;
        }
        signal.request = ecrt_slave_config_create_sdo_request(slave_config, signal.index, signal.subindex, size);
        if (!signal.request) {
            std::fprintf(stderr, "Failed to create async SDO request for 0x%04X\n", signal.index);
            return false;
        }
        ecrt_sdo_request_timeout(signal.request, 500);
    }
    return true;
}

void print_phase_change(Phase phase, uint64_t cycle, uint16_t statusword, int32_t actual, int32_t target) {
    std::printf("[phase] cycle=%llu phase=%s sw=0x%04X actual=%d target=%d\n",
                static_cast<unsigned long long>(cycle), phase_name(phase), statusword, actual, target);
    std::fflush(stdout);
}

void print_runtime_states(const ec_master_state_t &master_state,
                          const ec_domain_state_t &domain_state,
                          const ec_slave_config_state_t &slave_state) {
    std::printf("[state] master: slaves_responding=%u al_states=0x%02X link_up=%u\n",
                master_state.slaves_responding,
                master_state.al_states,
                master_state.link_up);
    std::printf("[state] domain: working_counter=%u wc_state=%u\n",
                domain_state.working_counter,
                domain_state.wc_state);
    std::printf("[state] slave: online=%u operational=%u\n",
                slave_state.online,
                slave_state.operational);
    std::fflush(stdout);
}

void start_next_diag_request(uint64_t cycle) {
    if (active_diag_index < diag_signals.size()) {
        return;
    }
    if (cycle < next_diag_cycle) {
        return;
    }
    DiagSignal &signal = diag_signals[next_diag_index];
    ecrt_sdo_request_read(signal.request);
    active_diag_index = next_diag_index;
    next_diag_index = (next_diag_index + 1) % diag_signals.size();
    next_diag_cycle = cycle + DIAG_INTERVAL_CYCLES;
}

void update_diag_value(DiagSignal &signal, uint64_t cycle) {
    const uint8_t *data = ecrt_sdo_request_data(signal.request);
    const size_t size = ecrt_sdo_request_data_size(signal.request);
    switch (signal.type) {
        case DiagType::U8:
            if (size >= sizeof(uint8_t)) {
                signal.value = EC_READ_U8(data);
                signal.valid = true;
                signal.last_success_cycle = cycle;
                ++signal.success_count;
            }
            break;
        case DiagType::U16:
            if (size >= sizeof(uint16_t)) {
                signal.value = EC_READ_U16(data);
                signal.valid = true;
                signal.last_success_cycle = cycle;
                ++signal.success_count;
            }
            break;
        case DiagType::U32:
            if (size >= sizeof(uint32_t)) {
                signal.value = EC_READ_U32(data);
                signal.valid = true;
                signal.last_success_cycle = cycle;
                ++signal.success_count;
            }
            break;
    }
}

void poll_diag_requests(uint64_t cycle) {
    if (active_diag_index < diag_signals.size()) {
        DiagSignal &signal = diag_signals[active_diag_index];
        switch (ecrt_sdo_request_state(signal.request)) {
            case EC_REQUEST_SUCCESS:
                update_diag_value(signal, cycle);
                active_diag_index = diag_signals.size();
                break;
            case EC_REQUEST_ERROR:
                ++signal.error_count;
                active_diag_index = diag_signals.size();
                break;
            case EC_REQUEST_UNUSED:
            case EC_REQUEST_BUSY:
                break;
        }
    }
    start_next_diag_request(cycle);
}

uint64_t diag_age_cycles(const DiagSignal &signal, uint64_t cycle) {
    if (!signal.valid) {
        return 0;
    }
    return cycle - signal.last_success_cycle;
}

void write_csv(const char *path) {
    FILE *file = std::fopen(path, "w");
    if (!file) {
        std::fprintf(stderr, "Failed to open CSV %s\n", path);
        return;
    }
    std::fprintf(file,
                 "cycle,timestamp_ns,deadline_ns,lateness_ns,missed_cycles,statusword_raw,statusword_masked,controlword,"
                 "mode_command,target_position,actual_position,actual_velocity,actual_torque,working_counter,wc_state,"
                 "slave_online,slave_operational,master_link_up,phase,"
                 "motor_int_pos_3005,motor_int_pos_3005_valid,motor_int_pos_3005_age_cycles,"
                 "current_a_ad_3006,current_a_ad_3006_valid,current_a_ad_3006_age_cycles,"
                 "current_b_ad_3007,current_b_ad_3007_valid,current_b_ad_3007_age_cycles,"
                 "current_c_ad_3008,current_c_ad_3008_valid,current_c_ad_3008_age_cycles,"
                 "current_oos_ad_3009,current_oos_ad_3009_valid,current_oos_ad_3009_age_cycles,"
                 "control_mode_300a,control_mode_300a_valid,control_mode_300a_age_cycles\n");
    for (size_t i = 0; i < log_count; ++i) {
        const LogRow &row = log_rows[i];
        std::fprintf(file,
                     "%llu,%lld,%lld,%lld,%u,0x%04X,0x%04X,0x%04X,%d,%d,%d,%d,%d,%u,%u,%u,%u,%u,%u,"
                     "%u,%u,%llu,%u,%u,%llu,%u,%u,%llu,%u,%u,%llu,%u,%u,%llu,%u,%u,%llu\n",
                     static_cast<unsigned long long>(row.cycle),
                     static_cast<long long>(row.timestamp_ns),
                     static_cast<long long>(row.deadline_ns),
                     static_cast<long long>(row.lateness_ns),
                     row.missed_cycles,
                     row.statusword_raw,
                     row.statusword_masked,
                     row.controlword,
                     static_cast<int>(row.mode_command),
                     row.target_position,
                     row.actual_position,
                     row.actual_velocity,
                     row.actual_torque,
                     row.working_counter,
                     row.wc_state,
                     row.slave_online,
                     row.slave_operational,
                     row.master_link_up,
                     row.phase,
                     row.motor_int_pos_3005,
                     row.motor_int_pos_3005_valid,
                     static_cast<unsigned long long>(row.motor_int_pos_3005_age_cycles),
                     row.current_a_ad_3006,
                     row.current_a_ad_3006_valid,
                     static_cast<unsigned long long>(row.current_a_ad_3006_age_cycles),
                     row.current_b_ad_3007,
                     row.current_b_ad_3007_valid,
                     static_cast<unsigned long long>(row.current_b_ad_3007_age_cycles),
                     row.current_c_ad_3008,
                     row.current_c_ad_3008_valid,
                     static_cast<unsigned long long>(row.current_c_ad_3008_age_cycles),
                     row.current_oos_ad_3009,
                     row.current_oos_ad_3009_valid,
                     static_cast<unsigned long long>(row.current_oos_ad_3009_age_cycles),
                     row.control_mode_300a,
                     row.control_mode_300a_valid,
                     static_cast<unsigned long long>(row.control_mode_300a_age_cycles));
    }
    std::fclose(file);
}

double mean_i16(const std::vector<int16_t> &values) {
    if (values.empty()) {
        return 0.0;
    }
    double sum = std::accumulate(values.begin(), values.end(), 0.0);
    return sum / static_cast<double>(values.size());
}

double abs_mean_i16(const std::vector<int16_t> &values) {
    if (values.empty()) {
        return 0.0;
    }
    double sum = 0.0;
    for (int16_t value : values) {
        sum += std::abs(static_cast<int>(value));
    }
    return sum / static_cast<double>(values.size());
}

template <typename T>
double mean_u(const std::vector<T> &values) {
    if (values.empty()) {
        return 0.0;
    }
    double sum = std::accumulate(values.begin(), values.end(), 0.0);
    return sum / static_cast<double>(values.size());
}

double median_double(std::vector<double> values) {
    if (values.empty()) {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    const size_t mid = values.size() / 2;
    if ((values.size() % 2U) == 0U) {
        return 0.5 * (values[mid - 1] + values[mid]);
    }
    return values[mid];
}

SummaryStats summarize_phase(Phase phase, const char *name) {
    SummaryStats stats{};
    stats.name = name;
    stats.pos_err_min = 0.0;
    stats.pos_err_max = 0.0;
    stats.pos_err_median = 0.0;
    stats.torque_mean = 0.0;
    stats.torque_abs_mean = 0.0;
    stats.torque_min = 0;
    stats.torque_max = 0;
    stats.current_a_mean = 0.0;
    stats.current_a_min = 0;
    stats.current_a_max = 0;
    stats.current_b_mean = 0.0;
    stats.current_b_min = 0;
    stats.current_b_max = 0;
    stats.current_c_mean = 0.0;
    stats.current_c_min = 0;
    stats.current_c_max = 0;
    stats.current_oos_mean = 0.0;
    stats.current_oos_min = 0;
    stats.current_oos_max = 0;
    stats.motor_int_pos_min = 0;
    stats.motor_int_pos_max = 0;
    stats.complete = false;

    std::vector<double> pos_errors;
    std::vector<int16_t> torques;
    std::vector<uint16_t> current_a;
    std::vector<uint16_t> current_b;
    std::vector<uint16_t> current_c;
    std::vector<uint16_t> current_oos;
    std::vector<uint32_t> motor_int_pos;

    for (size_t i = 0; i < log_count; ++i) {
        const LogRow &row = log_rows[i];
        if (row.phase != static_cast<uint8_t>(phase)) {
            continue;
        }
        pos_errors.push_back(static_cast<double>(row.target_position - row.actual_position));
        torques.push_back(row.actual_torque);
        if (row.current_a_ad_3006_valid) {
            current_a.push_back(row.current_a_ad_3006);
        }
        if (row.current_b_ad_3007_valid) {
            current_b.push_back(row.current_b_ad_3007);
        }
        if (row.current_c_ad_3008_valid) {
            current_c.push_back(row.current_c_ad_3008);
        }
        if (row.current_oos_ad_3009_valid) {
            current_oos.push_back(row.current_oos_ad_3009);
        }
        if (row.motor_int_pos_3005_valid) {
            motor_int_pos.push_back(row.motor_int_pos_3005);
        }
        if (row.control_mode_300a_valid) {
            stats.control_mode_values.insert(row.control_mode_300a);
        }
    }

    stats.samples = pos_errors.size();
    if (stats.samples == 0) {
        return stats;
    }

    const auto pos_minmax = std::minmax_element(pos_errors.begin(), pos_errors.end());
    stats.pos_err_min = *pos_minmax.first;
    stats.pos_err_max = *pos_minmax.second;
    stats.pos_err_median = median_double(pos_errors);

    const auto torque_minmax = std::minmax_element(torques.begin(), torques.end());
    stats.torque_min = *torque_minmax.first;
    stats.torque_max = *torque_minmax.second;
    stats.torque_mean = mean_i16(torques);
    stats.torque_abs_mean = abs_mean_i16(torques);

    if (!current_a.empty()) {
        const auto minmax = std::minmax_element(current_a.begin(), current_a.end());
        stats.current_a_min = *minmax.first;
        stats.current_a_max = *minmax.second;
        stats.current_a_mean = mean_u(current_a);
    }
    if (!current_b.empty()) {
        const auto minmax = std::minmax_element(current_b.begin(), current_b.end());
        stats.current_b_min = *minmax.first;
        stats.current_b_max = *minmax.second;
        stats.current_b_mean = mean_u(current_b);
    }
    if (!current_c.empty()) {
        const auto minmax = std::minmax_element(current_c.begin(), current_c.end());
        stats.current_c_min = *minmax.first;
        stats.current_c_max = *minmax.second;
        stats.current_c_mean = mean_u(current_c);
    }
    if (!current_oos.empty()) {
        const auto minmax = std::minmax_element(current_oos.begin(), current_oos.end());
        stats.current_oos_min = *minmax.first;
        stats.current_oos_max = *minmax.second;
        stats.current_oos_mean = mean_u(current_oos);
    }
    if (!motor_int_pos.empty()) {
        const auto minmax = std::minmax_element(motor_int_pos.begin(), motor_int_pos.end());
        stats.motor_int_pos_min = *minmax.first;
        stats.motor_int_pos_max = *minmax.second;
    }

    stats.complete = true;
    return stats;
}

void print_summary(const SummaryStats &stats) {
    std::printf("[summary] phase=%s samples=%zu\n", stats.name, stats.samples);
    if (!stats.complete) {
        std::printf("[summary] phase=%s no samples\n", stats.name);
        return;
    }
    std::printf("[summary] phase=%s position_error median=%.3f min=%.3f max=%.3f\n",
                stats.name, stats.pos_err_median, stats.pos_err_min, stats.pos_err_max);
    std::printf("[summary] phase=%s torque mean=%.3f absmean=%.3f min=%d max=%d\n",
                stats.name, stats.torque_mean, stats.torque_abs_mean, stats.torque_min, stats.torque_max);
    std::printf("[summary] phase=%s 3006_A mean=%.3f min=%u max=%u\n",
                stats.name, stats.current_a_mean, stats.current_a_min, stats.current_a_max);
    std::printf("[summary] phase=%s 3007_B mean=%.3f min=%u max=%u\n",
                stats.name, stats.current_b_mean, stats.current_b_min, stats.current_b_max);
    std::printf("[summary] phase=%s 3008_C mean=%.3f min=%u max=%u\n",
                stats.name, stats.current_c_mean, stats.current_c_min, stats.current_c_max);
    std::printf("[summary] phase=%s 3009_OOS mean=%.3f min=%u max=%u\n",
                stats.name, stats.current_oos_mean, stats.current_oos_min, stats.current_oos_max);
    std::printf("[summary] phase=%s 3005 min=%u max=%u\n",
                stats.name, stats.motor_int_pos_min, stats.motor_int_pos_max);
    std::printf("[summary] phase=%s 300A unique=", stats.name);
    if (stats.control_mode_values.empty()) {
        std::printf("none");
    } else {
        bool first = true;
        for (uint32_t value : stats.control_mode_values) {
            std::printf("%s%u", first ? "" : ",", value);
            first = false;
        }
    }
    std::printf("\n");
}

void print_comparison(const SummaryStats &enable_hold, const SummaryStats &hold_out) {
    if (!enable_hold.complete || !hold_out.complete) {
        std::printf("[comparison] insufficient data for ENABLE_HOLD vs HOLD_OUT\n");
        return;
    }
    const double enable_abs_err = std::abs(enable_hold.pos_err_median);
    const double hold_abs_err = std::abs(hold_out.pos_err_median);
    const bool error_grew = hold_abs_err > enable_abs_err + 5.0;
    const bool current_a_shift = std::abs(hold_out.current_a_mean - enable_hold.current_a_mean) > 5.0;
    const bool current_b_shift = std::abs(hold_out.current_b_mean - enable_hold.current_b_mean) > 5.0;
    const bool current_c_shift = std::abs(hold_out.current_c_mean - enable_hold.current_c_mean) > 5.0;
    std::printf("[comparison] enable_hold_pos_err_median=%.3f hold_out_pos_err_median=%.3f\n",
                enable_hold.pos_err_median, hold_out.pos_err_median);
    std::printf("[comparison] current_mean_shift A=%.3f B=%.3f C=%.3f\n",
                hold_out.current_a_mean - enable_hold.current_a_mean,
                hold_out.current_b_mean - enable_hold.current_b_mean,
                hold_out.current_c_mean - enable_hold.current_c_mean);
    if (error_grew && (current_a_shift || current_b_shift || current_c_shift)) {
        std::printf("[comparison] position error increased and CurrentA/B/C raw moved away from ENABLE_HOLD baseline\n");
    } else if (error_grew) {
        std::printf("[comparison] position error increased without a strong A/B/C raw baseline shift\n");
    } else {
        std::printf("[comparison] no material position error increase from ENABLE_HOLD to HOLD_OUT\n");
    }
}

}  // namespace

int main(int argc, char **argv) {
    int32_t requested_delta = MAX_DELTA_COUNTS;
    bool preflight_only = false;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--preflight") == 0) {
            preflight_only = true;
            continue;
        }
        requested_delta = std::atoi(argv[i]);
    }
    if (requested_delta < 0) {
        requested_delta = -requested_delta;
    }
    if (requested_delta > MAX_DELTA_COUNTS) {
        requested_delta = MAX_DELTA_COUNTS;
    }

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::printf("JE CSP internal diag preparation\n");
    std::printf("mode=%s delta=%d assign=0x%04X sync0_cycle=%u sync0_shift=%d diag_interval_cycles=%llu\n",
                preflight_only ? "preflight" : "motion",
                requested_delta,
                SDK_ASSIGN_ACTIVATE,
                SDK_SYNC0_CYCLE_NS,
                SDK_SYNC0_SHIFT_NS,
                static_cast<unsigned long long>(DIAG_INTERVAL_CYCLES));

    master = ecrt_request_master(0);
    if (!master) {
        std::fprintf(stderr, "Failed to request master 0\n");
        return 1;
    }

    domain = ecrt_master_create_domain(master);
    if (!domain) {
        std::fprintf(stderr, "Failed to create domain\n");
        ecrt_release_master(master);
        return 1;
    }

    slave_config = ecrt_master_slave_config(master, 0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE);
    if (!slave_config) {
        std::fprintf(stderr, "Failed to get slave config\n");
        ecrt_release_master(master);
        return 1;
    }

    if (!configure_slave()) {
        ecrt_release_master(master);
        return 1;
    }
    if (!create_diag_requests()) {
        ecrt_release_master(master);
        return 1;
    }

    if (ecrt_master_activate(master)) {
        std::fprintf(stderr, "Failed to activate master\n");
        ecrt_release_master(master);
        return 1;
    }

    domain_pd = ecrt_domain_data(domain);
    if (!domain_pd) {
        std::fprintf(stderr, "Failed to get process data\n");
        ecrt_master_deactivate(master);
        ecrt_release_master(master);
        return 1;
    }

    timespec next_deadline{};
    clock_gettime(CLOCK_MONOTONIC, &next_deadline);

    ec_master_state_t master_state{};
    ec_domain_state_t domain_state{};
    ec_slave_config_state_t slave_state{};

    Phase phase = Phase::Startup;
    Phase previous_phase = phase;

    uint16_t controlword = 0x0000;
    int32_t start_position = 0;
    int32_t target_position = 0;
    bool start_position_locked = false;
    bool motion_started = false;
    bool abort_requested = false;
    uint64_t stable_cycles = 0;
    uint64_t pre_enable_wait_cycles = 0;
    uint64_t phase_cycle = 0;
    uint64_t cycle = 0;
    uint64_t startup_problem_cycles = 0;
    int8_t commanded_mode = MODE_CSP;

    while (running) {
        add_ns(next_deadline, PERIOD_NS);
        const timespec cycle_deadline = next_deadline;

        int ret = 0;
        do {
            ret = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &cycle_deadline, nullptr);
        } while (ret == EINTR && running);
        if (!running) {
            break;
        }
        if (ret != 0 && ret != EINTR) {
            std::fprintf(stderr, "clock_nanosleep failed: %s\n", std::strerror(ret));
            abort_requested = true;
            break;
        }

        timespec cycle_time{};
        clock_gettime(CLOCK_MONOTONIC, &cycle_time);
        const int64_t cycle_time_ns = timespec_to_ns(cycle_time);
        const int64_t cycle_deadline_ns = timespec_to_ns(cycle_deadline);
        const int64_t lateness_ns = cycle_time_ns - cycle_deadline_ns;
        uint32_t missed_cycles = 0;
        while (timespec_is_past(cycle_time, next_deadline) &&
               cycle_time_ns - timespec_to_ns(next_deadline) >= PERIOD_NS) {
            add_ns(next_deadline, PERIOD_NS);
            ++missed_cycles;
        }
        if (missed_cycles > 0) {
            std::printf("[timing] cycle=%llu missed_cycles=%u lateness_ns=%lld\n",
                        static_cast<unsigned long long>(cycle),
                        missed_cycles,
                        static_cast<long long>(lateness_ns));
            std::fflush(stdout);
        }

        ecrt_master_application_time(master, cycle_time_ns);
        ecrt_master_receive(master);
        ecrt_domain_process(domain);

        uint16_t statusword = EC_READ_U16(domain_pd + off_6041);
        int32_t actual_position = EC_READ_S32(domain_pd + off_6064);
        int32_t actual_velocity = EC_READ_S32(domain_pd + off_606c);
        int16_t actual_torque = EC_READ_S16(domain_pd + off_6077);

        ecrt_domain_state(domain, &domain_state);
        ecrt_slave_config_state(slave_config, &slave_state);
        ecrt_master_state(master, &master_state);

        poll_diag_requests(cycle);

        const bool wkc_complete = domain_state.wc_state == EC_WC_COMPLETE;
        const bool statusword_usable = statusword != 0;
        const bool dc_ready = master_state.link_up && slave_state.online && slave_state.operational && wkc_complete;
        const bool fault = is_fault(statusword);

        if (!dc_ready || !statusword_usable) {
            ++startup_problem_cycles;
        } else {
            startup_problem_cycles = 0;
        }

        if (!start_position_locked && dc_ready) {
            start_position = actual_position;
            target_position = actual_position;
            start_position_locked = true;
            phase = Phase::PreEnableStable;
            phase_cycle = 0;
            stable_cycles = 0;
            pre_enable_wait_cycles = 0;
            print_phase_change(phase, cycle, statusword, actual_position, target_position);
        }

        if (startup_problem_cycles >= STARTUP_ABORT_CYCLES &&
            phase != Phase::Abort &&
            phase != Phase::DisableFlush &&
            phase != Phase::Complete) {
            abort_requested = true;
            phase = Phase::Abort;
            phase_cycle = 0;
            std::printf("[abort] cycle=%llu startup timeout wkc_complete=%u statusword=0x%04X\n",
                        static_cast<unsigned long long>(cycle),
                        wkc_complete ? 1U : 0U,
                        statusword);
            print_runtime_states(master_state, domain_state, slave_state);
        }

        const bool active_phase =
            phase == Phase::PreflightObserve ||
            phase == Phase::WaitReadyToSwitchOn ||
            phase == Phase::WaitSwitchedOn ||
            phase == Phase::WaitOperationEnabled ||
            phase == Phase::EnableHold ||
            phase == Phase::RampOut ||
            phase == Phase::HoldOut ||
            phase == Phase::RampBack;
        if ((fault || (active_phase && !dc_ready)) &&
            phase != Phase::Abort &&
            phase != Phase::DisableFlush &&
            phase != Phase::Complete) {
            abort_requested = true;
            phase = Phase::Abort;
            phase_cycle = 0;
            std::printf("[abort] cycle=%llu fault=%u link=%u online=%u operational=%u wc_state=%u sw=0x%04X phase=%s\n",
                        static_cast<unsigned long long>(cycle),
                        fault ? 1U : 0U,
                        master_state.link_up,
                        slave_state.online,
                        slave_state.operational,
                        domain_state.wc_state,
                        statusword,
                        phase_name(previous_phase));
            print_runtime_states(master_state, domain_state, slave_state);
        }

        if (!motion_started) {
            target_position = actual_position;
        }

        switch (phase) {
            case Phase::Startup:
                controlword = 0x0000;
                commanded_mode = MODE_CSP;
                break;
            case Phase::PreEnableStable:
                controlword = 0x0000;
                target_position = actual_position;
                commanded_mode = MODE_CSP;
                ++pre_enable_wait_cycles;
                if (dc_ready && !fault && statusword_state(statusword) == 0x0040) {
                    ++stable_cycles;
                } else {
                    stable_cycles = 0;
                }
                if (stable_cycles >= PRE_ENABLE_STABLE_CYCLES) {
                    if (preflight_only) {
                        phase = Phase::PreflightObserve;
                    } else {
                        phase = Phase::WaitReadyToSwitchOn;
                    }
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                } else if (pre_enable_wait_cycles >= PRE_ENABLE_MAX_WAIT_CYCLES) {
                    abort_requested = true;
                    phase = Phase::Abort;
                    phase_cycle = 0;
                    std::printf("[abort] cycle=%llu pre-enable stability timeout stable_cycles=%llu sw_masked=0x%04X\n",
                                static_cast<unsigned long long>(cycle),
                                static_cast<unsigned long long>(stable_cycles),
                                statusword_state(statusword));
                    print_runtime_states(master_state, domain_state, slave_state);
                }
                break;
            case Phase::PreflightObserve:
                controlword = 0x0000;
                target_position = actual_position;
                commanded_mode = MODE_CSP;
                if (++phase_cycle >= PREFLIGHT_OBSERVE_CYCLES) {
                    phase = Phase::DisableFlush;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                }
                break;
            case Phase::WaitReadyToSwitchOn:
                controlword = 0x0006;
                commanded_mode = MODE_CSP;
                if (state_is_ready_to_switch_on(statusword)) {
                    phase = Phase::WaitSwitchedOn;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                } else if (++phase_cycle >= PHASE_TIMEOUT_CYCLES) {
                    abort_requested = true;
                    phase = Phase::Abort;
                    phase_cycle = 0;
                    std::printf("[abort] cycle=%llu timeout waiting for ReadyToSwitchOn sw=0x%04X\n",
                                static_cast<unsigned long long>(cycle), statusword);
                    print_runtime_states(master_state, domain_state, slave_state);
                }
                break;
            case Phase::WaitSwitchedOn:
                controlword = 0x0007;
                commanded_mode = MODE_CSP;
                if (state_is_switched_on(statusword)) {
                    phase = Phase::WaitOperationEnabled;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                } else if (++phase_cycle >= PHASE_TIMEOUT_CYCLES) {
                    abort_requested = true;
                    phase = Phase::Abort;
                    phase_cycle = 0;
                    std::printf("[abort] cycle=%llu timeout waiting for SwitchedOn sw=0x%04X\n",
                                static_cast<unsigned long long>(cycle), statusword);
                    print_runtime_states(master_state, domain_state, slave_state);
                }
                break;
            case Phase::WaitOperationEnabled:
                controlword = 0x000F;
                commanded_mode = MODE_CSP;
                if (state_is_operation_enabled(statusword)) {
                    motion_started = true;
                    start_position = actual_position;
                    target_position = start_position;
                    phase = Phase::EnableHold;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                } else if (++phase_cycle >= PHASE_TIMEOUT_CYCLES) {
                    abort_requested = true;
                    phase = Phase::Abort;
                    phase_cycle = 0;
                    std::printf("[abort] cycle=%llu timeout waiting for OperationEnabled sw=0x%04X\n",
                                static_cast<unsigned long long>(cycle), statusword);
                    print_runtime_states(master_state, domain_state, slave_state);
                }
                break;
            case Phase::EnableHold:
                controlword = 0x000F;
                target_position = start_position;
                commanded_mode = MODE_CSP;
                if (++phase_cycle >= ENABLE_HOLD_CYCLES) {
                    phase = Phase::RampOut;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                }
                break;
            case Phase::RampOut: {
                controlword = 0x000F;
                commanded_mode = MODE_CSP;
                const int64_t numerator = static_cast<int64_t>(requested_delta) * static_cast<int64_t>(phase_cycle);
                target_position = start_position + static_cast<int32_t>(numerator / static_cast<int64_t>(RAMP_CYCLES));
                ++phase_cycle;
                if (phase_cycle >= RAMP_CYCLES) {
                    target_position = start_position + requested_delta;
                    phase = Phase::HoldOut;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                }
                break;
            }
            case Phase::HoldOut:
                controlword = 0x000F;
                target_position = start_position + requested_delta;
                commanded_mode = MODE_CSP;
                if (++phase_cycle >= HOLD_CYCLES) {
                    phase = Phase::RampBack;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                }
                break;
            case Phase::RampBack: {
                controlword = 0x000F;
                commanded_mode = MODE_CSP;
                const int64_t numerator = static_cast<int64_t>(requested_delta) * static_cast<int64_t>(RETURN_CYCLES - phase_cycle);
                target_position = start_position + static_cast<int32_t>(numerator / static_cast<int64_t>(RETURN_CYCLES));
                ++phase_cycle;
                if (phase_cycle >= RETURN_CYCLES) {
                    target_position = start_position;
                    phase = Phase::DisableFlush;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                }
                break;
            }
            case Phase::DisableFlush:
            case Phase::Abort:
                controlword = 0x0000;
                target_position = start_position_locked ? start_position : actual_position;
                commanded_mode = MODE_CSP;
                if (++phase_cycle >= DISABLE_FLUSH_CYCLES) {
                    phase = abort_requested ? Phase::Abort : Phase::Complete;
                    if (phase == Phase::Complete) {
                        print_phase_change(phase, cycle, statusword, actual_position, target_position);
                    }
                }
                break;
            case Phase::Complete:
                controlword = 0x0000;
                target_position = start_position_locked ? start_position : actual_position;
                commanded_mode = MODE_CSP;
                running = false;
                break;
        }

        write_safe_outputs(controlword, commanded_mode, target_position);

        if (log_count < LOG_CAPACITY) {
            const DiagSignal &sig3005 = diag_signals[0];
            const DiagSignal &sig3006 = diag_signals[1];
            const DiagSignal &sig3007 = diag_signals[2];
            const DiagSignal &sig3008 = diag_signals[3];
            const DiagSignal &sig3009 = diag_signals[4];
            const DiagSignal &sig300A = diag_signals[5];
            log_rows[log_count++] = LogRow{
                cycle,
                cycle_time_ns,
                cycle_deadline_ns,
                lateness_ns,
                missed_cycles,
                statusword,
                statusword_state(statusword),
                controlword,
                commanded_mode,
                target_position,
                actual_position,
                actual_velocity,
                actual_torque,
                domain_state.working_counter,
                domain_state.wc_state,
                static_cast<uint8_t>(slave_state.online),
                static_cast<uint8_t>(slave_state.operational),
                static_cast<uint8_t>(master_state.link_up),
                static_cast<uint8_t>(phase),
                static_cast<uint32_t>(sig3005.value),
                static_cast<uint8_t>(sig3005.valid),
                diag_age_cycles(sig3005, cycle),
                static_cast<uint16_t>(sig3006.value),
                static_cast<uint8_t>(sig3006.valid),
                diag_age_cycles(sig3006, cycle),
                static_cast<uint16_t>(sig3007.value),
                static_cast<uint8_t>(sig3007.valid),
                diag_age_cycles(sig3007, cycle),
                static_cast<uint16_t>(sig3008.value),
                static_cast<uint8_t>(sig3008.valid),
                diag_age_cycles(sig3008, cycle),
                static_cast<uint16_t>(sig3009.value),
                static_cast<uint8_t>(sig3009.valid),
                diag_age_cycles(sig3009, cycle),
                static_cast<uint8_t>(sig300A.value),
                static_cast<uint8_t>(sig300A.valid),
                diag_age_cycles(sig300A, cycle),
            };
        }

        if (previous_phase != phase) {
            previous_phase = phase;
        }
        if (phase == Phase::Abort && phase_cycle >= DISABLE_FLUSH_CYCLES) {
            running = false;
        }
        if (phase == Phase::Complete) {
            running = false;
        }

        timespec now_sync{};
        clock_gettime(CLOCK_MONOTONIC, &now_sync);
        ecrt_master_sync_reference_clock_to(master, timespec_to_ns(now_sync));
        ecrt_master_sync_slave_clocks(master);

        ecrt_domain_queue(domain);
        ecrt_master_send(master);

        ++cycle;
    }

    if (domain_pd) {
        for (uint64_t i = 0; i < DISABLE_FLUSH_CYCLES; ++i) {
            write_safe_outputs(0x0000, MODE_CSP, start_position_locked ? start_position : 0);
            ecrt_domain_queue(domain);
            ecrt_master_send(master);
            usleep(1000);
        }
    }

    write_csv("/tmp/je_single_motor_csp_internal_diag_log.csv");

    const SummaryStats enable_hold = summarize_phase(Phase::EnableHold, "ENABLE_HOLD");
    const SummaryStats ramp_out = summarize_phase(Phase::RampOut, "RAMP_OUT");
    const SummaryStats hold_out = summarize_phase(Phase::HoldOut, "HOLD_OUT");
    print_summary(enable_hold);
    print_summary(ramp_out);
    print_summary(hold_out);
    print_comparison(enable_hold, hold_out);

    for (const DiagSignal &signal : diag_signals) {
        std::printf("[diag] %s valid=%u success=%llu error=%llu last_value=%llu\n",
                    signal.name,
                    signal.valid ? 1U : 0U,
                    static_cast<unsigned long long>(signal.success_count),
                    static_cast<unsigned long long>(signal.error_count),
                    static_cast<unsigned long long>(signal.value));
    }

    if (master) {
        ecrt_master_deactivate(master);
        ecrt_release_master(master);
    }

    std::printf("Log written to /tmp/je_single_motor_csp_internal_diag_log.csv (%zu rows)\n", log_count);
    return abort_requested ? 2 : 0;
}
