"""
UefnReallink — server.py
=========================
HTTP server running inside the UEFN editor process.
Exposes a single atomic capability: execute arbitrary Python on the main thread.

Architecture:
    HTTP daemon thread  -->  queue.Queue  -->  Slate post-tick (main thread)
                                                  exec(code, globals)
                                               <--  result / error JSON

All unreal.* calls must happen on the editor main thread. The HTTP server
runs on a daemon thread; requests are queued and drained every editor tick
via register_slate_post_tick_callback.

Threading model validated by Kirch's uefn_listener.py and UEFN-TOOLBELT mcp_bridge.py.
"""

from __future__ import annotations

import io
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

import unreal

# ─── Config ───────────────────────────────────────────────────────────────────

DEFAULT_PORT     = int(os.environ.get("UEFN_PORT", "19877"))
TICK_BATCH_LIMIT = 5
TIMEOUT_SEC      = 30.0
POLL_SEC         = 0.02
STALE_SEC        = 60.0
CREATE_NO_WINDOW = 0x08000000

# ─── State ────────────────────────────────────────────────────────────────────

_server:        Optional[HTTPServer]       = None
_server_thread: Optional[threading.Thread] = None
_tick_handle:   Optional[object]           = None
_bound_port:    int   = 0
_start_time:    float = 0.0
_req_counter:   int   = 0

_queue     = queue.Queue()
_responses: Dict[str, dict] = {}
_resp_lock = threading.Lock()

# ─── Serialization ────────────────────────────────────────────────────────────

def _serialize(obj: Any) -> Any:
    """Recursively convert unreal types to JSON-serializable Python types."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if isinstance(obj, unreal.Vector):
        return {"x": obj.x, "y": obj.y, "z": obj.z}
    if isinstance(obj, unreal.Rotator):
        return {"pitch": obj.pitch, "yaw": obj.yaw, "roll": obj.roll}
    if isinstance(obj, unreal.Vector2D):
        return {"x": obj.x, "y": obj.y}
    if isinstance(obj, unreal.LinearColor):
        return {"r": obj.r, "g": obj.g, "b": obj.b, "a": obj.a}
    if isinstance(obj, unreal.Color):
        return {"r": obj.r, "g": obj.g, "b": obj.b, "a": obj.a}
    if isinstance(obj, unreal.Transform):
        return {
            "location": _serialize(obj.translation),
            "rotation": _serialize(obj.rotation.rotator()),
            "scale":    _serialize(obj.scale3d),
        }
    if hasattr(obj, "get_path_name"):
        return str(obj.get_path_name())
    if hasattr(obj, "get_name"):
        return str(obj.get_name())
    try:
        return str(obj)
    except Exception:
        return repr(obj)


# ─── Execution ────────────────────────────────────────────────────────────────

def _execute(code: str) -> dict:
    """Execute Python code on the main thread. Return result dict."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr

    globs: Dict[str, Any] = {
        "__builtins__": __builtins__,
        "unreal": unreal,
        "result": None,
    }
    for attr, cls_name in [
        ("actor_sub",  "EditorActorSubsystem"),
        ("asset_sub",  "EditorAssetSubsystem"),
        ("level_sub",  "LevelEditorSubsystem"),
    ]:
        try:
            globs[attr] = unreal.get_editor_subsystem(getattr(unreal, cls_name))
        except Exception:
            pass

    try:
        sys.stdout, sys.stderr = stdout_buf, stderr_buf
        exec(code, globs)
        return {
            "success": True,
            "result":  _serialize(globs.get("result")),
            "stdout":  stdout_buf.getvalue(),
            "stderr":  stderr_buf.getvalue(),
        }
    except Exception as e:
        traceback.print_exc(file=stderr_buf)
        return {
            "success": False,
            "error":   f"{type(e).__name__}: {e}",
            "stdout":  stdout_buf.getvalue(),
            "stderr":  stderr_buf.getvalue(),
        }
    finally:
        sys.stdout, sys.stderr = old_out, old_err


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):

    def do_GET(self) -> None:
        body = json.dumps({
            "status":  "ok",
            "app":     "UefnReallink",
            "python":  sys.version,
            "port":    _bound_port,
            "uptime":  round(time.time() - _start_time, 1) if _start_time else 0,
        }).encode()
        self._respond(200, body)

    def do_POST(self) -> None:
        global _req_counter
        length = int(self.headers.get("Content-Length", 0))
        code = self.rfile.read(length).decode("utf-8")

        if not code.strip():
            self._respond(400, json.dumps({
                "success": False, "error": "Empty code body",
            }).encode())
            return

        _req_counter += 1
        req_id = f"r_{_req_counter}_{time.time_ns()}"
        _queue.put((req_id, code))

        deadline = time.time() + TIMEOUT_SEC
        while time.time() < deadline:
            with _resp_lock:
                if req_id in _responses:
                    result = _responses.pop(req_id)
                    break
            time.sleep(POLL_SEC)
        else:
            self._respond(504, json.dumps({
                "success": False, "error": "Timeout waiting for main thread execution",
            }).encode())
            return

        self._respond(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "127.0.0.1")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        pass


