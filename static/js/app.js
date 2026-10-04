// 主控测试平台前端交互

// ============================================
// SOCKETIO 连接
// ============================================
const socket = io();

let testResults = {};

function appendCommLogRow(body, values, level) {
    const row = document.createElement('tr');
    values.forEach(value => {
        const cell = document.createElement('td');
        cell.textContent = value ?? '';
        row.appendChild(cell);
    });
    const statusCell = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = `status-dot ${level !== '正常' ? 'warning' : 'normal'}`;
    badge.textContent = level || '';
    statusCell.appendChild(badge);
    row.appendChild(statusCell);
    body.appendChild(row);
}

socket.on('connect', () => {
    console.log('主控测试平台已连接');
    updateSystemStatus(true);
});

socket.on('disconnect', () => {
    console.log('❌ 系统离线');
    updateSystemStatus(false);
});

function updateSystemStatus(online) {
    const indicators = document.querySelectorAll('.sys-status');
    indicators.forEach(el => {
        el.textContent = online ? 'Web服务在线' : 'Web服务离线';
        el.style.color = online ? 'rgba(0,240,255,0.5)' : 'rgba(255,45,117,0.5)';
    });
}

function appendHardwareLog(message, ok = true) {
    const panel = document.getElementById('pytestLogs');
    if (!panel) return;
    const line = document.createElement('div');
    line.style.color = ok ? 'rgba(0,240,255,0.75)' : 'rgba(255,80,110,0.85)';
    line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    panel.appendChild(line);
    panel.scrollTop = panel.scrollHeight;
}

function leftArmFailureMessage(data) {
    const detail = data.detail || {};
    const failedJoint = Array.isArray(detail.joints)
        ? detail.joints.find(item => !item.ok)
        : null;
    if (failedJoint) {
        const telemetry = failedJoint.telemetry || {};
        const status = telemetry.status_word || failedJoint.status_word;
        const errorCode = telemetry.error_code;
        return [
            `关节${failedJoint.joint}`,
            failedJoint.error,
            status ? `状态字=${status}` : '',
            errorCode ? `错误码=${errorCode}` : '',
        ].filter(Boolean).join(' · ');
    }
    return data.error || data.reason || data.info || detail.error || '主控未返回具体错误';
}

// ============================================
// 测试结果处理
// ============================================
socket.on('test_result', (data) => {
    console.log('📊 测试结果:', data);
    testResults[data.target] = data;
    
    // 更新按钮状态
    const btn = document.querySelector(`.test-btn[data-target="${data.target}"]`);
    if (btn) {
        btn.classList.remove('loading');
        btn.textContent = data.ok ? '✅ 通过' : '❌ 失败';
        btn.style.borderColor = data.ok ? 'rgba(0,240,255,0.3)' : 'rgba(255,45,117,0.3)';
        btn.style.color = data.ok ? '#00f0ff' : '#ff2d75';
        setTimeout(() => {
            btn.textContent = '测试';
            btn.style.borderColor = '';
            btn.style.color = '';
            btn.disabled = false;
        }, 3000);
    }
    
    // 显示霓虹通知
    if (data.target === 'left_arm') {
        const stopBtn = document.getElementById('stopLeftArmTest');
        if (stopBtn) stopBtn.disabled = true;
        appendHardwareLog(
            data.ok ? '左臂 EtherCAT 实机测试通过' : `左臂测试失败：${leftArmFailureMessage(data)}`,
            data.ok
        );
        if (data.ok && Array.isArray(data.detail && data.detail.joints)) {
            data.detail.joints.forEach(item => {
                const feedback = item.telemetry || {};
                appendHardwareLog(
                    `关节${item.joint}反馈 · 位置=${feedback.position} · 速度=${feedback.velocity} · ` +
                    `转矩=${feedback.torque} · 模式=${feedback.mode} · 状态=${feedback.status_word} · ` +
                    `错误=${feedback.error_code}`,
                    true
                );
            });
        }
    }
    showNeonToast(data.target, data.ok);
});

socket.on('test_progress', (data) => {
    console.log('⏳ 进度:', data);
    const btn = document.querySelector(`.test-btn[data-target="${data.target}"]`);
    if (btn) {
        btn.textContent = '⏳ ' + data.status;
    }
    if (data.target === 'left_arm') {
        const detail = data.detail || {};
        const joint = detail.joint ? ` · 关节${detail.joint}` : '';
        const target = detail.target !== undefined ? ` · 目标${detail.target}` : '';
        appendHardwareLog(`${data.status}${joint}${target}`, data.status !== 'warning');
    }
});

