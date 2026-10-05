(() => {
  const names = ['joint_1', 'joint_2', 'joint_3', 'joint_5'];
  const el = id => document.getElementById(id);
  let pending = false;
  let latest = null;
  function render(view) {
    latest = view;
    const s = view.system || {state: 'UNKNOWN', reason: view.error || '等待反馈'};
    const connected = view.connected === true;
    el('rosConnection').textContent = connected ? '主控网关已连接' : '主控未连接';
    el('rosReason').textContent = s.reason || view.error || '—';
    el('rosBackend').textContent = view.backend === 'mock' ? 'MOCK 模拟' : view.backend === 'ethercat_left_arm' ? 'EtherCAT 实机' : '—';
    el('rosState').textContent = s.state || 'UNKNOWN';
    el('rosHardware').textContent = s.hardware_state || 'UNKNOWN';
    el('rosController').textContent = s.controller_state || '—';
    el('rosOperation').textContent = s.operation ? `正在处理：${s.operation}` : s.last_result ? `上次操作：${s.last_result.operation} · ${s.last_result.success ? '完成' : '失败'} · ${s.last_result.reason}` : '暂无状态切换';
    const goal = view.goal || {};
    el('rosGoal').textContent = goal.status ? `轨迹：${goal.status}${goal.result ? ' · ' + (goal.result.message || '') : ''}` : '暂无轨迹';
    const busy = pending || !!s.operation || !!s.restart_required || !connected;
    document.querySelectorAll('[data-ros-command]').forEach(button => {
      const c = button.dataset.rosCommand;
      const allowed = c === 'enable' ? s.state === 'READY' && view.feedback_fresh :
        c === 'disable' ? ['READY', 'ENABLED', 'RUNNING'].includes(s.state) :
        c === 'recover' ? s.state === 'FAULT' && view.backend === 'mock' :
        c === 'shutdown' ? s.state !== 'SHUTDOWN' : ['ACCEPTED', 'RUNNING'].includes(goal.status);
      button.disabled = busy || !allowed;
    });
    const activeGoal = ['SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCELLING', 'UNKNOWN'].includes(goal.status);
    el('rosSend').disabled = busy || activeGoal || s.state !== 'ENABLED' || !s.motion_authorized || !s.feedback_fresh || !view.feedback_fresh;
    names.forEach(name => {
      const p = view.joints && view.joints[name];
      el('feedback-' + name).textContent = p && Number.isFinite(p.position) ? `反馈 ${p.position.toFixed(4)} rad` : '反馈未知';
    });
  }
  async function refresh() {
    try {
      const response = await fetch('/api/ros/state', {signal: AbortSignal.timeout(5000), cache: 'no-store'});
      render(await response.json());
    } catch (error) {
      render({connected: false, error: `状态读取失败：${error.message}`});
    }
    setTimeout(refresh, 500);
  }
  async function command(name, body = {}) {
    if (pending) return;
    pending = true;
    render(latest || {});
    try {
      const response = await fetch('/api/ros/' + name, {method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Linglong-Admin-Token': el('rosAdminToken').value},
        body: JSON.stringify(body), signal: AbortSignal.timeout(6000)});
      const result = await response.json();
      el('rosResult').textContent = result.ok ? '请求已受理，等待主控完成反馈' : (result.error || result.detail || '请求失败');
    } catch (error) {
      el('rosResult').textContent = `请求结果未知，请先查看状态：${error.message}`;
    } finally {
      pending = false;
      render(latest || {});
    }
  }
  document.querySelectorAll('[data-ros-command]').forEach(button =>
    button.addEventListener('click', () => command(button.dataset.rosCommand)));
  el('rosMotion').addEventListener('submit', event => {
    event.preventDefault();
    const data = new FormData(event.target);
    command('trajectory', {offsets: names.map(name => Number(data.get(name))), duration: Number(data.get('duration'))});
  });
  refresh();
})();
