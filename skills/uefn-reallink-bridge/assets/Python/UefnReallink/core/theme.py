"""core/theme.py — UI Theme system with Dark/Light presets."""

from __future__ import annotations

from dataclasses import dataclass, field


def _pick_mono_font() -> str:
    """Pick the best available monospace font (called lazily after tk root exists)."""
    try:
        import tkinter.font as tkfont
        families = set(tkfont.families())
        for candidate in ("Cascadia Mono", "Cascadia Code", "Consolas"):
            if candidate in families:
                return candidate
    except Exception:
        pass
    return "Consolas"


_mono_cache: str = ""


def _get_mono() -> str:
    global _mono_cache
    if not _mono_cache:
        _mono_cache = _pick_mono_font()
    return _mono_cache


@dataclass(frozen=True)
class Theme:
    # ── Backgrounds ──────────────────────────────────────────────────────────
    bg_primary: str = ""
    bg_secondary: str = ""
    bg_tertiary: str = ""
    bg_input: str = ""
    bg_tooltip: str = ""

    # ── Foregrounds ──────────────────────────────────────────────────────────
    fg_primary: str = ""
    fg_secondary: str = ""
    fg_muted: str = ""
    fg_bright: str = ""

    # ── Controls ─────────────────────────────────────────────────────────────
    ctrl_bg: str = ""
    ctrl_hover: str = ""
    ctrl_border: str = ""
    ctrl_scrollbar: str = ""
    ctrl_scrollbar_active: str = ""
    accent: str = ""

    # ── Action buttons ───────────────────────────────────────────────────────
    action_blue_bg: str = ""
    action_blue_fg: str = ""
    action_gold_bg: str = ""
    action_gold_fg: str = ""

    # ── Status ───────────────────────────────────────────────────────────────
    status_ok: str = ""
    status_error: str = ""
    status_warn: str = ""
    status_info: str = ""
    status_connected: str = ""
    status_disconnected: str = ""
    status_streaming: str = ""

    # ── Canvas / Map ─────────────────────────────────────────────────────────
    canvas_bg: str = ""
    grid_line: str = ""
    cell_selected_fill: str = ""
    cell_selected_outline: str = ""
    cell_text: str = ""
    overlay_capture: str = ""
    overlay_capture_outline: str = ""
    overlay_camera_fill: str = ""
    overlay_camera_outline: str = ""
    overlay_range: str = ""
    drag_rect: str = ""

    # ── Fonts ────────────────────────────────────────────────────────────────
    font_family: str = "Segoe UI"
    font_xs: int = 7
    font_sm: int = 8
    font_md: int = 9
    font_lg: int = 10
    font_xl: int = 11

    def font(self, size: str = "md", bold: bool = False,
             mono: bool = False) -> tuple:
        """Return a tk font tuple.  size: 'xs', 'sm', 'md', 'lg', 'xl'."""
        family = _get_mono() if mono else self.font_family
        sz = getattr(self, f"font_{size}", self.font_md)
        if bold:
            return (family, sz, "bold")
        return (family, sz)


# ─── Presets ──────────────────────────────────────────────────────────────────

DARK = Theme(
    bg_primary="#1e1e1e",
    bg_secondary="#2b2b2b",
    bg_tertiary="#333333",
    bg_input="#1a1a1a",
    bg_tooltip="#444444",

    fg_primary="#d4d4d4",
    fg_secondary="#aaaaaa",
    fg_muted="#555555",
    fg_bright="#ffffff",

    ctrl_bg="#3c3c3c",
    ctrl_hover="#505050",
    ctrl_border="#444444",
    ctrl_scrollbar="#444444",
    ctrl_scrollbar_active="#555555",
    accent="#264f78",

    action_blue_bg="#1c3a4a",
    action_blue_fg="#66ccff",
    action_gold_bg="#4a3c1c",
    action_gold_fg="#ffd966",

    status_ok="#66cc66",
    status_error="#e05252",
    status_warn="#ffd966",
    status_info="#66ccff",
    status_connected="#4ec94e",
    status_disconnected="#e05252",
    status_streaming="#8bc34a",

    canvas_bg="#1e1e1e",
    grid_line="#444444",
    cell_selected_fill="#3a5f8a",
    cell_selected_outline="#4fc3f7",
    cell_text="#cccccc",
    overlay_capture="#ff4444",
    overlay_capture_outline="#ff6666",
    overlay_camera_fill="#dddddd",
    overlay_camera_outline="#ffffff",
    overlay_range="#ff4444",
    drag_rect="#ffffff",
)

LIGHT = Theme(
    bg_primary="#ffffff",
    bg_secondary="#f3f3f3",
    bg_tertiary="#e0e0e0",
    bg_input="#ffffff",
    bg_tooltip="#f5f5f5",

    fg_primary="#1e1e1e",
    fg_secondary="#555555",
    fg_muted="#999999",
    fg_bright="#000000",

    ctrl_bg="#d4d4d4",
    ctrl_hover="#c0c0c0",
    ctrl_border="#bbbbbb",
    ctrl_scrollbar="#cccccc",
    ctrl_scrollbar_active="#aaaaaa",
    accent="#0078d4",

    action_blue_bg="#d0e8f8",
    action_blue_fg="#0060b0",
    action_gold_bg="#fff3d0",
    action_gold_fg="#8a6d00",

    status_ok="#2e8b2e",
    status_error="#cc3333",
    status_warn="#b8860b",
    status_info="#0078d4",
    status_connected="#2e8b2e",
    status_disconnected="#cc3333",
    status_streaming="#558b2f",

    canvas_bg="#f8f8f8",
    grid_line="#cccccc",
    cell_selected_fill="#b0d4f1",
    cell_selected_outline="#0078d4",
    cell_text="#333333",
    overlay_capture="#e03030",
    overlay_capture_outline="#ff5050",
    overlay_camera_fill="#333333",
    overlay_camera_outline="#000000",
    overlay_range="#e03030",
    drag_rect="#000000",
)

# ─── Global active theme ─────────────────────────────────────────────────────

theme: Theme = DARK


def set_theme(name: str) -> None:
    """Switch the global theme. name: 'dark' or 'light'."""
    global theme
    theme = {"dark": DARK, "light": LIGHT}[name.lower()]