socket.on('motor_preflight_progress', (data) => {
    appendHardwareLog(`只读预检：${data.message || data.stage || 'running'}`, data.stage !== 'mode_fallback');
    if (data.stage === 'connecting') document.getElementById('preflightTransport').textContent = `${data.mode} · ${data.host || '本机'}`;
    if (data.stage === 'mode_fallback') document.getElementById('preflightTransport').textContent = `${data.mode} · ${data.host || '本机'}`;
    if (data.stage === 'master_detected') {
        document.getElementById('preflightMaster').textContent = 'Master 已读取';
        document.getElementById('preflightLink').textContent = data.link_up ? '链路在线' : '链路未建立';
        document.getElementById('preflightSlaveCount').textContent = String(data.slave_count);
    }
    if (data.stage === 'inventory') renderSlaveInventory(data.slaves || []);
    if (data.stage === 'controller_info') renderControllerInfo(data);
});

socket.on('motor_preflight_result', (data) => {
    const button = document.getElementById('singleMotorPreflightBtn');
    const state = document.getElementById('preflightState');
    if (button) { button.disabled = false; button.classList.remove('loading'); button.textContent = '启动主控统一预检'; }
    if (state) { state.textContent = data.ok ? '只读预检通过' : '预检失败'; state.className = `status-tag ${data.ok ? 'normal' : ''}`; }
    if (data.inventory) {
        document.getElementById('preflightMaster').textContent = `Master ${data.inventory.master}`;
        document.getElementById('preflightLink').textContent = data.inventory.link_up ? '链路在线' : '链路未建立';
        document.getElementById('preflightSlaveCount').textContent = String(data.inventory.slave_count);
        renderSlaveInventory(data.inventory.slaves || []);
    }
    if (data.controller_info) renderControllerInfo(data.controller_info);
    if (document.getElementById('controllerTestDuration')) {
        document.getElementById('controllerTestDuration').textContent = Number.isFinite(data.duration_ms) ? `${data.duration_ms.toFixed(3)} ms` : '未返回';
    }
    const levels = data.levels || {};
    const setLevel = (id, value) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value === null || value === undefined ? '资料不足' : value ? '通过' : '不通过';
    };
    setLevel('levelL1', levels.L1_test_client);
    setLevel('levelL2', levels.L2_master);
    setLevel('levelL3', levels.L3_link);
    setLevel('levelL4', levels.L4_topology);
    setLevel('levelL5', levels.L5_identity);
    if (data.assessment) appendHardwareLog(`分级结论：${data.assessment}`, data.ok);
    appendHardwareLog(data.ok ? '只读通信预检通过；动作仍保持禁止' : `预检失败：${data.error || data.info || '未知错误'}`, data.ok);
});

function renderControllerInfo(info) {
    const setText = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = value; };
    const controllerProfile = document.getElementById('controllerProfileSelect');
    const configuredModel = controllerProfile && controllerProfile.value === 'ep_h507a1' ? 'EP-H507A1（任务配置）' : (info.hardware_model || '未识别');
    setText('controllerModel', configuredModel);
    setText('controllerHostname', info.hostname || '未返回');
    setText('controllerHardware', info.hardware_model || '未返回');
    setText('controllerOs', info.os || '未返回');
    setText('controllerKernel', info.kernel || '未返回');
    setText('controllerArchitecture', info.architecture || '未返回');
    setText('controllerCpu', `${info.cpu_model || '未返回'} · ${info.cpu_cores ?? '-'} 核`);
    setText('controllerMemory', `${info.memory_available_mb ?? '-'} / ${info.memory_total_mb ?? '-'} MB 可用`);
    setText('controllerLoad', `${info.load_1m ?? '-'} / ${info.load_5m ?? '-'} / ${info.load_15m ?? '-'}`);
    const uptime = Number(info.uptime_seconds || 0);
    setText('controllerUptime', uptime ? `${Math.floor(uptime / 86400)} 天 ${Math.floor((uptime % 86400) / 3600)} 小时` : '未返回');
    setText('controllerRealtime', info.realtime_kernel ? '已启用 PREEMPT_RT' : '未检测到 PREEMPT_RT');
    setText('controllerScheduler', `${info.scheduler || '未返回'} · 优先级 ${info.scheduler_priority ?? '-'}`);
    setText('controllerPid', info.pid ?? '未返回');
    setText('controllerMasterVersion', info.igh_master_version || '未返回');
    const state = document.getElementById('controllerInfoState');
    if (state) { state.textContent = '已检测'; state.className = 'status-tag normal'; }
}

function renderSlaveInventory(slaves) {
    const panel = document.getElementById('slaveInventory');
    if (!panel) return;
    if (!slaves.length) { panel.innerHTML = '<div class="status-item"><span>未发现可读取从站</span></div>'; return; }
    panel.innerHTML = '';
    slaves.forEach(slave => {
        const vendor = `0x${Number(slave.vendor_id).toString(16).padStart(8, '0').toUpperCase()}`;
        const product = `0x${Number(slave.product_code).toString(16).padStart(8, '0').toUpperCase()}`;
        const row = document.createElement('div'); row.className = 'status-item';
        const title = document.createElement('strong'); title.textContent = `p${slave.position} · ${slave.name || '未命名从站'}`;
        const detail = document.createElement('span'); detail.textContent = `Vendor ${vendor} · Product ${product} · AL 0x${Number(slave.al_state).toString(16).toUpperCase()}${slave.error_flag ? ' · ERROR' : ''}`;
        row.append(title, detail); panel.appendChild(row);
    });
}

