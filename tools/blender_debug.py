# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Explicit Blender startup helper and one-shot external Python client; --help for usage."""

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import socket
import sys
import tempfile
import time


def load_server():
    """Load this checkout's tooling into an installed addon, without restaging its engine."""
    import sculptcore_addon as addon
    name = "sculptcore_addon.debug_server"
    previous = sys.modules.get(name)
    if previous is not None:
        previous.stop()
    path = Path(__file__).resolve().parents[1] / "sculptcore_addon" / "debug_server.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    addon.debug_server = module
    # Older staged addon versions have no unregister hook for the new module.
    if not getattr(addon.unregister, "_sculptcore_debug_cleanup", False):
        original = addon.unregister

        def unregister():
            addon.debug_server.stop()
            return original()

        unregister._sculptcore_debug_cleanup = True
        addon.unregister = unregister
    return module


def request(connection, op, code="", timeout=35.0):
    """Send exactly once. Transport failures and unknown completion must never be blindly retried."""
    if connection["host"] != "127.0.0.1":
        raise ValueError("Only IPv4 loopback connections are supported")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    payload = json.dumps({"token": connection["token"], "op": op, "code": code}).encode() + b"\n"
    if len(payload) > 256 * 1024:
        raise ValueError("Request exceeds 256 KiB")
    deadline = time.monotonic() + timeout
    with socket.create_connection((connection["host"], connection["port"]), timeout=timeout) as client:
        client.sendall(payload)
        data = bytearray()
        while b"\n" not in data:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Reply deadline exceeded; command may have executed")
            client.settimeout(remaining)
            chunk = client.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed the connection; command may have executed")
            data.extend(chunk)
            if len(data) > 512 * 1024:
                raise ValueError("Reply exceeds 512 KiB; command may have executed")
    return json.loads(data.decode())


def publish_connection(path, connection):
    """Publish only complete credentials; the explicit output file is managed by the caller."""
    path = Path(path).resolve()
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(connection, stream)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    in_blender = "bpy" in sys.modules
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection-file", required=True, type=Path)
    if in_blender:
        parser.add_argument("--port", type=int, default=0)
        parser.add_argument("--background-seconds", type=float,
                            help="Explicit pump duration for background Blender; otherwise use headed timers")
        args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
        import bpy
        if bpy.app.background and (args.background_seconds is None or not math.isfinite(args.background_seconds)
                                   or args.background_seconds <= 0):
            parser.error("Background Blender requires a finite positive --background-seconds")
        server = load_server()
        connection = server.start(args.port)
        try:
            publish_connection(args.connection_file, connection)
            print("SculptCore debug server: {}:{}; credentials in {}".format(
                connection["host"], connection["port"], args.connection_file), flush=True)
            if bpy.app.background:
                deadline = time.monotonic() + args.background_seconds
                while time.monotonic() < deadline and server._server is not None:
                    server.pump()
                    time.sleep(0.01)
                server.stop()
        except BaseException:
            server.stop()
            raise
    else:
        operations = parser.add_mutually_exclusive_group(required=True)
        operations.add_argument("--ping", action="store_true")
        operations.add_argument("--eval", dest="expression")
        operations.add_argument("--exec", dest="statements")
        operations.add_argument("--file", type=Path, help="Execute a UTF-8 Python file")
        parser.add_argument("--timeout", type=float, default=35.0)
        args = parser.parse_args()
        op, code = "ping", ""
        if args.expression is not None:
            op, code = "eval", args.expression
        elif args.statements is not None or args.file is not None:
            op, code = "exec", args.file.read_text(encoding="utf-8") if args.file else args.statements
        try:
            reply = request(json.loads(args.connection_file.read_text(encoding="utf-8")), op, code, args.timeout)
        except (OSError, ValueError, KeyError) as error:
            parser.exit(2, "{}; no retry performed (execution may have completed).\n".format(error))
        print(json.dumps(reply, indent=2))
        return 0 if reply["ok"] else 1
    return 0


if __name__ == "__main__":
    result = main()
    if "bpy" not in sys.modules:
        sys.exit(result)
