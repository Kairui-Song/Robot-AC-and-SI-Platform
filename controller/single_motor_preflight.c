/* Read-only IgH EtherCAT preflight.  This program never activates a domain,
 * requests OP state, registers PDOs, or writes to a slave. */
#include <ecrt.h>
#include <errno.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysinfo.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>

static void json_string(const char *text) {
    const unsigned char *p = (const unsigned char *)(text ? text : "");
    putchar('"');
    for (; *p; ++p) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p >= 0x20) putchar(*p);
    }
    putchar('"');
}

static void trim(char *text) {
    size_t len = strlen(text);
    while (len && (text[len - 1] == '\n' || text[len - 1] == '\r' || text[len - 1] == ' ')) text[--len] = 0;
}

static int read_first_line(const char *path, char *output, size_t size) {
    FILE *file = fopen(path, "r");
    if (!file) return -1;
    char *result = fgets(output, (int)size, file);
    fclose(file);
    if (!result) return -1;
    trim(output);
    return 0;
}

static int read_key_value(const char *path, const char *key, char *output, size_t size) {
    FILE *file = fopen(path, "r");
    if (!file) return -1;
    char line[512];
    int found = -1;
    while (fgets(line, sizeof(line), file)) {
        char *separator = strchr(line, ':');
        if (!separator) separator = strchr(line, '=');
        if (!separator) continue;
        *separator = 0;
        trim(line);
        if (strcmp(line, key)) continue;
        char *value = separator + 1;
        while (*value == ' ' || *value == '\t' || *value == '"') ++value;
        snprintf(output, size, "%s", value);
        trim(output);
        size_t len = strlen(output);
        if (len && output[len - 1] == '"') output[len - 1] = 0;
        found = 0;
        break;
    }
    fclose(file);
    return found;
}

static const char *scheduler_name(int policy) {
    if (policy == SCHED_FIFO) return "SCHED_FIFO";
    if (policy == SCHED_RR) return "SCHED_RR";
    if (policy == SCHED_OTHER) return "SCHED_OTHER";
    return "UNKNOWN";
}

static int wait_for_stable_scan(ec_master_t *master, ec_master_info_t *info) {
    const struct timespec pause = {.tv_sec = 0, .tv_nsec = 100000000L};
    unsigned int previous_count = (unsigned int)-1;
    int stable_reads = 0;
    for (int attempt = 0; attempt < 50; ++attempt) {
        if (ecrt_master(master, info)) return -1;
        if (!info->scan_busy && info->slave_count == previous_count) {
            if (++stable_reads >= 3) return 0;
        } else {
            stable_reads = 0;
        }
        previous_count = info->slave_count;
        nanosleep(&pause, NULL);
    }
    return 1;
}

static void emit_controller_info(void) {
    struct utsname uts = {0};
    struct sysinfo system_info = {0};
    struct sched_param schedule = {0};
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
    if (!strcmp(cpu_model, "unknown")) read_key_value("/proc/cpuinfo", "Model", cpu_model, sizeof(cpu_model));
    read_first_line("/sys/firmware/devicetree/base/model", hardware_model, sizeof(hardware_model));
    read_key_value("/proc/meminfo", "MemAvailable", mem_available_text, sizeof(mem_available_text));
    read_first_line("/sys/module/ec_master/version", master_version, sizeof(master_version));
    long memory_available_kb = strtol(mem_available_text, NULL, 10);
    unsigned long long memory_total_bytes = (unsigned long long)system_info.totalram * system_info.mem_unit;
    int policy = sched_getscheduler(0);
    sched_getparam(0, &schedule);

    printf("{\"event\":\"controller_info\",\"hostname\":"); json_string(hostname);
    printf(",\"hardware_model\":"); json_string(hardware_model);
    printf(",\"os\":"); json_string(os_name);
    printf(",\"kernel\":"); json_string(uts.release);
    printf(",\"architecture\":"); json_string(uts.machine);
    printf(",\"realtime_kernel\":%s", (strstr(uts.release, "-rt") || strstr(uts.version, "PREEMPT_RT")) ? "true" : "false");
    printf(",\"cpu_model\":"); json_string(cpu_model);
    printf(",\"cpu_cores\":%ld", sysconf(_SC_NPROCESSORS_ONLN));
    printf(",\"memory_total_mb\":%llu", memory_total_bytes / 1024ULL / 1024ULL);
    printf(",\"memory_available_mb\":%ld", memory_available_kb / 1024L);
    printf(",\"load_1m\":%.2f,\"load_5m\":%.2f,\"load_15m\":%.2f", system_info.loads[0] / 65536.0, system_info.loads[1] / 65536.0, system_info.loads[2] / 65536.0);
    printf(",\"uptime_seconds\":%ld,\"pid\":%ld", system_info.uptime, (long)getpid());
    printf(",\"scheduler\":"); json_string(scheduler_name(policy));
    printf(",\"scheduler_priority\":%d,\"igh_master_version\":", schedule.sched_priority); json_string(master_version);
    puts("}");
    fflush(stdout);
}