socket.on('batch_report', (data) => {
    console.log('📋 批量报告:', data);
    const summaryEl = document.getElementById('batchSummary');
    if (summaryEl) {
        summaryEl.innerHTML = `
            <span style="color:rgba(0,240,255,0.5);">● 总计 ${data.summary.total}</span>
            <span style="color:rgba(0,240,255,0.3);">|</span>
            <span style="color:rgba(0,240,255,0.7);">✓ ${data.summary.ok}</span>
            <span style="color:rgba(255,45,117,0.5);">✗ ${data.summary.fail}</span>
        `;
    }
    
    const batchBtn = document.getElementById('batchTestBtn');
    if (batchBtn) {
        batchBtn.classList.remove('loading');
        batchBtn.textContent = data.summary.fail === 0 ? '✅ 全部通过' : '⚠ 部分失败';
        batchBtn.disabled = false;
        setTimeout(() => {
            batchBtn.textContent = '⚡ 一键测试';
        }, 4000);
    }
});

let overviewFeedbackTimer = null;
function clearOverviewFeedbackTimer() {
    clearTimeout(overviewFeedbackTimer);
    overviewFeedbackTimer = null;
}
function handleOverviewBenchmarkStream(data) {
    if (!window.__overviewLiveCharts || !data) return;
    if (data.stage === 'connecting') {
        clearOverviewFeedbackTimer();
        window.__overviewLiveCharts.setStatus(`JE 测试连接中 · ${data.mode || 'unknown'}`);
        return;
    }
    if (data.stage === 'status') {
        clearOverviewFeedbackTimer();
        if (data.status_fresh === false) {
            window.__overviewLiveCharts.setStatus('反馈已过期');
            return;
        }
        const threshold = Number(data.status_fresh_seconds);
        overviewFeedbackTimer = setTimeout(() => {
            window.__overviewLiveCharts.setStatus('反馈已过期');
        }, (Number.isFinite(threshold) && threshold > 0 ? threshold : 2) * 1000);
        window.__overviewLiveCharts.pushLiveSample(data);
        return;
    }
    if (data.stage === 'result') {
        clearOverviewFeedbackTimer();
        if (data.status_fresh === false) {
            window.__overviewLiveCharts.setStatus('反馈已过期');
            return;
        }
        window.__overviewLiveCharts.setStatus(data.ok ? 'JE 实测流已完成' : 'JE 实测流中断');
        return;
    }
    if (data.stage === 'controller_info') {
        window.__overviewLiveCharts.setStatus(`JE 主控在线 · ${data.hostname || 'unknown'}`);
    }
}

socket.on('benchmark_progress', (data) => {
    handleOverviewBenchmarkStream(data);
    const panel = document.getElementById('benchmarkLog');
    if (!panel) return;
    const line = document.createElement('div');
    if (data.stage === 'sample') {
        const closedLoop = Number.isFinite(data.closed_loop_latency_ms) ? data.closed_loop_latency_ms.toFixed(3) : '-';
        const jitter = Number.isFinite(data.schedule_jitter_ms) ? data.schedule_jitter_ms.toFixed(3) : '-';
        line.textContent = `样本 ${data.sequence + 1}: ${data.ok ? '成功' : '失败'} · 闭环 ${closedLoop} ms · 抖动 ${jitter} ms`;
    } else if (data.stage === 'sampling') {
        line.textContent = `采样进度 ${data.completed}/${data.total} · 请求频率 ${data.frequency_hz} Hz`;
    } else if (data.stage === 'status') {
        const staleNote = data.status_fresh === false ? '（反馈已过期）' : '';
        line.textContent = `SW ${data.statusword_hex} · Pos ${data.actual_position} · Vel ${data.actual_velocity} · Torque ${data.actual_torque} · AL ${data.al_state_hex} · Link ${data.link_up ? 'UP' : 'DOWN'} ${staleNote}`;
        if (data.status_fresh === false) line.style.color = '#ff8b94';
    } else if (data.stage === 'controller_info') {
        renderControllerInfo(data);
        line.textContent = `主控信息已读取 · ${data.hostname || 'unknown'} · ${data.os || 'unknown'}`;
    } else if (data.stage === 'info' || data.stage === 'log') {
        line.textContent = data.message || data.stage;
    } else {
        line.textContent = `${data.stage}${data.joint ? ` · 关节${data.joint}` : ''}`;
    }
    panel.appendChild(line);
    panel.scrollTop = panel.scrollHeight;
});

