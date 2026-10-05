"""Flask-side ROS gateway client; works on Windows without ROS libraries."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


def configured():
    return bool(os.environ.get('LINGLONG_ROS_URL', '').strip())


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def call(command='state', payload=None):
    if command not in ('state', 'enable', 'disable', 'recover', 'shutdown', 'trajectory', 'cancel'):
        return dict(ok=False, error='unknown ROS command'), 400
    if not configured():
        return dict(ok=False, connected=False, state='UNKNOWN',
                    error='未配置 ROS 主控网关：请设置 LINGLONG_ROS_URL'), 503
    url = os.environ['LINGLONG_ROS_URL'].strip().rstrip('/')
    parsed = urlsplit(url)
    token = os.environ.get('LINGLONG_ROS_TOKEN', '')
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or \
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        return dict(ok=False, error='LINGLONG_ROS_URL 必须是网关根地址'), 503
    if parsed.hostname not in ('localhost', '127.0.0.1') and not token:
        return dict(ok=False, error='远程 ROS 网关需要 LINGLONG_ROS_TOKEN'), 503
    try:
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        body = None if command == 'state' else json.dumps(payload or {}, allow_nan=False).encode('utf-8')
        request = Request(url + '/' + command, data=body, headers=headers,
                          method='GET' if command == 'state' else 'POST')
        opener = build_opener(ProxyHandler({}), NoRedirect())
        try:
            response = opener.open(request, timeout=4.)
        except HTTPError as error:
            response = error
        with response:
            status = response.code
            result = json.loads(response.read(65537))
            if not isinstance(result, dict):
                raise ValueError('gateway returned a non-object response')
            return result, status
    except (URLError, OSError, ValueError) as error:
        return dict(ok=False, connected=False, state='UNKNOWN',
                    completion_unknown=command != 'state', error='ROS 网关请求失败：' + str(error)), 503


def register(app):
    from flask import jsonify, request, render_template

    @app.get('/ros-control')
    def ros_control():
        return render_template('ros_control.html', page='ros-control')

    @app.get('/api/ros/state')
    def ros_state():
        result, status = call()
        return jsonify(result), status

    @app.post('/api/ros/<command>')
    def ros_command(command):
        # Cross-site browser requests must not trigger motion even on localhost.
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
            return jsonify(ok=False, error='跨站控制请求已拒绝'), 403
        token = os.environ.get('LINGLONG_ADMIN_TOKEN')
        if token and request.headers.get('X-Linglong-Admin-Token') != token:
            return jsonify(ok=False, error='需要管理员令牌'), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(ok=False, error='需要 JSON 对象'), 400
        if command == 'state':
            return jsonify(ok=False, error='状态接口仅支持 GET'), 405
        result, status = call(command, payload)
        return jsonify(result), status
