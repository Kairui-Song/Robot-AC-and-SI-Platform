"""Bounded HTTP transport. ROS callbacks execute queued work in their own executor."""
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import queue
import threading
import time


@dataclass
class RequestTask:
    command: str
    payload: dict
    deadline: float
    event: threading.Event = field(default_factory=threading.Event)
    status: int = 503
    result: dict = field(default_factory=dict)

    def finish(self, status, **result):
        self.status, self.result = status, result
        self.event.set()


class GatewayTransport:
    def __init__(self, token='', timeout=3.0):
        self.token, self.timeout = token, timeout
        self.tasks = queue.Queue(maxsize=16)
        self.lock = threading.Lock()
        self.value = None
        self.received = None

    def publish(self, value):
        # Serialize in the producer; readers never see mutable ROS-owned objects.
        with self.lock:
            self.value = json.loads(json.dumps(value, allow_nan=False))
            self.received = time.monotonic()

    def snapshot(self):
        with self.lock:
            age = None if self.received is None else time.monotonic() - self.received
            value = dict(self.value or {})
        if age is None or age > 1.0:
            return 503, dict(ok=False, connected=False, state='UNKNOWN',
                             error='ROS gateway executor unavailable or stale', gateway_age_seconds=age)
        value['gateway_age_seconds'] = age
        return (200 if value.get('connected') else 503), value

    def submit(self, command, payload):
        task = RequestTask(command, payload, time.monotonic() + self.timeout)
        try:
            self.tasks.put_nowait(task)
        except queue.Full:
            return 503, dict(ok=False, error='gateway command queue full')
        if not task.event.wait(self.timeout):
            return 504, dict(ok=False, completion_unknown=True,
                             error='request timed out; inspect system state before sending another request')
        return task.status, task.result


def make_server(address, transport):
    if address[0] not in ('127.0.0.1', 'localhost') and not transport.token:
        raise ValueError('Remote gateway binding requires LINGLONG_ROS_TOKEN')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, value):
            body = json.dumps(value, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            self.connection.settimeout(4.0)
            if transport.token and not hmac.compare_digest(
                    self.headers.get('Authorization', ''), 'Bearer ' + transport.token):
                self.reply(401, dict(ok=False, error='gateway authorization required'))
                return False
            # This is a server-to-server API; browser cross-origin requests are rejected.
            if self.headers.get('Origin'):
                self.reply(403, dict(ok=False, error='browser access must use the Web platform'))
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            if self.path != '/state':
                self.reply(404, dict(ok=False, error='unknown endpoint'))
                return
            self.reply(*transport.snapshot())

        def do_POST(self):
            if not self.authorized():
                return
            command = self.path.removeprefix('/')
            if self.path not in ('/enable', '/disable', '/recover', '/shutdown', '/trajectory', '/cancel'):
                self.reply(404, dict(ok=False, error='unknown command'))
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096:
                    raise ValueError('JSON request size must be between 1 and 4096 bytes')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('JSON object required')
            except (ValueError, OSError) as error:
                self.reply(400, dict(ok=False, error=str(error)))
                return
            self.reply(*transport.submit(command, payload))

    return ThreadingHTTPServer(address, Handler)