socket.on('benchmark_stream', handleOverviewBenchmarkStream);

socket.on('benchmark_result', (data) => {
    handleOverviewBenchmarkStream({stage: 'result', ...data});
    const start = document.getElementById('startControllerBenchmark');
    const stop = document.getElementById('stopControllerBenchmark');
    if (start) start.disabled = false;
    if (stop) stop.disabled = true;
    const state = document.getElementById('benchmarkState');
    if (state) state.textContent = data.ok ? '测试完成' : '测试异常';
    const setText = (id, value) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    };
    setText('metricSuccess', data.statusword_hex || (data.ok ? '已运行' : '失败'));
    setText('metricResponse', data.status_fresh === false ? '反馈已过期' : (data.actual_position == null ? '未返回' : String(data.actual_position)));
    setText('metricClosedLoop', data.status_fresh === false ? '反馈已过期' : (data.actual_velocity == null ? '未返回' : String(data.actual_velocity)));
    setText('metricJitter', data.status_fresh === false ? '反馈已过期' : (data.actual_torque == null ? '未返回' : String(data.actual_torque)));
    setText('metricRate', data.al_state_hex || '未返回');
    setText('metricCpu', data.status_fresh === false ? '反馈已过期' : data.link_up == null ? '未返回' : (data.link_up ? 'UP' : 'DOWN'));
    if (data.controller_info) renderControllerInfo(data.controller_info);
    const rows = document.getElementById('benchmarkMetricRows');
    if (rows) {
        rows.innerHTML = [
            `<tr><td>工作计数器</td><td>${data.working_counter ?? '-'}</td><td>WC 状态</td><td>${data.wc_state ?? '-'}</td><td>样本 ${data.sample_count ?? 0}</td></tr>`,
            `<tr><td>从站在线</td><td>${data.slave_online == null ? '-' : (data.slave_online ? '是' : '否')}</td><td>从站 OP</td><td>${data.slave_operational == null ? '-' : (data.slave_operational ? '是' : '否')}</td><td>返回码 ${data.returncode ?? '-'}</td></tr>`,
        ].join('');
    }
    const panel = document.getElementById('benchmarkLog');
    if (panel) {
        const line = document.createElement('div');
        line.style.color = data.ok ? '#00f0ff' : '#ff5070';
        line.textContent = data.ok ? 'JE 主控测试完成' : `测试失败：${data.error || '未知错误'}`;
        panel.appendChild(line);
    }
});

// ============================================
// Pytest 输出
// ============================================
socket.on('pytest_output', (data) => {
    const logPanel = document.getElementById('pytestLogs');
    if (logPanel) {
        const line = document.createElement('div');
        line.textContent = data.line;
        line.style.fontFamily = "'JetBrains Mono', monospace";
        line.style.fontSize = '11px';
        line.style.color = data.line.includes('FAILED') ? '#ff2d75' : 
                           data.line.includes('PASSED') ? '#00f0ff' : 
                           data.line.includes('ERROR') ? '#ffd740' : 'rgba(180,210,255,0.4)';
        line.style.padding = '1px 0';
        line.style.borderBottom = '1px solid rgba(0,240,255,0.02)';
        logPanel.appendChild(line);
        logPanel.scrollTop = logPanel.scrollHeight;
    }

    const body = document.getElementById('commLogBody');
    if (body) {
        const noEntryRow = body.querySelector('.no-entry');
        if (noEntryRow) {
            noEntryRow.remove();
        }
        const now = new Date().toLocaleString('zh-CN');
        const level = /FAILED|ERROR|CRITICAL/.test(String(data.line || '').toUpperCase()) ? '异常' : '正常';
        appendCommLogRow(body, [now, data.target, data.line], level);
    }
});

socket.on('pytest_result', (data) => {
    console.log('🧪 Pytest 结果:', data);
    const logPanel = document.getElementById('pytestLogs');
    if (logPanel) {
        const line = document.createElement('div');
        line.textContent = `━━━ ${data.target} ${data.ok ? '✓ PASS' : '✗ FAIL'} ━━━`;
        line.style.fontFamily = "'Orbitron', monospace";
        line.style.fontSize = '10px';
        line.style.letterSpacing = '1px';
        line.style.color = data.ok ? 'rgba(0,240,255,0.3)' : 'rgba(255,45,117,0.3)';
        line.style.padding = '4px 0';
        line.style.marginTop = '4px';
        line.style.borderTop = '1px solid rgba(0,240,255,0.03)';
        logPanel.appendChild(line);
        logPanel.scrollTop = logPanel.scrollHeight;
    }

    const body = document.getElementById('commLogBody');
    if (body) {
        const noEntryRow = body.querySelector('.no-entry');
        if (noEntryRow) {
            noEntryRow.remove();
        }
        const now = new Date().toLocaleString('zh-CN');
        appendCommLogRow(body, [now, data.target, data.ok ? '测试完成' : '测试失败'], data.ok ? '正常' : '异常');
    }
});

