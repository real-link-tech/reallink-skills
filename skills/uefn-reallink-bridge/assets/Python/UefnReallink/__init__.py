"""
UefnReallink — UEFN Editor Python Bridge
=========================================
Exposes a single atomic capability: execute arbitrary Python code
on the editor's main thread via HTTP.

Auto-started by init_unreal.py on editor launch.
Also serves as the package root for the standalone Reallink UEFN Editor GUI.
"""

try:
    import unreal as _unreal
    _HAS_UNREAL = True
except ImportError:
    _HAS_UNREAL = False


def register() -> None:
    """Called by init_unreal.py generic loader on editor startup."""
    if not _HAS_UNREAL:
        return
    _unreal.log("[UefnReallink] Initializing...")
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
        _unreal.unregister_slate_pre_tick_callback(_handle)

        try:
            from .server import start
            port = start()
            _unreal.log(f"[UefnReallink] Ready on http://127.0.0.1:{port}")
        except Exception as e:
            _unreal.log_error(f"[UefnReallink] Failed to start: {e}")

        _inject_toolbar_button()

    _handle = _unreal.register_slate_pre_tick_callback(_on_tick)


# ─── Viewport Toolbar Button ─────────────────────────────────────────────────

# 这段代码在编辑器进程内执行，自动找到内嵌 Python 和包路径
_LAUNCH_EDITOR_CMD = """
import sys, os, subprocess
prefix = os.path.normpath(os.path.join(os.path.dirname(sys.executable), sys.prefix))
py_exe = os.path.join(prefix, 'python.exe')
pkg_dir = os.path.dirname(os.path.abspath(__import__('UefnReallink').__file__))
python_dir = os.path.dirname(pkg_dir)
subprocess.Popen(
    [py_exe, '-m', 'UefnReallink.reallink_uefn_editor'],
    cwd=python_dir,
    creationflags=0x08000000,
)
"""


def _inject_toolbar_button() -> None:
    """Inject a 'Reallink' button into LevelEditor.ViewportToolBar."""
    try:
        menus = _unreal.ToolMenus.get()
        toolbar = menus.find_menu("LevelEditor.ViewportToolBar")
        if not toolbar:
            _unreal.log_warning(
                "[UefnReallink] ViewportToolBar not found, skip button")
            return

        entry = _unreal.ToolMenuEntry(
            name="ReallinkEditor",
            type=_unreal.MultiBlockType.TOOL_BAR_BUTTON,
            insert_position=_unreal.ToolMenuInsert(
                "", _unreal.ToolMenuInsertType.DEFAULT),
        )
        entry.set_label(_unreal.Text("Reallink"))
        entry.set_tool_tip(_unreal.Text("Open Reallink UEFN Editor"))
        entry.set_string_command(
            type=_unreal.ToolMenuStringCommandType.PYTHON,
            custom_type=_unreal.Name(""),
            string=_LAUNCH_EDITOR_CMD,
        )

        toolbar.add_menu_entry("", entry)
        menus.refresh_all_widgets()
        _unreal.log("[UefnReallink] Toolbar button 'Reallink' injected")

    except Exception as e:
        _unreal.log_warning(f"[UefnReallink] Toolbar inject failed: {e}")
