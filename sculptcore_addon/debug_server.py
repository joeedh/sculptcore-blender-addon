# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opt-in, authenticated loopback Python console. See claudeMemory/codebase/blender-debug-server.md."""

import contextlib
import hmac
import io
import json
import queue
import secrets
import socket
import socketserver
import threading
import time
import traceback

# Reload must release the old instance before replacing its callbacks and globals.
if globals().get("_server") is not None:
    stop()

_server = None
_MAX_REQUEST = 256 * 1024
_MAX_RESPONSE = 512 * 1024
_MAX_TEXT = 32 * 1024
_MAX_CONNECTIONS = 8
_READ_TIMEOUT = 5.0
_JOB_TIMEOUT = 30.0
_INTERVAL = 0.05


def _main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender debug server lifecycle and pump require the main thread")


def _error(status, message):
    return {"ok": False, "status": status, "error": message}


class _Capture(io.TextIOBase):
    def __init__(self):
        self.parts = []
        self.length = 0
        self.truncated = False

    def write(self, value):
        count = len(value)
        remaining = _MAX_TEXT - self.length
        if count > remaining:
            self.truncated = True
        if remaining and count:
            self.parts.append(value[:remaining])
        self.length += min(count, remaining)
        return count

    def getvalue(self):
        return "".join(self.parts)


class _Job:
    def __init__(self, request):
        self.request = request
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.status = 'QUEUED'
        self.reply = None

    def expire(self):
        with self.lock:
            if self.status == 'DONE':
                return self.reply
            if self.status == 'QUEUED':
                self.status = 'CANCELLED'
                self.reply = _error("cancelled", "Timed out before execution; command was cancelled")
                self.event.set()
                return self.reply
            if self.status == 'CANCELLED':
                return self.reply
            return _error("unknown", "Execution started; completion is unknown. Do not automatically retry")


class _Transport(socketserver.ThreadingTCPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, state, port):
        self.state = state
        self.slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        self.clients_lock = threading.Lock()
        self.clients = set()
        super().__init__(("127.0.0.1", port), _Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self.clients_lock:
            self.clients.add(request)
        try:
            super().process_request(request, address)
        except BaseException:
            self._release(request)
            raise

    def _release(self, request):
        with self.clients_lock:
            self.clients.discard(request)
        self.slots.release()

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self._release(request)

    def close_clients(self):
        with self.clients_lock:
            for client in self.clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client.close()


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            reply = self._receive()
            payload = json.dumps(reply, ensure_ascii=True).encode("utf-8") + b"\n"
            if len(payload) > _MAX_RESPONSE:
                payload = json.dumps(_error("response_limit", "Response exceeded byte limit; command ran")).encode()
                payload += b"\n"
            self.request.settimeout(_READ_TIMEOUT)
            self.request.sendall(payload)
        except (OSError, ValueError):
            # Disconnects never enqueue a retry; a command may already have run.
            pass

    def _receive(self):
        deadline = time.monotonic() + _READ_TIMEOUT
        data = bytearray()
        while b"\n" not in data:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _error("invalid", "Request read deadline exceeded")
            self.request.settimeout(remaining)
            chunk = self.request.recv(min(4096, _MAX_REQUEST + 1 - len(data)))
            if not chunk:
                return _error("invalid", "Expected one JSON line")
            data.extend(chunk)
            if len(data) > _MAX_REQUEST:
                return _error("invalid", "Request exceeds byte limit")
        try:
            request = json.loads(bytes(data).decode("utf-8"))
        except (ValueError, RecursionError):
            return _error("invalid", "Expected one UTF-8 JSON object")
        if not isinstance(request, dict):
            return _error("invalid", "Expected a JSON object")
        token = request.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.server.state.token.encode()):
            return _error("unauthorized", "Invalid token")
        op = request.get("op")
        if op not in ("ping", "eval", "exec") or not isinstance(request.get("code", ""), str):
            return _error("invalid", "Expected ping, eval or exec and a string code field")
        job = _Job(request)
        state = self.server.state
        # Admission and stop share a lock: no queued job can appear after stop drains it.
        with state.admission_lock:
            if state.stopped:
                return _error("stopped", "Server stopped")
            try:
                state.jobs.put_nowait(job)
            except queue.Full:
                return _error("busy", "Request queue is full; command was not queued")
        if job.event.wait(_JOB_TIMEOUT):
            return job.reply
        return job.expire()


