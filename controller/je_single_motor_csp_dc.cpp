#include <ecrt.h>

#include <atomic>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <unistd.h>

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
constexpr uint64_t MODE_PROBE_HOLD_CYCLES = 2000;
constexpr uint64_t PHASE_TIMEOUT_CYCLES = 2000;
constexpr uint64_t ENABLE_HOLD_CYCLES = 1000;
constexpr uint64_t RAMP_CYCLES = 2000;
constexpr uint64_t HOLD_CYCLES = 3000;
constexpr uint64_t RETURN_CYCLES = 2000;
constexpr uint64_t DISABLE_FLUSH_CYCLES = 32;
constexpr size_t LOG_CAPACITY = 12000;

constexpr int8_t MODE_CSP = 8;
constexpr int8_t MODE_CSV = 9;
constexpr int8_t MODE_CST = 10;
constexpr int8_t MODE_UNAVAILABLE = -128;

ec_master_t *master = nullptr;
ec_domain_t *domain = nullptr;
ec_slave_config_t *slave_config = nullptr;
uint8_t *domain_pd = nullptr;
ec_sdo_request_t *mode_command_request = nullptr;
ec_sdo_request_t *mode_display_request = nullptr;

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
    ModeProbe8,
    ModeProbe9,
    ModeProbe10,
    ModeProbeRestore8,
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
    int8_t mode_display;
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
};

LogRow log_rows[LOG_CAPACITY];
size_t log_count = 0;

struct ModeProbeResult {
    int8_t requested_mode;
    int8_t readback_mode;
    int8_t displayed_mode;
    ec_request_state_t readback_6060_state;
    ec_request_state_t readback_6061_state;
    uint16_t statusword;
    uint32_t working_counter;
    uint32_t wc_state;
    uint8_t slave_operational;
};

int8_t latest_mode_command_readback = MODE_UNAVAILABLE;
int8_t latest_mode_display = MODE_UNAVAILABLE;
ModeProbeResult mode_probe_results[4] = {};
size_t mode_probe_result_count = 0;

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
        case Phase::ModeProbe8: return "mode_probe_8";
        case Phase::ModeProbe9: return "mode_probe_9";
        case Phase::ModeProbe10: return "mode_probe_10";
        case Phase::ModeProbeRestore8: return "mode_probe_restore_8";
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

void poll_int8_request(ec_sdo_request_t *request,
                       int8_t &latest_value,
                       ec_request_state_t &latest_state) {
    if (!request) {
        return;
    }

    latest_state = ecrt_sdo_request_state(request);
    switch (latest_state) {
        case EC_REQUEST_UNUSED:
        case EC_REQUEST_SUCCESS: {
            const size_t size = ecrt_sdo_request_data_size(request);
            if (size >= sizeof(int8_t)) {
                latest_value = static_cast<int8_t>(EC_READ_S8(ecrt_sdo_request_data(request)));
            }
            ecrt_sdo_request_read(request);
            break;
        }
        case EC_REQUEST_ERROR:
            latest_value = MODE_UNAVAILABLE;
            ecrt_sdo_request_read(request);
            break;
        case EC_REQUEST_BUSY:
            break;
    }
}

void poll_mode_requests(ec_request_state_t &mode_command_state,
                        ec_request_state_t &mode_display_state) {
    poll_int8_request(mode_command_request, latest_mode_command_readback, mode_command_state);
    poll_int8_request(mode_display_request, latest_mode_display, mode_display_state);
}

void record_mode_probe_result(int8_t requested_mode,
                              ec_request_state_t mode_command_state,
                              ec_request_state_t mode_display_state,
                              uint16_t statusword,
                              const ec_domain_state_t &domain_state,
                              const ec_slave_config_state_t &slave_state) {
    if (mode_probe_result_count >= 4) {
        return;
    }
    mode_probe_results[mode_probe_result_count++] = ModeProbeResult{
        requested_mode,
        latest_mode_command_readback,
        latest_mode_display,
        mode_command_state,
        mode_display_state,
        statusword,
        domain_state.working_counter,
        domain_state.wc_state,
        static_cast<uint8_t>(slave_state.operational),
    };
}