# ─── Tick (main thread) ──────────────────────────────────────────────────────

def _tick(dt: float) -> None:
    """Drain the queue on the main thread — unreal.* calls are safe here."""
    processed = 0
    while not _queue.empty() and processed < TICK_BATCH_LIMIT:
        try:
            req_id, code = _queue.get_nowait()
        except queue.Empty:
            break
        response = _execute(code)
        with _resp_lock:
            _responses[req_id] = response
        processed += 1

    now = time.time()
    with _resp_lock:
        stale = [k for k in _responses
                 if float(k.split("_")[2]) / 1e9 < now - STALE_SEC]
        for k in stale:
            del _responses[k]


# ─── Lifecycle ────────────────────────────────────────────────────────────────

def _pid_listening_on_port(port: int) -> list[int]:
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            creationflags=CREATE_NO_WINDOW,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as e:
        unreal.log_warning(f"[UefnReallink] netstat failed: {e}")
        return []

    pids: list[int] = []
    token = f"127.0.0.1:{port}"
    for line in out.splitlines():
        line = line.strip()
        if token not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[-1])
        except Exception:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def _kill_process(pid: int) -> bool:
    try:
        current_pid = os.getpid()
    except Exception:
        current_pid = -1
    if pid <= 0 or pid == current_pid:
        return False
    try:
        subprocess.check_call(
            ["taskkill", "/PID", str(pid), "/F"],
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        unreal.log_warning(f"[UefnReallink] Killed process using port: PID {pid}")
        return True
    except Exception as e:
        unreal.log_warning(f"[UefnReallink] Failed to kill PID {pid}: {e}")
        return False


def _ensure_port_available(port: int) -> int:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.close()
        return port
    except OSError:
        pids = _pid_listening_on_port(port)
        if not pids:
            raise RuntimeError(f"Port {port} is unavailable and owner PID could not be found")
        for pid in pids:
            _kill_process(pid)
        time.sleep(0.5)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return port
        finally:
            s.close()


def start(port: int = 0) -> int:
    """Start the HTTP listener. Returns the bound port."""
    global _server, _server_thread, _tick_handle, _bound_port, _start_time

    if _server is not None:
        unreal.log(f"[UefnReallink] Already running on port {_bound_port}")
        return _bound_port

    if port == 0:
        port = DEFAULT_PORT

    port = _ensure_port_available(port)

    _server = HTTPServer(("127.0.0.1", port), _Handler)
    _bound_port = port
    _start_time = time.time()

    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()

    try:
        _tick_handle = unreal.register_slate_post_tick_callback(_tick)
    except Exception as e:
        unreal.log_warning(f"[UefnReallink] Tick callback failed: {e}")

    unreal.log(f"[UefnReallink] Listening on http://127.0.0.1:{port}")
    return port


def stop() -> None:
    """Stop the HTTP listener."""
    global _server, _server_thread, _tick_handle, _bound_port

    if _server is None:
        return

    if _tick_handle is not None:
        unreal.unregister_slate_post_tick_callback(_tick_handle)
        _tick_handle = None

    _server.shutdown()
    if _server_thread:
        _server_thread.join(timeout=3.0)

    old = _bound_port
    _server = None
    _server_thread = None
    _bound_port = 0
    unreal.log(f"[UefnReallink] Stopped (was port {old})")


def get_port() -> int:
    return _bound_port