socket.on('comm_log_entry', (entry) => {
    const body = document.getElementById('commLogBody');
    if (!body) {
        return;
    }

    const noEntryRow = body.querySelector('.no-entry');
    if (noEntryRow) {
        noEntryRow.remove();
    }

    appendCommLogRow(body, [entry.time, entry.target, entry.event], entry.level);
});

// ============================================
// IMU 数据 - 全息显示
// ============================================
socket.on('imu_data', (data) => {
    const display = document.getElementById('imuDisplay');
    if (display && data) {
        if (data.yaw !== undefined) {
            display.innerHTML = `
                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; font-family:'JetBrains Mono',monospace; font-size:12px;">
                    <div style="background:rgba(0,240,255,0.02); padding:6px 10px; border-radius:4px; border:1px solid rgba(0,240,255,0.04);">
                        <span style="color:rgba(0,240,255,0.3);">YAW</span>
                        <span style="color:rgba(0,240,255,0.7); float:right;">${data.yaw.toFixed(2)}°</span>
                    </div>
                    <div style="background:rgba(0,240,255,0.02); padding:6px 10px; border-radius:4px; border:1px solid rgba(0,240,255,0.04);">
                        <span style="color:rgba(0,240,255,0.3);">PITCH</span>
                        <span style="color:rgba(0,240,255,0.7); float:right;">${data.pitch.toFixed(2)}°</span>
                    </div>
                    <div style="background:rgba(0,240,255,0.02); padding:6px 10px; border-radius:4px; border:1px solid rgba(0,240,255,0.04);">
                        <span style="color:rgba(0,240,255,0.3);">ROLL</span>
                        <span style="color:rgba(0,240,255,0.7); float:right;">${data.roll.toFixed(2)}°</span>
                    </div>
                </div>
            `;
        }
    }
});

socket.on('imu_status', (status) => {
    const display = document.getElementById('imuDisplay');
    if (!display || !status || status.mode === 'online') return;
    display.textContent = status.mode === 'simulated'
        ? 'IMU 模拟数据（非实测）'
        : `IMU 未连接${status.reason ? `：${status.reason}` : ''}`;
});

