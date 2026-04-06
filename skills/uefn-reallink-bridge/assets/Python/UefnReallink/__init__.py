"""
UefnReallink — UEFN Editor Python Bridge
=========================================
Exposes a single atomic capability: execute arbitrary Python code
on the editor's main thread via HTTP.

Auto-started by init_unreal.py on editor launch.
"""

import unreal


def register() -> None:
    """Called by init_unreal.py generic loader on editor startup."""
    unreal.log("[UefnReallink] Initializing...")
    _schedule_start()


def _schedule_start() -> None:
    """Defer server start until Slate UI is ready."""
    _state = {"ticks": 0, "done": False}

    def _on_tick(dt: float) -> None:
        if _state["done"]:
            return
        _state["ticks"] += 1
        if _state["ticks"] < 3:
            return
        _state["done"] = True
        unreal.unregister_slate_pre_tick_callback(_handle)

        try:
            from .server import start
            port = start()
            unreal.log(f"[UefnReallink] Ready on http://127.0.0.1:{port}")
        except Exception as e:
            unreal.log_error(f"[UefnReallink] Failed to start: {e}")

    _handle = unreal.register_slate_pre_tick_callback(_on_tick)