int main(int argc, char **argv) {
    struct timespec started = {0}, finished = {0};
    clock_gettime(CLOCK_MONOTONIC, &started);
    unsigned int master_index = 0;
    if (argc == 3 && strcmp(argv[1], "--master") == 0) {
        char *end = NULL;
        unsigned long value = strtoul(argv[2], &end, 10);
        if (!end || *end || value > 255) {
            puts("{\"event\":\"result\",\"target\":\"single_motor_preflight\",\"ok\":false,\"error\":\"invalid master index\"}");
            return 2;
        }
        master_index = (unsigned int)value;
    } else if (argc != 1) {
        puts("{\"event\":\"result\",\"target\":\"single_motor_preflight\",\"ok\":false,\"error\":\"usage: single_motor_preflight [--master N]\"}");
        return 2;
    }

    emit_controller_info();
    printf("{\"event\":\"progress\",\"stage\":\"requesting_master\",\"master\":%u}\n", master_index);
    fflush(stdout);
    ec_master_t *master = ecrt_request_master(master_index);
    if (!master) {
        printf("{\"event\":\"result\",\"target\":\"single_motor_preflight\",\"ok\":false,\"error\":\"ecrt_request_master failed\",\"errno\":%d}\n", errno);
        return 1;
    }

    ec_master_info_t info = {0};
    int scan_status = wait_for_stable_scan(master, &info);
    if (scan_status < 0) {
        ecrt_release_master(master);
        puts("{\"event\":\"result\",\"target\":\"single_motor_preflight\",\"ok\":false,\"error\":\"ecrt_master info failed\"}");
        return 1;
    }
    if (scan_status > 0) {
        ecrt_release_master(master);
        puts("{\"event\":\"result\",\"target\":\"single_motor_preflight\",\"ok\":false,\"error\":\"EtherCAT scan did not become stable within 5 seconds\"}");
        return 1;
    }

    printf("{\"event\":\"progress\",\"stage\":\"master_detected\",\"slave_count\":%u,\"link_up\":%s,\"scan_busy\":%s}\n",
           info.slave_count, info.link_up ? "true" : "false", info.scan_busy ? "true" : "false");

    printf("{\"event\":\"inventory\",\"master\":%u,\"slave_count\":%u,\"link_up\":%s,\"slaves\":[",
           master_index, info.slave_count, info.link_up ? "true" : "false");
    unsigned int readable = 0;
    for (unsigned int i = 0; i < info.slave_count; ++i) {
        ec_slave_info_t slave;
        if (ecrt_master_get_slave(master, i, &slave)) continue;
        if (readable++) putchar(',');
        printf("{\"position\":%u,\"alias\":%u,\"vendor_id\":%u,\"product_code\":%u,\"revision_number\":%u,\"serial_number\":%u,\"al_state\":%u,\"error_flag\":%s,\"name\":",
               i, slave.alias, slave.vendor_id, slave.product_code,
               slave.revision_number, slave.serial_number, slave.al_state,
               slave.error_flag ? "true" : "false");
        json_string(slave.name);
        putchar('}');
    }
    puts("]}");

    ecrt_release_master(master);
    clock_gettime(CLOCK_MONOTONIC, &finished);
    double duration_ms = (finished.tv_sec - started.tv_sec) * 1000.0 + (finished.tv_nsec - started.tv_nsec) / 1000000.0;
    printf("{\"event\":\"result\",\"target\":\"single_motor_preflight\",\"ok\":%s,\"master\":%u,\"slave_count\":%u,\"readable_slaves\":%u,\"duration_ms\":%.3f,\"motion_allowed\":false,\"info\":\"read-only preflight complete; no PDO writes or enable command sent\"}\n",
           (info.link_up && info.slave_count > 0 && readable == info.slave_count) ? "true" : "false",
           master_index, info.slave_count, readable, duration_ms);
    return (info.link_up && info.slave_count > 0 && readable == info.slave_count) ? 0 : 1;
}
