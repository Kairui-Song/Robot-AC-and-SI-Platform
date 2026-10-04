const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const local = path.join(__dirname, 'app.js');
const source = fs.readFileSync(fs.existsSync(local) ? local : path.join(__dirname, '../static/js/app.js'), 'utf8');
const callbacks = {}, elements = {}, timers = new Map();
let sequence = 0, label = '', samples = 0;
const context = vm.createContext({
    socket: {on: (name, callback) => callbacks[name] = callback},
    window: {__overviewLiveCharts: {setStatus: text => label = text, pushLiveSample: () => samples++}},
    document: {getElementById: id => elements[id] || null},
    setTimeout: (callback, delay) => {timers.set(++sequence, {callback, delay}); return sequence;},
    clearTimeout: id => timers.delete(id),
});
vm.runInContext(source.slice(source.indexOf('let overviewFeedbackTimer'), source.indexOf("socket.on('benchmark_progress'")), context);
const handle = context.handleOverviewBenchmarkStream;
handle({stage: 'status', status_fresh: true, status_fresh_seconds: 3});
assert.equal(samples, 1);
assert.equal([...timers.values()][0].delay, 3000);
[...timers.values()][0].callback();
assert.equal(label, '反馈已过期');
handle({stage: 'status', status_fresh: false});
assert.equal(samples, 1);
assert.equal(timers.size, 0);
handle({stage: 'status', status_fresh: true});
handle({stage: 'result', ok: true, status_fresh: false});
assert.equal(timers.size, 0);
assert.equal(label, '反馈已过期');
const start = source.indexOf("socket.on('benchmark_result'");
vm.runInContext(source.slice(start, source.indexOf('\n});', start) + 4), context);
for (const id of ['metricResponse', 'metricClosedLoop', 'metricJitter', 'metricCpu']) elements[id] = {};
callbacks.benchmark_result({status_fresh: false, actual_position: null, actual_velocity: null, actual_torque: null, link_up: null});
for (const element of Object.values(elements)) assert.equal(element.textContent, '反馈已过期');
console.log('PASS: stream silence, stale sample rejection, timer cleanup, null rendering');
