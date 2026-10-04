// static/js/app.js - 赛博科技版

// ============================================
// SOCKETIO 连接
// ============================================
const socket = io();

let testResults = {};

socket.on('connect', () => {
    console.log('✅ 系统已连接 · 赛博自检 v2.0');
    updateSystemStatus(true);
});

socket.on('disconnect', () => {
    console.log('❌ 系统离线');
    updateSystemStatus(false);
});

function updateSystemStatus(online) {
    const indicators = document.querySelectorAll('.sys-status');
    indicators.forEach(el => {
        el.textContent = online ? '● ONLINE' : '● OFFLINE';
        el.style.color = online ? 'rgba(0,240,255,0.5)' : 'rgba(255,45,117,0.5)';
    });
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
    showNeonToast(data.target, data.ok);
});

socket.on('test_progress', (data) => {
    console.log('⏳ 进度:', data);
    const btn = document.querySelector(`.test-btn[data-target="${data.target}"]`);
    if (btn) {
        btn.textContent = '⏳ ' + data.status;
    }
});

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
        const row = document.createElement('tr');
        const now = new Date().toLocaleString('zh-CN');
        row.innerHTML = `
            <td>${now}</td>
            <td>${data.target || ''}</td>
            <td>${data.line || ''}</td>
            <td><span class="status-dot ${/FAILED|ERROR|CRITICAL/.test(data.line.toUpperCase()) ? 'warning' : 'normal'}">${/FAILED|ERROR|CRITICAL/.test(data.line.toUpperCase()) ? '异常' : '正常'}</span></td>
        `;
        body.appendChild(row);
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
        const row = document.createElement('tr');
        const now = new Date().toLocaleString('zh-CN');
        row.innerHTML = `
            <td>${now}</td>
            <td>${data.target || ''}</td>
            <td>${data.ok ? '测试完成' : '测试失败'}</td>
            <td><span class="status-dot ${data.ok ? 'normal' : 'warning'}">${data.ok ? '正常' : '异常'}</span></td>
        `;
        body.appendChild(row);
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

    const row = document.createElement('tr');
    row.innerHTML = `
        <td>${entry.time || ''}</td>
        <td>${entry.target || ''}</td>
        <td>${entry.event || ''}</td>
        <td><span class="status-dot ${entry.level !== '正常' ? 'warning' : 'normal'}">${entry.level || ''}</span></td>
    `;
    body.appendChild(row);
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

// 整机总览实时曲线：前端动态模拟，不影响后端通信数据。
function initOverviewLiveCharts() {
    const charts = document.querySelectorAll('.curve-graph');
    if (!charts.length) return;

    charts.forEach((container, chartIndex) => {
        const width = 620;
        const height = 210;
        const padding = 18;
        const pointCount = 34;
        const base = chartIndex === 0 ? 62 : 0.42;
        const volatility = chartIndex === 0 ? 11 : 0.11;
        const unit = chartIndex === 0 ? ' ms' : ' %';
        const decimals = chartIndex === 0 ? 1 : 2;
        const values = Array.from({ length: pointCount }, (_, index) =>
            base + Math.sin(index * .48 + chartIndex) * volatility + (Math.random() - .5) * volatility
        );

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
            <span class="live-chart-status">LIVE · 800 MS</span>`;

        const svg = container.querySelector('svg');
        const grid = svg.querySelector('.live-grid');
        const area = svg.querySelector('.live-area');
        const line = svg.querySelector('.live-line');
        const dot = svg.querySelector('.live-dot');
        const halo = svg.querySelector('.live-dot-halo');
        const badge = container.querySelector('.live-chart-value');

        for (let row = 1; row < 5; row += 1) {
            const y = padding + ((height - padding * 2) / 5) * row;
            grid.insertAdjacentHTML('beforeend', `<line class="live-grid-line" x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}"></line>`);
        }
        for (let column = 1; column < 7; column += 1) {
            const x = padding + ((width - padding * 2) / 7) * column;
            grid.insertAdjacentHTML('beforeend', `<line class="live-grid-line" x1="${x}" y1="${padding}" x2="${x}" y2="${height - padding}"></line>`);
        }

        const draw = () => {
            const min = Math.min(...values) - volatility;
            const max = Math.max(...values) + volatility;
            const range = Math.max(max - min, .001);
            const points = values.map((value, index) => {
                const x = padding + index * ((width - padding * 2) / (pointCount - 1));
                const y = height - padding - ((value - min) / range) * (height - padding * 2);
                return [x, y];
            });
            const lineData = points.map(([x, y], index) => `${index ? 'L' : 'M'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
            const last = points[points.length - 1];
            line.setAttribute('d', lineData);
            area.setAttribute('d', `${lineData} L ${last[0]} ${height - padding} L ${padding} ${height - padding} Z`);
            dot.setAttribute('cx', last[0]); dot.setAttribute('cy', last[1]);
            halo.setAttribute('cx', last[0]); halo.setAttribute('cy', last[1]);
            badge.textContent = `${values[values.length - 1].toFixed(decimals)}${unit}`;
        };

        draw();
        window.setInterval(() => {
            const previous = values[values.length - 1];
            const next = previous + (base - previous) * .18 + (Math.random() - .48) * volatility;
            values.push(Math.max(chartIndex === 0 ? 12 : .01, next));
            values.shift();
            draw();
        }, 800);
    });
}

document.addEventListener('DOMContentLoaded', initOverviewLiveCharts);

document.addEventListener('DOMContentLoaded', () => {
    const heroCurveButton = document.getElementById('heroCurveButton');
    const originalCurveButton = document.getElementById('openCurve');
    if (heroCurveButton && originalCurveButton) {
        heroCurveButton.addEventListener('click', () => originalCurveButton.click());
    }
});

console.log('⚡ 赛博自检系统 v2.0 已加载');
console.log('◈ LINGLONG 1025 · 数据链路就绪');
