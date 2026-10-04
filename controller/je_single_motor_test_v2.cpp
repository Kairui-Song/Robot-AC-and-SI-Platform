#include <ecrt.h>

#include <atomic>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/sysinfo.h>
#include <sys/utsname.h>
#include <ctime>
#include <unistd.h>

#define JE_VENDOR_ID 0x03456789
#define JE_PRODUCT_CODE 0x00000000

static ec_master_t *master = nullptr;
static ec_domain_t *domain = nullptr;
static ec_slave_config_t *sc = nullptr;
static uint8_t *domain_pd = nullptr;

static std::atomic<bool> running(true);
static unsigned int master_index = 0;

static unsigned int off_607a;
static unsigned int off_60ff;
static unsigned int off_6071;
static unsigned int off_6040;
static unsigned int off_6060;
static unsigned int off_2000;
static unsigned int off_60b2;
static unsigned int off_60b1;
static unsigned int off_6064;
static unsigned int off_606c;
static unsigned int off_6077;
static unsigned int off_6041;

static ec_pdo_entry_info_t slave_0_pdo_entries[] = {
    {0x607a, 0x00, 32}, {0x60ff, 0x00, 32}, {0x6071, 0x00, 16}, {0x6040, 0x00, 16},
    {0x6060, 0x00, 8},  {0x2000, 0x00, 8},  {0x60b2, 0x00, 16}, {0x60b1, 0x00, 32},
    {0x6064, 0x00, 32}, {0x606c, 0x00, 32}, {0x6077, 0x00, 16}, {0x6041, 0x00, 16},
};

static ec_pdo_info_t slave_0_pdos[] = {
    {0x1600, 8, slave_0_pdo_entries + 0},
    {0x1a00, 4, slave_0_pdo_entries + 8},
};

static ec_sync_info_t slave_0_syncs[] = {
    {0, EC_DIR_OUTPUT, 0, nullptr, EC_WD_DISABLE},
    {1, EC_DIR_INPUT, 0, nullptr, EC_WD_DISABLE},
    {2, EC_DIR_OUTPUT, 1, slave_0_pdos + 0, EC_WD_ENABLE},
    {3, EC_DIR_INPUT, 1, slave_0_pdos + 1, EC_WD_DISABLE},
    {0xff},
};