// ============================================
// 霓虹通知系统
// ============================================
function showNeonToast(target, ok) {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        padding: 14px 28px;
        border-radius: 8px;
        font-family: 'Orbitron', monospace;
        font-size: 12px;
        letter-spacing: 1px;
        z-index: 9999;
        animation: slideIn 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        background: ${ok ? 'rgba(0,240,255,0.04)' : 'rgba(255,45,117,0.04)'};
        border: 1px solid ${ok ? 'rgba(0,240,255,0.15)' : 'rgba(255,45,117,0.15)'};
        color: ${ok ? '#00f0ff' : '#ff2d75'};
        backdrop-filter: blur(16px);
        box-shadow: ${ok ? '0 0 40px rgba(0,240,255,0.04)' : '0 0 40px rgba(255,45,117,0.04)'};
        text-shadow: ${ok ? '0 0 20px rgba(0,240,255,0.1)' : '0 0 20px rgba(255,45,117,0.1)'};
    `;
    toast.textContent = `${ok ? '✓' : '✗'} ${target} ${ok ? '通过' : '失败'}`;
    document.body.appendChild(toast);
    
    // 流光带效果
    const flow = document.createElement('div');
    flow.style.cssText = `
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, ${ok ? 'rgba(0,240,255,0.3)' : 'rgba(255,45,117,0.3)'}, transparent);
        background-size: 200% 100%;
        animation: dataFlow 2s linear infinite;
    `;
    toast.appendChild(flow);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'all 0.4s ease';
        setTimeout(() => toast.remove(), 400);
    }, 3000);
}

// ============================================
// 测试按钮事件
// ============================================
document.addEventListener('DOMContentLoaded', function() {
    // 单测试
    document.querySelectorAll('.test-btn[data-target]').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const target = this.dataset.target;
            
            this.classList.add('loading');
            this.textContent = '⏳ 执行中';
            this.disabled = true;
            
            if (target === 'left_arm') {
                const stopBtn = document.getElementById('stopLeftArmTest');
                if (stopBtn) stopBtn.disabled = false;
                appendHardwareLog('请求左臂 EtherCAT 测试');
            }
            socket.emit('run_test', { target: target });
        });
    });
    
    // 批量测试
    const batchBtn = document.getElementById('batchTestBtn');
    if (batchBtn) {
        batchBtn.addEventListener('click', function() {
            this.classList.add('loading');
            this.textContent = '⏳ 批量执行';
            this.disabled = true;
            
            const logPanel = document.getElementById('pytestLogs');
            if (logPanel) {
                logPanel.innerHTML = '<div style="color:rgba(0,240,255,0.2); font-family:\'JetBrains Mono\',monospace; font-size:11px;">⏳ 初始化批量测试...</div>';
            }
            
            socket.emit('run_batch', { 
                targets: ['left_leg', 'right_leg', 'left_arm', 'right_arm', 'head', 'IMU'] 
            });
        });
    }
    
    const stopLeftArmBtn = document.getElementById('stopLeftArmTest');
    if (stopLeftArmBtn) {
        stopLeftArmBtn.addEventListener('click', function() {
            this.disabled = true;
            appendHardwareLog('正在请求停止并失能左臂...', false);
            socket.emit('stop_test', { target: 'left_arm' });
        });
    }

    const emergencyBtn = document.querySelector('.emergency-button');
    if (emergencyBtn) {
        emergencyBtn.addEventListener('click', () => {
            socket.emit('stop_test', { target: 'single_motor_preflight' });
            socket.emit('stop_test', { target: 'controller_benchmark' });
            appendHardwareLog('已请求停止当前软件测试任务；硬件急停需由独立安全回路执行。', false);
        });
    }

    const saveConfigBtn = document.getElementById('saveEthercatConfig');
    const configForm = document.getElementById('ethercatConfigForm');
    if (saveConfigBtn && configForm) {
        saveConfigBtn.addEventListener('click', async () => {
            const payload = Object.fromEntries(new FormData(configForm).entries());
            ['connect_timeout', 'total_timeout', 'master_index', 'expected_slave_count'].forEach(key => {
                if (Object.prototype.hasOwnProperty.call(payload, key)) payload[key] = Number(payload[key]);
            });
            const message = document.getElementById('configMessage');
            saveConfigBtn.disabled = true;
            try {
                const postConfig = (token = '') => fetch('/api/ethercat-config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(token ? {'X-Linglong-Admin-Token': token} : {}),
                    },
                    body: JSON.stringify(payload),
                });
                let token = sessionStorage.getItem('linglongAdminToken') || '';
                let response = await postConfig(token);
                if (response.status === 403 && !token) {
                    token = window.prompt('请输入配置管理令牌') || '';
                    if (token) {
                        sessionStorage.setItem('linglongAdminToken', token);
                        response = await postConfig(token);
                    }
                }
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || '保存失败');
                if (message) {
                    message.textContent = payload.mode === 'local'
                        ? '配置已保存。本机模式要求本机存在 single_motor_preflight 且 sudo -n 免密可执行；若缺失将自动回退到 SSH。'
                        : '配置已保存。SSH 模式要求本机可执行 ssh、主机指纹正确，且远程主控已部署只读预检程序。';
                }
                const status = document.getElementById('configStatus');
                if (status) status.textContent = '最小权限模式';
            } catch (error) {
                if (message) message.textContent = `保存失败：${error.message}`;
            } finally {
                saveConfigBtn.disabled = false;
            }
        });
    }

    const startBenchmark = document.getElementById('startControllerBenchmark');
    const stopBenchmark = document.getElementById('stopControllerBenchmark');
    const benchmarkForm = document.getElementById('benchmarkForm');
    if (startBenchmark) {
        startBenchmark.addEventListener('click', () => {
            const payload = {};
            document.getElementById('benchmarkLog').innerHTML = '';
            startBenchmark.disabled = true;
            stopBenchmark.disabled = false;
            document.getElementById('benchmarkState').textContent = '执行中';
            const infoState = document.getElementById('controllerInfoState');
            if (infoState) infoState.textContent = '检测中';
            socket.emit('run_controller_benchmark', payload);
        });
    }
    if (stopBenchmark) {
        stopBenchmark.addEventListener('click', () => {
            stopBenchmark.disabled = true;
            socket.emit('stop_test', {target: 'controller_benchmark'});
        });
    }

    // 多型号单电机只读预检
    const motorProfileSelect = document.getElementById('motorProfileSelect');
    const controllerProfileSelect = document.getElementById('controllerProfileSelect');
    const preflightButton = document.getElementById('singleMotorPreflightBtn');
    const refreshMotorProfile = () => {
        if (!motorProfileSelect) return;
        const selected = motorProfileSelect.selectedOptions[0];
        document.getElementById('motorSupply').textContent = selected.dataset.supply;
        document.getElementById('motorVendor').textContent = selected.dataset.vendor;
        document.getElementById('motorProduct').textContent = selected.dataset.product;
        document.getElementById('motorPdo').textContent = selected.dataset.pdo;
    };
    if (motorProfileSelect) {
        motorProfileSelect.addEventListener('change', refreshMotorProfile);
        refreshMotorProfile();
    }
    const refreshControllerProfile = () => {
        if (!controllerProfileSelect) return;
        const selected = controllerProfileSelect.selectedOptions[0];
        const badge = document.getElementById('selectedControllerBadge');
        const model = document.getElementById('controllerModel');
        if (badge) badge.textContent = selected.textContent.replace('（项目设备）', '');
        if (model) model.textContent = controllerProfileSelect.value === 'ep_h507a1' ? 'EP-H507A1（任务配置）' : '—';
    };
    if (controllerProfileSelect) {
        controllerProfileSelect.addEventListener('change', refreshControllerProfile);
        refreshControllerProfile();
    }
    if (preflightButton && motorProfileSelect) {
        preflightButton.addEventListener('click', () => {
            preflightButton.disabled = true;
            preflightButton.classList.add('loading');
            preflightButton.textContent = '正在测试恩菲特主控';
            document.getElementById('preflightState').textContent = '执行中';
            document.getElementById('pytestLogs').innerHTML = '';
            appendHardwareLog(`主控测试负载：${motorProfileSelect.selectedOptions[0].textContent.trim()}`);
            socket.emit('run_motor_preflight', {
                profile_id: motorProfileSelect.value,
                controller_profile: controllerProfileSelect ? controllerProfileSelect.value : 'auto',
            });
        });
    }

    // 模态框
    const openModal = document.getElementById('openCurve');
    const closeModal = document.getElementById('closeModal');
    const modal = document.getElementById('curveModal');
    
    if (openModal && modal) {
        openModal.addEventListener('click', () => modal.classList.add('open'));
    }
    if (closeModal && modal) {
        closeModal.addEventListener('click', () => modal.classList.remove('open'));
    }
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.classList.remove('open');
        });
    }
    
    // 调整器
    document.querySelectorAll('.adjuster').forEach(group => {
        const [minus, plus] = group.querySelectorAll('.round-btn');
        const val = group.querySelector('.adjust-value');
        if (minus && plus && val) {
            minus.addEventListener('click', () => {
                let v = parseInt(val.textContent) || 0;
                v = Math.max(0, v - 1);
                val.textContent = v;
            });
            plus.addEventListener('click', () => {
                let v = parseInt(val.textContent) || 0;
                v = Math.min(100, v + 1);
                val.textContent = v;
            });
        }
    });
});

// ============================================
// 注入额外样式
// ============================================
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { opacity: 0; transform: translateX(30px) scale(0.95); }
        to { opacity: 1; transform: translateX(0) scale(1); }
    }
    
    .test-btn.loading {
        position: relative;
        color: transparent !important;
        pointer-events: none;
        border-color: rgba(0,240,255,0.2) !important;
    }
    
    .test-btn.loading::after {
        content: '';
        position: absolute;
        width: 16px;
        height: 16px;
        border: 2px solid rgba(0,240,255,0.1);
        border-top-color: #00f0ff;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        box-shadow: 0 0 20px rgba(0,240,255,0.1);
    }
    
    .test-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
    
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
    
    /* 机甲边框装饰角 - 添加到卡片 */
    .glass-card .corner-tl,
    .glass-card .corner-tr,
    .glass-card .corner-bl,
    .glass-card .corner-br {
        position: absolute;
        width: 12px;
        height: 12px;
        border-color: rgba(0,240,255,0.06);
        border-style: solid;
        border-width: 0;
    }
    .glass-card .corner-tl { top: 6px; left: 6px; border-top-width: 1px; border-left-width: 1px; }
    .glass-card .corner-tr { top: 6px; right: 6px; border-top-width: 1px; border-right-width: 1px; }
    .glass-card .corner-bl { bottom: 6px; left: 6px; border-bottom-width: 1px; border-left-width: 1px; }
    .glass-card .corner-br { bottom: 6px; right: 6px; border-bottom-width: 1px; border-right-width: 1px; }
`;