bool read_initial_actual_position(int32_t &position) {
    uint8_t data[4] = {0};
    size_t result_size = 0;
    uint32_t abort_code = 0;
    int ret = ecrt_master_sdo_upload(
        master, 0, 0x6064, 0x00, data, sizeof(data), &result_size, &abort_code);
    if (ret < 0 || result_size != sizeof(data)) {
        std::fprintf(stderr, "Failed to read initial 0x6064: ret=%d abort=0x%08x size=%zu\n",
                     ret, abort_code, result_size);
        return false;
    }
    position = EC_READ_S32(data);
    return true;
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

void print_phase_change(Phase phase, uint64_t cycle, uint16_t statusword, int32_t actual, int32_t target) {
    std::printf("[phase] cycle=%llu phase=%s sw=0x%04X actual=%d target=%d\n",
                static_cast<unsigned long long>(cycle), phase_name(phase), statusword, actual, target);
    std::fflush(stdout);
}

void write_csv(const char *path) {
    FILE *file = std::fopen(path, "w");
    if (!file) {
        std::fprintf(stderr, "Failed to open CSV %s\n", path);
        return;
    }
    std::fprintf(file,
                 "cycle,timestamp_ns,deadline_ns,lateness_ns,missed_cycles,statusword_raw,statusword_masked,controlword,"
                 "mode_command,mode_display,target_position,actual_position,actual_velocity,"
                 "actual_torque,working_counter,wc_state,slave_online,slave_operational,"
                 "master_link_up,phase\n");
    for (size_t i = 0; i < log_count; ++i) {
        const LogRow &row = log_rows[i];
        std::fprintf(file,
                     "%llu,%lld,%lld,%lld,%u,0x%04X,0x%04X,0x%04X,%d,%d,%d,%d,%d,%d,%u,%u,%u,%u,%u,%u\n",
                     static_cast<unsigned long long>(row.cycle),
                     static_cast<long long>(row.timestamp_ns),
                     static_cast<long long>(row.deadline_ns),
                     static_cast<long long>(row.lateness_ns),
                     row.missed_cycles,
                     row.statusword_raw,
                     row.statusword_masked,
                     row.controlword,
                     static_cast<int>(row.mode_command),
                     static_cast<int>(row.mode_display),
                     row.target_position,
                     row.actual_position,
                     row.actual_velocity,
                     row.actual_torque,
                     row.working_counter,
                     row.wc_state,
                     row.slave_online,
                     row.slave_operational,
                     row.master_link_up,
                     row.phase);
    }
    std::fclose(file);
}

}  // namespace