class _State:
    def __init__(self, bpy, port):
        self.bpy = bpy
        self.token = secrets.token_hex(32)
        self.namespace = {"bpy": bpy, "__name__": "__sculptcore_debug__"}
        self.jobs = queue.Queue(maxsize=_MAX_CONNECTIONS)
        self.admission_lock = threading.Lock()
        self.stopped = False
        self.pumping = False
        self.transport = _Transport(self, port)
        self.thread = threading.Thread(target=self.transport.serve_forever, kwargs={"poll_interval": 0.05},
                                       name="SculptCore debug listener", daemon=True)
        # Stable callable identities are required by Blender's timer registry.
        self.timer = self.tick
        self.on_load = lambda *_args: stop()

    def info(self):
        return {"host": "127.0.0.1", "port": self.transport.server_address[1], "token": self.token}

    def tick(self):
        self.pump()
        return None if self.stopped else _INTERVAL

    def pump(self):
        _main_thread()
        if self.pumping:
            raise RuntimeError("Recursive debug server pumping is not supported")
        if self.stopped:
            return
        self.pumping = True
        try:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return
            with job.lock:
                if job.status != 'QUEUED':
                    return
                job.status = 'RUNNING'
            reply = self.execute(job.request)
            with job.lock:
                job.reply = reply
                job.status = 'DONE'
                job.event.set()
        finally:
            self.pumping = False
            if self.stopped:
                self.namespace.clear()

    def execute(self, request):
        stdout, stderr = _Capture(), _Capture()
        reply = {"ok": True, "status": "done", "result": None}
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                op = request["op"]
                if op == "ping":
                    reply["result"] = "pong"
                elif op == "eval":
                    value = eval(compile(request.get("code", ""), "<sculptcore-debug>", "eval"), self.namespace)
                    result = repr(value)
                    reply["result"] = result[:_MAX_TEXT]
                    reply["result_truncated"] = len(result) > _MAX_TEXT
                else:
                    exec(compile(request.get("code", ""), "<sculptcore-debug>", "exec"), self.namespace)
            except BaseException as error:
                try:
                    detail = "".join(traceback.format_exception(error))[:_MAX_TEXT]
                except BaseException:
                    detail = "Exception could not be formatted"
                reply = _error("exception", detail)
        reply.update(stdout=stdout.getvalue(), stderr=stderr.getvalue(),
                     output_truncated=stdout.truncated or stderr.truncated)
        return reply

    def close(self):
        with self.admission_lock:
            self.stopped = True
            while True:
                try:
                    self.jobs.get_nowait().expire()
                except queue.Empty:
                    break
        if self.on_load in self.bpy.app.handlers.load_pre:
            self.bpy.app.handlers.load_pre.remove(self.on_load)
        if self.bpy.app.timers.is_registered(self.timer):
            self.bpy.app.timers.unregister(self.timer)
        # Only the listener is joined; handlers may be waiting on this very main thread.
        if self.thread.is_alive():
            self.transport.shutdown()
        self.transport.server_close()
        self.transport.close_clients()
        if not self.pumping:
            self.namespace.clear()


def start(port=0):
    """Start explicitly on IPv4 loopback; return host/port/token. Repeated starts are idempotent."""
    global _server
    _main_thread()
    if _server is not None:
        return _server.info()
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be an integer from 0 through 65535")
    import bpy
    state = _State(bpy, port)
    _server = state
    try:
        state.thread.start()
        bpy.app.handlers.load_pre.append(state.on_load)
        bpy.app.timers.register(state.timer, first_interval=_INTERVAL)
    except BaseException:
        stop()
        raise
    return state.info()


def stop():
    """Stop before file load, addon teardown or reload. Existing connections are closed."""
    global _server
    _main_thread()
    state, _server = _server, None
    if state is not None:
        state.close()


def pump():
    """Execute at most one queued command, on the main thread, for background test harnesses."""
    _main_thread()
    if _server is not None:
        _server.pump()