document.head.appendChild(style);

// 总览曲线只使用主控闭环测试返回的实测样本。
function initOverviewLiveCharts() {
    const charts = document.querySelectorAll('.curve-graph');
    if (!charts.length) return;

    let samples = [];
    const source = document.getElementById('overviewCurveData');
    if (source) {
        try { samples = JSON.parse(source.textContent || '[]'); } catch (_) { samples = []; }
    }

    const chartStates = [];

    charts.forEach((container, chartIndex) => {
        const width = 620;
        const height = 210;
        const padding = 18;
        const metric = container.dataset.metric;
        const unit = container.dataset.unit || '';
        const liveMetric = container.dataset.liveMetric || metric;
        const liveUnit = container.dataset.liveUnit ?? unit;
        const label = container.previousElementSibling;
        const defaultLabel = label ? label.textContent : '';
        const liveLabel = container.dataset.liveLabel || defaultLabel;
        const values = samples.map(item => Number(item[metric])).filter(Number.isFinite);

        container.innerHTML = `
            <svg class="live-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
                <defs>
                    <linearGradient id="liveAreaGradient-${chartIndex}" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#ff6b2c" stop-opacity=".48"></stop>
                        <stop offset="70%" stop-color="#ff6b2c" stop-opacity=".08"></stop>
                        <stop offset="100%" stop-color="#ff6b2c" stop-opacity="0"></stop>
                    </linearGradient>
                </defs>
                <g class="live-grid"></g>
                <path class="live-area" fill="url(#liveAreaGradient-${chartIndex})"></path>
                <path class="live-line"></path>
                <circle class="live-dot-halo" r="9"></circle>
                <circle class="live-dot" r="3.5"></circle>
            </svg>
            <span class="live-chart-value"></span>
            <span class="live-chart-status">实测样本</span>`;

        const svg = container.querySelector('svg');
        const grid = svg.querySelector('.live-grid');
        const area = svg.querySelector('.live-area');
        const line = svg.querySelector('.live-line');
        const dot = svg.querySelector('.live-dot');
        const halo = svg.querySelector('.live-dot-halo');
        const badge = container.querySelector('.live-chart-value');
        const status = container.querySelector('.live-chart-status');

        const state = {
            label,
            defaultLabel,
            liveLabel,
            defaultMetric: metric,
            liveMetric,
            defaultUnit: unit,
            liveUnit,
            values,
            liveValues: [],
            usingLive: false,
            line,
            area,
            dot,
            halo,
            badge,
            status,
        };
        chartStates.push(state);

        for (let row = 1; row < 5; row += 1) {
            const y = padding + ((height - padding * 2) / 5) * row;
            grid.insertAdjacentHTML('beforeend', `<line class="live-grid-line" x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}"></line>`);
        }
        for (let column = 1; column < 7; column += 1) {
            const x = padding + ((width - padding * 2) / 7) * column;
            grid.insertAdjacentHTML('beforeend', `<line class="live-grid-line" x1="${x}" y1="${padding}" x2="${x}" y2="${height - padding}"></line>`);
        }

        const draw = () => {
            const activeValues = state.usingLive ? state.liveValues : state.values;
            const activeUnit = state.usingLive ? state.liveUnit : state.defaultUnit;
            if (!activeValues.length) {
                state.line.removeAttribute('d');
                state.area.removeAttribute('d');
                state.dot.style.display = 'none';
                state.halo.style.display = 'none';
                state.badge.textContent = '暂无实测数据';
                return;
            }
            const minValue = Math.min(...activeValues);
            const maxValue = Math.max(...activeValues);
            const margin = Math.max((maxValue - minValue) * .15, .001);
            const min = minValue - margin;
            const max = maxValue + margin;
            const range = Math.max(max - min, .001);
            const points = activeValues.map((value, index) => {
                const x = activeValues.length === 1 ? width / 2 : padding + index * ((width - padding * 2) / (activeValues.length - 1));
                const y = height - padding - ((value - min) / range) * (height - padding * 2);
                return [x, y];
            });
            const lineData = points.map(([x, y], index) => `${index ? 'L' : 'M'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
            const last = points[points.length - 1];
            state.line.setAttribute('d', lineData);
            state.area.setAttribute('d', `${lineData} L ${last[0]} ${height - padding} L ${padding} ${height - padding} Z`);
            state.dot.setAttribute('cx', last[0]); state.dot.setAttribute('cy', last[1]);
            state.halo.setAttribute('cx', last[0]); state.halo.setAttribute('cy', last[1]);
            state.badge.textContent = `${activeValues[activeValues.length - 1].toFixed(3)}${activeUnit}`;
        };

        state.draw = draw;
        draw();
    });

    window.__overviewLiveCharts = {
        pushLiveSample(sample) {
            if (sample.status_fresh === false) return;
            chartStates.forEach((state) => {
                if (sample[state.liveMetric] == null) return;
                const value = Number(sample[state.liveMetric]);
                if (!Number.isFinite(value)) return;
                state.usingLive = true;
                state.liveValues.push(value);
                if (state.liveValues.length > 60) {
                    state.liveValues.shift();
                }
                if (state.label) state.label.textContent = state.liveLabel;
                if (state.status) state.status.textContent = 'JE 实测流';
                state.draw();
            });
        },
        setStatus(text) {
            chartStates.forEach((state) => {
                if (state.status) state.status.textContent = text;
            });
        },
    };

    const state = document.getElementById('webClientState');
    if (state && typeof socket !== 'undefined') {
        const update = () => { state.textContent = socket.connected ? '连接正常' : '未连接'; };
        socket.on('connect', update);
        socket.on('disconnect', update);
        update();
    }
}

document.addEventListener('DOMContentLoaded', initOverviewLiveCharts);

document.addEventListener('DOMContentLoaded', () => {
    const heroCurveButton = document.getElementById('heroCurveButton');
    const originalCurveButton = document.getElementById('openCurve');
    if (heroCurveButton && originalCurveButton) {
        heroCurveButton.addEventListener('click', () => originalCurveButton.click());
    }
});
