from pathlib import Path
p = Path(__file__).parent
f=p/'ethercat_bridge.py'
s=f.read_text(encoding='utf-8').replace('import json\n', 'import json\nimport math\n', 1)
s=s.replace('    status_samples = []\n', '''    status_samples = []
    last_status_received = None
    try:
        fresh_threshold = float(os.environ.get("LINGLONG_STATUS_FRESH_SECONDS", "2.0"))
        if not math.isfinite(fresh_threshold) or fresh_threshold <= 0:
            fresh_threshold = 2.0
    except (TypeError, ValueError):
        fresh_threshold = 2.0
''')
s=s.replace('status["ts"] = time.time()', 'status["ts"] = time.time()\n                    last_status_received = time.monotonic()', 1)
pos=s.index('            status = _parse_controller_status_line(text)', s.index('def run_controller_benchmark'))
s=s[:pos]+s[pos:].replace('status["ts"] = time.time()', 'status["ts"] = time.time()\n                last_status_received = time.monotonic()',1)
s=s.replace('progress({"stage": "status", **status})', 'progress({**status, "stage": "status", "status_fresh": True,\n                                  "status_age_seconds": 0.0, "status_fresh_seconds": fresh_threshold})')
a=s.index('        # 评估最后一个状态样本')
b=s.index('        default_result = {',a)
s=s[:a]+'''        status_age = (None if last_status_received is None else
                      max(0.0, time.monotonic() - last_status_received))
        status_fresh = status_age is not None and status_age <= fresh_threshold
'''+s[b:]
needle='        if not result["ok"]:\n'
idx=s.index(needle,s.index('def run_controller_benchmark'))
s=s[:idx]+'''        # Child result payloads must not override the bridge's freshness decision.
        result.update(status_fresh=status_fresh, status_age_seconds=status_age,
                      status_fresh_seconds=fresh_threshold)
        if not status_fresh:
            for field in ("statusword_hex", "actual_position", "actual_velocity",
                          "actual_torque", "working_counter", "wc_state", "slave_online",
                          "slave_operational", "al_state_hex", "link_up"):
                result[field] = None
'''+s[idx:]
f.write_text(s,encoding='utf-8')
f=p/'adapter.py';s=f.read_text(encoding='utf-8')
s=s.replace("    if importlib.util.find_spec('can_mask') is None:\n        logger.debug('no can_mask module available, skipping mask step')\n        return False\n\n    try:\n", "    try:\n        if importlib.util.find_spec('can_mask') is None:\n            logger.debug('no can_mask module available, skipping mask step')\n            return False\n")
f.write_text(s,encoding='utf-8')
f=p/'app.js';s=f.read_text(encoding='utf-8')
s=s.replace('function handleOverviewBenchmarkStream(data) {', '''let overviewFeedbackTimer = null;
function clearOverviewFeedbackTimer() {
    clearTimeout(overviewFeedbackTimer);
    overviewFeedbackTimer = null;
}
function handleOverviewBenchmarkStream(data) {''')
s=s.replace("    if (data.stage === 'connecting') {", "    if (data.stage === 'connecting') {\n        clearOverviewFeedbackTimer();",1)
a=s.index('        // 如果状态被判断为过期')
b=s.index('        window.__overviewLiveCharts.pushLiveSample(data);',a)
s=s[:a]+'''        clearOverviewFeedbackTimer();
        if (data.status_fresh === false) {
            window.__overviewLiveCharts.setStatus('反馈已过期');
            return;
        }
        const threshold = Number(data.status_fresh_seconds);
        overviewFeedbackTimer = setTimeout(() => {
            window.__overviewLiveCharts.setStatus('反馈已过期');
        }, (Number.isFinite(threshold) && threshold > 0 ? threshold : 2) * 1000);
'''+s[b:]
s=s.replace("    if (data.stage === 'result') {\n        window", "    if (data.stage === 'result') {\n        clearOverviewFeedbackTimer();\n        if (data.status_fresh === false) {\n            window.__overviewLiveCharts.setStatus('反馈已过期');\n            return;\n        }\n        window",1)
for field in ('actual_position','actual_velocity','actual_torque'):
    s=s.replace(f"data.{field} !== undefined ? String(data.{field}) : (data.status_fresh === false ? '反馈已过期' : '未返回')", f"data.status_fresh === false ? '反馈已过期' : (data.{field} == null ? '未返回' : String(data.{field}))")
s=s.replace("data.link_up === undefined ? '未返回'", "data.status_fresh === false ? '反馈已过期' : data.link_up == null ? '未返回'")
s=s.replace("data.slave_online === undefined", "data.slave_online == null").replace("data.slave_operational === undefined", "data.slave_operational == null")
s=s.replace('        pushLiveSample(sample) {\n', '        pushLiveSample(sample) {\n            if (sample.status_fresh === false) return;\n')
s=s.replace('                const value = Number(sample[state.liveMetric]);', '                if (sample[state.liveMetric] == null) return;\n                const value = Number(sample[state.liveMetric]);')
f.write_text(s,encoding='utf-8')
f=p/'compare_vm_sources.py';s=f.read_text(encoding='utf-8')
s=s.replace("        if p.is_file():", "        if any(part in {'.git', '__pycache__', '.pytest_cache', '.venv', '.venv_local', 'venv', 'node_modules', 'build', 'dist', 'logs'} for part in p.relative_to(root).parts):\n            continue\n        if p.is_file():")
s=s.replace('    for f in common[:200]:','    errors = []\n    for f in common:')
s=s.replace("                with open(vm_file", "                if diffs:\n                    diffs.append(f)\n                    continue\n                with open(vm_file")
s=s.replace('        except Exception:\n            continue', "        except OSError as exc:\n            errors.append(f'{f}: {exc}')")
s=s.replace('Differing files (sample up to 200):', 'Differing files:')
s=s.replace("    print('\\nDone')\n    return 0", "    for error in errors:\n        print('Comparison failed:', error)\n    print('\\nDone')\n    return 2 if errors else (1 if diffs or only_in_vm or only_in_local else 0)")
f.write_text(s,encoding='utf-8')