int main(int argc, char **argv) {
    int32_t requested_delta = MAX_DELTA_COUNTS;
    bool preflight_only = false;
    bool mode_probe_only = false;
    bool mode_probe_v2_only = false;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--preflight") == 0) {
            preflight_only = true;
            continue;
        }
        if (std::strcmp(argv[i], "--mode-probe") == 0) {
            mode_probe_only = true;
            continue;
        }
        if (std::strcmp(argv[i], "--mode-probe-v2") == 0) {
            mode_probe_v2_only = true;
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

    std::printf("JE CSP DC test preparation\n");
    std::printf("mode=%s delta=%d assign=0x%04X sync0_cycle=%u sync0_shift=%d\n",
                mode_probe_v2_only ? "mode-probe-v2" :
                (mode_probe_only ? "mode-probe" : (preflight_only ? "preflight" : "motion")),
                requested_delta,
                SDK_ASSIGN_ACTIVATE,
                SDK_SYNC0_CYCLE_NS,
                SDK_SYNC0_SHIFT_NS);

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

    int32_t initial_position = 0;
    if (!read_initial_actual_position(initial_position)) {
        ecrt_release_master(master);
        return 1;
    }
    std::printf("Initial actual position: %d\n", initial_position);

    if (!configure_slave()) {
        ecrt_release_master(master);
        return 1;
    }

    if (mode_probe_only || mode_probe_v2_only) {
        mode_display_request = ecrt_slave_config_create_sdo_request(slave_config, 0x6061, 0x00, sizeof(int8_t));
        if (!mode_display_request) {
            std::fprintf(stderr, "Failed to create async SDO request for 0x6061\n");
            ecrt_release_master(master);
            return 1;
        }
        ecrt_sdo_request_timeout(mode_display_request, 500);
    }
    if (mode_probe_v2_only) {
        mode_command_request = ecrt_slave_config_create_sdo_request(slave_config, 0x6060, 0x00, sizeof(int8_t));
        if (!mode_command_request) {
            std::fprintf(stderr, "Failed to create async SDO request for 0x6060\n");
            ecrt_release_master(master);
            return 1;
        }
        ecrt_sdo_request_timeout(mode_command_request, 500);
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

    timespec next_deadline {};
    clock_gettime(CLOCK_MONOTONIC, &next_deadline);

    ec_master_state_t master_state {};
    ec_domain_state_t domain_state {};
    ec_slave_config_state_t slave_state {};

    Phase phase = Phase::Startup;
    Phase previous_phase = phase;

    uint16_t controlword = 0x0000;
    int32_t start_position = initial_position;
    int32_t target_position = initial_position;
    bool start_position_locked = false;
    bool motion_started = false;
    bool abort_requested = false;
    uint64_t stable_cycles = 0;
    uint64_t pre_enable_wait_cycles = 0;
    uint64_t phase_cycle = 0;
    uint64_t cycle = 0;
    int8_t commanded_mode = MODE_CSP;
    ec_request_state_t mode_command_state = EC_REQUEST_UNUSED;
    ec_request_state_t mode_display_state = EC_REQUEST_UNUSED;

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

        timespec cycle_time {};
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
        poll_mode_requests(mode_command_state, mode_display_state);

        uint16_t statusword = EC_READ_U16(domain_pd + off_6041);
        int32_t actual_position = EC_READ_S32(domain_pd + off_6064);
        int32_t actual_velocity = EC_READ_S32(domain_pd + off_606c);
        int16_t actual_torque = EC_READ_S16(domain_pd + off_6077);

        ecrt_domain_state(domain, &domain_state);
        ecrt_slave_config_state(slave_config, &slave_state);
        ecrt_master_state(master, &master_state);

        const bool wkc_complete = domain_state.wc_state == EC_WC_COMPLETE;
        const bool dc_ready = master_state.link_up && slave_state.online && slave_state.operational && wkc_complete;
        const bool fault = is_fault(statusword);

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

        const bool motion_or_preflight_phase =
            phase == Phase::PreflightObserve ||
            phase == Phase::ModeProbe8 ||
            phase == Phase::ModeProbe9 ||
            phase == Phase::ModeProbe10 ||
            phase == Phase::ModeProbeRestore8 ||
            phase == Phase::WaitReadyToSwitchOn ||
            phase == Phase::WaitSwitchedOn ||
            phase == Phase::WaitOperationEnabled ||
            phase == Phase::EnableHold ||
            phase == Phase::RampOut ||
            phase == Phase::HoldOut ||
            phase == Phase::RampBack;
        const bool bad_runtime_bus = motion_or_preflight_phase && !dc_ready;

        if ((fault || bad_runtime_bus) && phase != Phase::Abort && phase != Phase::DisableFlush && phase != Phase::Complete) {
            abort_requested = true;
            phase = Phase::Abort;
            phase_cycle = 0;
            std::printf("[abort] cycle=%llu fault=%d link=%u online=%u operational=%u wc_state=%u sw=0x%04X phase=%s\n",
                        static_cast<unsigned long long>(cycle),
                        fault ? 1 : 0,
                        master_state.link_up,
                        slave_state.online,
                        slave_state.operational,
                        domain_state.wc_state,
                        statusword,
                        phase_name(previous_phase));
            std::fflush(stdout);
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
                if (dc_ready && !fault) {
                    ++stable_cycles;
                } else {
                    stable_cycles = 0;
                }
                if (stable_cycles >= PRE_ENABLE_STABLE_CYCLES) {
                    if (mode_probe_only || mode_probe_v2_only) {
                        phase = Phase::ModeProbe8;
                        phase_cycle = 0;
                        print_phase_change(phase, cycle, statusword, actual_position, target_position);
                    } else if (statusword_state(statusword) != 0x0040) {
                        abort_requested = true;
                        phase = Phase::Abort;
                        phase_cycle = 0;
                        std::printf("[abort] cycle=%llu expected switch_on_disabled sw_masked=0x%04X\n",
                                    static_cast<unsigned long long>(cycle),
                                    statusword_state(statusword));
                        std::fflush(stdout);
                    } else if (preflight_only) {
                        phase = Phase::PreflightObserve;
                        phase_cycle = 0;
                        print_phase_change(phase, cycle, statusword, actual_position, target_position);
                    } else {
                        phase = Phase::WaitReadyToSwitchOn;
                        phase_cycle = 0;
                        print_phase_change(phase, cycle, statusword, actual_position, target_position);
                    }
                } else if (pre_enable_wait_cycles >= PRE_ENABLE_MAX_WAIT_CYCLES) {
                    abort_requested = true;
                    phase = Phase::Abort;
                    phase_cycle = 0;
                    std::printf("[abort] cycle=%llu pre-enable stability timeout stable_cycles=%llu\n",
                                static_cast<unsigned long long>(cycle),
                                static_cast<unsigned long long>(stable_cycles));
                    std::fflush(stdout);
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
            case Phase::ModeProbe8:
                controlword = 0x0000;
                target_position = actual_position;
                commanded_mode = MODE_CSP;
                if (++phase_cycle >= MODE_PROBE_HOLD_CYCLES) {
                    record_mode_probe_result(commanded_mode, mode_command_state, mode_display_state, statusword, domain_state, slave_state);
                    phase = Phase::ModeProbe9;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                }
                break;
            case Phase::ModeProbe9:
                controlword = 0x0000;
                target_position = actual_position;
                commanded_mode = MODE_CSV;
                if (++phase_cycle >= MODE_PROBE_HOLD_CYCLES) {
                    record_mode_probe_result(commanded_mode, mode_command_state, mode_display_state, statusword, domain_state, slave_state);
                    phase = Phase::ModeProbe10;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                }
                break;
            case Phase::ModeProbe10:
                controlword = 0x0000;
                target_position = actual_position;
                commanded_mode = MODE_CST;
                if (++phase_cycle >= MODE_PROBE_HOLD_CYCLES) {
                    record_mode_probe_result(commanded_mode, mode_command_state, mode_display_state, statusword, domain_state, slave_state);
                    phase = Phase::ModeProbeRestore8;
                    phase_cycle = 0;
                    print_phase_change(phase, cycle, statusword, actual_position, target_position);
                }
                break;
            case Phase::ModeProbeRestore8:
                controlword = 0x0000;
                target_position = actual_position;
                commanded_mode = MODE_CSP;
                if (++phase_cycle >= MODE_PROBE_HOLD_CYCLES) {
                    record_mode_probe_result(commanded_mode, mode_command_state, mode_display_state, statusword, domain_state, slave_state);
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
                    std::fflush(stdout);
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
                    std::fflush(stdout);
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
                    std::fflush(stdout);
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
                target_position = start_position;
                commanded_mode = MODE_CSP;
                running = false;
                break;
        }

        write_safe_outputs(controlword, commanded_mode, target_position);

        if (log_count < LOG_CAPACITY) {
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
                latest_mode_display,
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

        timespec now_sync {};
        clock_gettime(CLOCK_MONOTONIC, &now_sync);
        ecrt_master_sync_reference_clock_to(master, timespec_to_ns(now_sync));
        ecrt_master_sync_slave_clocks(master);

        ecrt_domain_queue(domain);
        ecrt_master_send(master);

        ++cycle;
    }

    if (domain_pd) {
        for (uint64_t i = 0; i < DISABLE_FLUSH_CYCLES; ++i) {
            write_safe_outputs(0x0000, MODE_CSP, start_position_locked ? start_position : initial_position);
            ecrt_domain_queue(domain);
            ecrt_master_send(master);
            usleep(1000);
        }
    }

    write_csv("/tmp/je_single_motor_csp_dc_log.csv");

    if (mode_probe_only || mode_probe_v2_only) {
        for (size_t i = 0; i < mode_probe_result_count; ++i) {
            const ModeProbeResult &result = mode_probe_results[i];
            const bool mode_request_reflected = result.readback_mode == result.requested_mode;
            const bool mode_activated = mode_request_reflected && result.displayed_mode == result.requested_mode;
            const char *interpretation =
                mode_activated ? "request accepted, mode activated" :
                (mode_request_reflected ? "request accepted, mode not activated" :
                                          "mode request not reflected in object");
            std::printf("commanded=%d readback6060=%d displayed6061=%d statusword=0x%04X wkc=%u wc_state=%u slave_operational=%u state6060=%d state6061=%d %s\n",
                        static_cast<int>(result.requested_mode),
                        static_cast<int>(result.readback_mode),
                        static_cast<int>(result.displayed_mode),
                        result.statusword,
                        result.working_counter,
                        result.wc_state,
                        result.slave_operational,
                        static_cast<int>(result.readback_6060_state),
                        static_cast<int>(result.readback_6061_state),
                        interpretation);
        }
    }

    if (master) {
        ecrt_master_deactivate(master);
        ecrt_release_master(master);
    }

    std::printf("Log written to /tmp/je_single_motor_csp_dc_log.csv (%zu rows)\n", log_count);
    return abort_requested ? 2 : 0;
}