static ec_pdo_entry_reg_t domain_regs[] = {
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

static void signal_handler(int) {
    running = false;
}

static void add_ns(timespec &ts, long ns) {
    ts.tv_nsec += ns;
    while (ts.tv_nsec >= 1000000000L) {
        ts.tv_nsec -= 1000000000L;
        ts.tv_sec++;
    }
}

static void emit_progress(const char *stage, const char *level, const char *message) {
    std::printf("{\"event\":\"progress\",\"stage\":\"%s\",\"level\":\"%s\",\"message\":\"%s\"}\n",
                stage, level, message);
    std::fflush(stdout);
}

static void trim(char *text) {
    size_t len = std::strlen(text);
    while (len && (text[len - 1] == '\n' || text[len - 1] == '\r' || text[len - 1] == ' ')) {
        text[--len] = 0;
    }
}

static int read_first_line(const char *path, char *output, size_t size) {
    FILE *file = std::fopen(path, "r");
    if (!file) return -1;
    char *result = std::fgets(output, static_cast<int>(size), file);
    std::fclose(file);
    if (!result) return -1;
    trim(output);
    return 0;
}

static int read_key_value(const char *path, const char *key, char *output, size_t size) {
    FILE *file = std::fopen(path, "r");
    if (!file) return -1;
    char line[512];
    int found = -1;
    while (std::fgets(line, sizeof(line), file)) {
        char *separator = std::strchr(line, ':');
        if (!separator) separator = std::strchr(line, '=');
        if (!separator) continue;
        *separator = 0;
        trim(line);
        if (std::strcmp(line, key)) continue;
        char *value = separator + 1;
        while (*value == ' ' || *value == '\t' || *value == '"') ++value;
        std::snprintf(output, size, "%s", value);
        trim(output);
        size_t len = std::strlen(output);
        if (len && output[len - 1] == '"') output[len - 1] = 0;
        found = 0;
        break;
    }
    std::fclose(file);
    return found;
}

static const char *scheduler_name(int policy) {
    if (policy == SCHED_FIFO) return "SCHED_FIFO";
    if (policy == SCHED_RR) return "SCHED_RR";
    if (policy == SCHED_OTHER) return "SCHED_OTHER";
    return "UNKNOWN";
}

static void emit_controller_info() {
    struct utsname uts = {};
    struct sysinfo system_info = {};
    struct sched_param schedule = {};
    char hostname[256] = "unknown";
    char os_name[256] = "unknown";
    char cpu_model[256] = "unknown";
    char hardware_model[256] = "unknown";
    char mem_available_text[64] = "0";
    char master_version[128] = "unknown";
    gethostname(hostname, sizeof(hostname) - 1);
    uname(&uts);
    sysinfo(&system_info);
    read_key_value("/etc/os-release", "PRETTY_NAME", os_name, sizeof(os_name));
    read_key_value("/proc/cpuinfo", "model name", cpu_model, sizeof(cpu_model));
    if (!std::strcmp(cpu_model, "unknown")) read_key_value("/proc/cpuinfo", "Model", cpu_model, sizeof(cpu_model));
    read_first_line("/sys/firmware/devicetree/base/model", hardware_model, sizeof(hardware_model));
    read_key_value("/proc/meminfo", "MemAvailable", mem_available_text, sizeof(mem_available_text));
    read_first_line("/sys/module/ec_master/version", master_version, sizeof(master_version));
    long memory_available_kb = std::strtol(mem_available_text, nullptr, 10);
    unsigned long long memory_total_bytes = static_cast<unsigned long long>(system_info.totalram) * system_info.mem_unit;
    int policy = sched_getscheduler(0);
    sched_getparam(0, &schedule);

    std::printf(
        "{\"event\":\"controller_info\",\"hostname\":\"%s\",\"hardware_model\":\"%s\","
        "\"os\":\"%s\",\"kernel\":\"%s\",\"architecture\":\"%s\",\"realtime_kernel\":%s,"
        "\"cpu_model\":\"%s\",\"cpu_cores\":%ld,\"memory_total_mb\":%llu,"
        "\"memory_available_mb\":%ld,\"load_1m\":%.2f,\"load_5m\":%.2f,\"load_15m\":%.2f,"
        "\"uptime_seconds\":%ld,\"pid\":%ld,\"scheduler\":\"%s\",\"scheduler_priority\":%d,"
        "\"igh_master_version\":\"%s\"}\n",
        hostname,
        hardware_model,
        os_name,
        uts.release,
        uts.machine,
        (std::strstr(uts.release, "-rt") || std::strstr(uts.version, "PREEMPT_RT")) ? "true" : "false",
        cpu_model,
        sysconf(_SC_NPROCESSORS_ONLN),
        memory_total_bytes / 1024ULL / 1024ULL,
        memory_available_kb / 1024L,
        system_info.loads[0] / 65536.0,
        system_info.loads[1] / 65536.0,
        system_info.loads[2] / 65536.0,
        system_info.uptime,
        static_cast<long>(getpid()),
        scheduler_name(policy),
        schedule.sched_priority,
        master_version);
    std::fflush(stdout);
}

static void emit_status(uint16_t sw, int32_t pos, int32_t vel, int16_t torque,
                        unsigned int wc, unsigned int wc_state, bool online,
                        bool operational, unsigned int al_state, bool link_up) {
    std::printf(
        "{\"event\":\"status\",\"statusword_hex\":\"0x%04X\",\"actual_position\":%d,"
        "\"actual_velocity\":%d,\"actual_torque\":%d,\"working_counter\":%u,"
        "\"wc_state\":%u,\"slave_online\":%s,\"slave_operational\":%s,"
        "\"al_state_hex\":\"0x%02X\",\"link_up\":%s}\n",
        sw, pos, vel, torque, wc, wc_state,
        online ? "true" : "false",
        operational ? "true" : "false",
        al_state,
        link_up ? "true" : "false");
    std::fflush(stdout);
}

int main(int argc, char **argv) {
    if (argc == 3 && std::strcmp(argv[1], "--master") == 0) {
        char *end = nullptr;
        const unsigned long parsed = std::strtoul(argv[2], &end, 10);
        if (!argv[2][0] || *end != '\0' || parsed > 255) {
            std::fprintf(stderr, "invalid master index: %s\n", argv[2]);
            return 2;
        }
        master_index = static_cast<unsigned int>(parsed);
    } else if (argc != 1) {
        std::fprintf(stderr, "usage: %s [--master 0..255]\n", argv[0]);
        return 2;
    }
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);
    emit_progress("startup", "info", "JE single motor test V2 started");
    emit_controller_info();

    master = ecrt_request_master(master_index);
    if (!master) {
        std::printf("{\"event\":\"result\",\"target\":\"controller_benchmark\",\"ok\":false,"
                    "\"error\":\"Failed to request EtherCAT Master0\"}\n");
        return 1;
    }
    emit_progress("master", "ok", "Master0 requested");

    domain = ecrt_master_create_domain(master);
    if (!domain) {
        std::printf("{\"event\":\"result\",\"target\":\"controller_benchmark\",\"ok\":false,"
                    "\"error\":\"Failed to create domain\"}\n");
        ecrt_release_master(master);
        return 1;
    }

    sc = ecrt_master_slave_config(master, 0, 0, JE_VENDOR_ID, JE_PRODUCT_CODE);
    if (!sc) {
        std::printf("{\"event\":\"result\",\"target\":\"controller_benchmark\",\"ok\":false,"
                    "\"error\":\"Failed to get JE slave config\"}\n");
        ecrt_release_master(master);
        return 1;
    }

    if (ecrt_slave_config_pdos(sc, EC_END, slave_0_syncs)) {
        std::printf("{\"event\":\"result\",\"target\":\"controller_benchmark\",\"ok\":false,"
                    "\"error\":\"Failed to configure PDOs\"}\n");
        ecrt_release_master(master);
        return 1;
    }

    if (ecrt_domain_reg_pdo_entry_list(domain, domain_regs)) {
        std::printf("{\"event\":\"result\",\"target\":\"controller_benchmark\",\"ok\":false,"
                    "\"error\":\"Failed to register PDO entries\"}\n");
        ecrt_release_master(master);
        return 1;
    }

    if (ecrt_master_activate(master)) {
        std::printf("{\"event\":\"result\",\"target\":\"controller_benchmark\",\"ok\":false,"
                    "\"error\":\"Failed to activate master\"}\n");
        ecrt_release_master(master);
        return 1;
    }

    domain_pd = ecrt_domain_data(domain);
    if (!domain_pd) {
        std::printf("{\"event\":\"result\",\"target\":\"controller_benchmark\",\"ok\":false,"
                    "\"error\":\"Failed to get domain process data\"}\n");
        ecrt_master_deactivate(master);
        ecrt_release_master(master);
        return 1;
    }

    constexpr long PERIOD_NS = 1000000L;
    timespec wakeup_time{};
    clock_gettime(CLOCK_MONOTONIC, &wakeup_time);
    uint64_t cycle = 0;
    ec_master_state_t master_state{};
    ec_domain_state_t domain_state{};
    ec_slave_config_state_t slave_state{};

    while (running) {
        add_ns(wakeup_time, PERIOD_NS);
        ecrt_master_receive(master);
        ecrt_domain_process(domain);

        const uint16_t statusword = EC_READ_U16(domain_pd + off_6041);
        const int32_t actual_position = EC_READ_S32(domain_pd + off_6064);
        const int32_t actual_velocity = EC_READ_S32(domain_pd + off_606c);
        const int16_t actual_torque = EC_READ_S16(domain_pd + off_6077);

        ecrt_domain_state(domain, &domain_state);

        EC_WRITE_S32(domain_pd + off_607a, actual_position);
        EC_WRITE_S32(domain_pd + off_60ff, 0);
        EC_WRITE_S16(domain_pd + off_6071, 0);
        EC_WRITE_U16(domain_pd + off_6040, 0x0000);
        EC_WRITE_U8(domain_pd + off_6060, 0);
        EC_WRITE_U8(domain_pd + off_2000, 0);
        EC_WRITE_S16(domain_pd + off_60b2, 0);
        EC_WRITE_S32(domain_pd + off_60b1, 0);

        ecrt_domain_queue(domain);
        ecrt_master_send(master);
        cycle++;

        if (cycle % 1000 == 0) {
            ecrt_master_state(master, &master_state);
            ecrt_slave_config_state(sc, &slave_state);
            emit_status(statusword, actual_position, actual_velocity, actual_torque,
                        domain_state.working_counter, domain_state.wc_state,
                        slave_state.online, slave_state.operational,
                        slave_state.al_state, master_state.link_up);
        }

        int ret;
        do {
            ret = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &wakeup_time, nullptr);
        } while (ret == EINTR && running);
    }

    if (domain_pd) {
        EC_WRITE_U16(domain_pd + off_6040, 0x0000);
        EC_WRITE_U8(domain_pd + off_6060, 0);
        ecrt_domain_queue(domain);
        ecrt_master_send(master);
        usleep(10000);
    }

    ecrt_master_deactivate(master);
    ecrt_release_master(master);
    std::printf("{\"event\":\"result\",\"target\":\"controller_benchmark\",\"ok\":true,"
                "\"motion_allowed\":false,\"message\":\"controller test stopped cleanly\"}\n");
    return 0;
}
