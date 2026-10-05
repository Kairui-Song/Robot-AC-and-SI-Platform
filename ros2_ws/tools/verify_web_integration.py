#!/usr/bin/env python3
"""Live HTTP → ROS supervisor → ros2_control → mock plugin verification.

Run from a sourced Jazzy workspace. Starts only isolated MOCK launches; no drives.
"""
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def request(url, token, command='state', payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(url + '/' + command, data=body,
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        response = urlopen(req, timeout=4.)
    except HTTPError as error:
        response = error
    with response:
        return response.code, json.loads(response.read())


def scenario(out, fault=False):
    label = 'fault' if fault else 'normal'
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    token = secrets.token_hex(24)
    env = dict(os.environ, LINGLONG_ROS_BIND='127.0.0.1', LINGLONG_ROS_PORT=str(port),
               LINGLONG_ROS_TOKEN=token, ROS_DOMAIN_ID=os.getenv('LINGLONG_TEST_DOMAIN_ID', '95'),
               ROS_LOCALHOST_ONLY='1')
    history = []
    url = f'http://127.0.0.1:{port}'
    process = None
    def wait(predicate, timeout=50):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('mock launch exited; inspect ' + label + '-launch.log')
            try:
                code, value = request(url, token)
                history.append(value)
                if code == 200 and predicate(value):
                    return value
            except (URLError, OSError):
                pass
            time.sleep(.1)
        raise TimeoutError('Web integration condition timed out')

    def accepted(command, payload=None):
        code, value = request(url, token, command, {} if payload is None else payload)
        assert code == 202 and value['accepted'], (command, code, value)
        return value

    passed = False
    with (out / (label + '-launch.log')).open('w') as log:
        process = subprocess.Popen(['ros2', 'launch', 'linglong_control', 'control.launch.py',
            'backend:=mock', 'rviz:=false', f'fault_after_cycles:={250 if fault else 0}'],
            env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            ready = wait(lambda v: v['system']['state'] == 'READY')
            assert ready['feedback_fresh'] and not ready['system']['motion_authorized']
            assert request(url, token, 'trajectory', dict(offsets=[.01]*4, duration=2))[0] == 409
            accepted('enable')
            wait(lambda v: v['system']['state'] == 'ENABLED')
            accepted('trajectory', dict(offsets=[.01]*4, duration=6 if fault else 2))
            wait(lambda v: v['system']['state'] == 'RUNNING', timeout=5)
            if fault:
                stopped = wait(lambda v: v['system']['state'] == 'FAULT' and not v['system']['operation'])
                assert not stopped['system']['motion_authorized']
                assert stopped['system']['last_result']['operation'] == 'fault_stop'
                assert stopped['system']['last_result']['success']
                assert request(url, token, 'enable', {})[0] == 409
                wait(lambda v: v['goal']['status'] in ('FAILED', 'CANCELLED'), timeout=10)
                accepted('recover')
                restored = wait(lambda v: v['system']['state'] == 'READY')
                assert not restored['system']['motion_authorized']
            else:
                completed = wait(lambda v: v['goal']['status'] == 'SUCCEEDED', timeout=10)
                assert completed['goal']['result']['success']
                wait(lambda v: v['system']['state'] == 'ENABLED')
                accepted('trajectory', dict(offsets=[.03]*4, duration=6))
                wait(lambda v: v['goal']['status'] in ('ACCEPTED', 'RUNNING'))
                accepted('cancel')
                wait(lambda v: v['goal']['status'] == 'CANCELLED', timeout=10)
                wait(lambda v: v['system']['state'] == 'ENABLED')
                accepted('disable')
                stopped = wait(lambda v: v['system']['state'] == 'READY')
                assert not stopped['system']['motion_authorized']
                assert stopped['system']['hardware_state'] == 'INACTIVE'
            accepted('shutdown')
            wait(lambda v: v['system']['state'] == 'SHUTDOWN')
            assert request(url, token, 'enable', {})[0] == 409
            passed = True
        finally:
            process.send_signal(signal.SIGINT) if process.poll() is None else None
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            (out / (label + '-states.json')).write_text(json.dumps(history, indent=2) + '\n')
    return dict(scenario=label, passed=passed)


def main():
    out = Path('verification') / time.strftime('web-integration-%Y%m%d-%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    results = []
    try:
        results.append(scenario(out))
        results.append(scenario(out, fault=True))
        print(json.dumps(results))
    finally:
        (out / 'result.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
