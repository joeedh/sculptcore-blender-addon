# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Standard-library protocol/lifecycle tests, using real sockets and a fake Blender timer registry."""

import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


server = load("debug_server_test_target", ROOT / "sculptcore_addon/debug_server.py")
client = load("debug_client_test_target", ROOT / "tools/blender_debug.py")


class Timers:
    def __init__(self):
        self.functions = set()

    def register(self, fn, **_kwargs):
        self.functions.add(fn)

    def unregister(self, fn):
        self.functions.remove(fn)

    def is_registered(self, fn):
        return fn in self.functions


class DebugTests(unittest.TestCase):
    def setUp(self):
        self.bpy = SimpleNamespace(app=SimpleNamespace(timers=Timers(), handlers=SimpleNamespace(load_pre=[])))
        sys.modules["bpy"] = self.bpy
        server._JOB_TIMEOUT = 1.0
        server._READ_TIMEOUT = 0.3
        self.info = server.start()

    def tearDown(self):
        server.stop()
        self.assertFalse(self.bpy.app.timers.functions)
        self.assertFalse(self.bpy.app.handlers.load_pre)

    def async_call(self, fn):
        result = []

        def run():
            try:
                result.append(fn())
            except BaseException as error:
                result.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        return thread, result

    def finish(self, call, pump=True):
        thread, result = call
        deadline = time.monotonic() + 4
        while thread.is_alive() and time.monotonic() < deadline:
            if pump:
                server.pump()
            thread.join(0.005)
        self.assertFalse(thread.is_alive(), "client did not finish")
        if isinstance(result[0], BaseException):
            raise result[0]
        return result[0]

    def command(self, op, code="", info=None):
        return self.finish(self.async_call(lambda: client.request(info or self.info, op, code, timeout=3)))

    def wait_queued(self):
        deadline = time.monotonic() + 2
        while server._server.jobs.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(server._server.jobs.empty())

    def raw(self, payload):
        with socket.create_connection((self.info["host"], self.info["port"]), timeout=2) as connection:
            connection.sendall(payload)
            with connection.makefile("rb") as stream:
                return json.loads(stream.readline())

    def test_eval_exec_namespace_streams_main_thread(self):
        reply = self.command("exec", "import threading, sys\nx = 41\nprint('out')\nprint('err', file=sys.stderr)")
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["stdout"], "out\n")
        self.assertEqual(reply["stderr"], "err\n")
        self.assertEqual(self.command("eval", "x + 1")["result"], "42")
        reply = self.command("eval", "threading.current_thread() is threading.main_thread()")
        self.assertEqual(reply["result"], "True")

    def test_auth_validation(self):
        wrong = dict(self.info, token="bad")
        self.assertEqual(self.command("exec", "bad = True", wrong)["status"], "unauthorized")
        self.assertEqual(self.command("eval", "'bad' in globals()")["result"], "False")
        for payload in (b"[]\n", b"not json\n", b"\xff\n", b"{\n", b"x" * (server._MAX_REQUEST + 1)):
            self.assertEqual(self.raw(payload)["status"], "invalid")
        self.assertEqual(self.command("other")["status"], "invalid")

    def test_exceptions_do_not_break_timer_or_output(self):
        for code in ("raise SystemExit(2)", "raise ValueError('oops')"):
            self.assertEqual(self.command("exec", code)["status"], "exception")
        self.command("exec", "class Bad:\n    def __repr__(self): raise RuntimeError('repr broke')")
        self.assertEqual(self.command("eval", "Bad()")["status"], "exception")
        self.assertEqual(self.command("ping")["result"], "pong")

    def test_output_bounds(self):
        reply = self.command("exec", "print('x' * 1000000)")
        self.assertTrue(reply["output_truncated"])
        self.assertLessEqual(len(reply["stdout"]), server._MAX_TEXT)
        reply = self.command("eval", "'x' * 1000000")
        self.assertTrue(reply["result_truncated"])
        reply = self.command("exec", "raise ValueError('x' * 1000000)")
        self.assertLessEqual(len(reply["error"]), server._MAX_TEXT)
        reply = self.command("eval", "'😀' * 100000")
        self.assertLessEqual(len(json.dumps(reply).encode()), server._MAX_RESPONSE)

    def test_queued_timeout_never_executes(self):
        server._JOB_TIMEOUT = 0.05
        call = self.async_call(lambda: client.request(self.info, "exec", "late_mutation = True"))
        self.wait_queued()
        reply = self.finish(call, pump=False)
        self.assertEqual(reply["status"], "cancelled")
        server.pump()
        self.assertNotIn("late_mutation", server._server.namespace)

    def test_running_timeout_reports_unknown_and_finishes_once(self):
        server._JOB_TIMEOUT = 0.05
        call = self.async_call(lambda: client.request(self.info, "exec", "import time\ntime.sleep(.15)\ncount = 1"))
        self.wait_queued()
        server.pump()
        self.assertEqual(self.finish(call)["status"], "unknown")
        self.assertEqual(server._server.namespace["count"], 1)

    def test_atomic_job_transitions(self):
        job = server._Job({})
        self.assertEqual(job.expire()["status"], "cancelled")
        self.assertEqual(job.status, 'CANCELLED')
        running = server._Job({})
        with running.lock:
            running.status = 'RUNNING'
        self.assertEqual(running.expire()["status"], "unknown")
        self.assertEqual(running.status, 'RUNNING')

    def test_restart_bind_failure_and_stale_credentials(self):
        self.assertEqual(server.start(), self.info)
        server.stop()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            with self.assertRaises(OSError):
                server.start(occupied.getsockname()[1])
        self.assertIsNone(server._server)
        old = self.info
        self.info = server.start()
        self.assertNotEqual(old["token"], self.info["token"])
        self.assertEqual(self.command("ping", info=dict(self.info, token=old["token"]))["status"], "unauthorized")

    def test_stop_cancels_pending_and_partial_connections(self):
        state = server._server
        partial = socket.create_connection((self.info["host"], self.info["port"]), timeout=1)
        partial.sendall(b"{")
        call = self.async_call(lambda: client.request(self.info, "exec", "late = True"))
        self.wait_queued()
        server.stop()
        call[0].join(2)
        self.assertFalse(call[0].is_alive())
        self.assertEqual(partial.recv(1), b"")
        partial.close()
        self.assertFalse(state.namespace)

    def test_absolute_read_deadline_and_connection_cap(self):
        sockets = []
        try:
            for _ in range(server._MAX_CONNECTIONS):
                sock = socket.create_connection((self.info["host"], self.info["port"]), timeout=1)
                sock.sendall(b"{")
                sockets.append(sock)
            time.sleep(0.05)
            extra = socket.create_connection((self.info["host"], self.info["port"]), timeout=1)
            self.assertEqual(extra.recv(1), b"")
            extra.close()
            time.sleep(0.1)
            sockets[0].sendall(b" ")
            time.sleep(0.2)
            self.assertEqual(sockets[0].recv(1), b"")
        finally:
            for sock in sockets:
                sock.close()

    def test_load_handler_and_reload(self):
        state = server._server
        self.bpy.app.handlers.load_pre[0](None)
        self.assertIsNone(server._server)
        self.assertFalse(state.namespace)
        self.info = server.start()
        state = server._server
        server.__spec__.loader.exec_module(server)
        self.assertIsNone(server._server)
        self.assertTrue(state.stopped)

    def test_main_thread_and_reentrancy_guards(self):
        for fn in (server.start, server.stop, server.pump):
            call = self.async_call(fn)
            call[0].join(1)
            self.assertIsInstance(call[1][0], RuntimeError)
        server._server.namespace["server"] = server
        self.assertEqual(self.command("exec", "server.pump()")["status"], "exception")
        self.assertEqual(self.command("ping")["result"], "pong")


if __name__ == "__main__":
    unittest.main()
