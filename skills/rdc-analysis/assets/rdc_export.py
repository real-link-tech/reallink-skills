# -*- coding: utf-8 -*-

#!/usr/bin/env python3
"""
RenderDoc Capture Export Tool
=============================
Exports all core data from a RenderDoc capture (.rdc) file into a structured
directory with Markdown documentation, PNG images for textures/RTs, and
formatted or hex-dump data for buffers.

Usage (standalone):
    python rdc_export.py <capture.rdc>
    python rdc_export.py --renderdoc-path "D:\\path\\to\\pymodules" <capture.rdc>
    python rdc_export.py --no-skip-slateui-title <capture.rdc>
    python rdc_export.py --eid 1234 <capture.rdc>
    python rdc_export.py --eid 1000-2000 <capture.rdc>
    python rdc_export.py --eid -1 <capture.rdc>    (event_list only)
    python rdc_export.py -eid 1234 <capture.rdc>   (alias, case-insensitive)

Usage (via bat):
    rdc_export.bat <capture.rdc>      (or drag .rdc onto the bat)

Usage (inside RenderDoc UI Python console):
    exec(open('rdc_export.py').read())
"""

import sys
import os
import re
import struct
import hashlib
import shutil
import time
import json
import subprocess
import tempfile

# ---------------------------------------------------------------------------
# Import renderdoc - with auto-detection for standalone usage
# ---------------------------------------------------------------------------

def _find_renderdoc_module():
    if 'renderdoc' in sys.modules or '_renderdoc' in sys.modules:
        return True
    candidates = []
    for i, arg in enumerate(sys.argv):
        if arg == '--renderdoc-path' and i + 1 < len(sys.argv):
            candidates.append(sys.argv[i + 1])
            candidates.append(os.path.join(sys.argv[i + 1], 'pymodules'))
    env_path = os.environ.get('RENDERDOC_PATH', '')
    if env_path:
        candidates.append(env_path)
        candidates.append(os.path.join(env_path, 'pymodules'))
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_root = os.path.dirname(script_dir)
    for config in ['Development', 'Release', 'Debug', 'RelWithDebInfo']:
        candidates.append(os.path.join(source_root, 'x64', config, 'pymodules'))
    for base in [
        os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), 'RenderDoc'),
        os.path.join(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'), 'RenderDoc'),
        'D:\\Program Files\\RenderDoc',
    ]:
        candidates.append(base)
        candidates.append(os.path.join(base, 'pymodules'))
    for cand in candidates:
        cand = os.path.abspath(cand)
        if os.path.isfile(os.path.join(cand, 'renderdoc.pyd')) or \
           os.path.isfile(os.path.join(cand, 'renderdoc.so')):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            if sys.platform == 'win32':
                for dll_dir in [cand, os.path.dirname(cand)]:
                    if os.path.isfile(os.path.join(dll_dir, 'renderdoc.dll')):
                        os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
                        if sys.version_info >= (3, 8):
                            os.add_dll_directory(dll_dir)
                        break
            return True
    return False


def _import_renderdoc():
    if 'renderdoc' in sys.modules or '_renderdoc' in sys.modules:
        return
    if not _find_renderdoc_module():
        print("=" * 72)
        print("ERROR: Cannot find the renderdoc Python module (renderdoc.pyd).")
        print()
        print("Build it from source (pyrenderdoc_module project) or use")
        print("  --renderdoc-path <dir>  /  set RENDERDOC_PATH=<dir>")
        print("=" * 72)
        sys.exit(1)
    import renderdoc  # noqa


if 'pyrenderdoc' not in globals():
    _import_renderdoc()

import renderdoc  # noqa
rd = renderdoc

def _get_process_working_set_bytes(pid=None):
    if sys.platform != "win32":
        return 0
    try:
        import ctypes

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess
        OpenProcess = ctypes.windll.kernel32.OpenProcess
        CloseHandle = ctypes.windll.kernel32.CloseHandle
        GetProcessMemoryInfo = ctypes.windll.psapi.GetProcessMemoryInfo
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
        handle = GetCurrentProcess() if pid is None else OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
        if not handle:
            return 0
        ok = GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if pid is not None:
            CloseHandle(handle)
        if ok:
            return int(counters.WorkingSetSize)
    except Exception:
        pass
    return 0


# ===========================================================================
# Version check utilities
# ===========================================================================

def _compute_script_sha1():
    """Compute SHA1 hash of this script file's contents."""
    script_path = os.path.abspath(__file__)
    with open(script_path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


def _check_version(output_dir, current_sha1, config_sig=None):
    """Return True if export can be skipped (version match).
    If directory exists but has no version.md, treat as mismatch."""
    ver_file = os.path.join(output_dir, 'version.md')
    if not os.path.isdir(output_dir):
        return False
    if not os.path.isfile(ver_file):
        return False  # directory exists but no version.md -> mismatch
    existing_sha1 = None
    existing_cfg = None
    try:
        with open(ver_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('script_sha1:'):
                    existing_sha1 = line.split(':', 1)[1].strip()
                elif line.startswith('config_sig:'):
                    existing_cfg = line.split(':', 1)[1].strip()
    except Exception:
        return False

    if existing_sha1 != current_sha1:
        return False

    if config_sig is None:
        return True

    return existing_cfg == str(config_sig)


def _write_version(output_dir, current_sha1, config_sig=None):
    """Write version.md with current script SHA1."""
    with open(os.path.join(output_dir, 'version.md'), 'w', encoding='utf-8') as f:
        f.write("# Export Version\n\n")
        f.write("script_sha1: %s\n" % current_sha1)
        if config_sig is not None:
            f.write("config_sig: %s\n" % str(config_sig))


def _cleanup_output_dir(output_dir):
    """Strict cleanup for version mismatch exports.
    On Windows files may be temporarily locked (WinError 32), so we retry.
    If full cleanup still fails, raise and abort export."""
    if not os.path.isdir(output_dir):
        return True

    last_error = None
    for attempt in range(5):
        try:
            shutil.rmtree(output_dir)
            return True
        except Exception as e:
            last_error = e
            print("[rdc_export] Cleanup retry %d/5 failed: %s" % (attempt + 1, e))
            time.sleep(0.5 * (attempt + 1))

    raise RuntimeError(
        "Failed to fully remove old output directory: %s\n"
        "Directory: %s\n"
        "Possible cause: files are locked by another process.\n"
        "Please close programs/processes that may be using this folder (e.g. explorer preview, editors, antivirus scan), then run again." %
        (last_error, output_dir)
    )


# ===========================================================================
# Helper utilities
# ===========================================================================

def rid_str(resource_id):
    if resource_id == rd.ResourceId.Null():
        return "null"
    return str(int(resource_id))


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f ]', '_', name)
    name = name.strip('. ')
    return name if name else '_'


def get_action_type_str(flags):
    if flags & rd.ActionFlags.Drawcall:   return "**Drawcall**"
    if flags & rd.ActionFlags.Dispatch:   return "**Dispatch**"
    if flags & rd.ActionFlags.Clear:      return "Clear"
    if flags & rd.ActionFlags.Copy:       return "Copy"
    if flags & rd.ActionFlags.Resolve:    return "Resolve"
    if flags & rd.ActionFlags.Present:    return "Present"
    if flags & rd.ActionFlags.GenMips:    return "GenMips"
    if flags & rd.ActionFlags.PassBoundary: return "PassBoundary"
    if flags & (rd.ActionFlags.PushMarker | rd.ActionFlags.PopMarker | rd.ActionFlags.SetMarker):
        return "Marker"
    return ""


def get_action_details(action):
    parts = []
    if action.flags & rd.ActionFlags.Drawcall:
        if action.numIndices > 0:    parts.append("indices=%d" % action.numIndices)
        if action.numInstances > 0:  parts.append("instances=%d" % action.numInstances)
    if action.flags & rd.ActionFlags.Dispatch:
        d = action.dispatchDimension
        parts.append("groups=%dx%dx%d" % (d[0], d[1], d[2]))
    return " ".join(parts)


SHADER_STAGES = [
    (rd.ShaderStage.Vertex,   "VS", "Vertex Shader"),
    (rd.ShaderStage.Hull,     "HS", "Hull Shader"),
    (rd.ShaderStage.Domain,   "DS", "Domain Shader"),
    (rd.ShaderStage.Geometry, "GS", "Geometry Shader"),
    (rd.ShaderStage.Pixel,    "PS", "Pixel Shader"),
    (rd.ShaderStage.Compute,  "CS", "Compute Shader"),
]
STAGE_ABBREV = {s: a for s, a, _ in SHADER_STAGES}
STAGE_NAME   = {s: n for s, _, n in SHADER_STAGES}

# ResourceUsage -> human-readable short name
_USAGE_NAMES = {}
def _init_usage_names():
    pairs = [
        ("VertexBuffer", "VB"), ("IndexBuffer", "IB"), ("StreamOut", "SO"),
        ("VS_Constants", "VS_CB"), ("HS_Constants", "HS_CB"), ("DS_Constants", "DS_CB"),
        ("GS_Constants", "GS_CB"), ("PS_Constants", "PS_CB"), ("CS_Constants", "CS_CB"),
        ("VS_Resource", "VS_SRV"), ("HS_Resource", "HS_SRV"), ("DS_Resource", "DS_SRV"),
        ("GS_Resource", "GS_SRV"), ("PS_Resource", "PS_SRV"), ("CS_Resource", "CS_SRV"),
        ("VS_RWResource", "VS_UAV"), ("HS_RWResource", "HS_UAV"), ("DS_RWResource", "DS_UAV"),
        ("GS_RWResource", "GS_UAV"), ("PS_RWResource", "PS_UAV"), ("CS_RWResource", "CS_UAV"),
        ("ColorTarget", "RT"), ("DepthStencilTarget", "DS"),
        ("Indirect", "Indirect"), ("Clear", "Clear"), ("Copy", "Copy"),
        ("CopySrc", "CopySrc"), ("CopyDst", "CopyDst"),
    ]
    for attr, short in pairs:
        if hasattr(rd.ResourceUsage, attr):
            _USAGE_NAMES[getattr(rd.ResourceUsage, attr)] = short
_init_usage_names()

# Usage categories
_TEX_SRV_USAGES = set()
_TEX_UAV_USAGES = set()
_BUF_CB_USAGES  = set()
_BUF_VB_IB_USAGES = set()
_BUF_UAV_USAGES = set()
for attr in ["VS_Resource","HS_Resource","DS_Resource","GS_Resource","PS_Resource","CS_Resource"]:
    if hasattr(rd.ResourceUsage, attr): _TEX_SRV_USAGES.add(getattr(rd.ResourceUsage, attr))
for attr in ["VS_RWResource","HS_RWResource","DS_RWResource","GS_RWResource","PS_RWResource","CS_RWResource"]:
    if hasattr(rd.ResourceUsage, attr): _TEX_UAV_USAGES.add(getattr(rd.ResourceUsage, attr))
for attr in ["VS_Constants","HS_Constants","DS_Constants","GS_Constants","PS_Constants","CS_Constants"]:
    if hasattr(rd.ResourceUsage, attr): _BUF_CB_USAGES.add(getattr(rd.ResourceUsage, attr))
for attr in ["VertexBuffer","IndexBuffer"]:
    if hasattr(rd.ResourceUsage, attr): _BUF_VB_IB_USAGES.add(getattr(rd.ResourceUsage, attr))
for attr in ["VS_RWResource","HS_RWResource","DS_RWResource","GS_RWResource","PS_RWResource","CS_RWResource"]:
    if hasattr(rd.ResourceUsage, attr): _BUF_UAV_USAGES.add(getattr(rd.ResourceUsage, attr))

_ALL_TEX_USAGES = _TEX_SRV_USAGES | _TEX_UAV_USAGES
_ALL_BUF_USAGES = _BUF_CB_USAGES | _BUF_VB_IB_USAGES | _BUF_UAV_USAGES


def _enum_to_int(value, default=0):
    try:
        return int(value)
    except Exception:
        pass
    try:
        return int(value.value)
    except Exception:
        return default


def _enum_mask(enum_obj, names):
    mask = 0
    for name in names:
        if hasattr(enum_obj, name):
            mask |= _enum_to_int(getattr(enum_obj, name), 0)
    return mask


def _env_flag(name, default=True):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in ("0", "false", "off", "no", "")


def _parse_eid_filter_spec(raw):
    """Parse --eid / RDC_EXPORT_EID spec.

    Supported:
      - "-1"      : event_list only mode
      - "123"     : single event id
      - "100-200" : inclusive range
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    if text == "-1":
        return {
            "raw": text,
            "event_list_only": True,
            "min_eid": None,
            "max_eid": None,
        }

    m = re.match(r"^(\d+)$", text)
    if m:
        v = int(m.group(1))
        return {
            "raw": text,
            "event_list_only": False,
            "min_eid": v,
            "max_eid": v,
        }

    m = re.match(r"^(\d+)\s*-\s*(\d+)$", text)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        lo = min(a, b)
        hi = max(a, b)
        return {
            "raw": text,
            "event_list_only": False,
            "min_eid": lo,
            "max_eid": hi,
        }

    raise ValueError(
        "Invalid EID filter '%s'. Use -1, <eid>, or <start>-<end>." % text)


def _on_off(enabled):
    return "ON" if bool(enabled) else "OFF"


def _describe_eid_filter(eid_filter):
    if not eid_filter:
        return "OFF"
    if eid_filter.get("event_list_only"):
        return "ON (event_list_only: -1)"
    lo = eid_filter.get("min_eid")
    hi = eid_filter.get("max_eid")
    if lo is not None and hi is not None and lo == hi:
        return "ON (single: %d)" % lo
    if lo is not None and hi is not None:
        return "ON (range: %d-%d)" % (lo, hi)
    return "ON (custom)"


def _print_cli_branch_status(worker_mode, renderdoc_path_arg, skip_slateui_title_arg, eid_filter_arg, capture_arg):
    print("[rdc_export] Startup argument branches:")
    print("[rdc_export]   branch.worker_export: %s" % _on_off(worker_mode))
    print("[rdc_export]   branch.renderdoc_path: %s" % _on_off(bool(renderdoc_path_arg)))
    if renderdoc_path_arg:
        print("[rdc_export]     value.renderdoc_path: %s" % renderdoc_path_arg)

    no_skip_branch = not bool(skip_slateui_title_arg)
    print("[rdc_export]   branch.no_skip_slateui_title: %s" % _on_off(no_skip_branch))
    print("[rdc_export]   effective.skip_slateui_title(from CLI): %s" % _on_off(skip_slateui_title_arg))

    eid_error = None
    eid_parsed = None
    try:
        eid_parsed = _parse_eid_filter_spec(eid_filter_arg)
    except Exception as e:
        eid_error = str(e)
    print("[rdc_export]   branch.eid_option: %s" % _on_off(eid_filter_arg is not None))
    print("[rdc_export]   effective.eid_filter(from CLI): %s" % _describe_eid_filter(eid_parsed))
    if eid_filter_arg is not None:
        print("[rdc_export]     value.eid_raw: %s" % str(eid_filter_arg))
    if eid_error:
        print("[rdc_export]     value.eid_parse_error: %s" % eid_error)

    print("[rdc_export]   capture_file_arg: %s" % (capture_arg if capture_arg else "<missing>"))


def _print_effective_branch_status(
    mode_name,
    output_dir,
    skip_slateui_title,
    skip_slateui_title_source,
    skip_marker_name,
    skip_marker_source,
    eid_filter_spec,
    eid_filter,
    eid_filter_source,
):
    print("[rdc_export] Effective parameter branches (%s):" % mode_name)
    print("[rdc_export]   output_dir: %s" % output_dir)
    print("[rdc_export]   branch.skip_slateui_title: %s (source=%s)" % (
        _on_off(skip_slateui_title), skip_slateui_title_source))
    print("[rdc_export]   branch.skip_marker_name: %s (source=%s)" % (
        skip_marker_name, skip_marker_source))
    print("[rdc_export]   branch.eid_filter: %s (source=%s)" % (
        _describe_eid_filter(eid_filter), eid_filter_source))
    if eid_filter_spec is not None:
        print("[rdc_export]     value.eid_raw: %s" % str(eid_filter_spec))


_TEX_USAGE_CATEGORY_MASK = _enum_mask(
    rd.TextureCategory, ["ShaderRead", "ShaderReadWrite"])
_BUF_USAGE_CATEGORY_MASK = _enum_mask(
    rd.BufferCategory, ["Vertex", "Index", "Constants", "ReadWrite"])


def hex_dump(data, base_offset=0):
    lines = []
    length = len(data)
    for offset in range(0, length, 16):
        chunk = data[offset:offset + 16]
        hex_parts = []
        for i, b in enumerate(chunk):
            hex_parts.append("%02X" % b)
            if i == 7:
                hex_parts.append("")
        hex_str = " ".join(hex_parts)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append("%08X: %-49s |%-16s|" % (base_offset + offset, hex_str, ascii_str))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Buffer structured format helpers
# ---------------------------------------------------------------------------

_VARTYPE_FMT = {}
def _init_vartype():
    mapping = [
        ("Float", "f", 4), ("Half", "e", 2), ("Double", "d", 8),
        ("SInt", "i", 4), ("UInt", "I", 4),
        ("SShort", "h", 2), ("UShort", "H", 2),
        ("SLong", "q", 8), ("ULong", "Q", 8),
        ("SByte", "b", 1), ("UByte", "B", 1),
        ("Bool", "I", 4),
    ]
    for attr, fmt, sz in mapping:
        if hasattr(rd.VarType, attr):
            _VARTYPE_FMT[getattr(rd.VarType, attr)] = (fmt, sz)
_init_vartype()


def _type_name_str(stype):
    base_names = {}
    for attr in ["Float","Half","Double","SInt","UInt","SShort","UShort",
                 "SLong","ULong","SByte","UByte","Bool"]:
        if hasattr(rd.VarType, attr):
            base_names[getattr(rd.VarType, attr)] = attr.lower()
    base = base_names.get(stype.baseType, str(stype.baseType))
    rows = stype.rows
    cols = stype.columns
    if rows > 1 and cols > 1:
        return "%s%dx%d" % (base, rows, cols)
    elif rows == 1 and cols > 1:
        return "%s%d" % (base, cols)
    elif rows > 1 and cols == 1:
        return "%s%d" % (base, rows)
    return base


def _decode_value(data, offset, stype):
    if stype.baseType not in _VARTYPE_FMT:
        return None
    fmt_char, elem_size = _VARTYPE_FMT[stype.baseType]
    rows = max(stype.rows, 1)
    cols = max(stype.columns, 1)
    total = rows * cols
    try:
        end = offset + total * elem_size
        if end > len(data):
            return None
        vals = list(struct.unpack_from("<%d%s" % (total, fmt_char), data, offset))
        if rows == 1 and cols == 1:
            return vals[0]
        if rows == 1:
            return vals
        return [vals[r*cols:(r+1)*cols] for r in range(rows)]
    except Exception:
        return None


def _format_value(val):
    if val is None:
        return "*(decode error)*"
    if isinstance(val, float):
        return "%.6g" % val
    if isinstance(val, int):
        return str(val)
    if isinstance(val, list):
        if len(val) > 0 and isinstance(val[0], list):
            row_strs = ["[%s]" % ", ".join("%.6g" % v if isinstance(v, float) else str(v) for v in row)
                        for row in val]
            return "[%s]" % ", ".join(row_strs)
        return "[%s]" % ", ".join("%.6g" % v if isinstance(v, float) else str(v) for v in val)
    return str(val)


def _format_constants(variables, data, base_offset=0, indent=0, display_offset_base=None):
    rows = []
    if display_offset_base is None:
        display_offset_base = base_offset
    prefix = "&ensp;" * (indent * 2)
    for var in variables:
        name = var.name
        decode_off = base_offset + var.byteOffset
        display_off = display_offset_base + var.byteOffset
        stype = var.type
        members = stype.members if hasattr(stype, 'members') else []
        if len(members) > 0:
            rows.append("| %s**%s** | %d | struct | |" % (prefix, name, display_off))
            rows.extend(_format_constants(members, data, decode_off, indent + 1, display_off))
        else:
            type_str = _type_name_str(stype)
            val = _decode_value(data, decode_off, stype)
            val_str = _format_value(val)
            rows.append("| %s%s | %d | %s | %s |" % (prefix, name, display_off, type_str, val_str))
    return rows


def _compute_struct_stride(members):
    """Compute byte stride of a struct from its ShaderConstant members."""
    max_end = 0
    for m in members:
        stype = m.type
        sub_members = stype.members if hasattr(stype, 'members') else []
        if len(sub_members) > 0:
            nested_size = _compute_struct_stride(sub_members)
            end = m.byteOffset + nested_size
        else:
            if stype.baseType in _VARTYPE_FMT:
                _, elem_size = _VARTYPE_FMT[stype.baseType]
                rows = max(stype.rows, 1)
                cols = max(stype.columns, 1)
                end = m.byteOffset + rows * cols * elem_size
            else:
                end = m.byteOffset + 4
        max_end = max(max_end, end)
    # Align to 16 bytes (GPU struct alignment)
    return (max_end + 15) & ~15 if max_end > 0 else 0


def _format_struct_definition(name, members):
    """Format a struct's field definitions as markdown table rows."""
    rows = ["## Structure: %s\n" % name,
            "| Field | Offset | Type |",
            "|-------|--------|------|"]
    for m in members:
        stype = m.type
        sub_members = stype.members if hasattr(stype, 'members') else []
        if len(sub_members) > 0:
            rows.append("| %s | %d | struct |" % (m.name, m.byteOffset))
        else:
            rows.append("| %s | %d | %s |" % (m.name, m.byteOffset, _type_name_str(stype)))
    rows.append("")
    return rows


def _format_struct_fields_table(members):
    """Format struct fields as a markdown table (no title row)."""
    rows = ["| Field | Offset | Type |",
            "|-------|--------|------|"]
    for m in members:
        stype = m.type
        sub_members = stype.members if hasattr(stype, 'members') else []
        if len(sub_members) > 0:
            rows.append("| %s | %d | struct |" % (m.name, m.byteOffset))
        else:
            rows.append("| %s | %d | %s |" % (m.name, m.byteOffset, _type_name_str(stype)))
    rows.append("")
    return rows


def _md_escape_cell(text):
    s = str(text)
    s = s.replace("\r", "")
    s = s.replace("\n", "<br>")
    s = s.replace("|", "\\|")
    return s


def _flatten_struct_leaf_members(members, base_offset=0, prefix=""):
    leaves = []
    for i, m in enumerate(members):
        stype = m.type
        sub_members = stype.members if hasattr(stype, 'members') else []
        mname = m.name if m.name else ("field%d" % i)
        full_name = ("%s.%s" % (prefix, mname)) if prefix else mname
        try:
            rel_off = int(base_offset) + int(m.byteOffset)
        except Exception:
            rel_off = int(base_offset)
        if len(sub_members) > 0:
            leaves.extend(_flatten_struct_leaf_members(sub_members, rel_off, full_name))
        else:
            leaves.append((full_name, rel_off, stype))
    return leaves


def _build_struct_columns(members):
    leaves = _flatten_struct_leaf_members(members, 0, "")
    counts = {}
    cols = []
    for idx, (name, rel_off, stype) in enumerate(leaves):
        col = str(name or ("field%d" % idx))
        dup = counts.get(col, 0)
        counts[col] = dup + 1
        if dup > 0:
            col = "%s_%d" % (col, dup)
        cols.append((col, int(rel_off), stype))
    return cols


def _normalize_name(name):
    if not name:
        return ""
    return re.sub(r'[^a-z0-9]+', '', name.lower())


def _member_signature(members, prefix=""):
    sig = []
    for m in members:
        stype = m.type
        mname = m.name if m.name else "(unnamed)"
        full_name = ("%s.%s" % (prefix, mname)) if prefix else mname
        sub_members = stype.members if hasattr(stype, 'members') else []
        if len(sub_members) > 0:
            sig.extend(_member_signature(sub_members, full_name))
        else:
            sig.append((full_name, m.byteOffset, int(stype.baseType),
                        int(stype.rows), int(stype.columns)))
    return tuple(sig)


# ---------------------------------------------------------------------------
# Shader binding helpers
# ---------------------------------------------------------------------------

def _make_register_str(prefix, bind_num, bind_space):
    """Build register string like 't0' or 't3, space1'."""
    s = "%s%d" % (prefix, bind_num)
    if bind_space > 0:
        s += ", space%d" % bind_space
    return s


def _extract_bindings(refl):
    """Extract (srv_bindings, uav_bindings, cb_bindings) from ShaderReflection.
    Each is a list of (name, register_str)."""
    srvs = []
    uavs = []
    cbs = []
    if hasattr(refl, 'readOnlyResources'):
        for res in refl.readOnlyResources:
            name = res.name if res.name else "(unnamed)"
            reg = _make_register_str("t", res.fixedBindNumber, res.fixedBindSetOrSpace)
            srvs.append((name, reg))
    if hasattr(refl, 'readWriteResources'):
        for res in refl.readWriteResources:
            name = res.name if res.name else "(unnamed)"
            reg = _make_register_str("u", res.fixedBindNumber, res.fixedBindSetOrSpace)
            uavs.append((name, reg))
    if hasattr(refl, 'constantBlocks'):
        for cb in refl.constantBlocks:
            name = cb.name if cb.name else "(unnamed)"
            reg = _make_register_str("b", cb.fixedBindNumber, cb.fixedBindSetOrSpace)
            cbs.append((name, reg))
    return srvs, uavs, cbs


# ---------------------------------------------------------------------------
# SDObject -> markdown helpers (for PSO export)
# ---------------------------------------------------------------------------

def _sdobject_value_str(obj):
    try:
        d = obj.data
        if hasattr(d, 'basic'):
            b = d.basic
            if hasattr(b, 'id') and int(b.id) != 0:
                return str(int(b.id))
            if hasattr(b, 'u'):
                return str(b.u)
            if hasattr(b, 'd'):
                return str(b.d)
            if hasattr(b, 'b'):
                return str(bool(b.b))
            if hasattr(b, 'c'):
                return str(b.c)
        if hasattr(d, 'str'):
            s = d.str
            if s:
                return str(s)
    except Exception:
        pass
    return ""


def _sdobject_to_md_rows(obj, prefix=""):
    rows = []
    num = obj.NumChildren()
    if num == 0:
        val = _sdobject_value_str(obj)
        if val:
            rows.append("| %s | %s |" % (prefix + obj.name if prefix else obj.name, val))
        return rows
    for i in range(num):
        child = obj.GetChild(i)
        child_name = child.name if child.name else "[%d]" % i
        full = ("%s.%s" % (prefix, child_name)) if prefix else child_name
        child_num = child.NumChildren()
        if child_num == 0:
            val = _sdobject_value_str(child)
            rows.append("| %s | %s |" % (full, val))
        else:
            rows.extend(_sdobject_to_md_rows(child, full))
    return rows


# ===========================================================================
# Exporter class
# ===========================================================================

class RDCExporter:
    def __init__(self, controller, output_dir, skip_slateui_title=True,
                 skip_marker_name="SlateUI Title", eid_filter=None):
        self.controller = controller
        self.output_dir = output_dir
        self.sfile = controller.GetStructuredFile()

        # De-duplication tracking
        self.exported_shaders  = {}   # key -> filepath
        self.exported_textures = {}   # rid_str -> filepath
        self.exported_buffers  = {}   # rid_str -> filepath
        self.exported_psos     = {}   # rid_str -> filepath

        # Build resource lookup tables
        self._tex_descs = {}
        self._buf_descs = {}
        self._res_descs = {}
        for tex in controller.GetTextures():
            self._tex_descs[str(int(tex.resourceId))] = tex
        for buf in controller.GetBuffers():
            self._buf_descs[str(int(buf.resourceId))] = buf
        for res in controller.GetResources():
            self._res_descs[str(int(res.resourceId))] = res

        # Disassembly targets
        self._disasm_targets = controller.GetDisassemblyTargets(True)
        self._preferred_disasm_target = self._choose_preferred_disasm_target()

        # PSO -> Shader mapping
        self._pso_shaders = {}
        self._build_pso_shader_map()
        self._pso_types = {}   # pso_rid_int -> "graphics" | "compute" | "unknown"

        # Shader metadata cache (lazy, on-demand)
        # _shader_cache: { key -> (entry_name, srvs, uavs, cbs) }
        self._shader_cache = {}
        self._cb_layouts   = {}   # byteSize -> [ConstantBlock]
        self._struct_layouts = {} # stride -> [{name,members,signature}]
        self._shader_cache_fail = set()

        # PSO creation data from StructuredFile
        self._pso_creation_data = {}
        self._build_pso_creation_map()

        # Per-event resource usage map
        self._event_textures = {}
        self._event_buffers  = {}
        self._event_ia_state = {}      # eid -> {"ib_format": int|None, "vb_slots": {slot: stride}}
        self._event_cbv_state = {}     # eid -> {rootIndex: {"rid": rid_s, "offset": int}}
        self._buffer_fmt_hints = {}    # rid_s -> {"ib_format": int|None, "vb_stride": int|None}
        self._cbv_length_hints = {}    # rid_s -> inferred CB slice length
        self._has_usage_batch_api = hasattr(controller, "GetUsageBatch")
        self._usage_batch_broken = False
        self._enable_usage_prefilter = _env_flag("RDC_USAGE_PREFILTER", True)
        self._enable_event_usage_map = _env_flag("RDC_EXPORT_EVENT_USAGE_MAP", True)
        self._skip_slateui_title = bool(skip_slateui_title)
        self._skip_marker_name = str(skip_marker_name or "").strip()
        self._eid_filter = eid_filter or None
        self._event_list_only_mode = bool(self._eid_filter and self._eid_filter.get("event_list_only"))
        self._eid_min = None
        self._eid_max = None
        if self._eid_filter and not self._event_list_only_mode:
            self._eid_min = self._eid_filter.get("min_eid")
            self._eid_max = self._eid_filter.get("max_eid")
        self._skip_event_ids = set()
        self._excluded_tex_rids = set()
        self._excluded_buf_rids = set()
        self._set_frame_event_one_arg = False
        self._texture_save_warned = 0
        self._buffer_size_cache = {}
        self._current_event_id = None
        self._texture_snapshot_cache = {}
        self._buffer_snapshot_cache = {}
        self._snapshot_texture_files = set()
        self._snapshot_buffer_files = set()
        for rid_s, buf in self._buf_descs.items():
            try:
                if buf.length > 0:
                    self._buffer_size_cache[rid_s] = int(buf.length)
            except Exception:
                pass

    # -------------------------------------------------------------------
    # Filename helper: DebugName_ID.ext or ID.ext
    # -------------------------------------------------------------------
    def _res_filename(self, rid_s, ext, suffix=""):
        """Generate filename with debug name if available.
        suffix is appended before ext, e.g. suffix="_VS" -> "Name_ID_VS.md"
        """
        name = ""
        if rid_s in self._res_descs:
            n = self._res_descs[rid_s].name
            if n:
                name = safe_filename(n)
        if name:
            # If debug name already ends with this numeric ID, don't append it again.
            if name == rid_s or re.search(r'(^|[^0-9])%s$' % re.escape(rid_s), name):
                return "%s%s%s" % (name, suffix, ext)
            return "%s_%s%s%s" % (name, rid_s, suffix, ext)
        return "%s%s%s" % (rid_s, suffix, ext)

    def _choose_preferred_disasm_target(self):
        """Prefer HLSL disassembly target when available."""
        try:
            for target in self._disasm_targets:
                t = str(target)
                if "hlsl" in t.lower():
                    return t
        except Exception:
            pass
        return ""

    def _shader_encoding_name(self, encoding):
        try:
            name = str(encoding)
        except Exception:
            name = ""
        if "." in name:
            name = name.split(".")[-1]
        return name if name else "Unknown"

    def _shader_code_lang(self, encoding_name):
        name = str(encoding_name or "").lower()
        if "hlsl" in name:
            return "hlsl"
        if "glsl" in name:
            return "glsl"
        if "slang" in name:
            return "txt"
        if "spirv" in name and "asm" in name:
            return "asm"
        return "txt"

    def _is_probably_text(self, text):
        if not text:
            return False
        sample = text[:4096]
        if not sample:
            return False
        ctrl = 0
        for ch in sample:
            o = ord(ch)
            if o < 32 and ch not in ("\n", "\r", "\t"):
                ctrl += 1
        return (float(ctrl) / float(len(sample))) < 0.02

    def _decode_shader_raw_text(self, raw_bytes):
        if raw_bytes is None:
            return ""
        try:
            data = bytes(raw_bytes)
        except Exception:
            return ""
        if not data:
            return ""
        for enc in ["utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"]:
            try:
                text = data.decode(enc)
                if self._is_probably_text(text):
                    return text
            except Exception:
                pass
        try:
            text = data.decode("latin1")
            if self._is_probably_text(text):
                return text
        except Exception:
            pass
        return ""

    def _extract_shader_sources(self, refl):
        sources = []
        encoding = getattr(refl, "encoding", None)
        source_kind = ""

        debug_info = getattr(refl, "debugInfo", None)
        if debug_info is not None:
            try:
                dbg_encoding = getattr(debug_info, "encoding", None)
                if dbg_encoding is not None:
                    encoding = dbg_encoding
            except Exception:
                pass

            try:
                dbg_files = list(getattr(debug_info, "files", []) or [])
            except Exception:
                dbg_files = []

            if dbg_files:
                normalized = []
                for sf in dbg_files:
                    fname = ""
                    src = ""
                    try:
                        fname = str(getattr(sf, "filename", "") or "")
                    except Exception:
                        fname = ""
                    try:
                        src = getattr(sf, "contents", "")
                    except Exception:
                        src = ""
                    if isinstance(src, (bytes, bytearray)):
                        src = self._decode_shader_raw_text(src)
                    else:
                        try:
                            src = str(src)
                        except Exception:
                            src = ""
                    normalized.append((fname, src))

                order = list(range(len(normalized)))
                try:
                    edit_base = int(getattr(debug_info, "editBaseFile", -1))
                except Exception:
                    edit_base = -1
                if 0 <= edit_base < len(order):
                    order = [edit_base] + [i for i in order if i != edit_base]

                for idx in order:
                    fname, src = normalized[idx]
                    if not src or not self._is_probably_text(src):
                        continue
                    sources.append((fname if fname else "(unnamed)", src))

                if sources:
                    source_kind = "debug-info"
                    return sources, encoding, source_kind

        raw_text = self._decode_shader_raw_text(getattr(refl, "rawBytes", b""))
        if raw_text:
            sources = [("(raw source)", raw_text)]
            source_kind = "raw-bytes"
            return sources, encoding, source_kind

        return [], encoding, source_kind

    # -------------------------------------------------------------------
    # Init helpers
    # -------------------------------------------------------------------
    def _build_pso_shader_map(self):
        print("[rdc_export] Building PSO -> Shader mapping ...")
        pso_count = 0
        shader_count = 0
        for rid_s, res in self._res_descs.items():
            if res.type == rd.ResourceType.PipelineState:
                pso_count += 1
                pso_rid_int = int(res.resourceId)
                shaders = []
                for parent in res.parentResources:
                    parent_s = str(int(parent))
                    if parent_s in self._res_descs:
                        parent_res = self._res_descs[parent_s]
                        if parent_res.type == rd.ResourceType.Shader:
                            entries = self.controller.GetShaderEntryPoints(parent)
                            for e in entries:
                                shaders.append((parent, e.stage, e))
                                shader_count += 1
                self._pso_shaders[pso_rid_int] = shaders
        print("[rdc_export]   Found %d PSOs with %d shader bindings" % (pso_count, shader_count))

    def _cache_layouts_from_refl(self, refl):
        cb_added = 0
        struct_added = 0
        struct_res_total = 0
        struct_res_with_members = 0
        # Cache CB layouts for buffer format
        if hasattr(refl, 'constantBlocks'):
            for cb in refl.constantBlocks:
                if cb.byteSize > 0 and len(cb.variables) > 0:
                    self._cb_layouts.setdefault(cb.byteSize, []).append(cb)
                    cb_added += 1
        # Cache struct layouts from SRV/UAV resources
        for res_list in [refl.readOnlyResources if hasattr(refl, 'readOnlyResources') else [],
                         refl.readWriteResources if hasattr(refl, 'readWriteResources') else []]:
            for res in res_list:
                struct_res_total += 1
                if hasattr(res, 'variableType'):
                    vtype = res.variableType
                    members = vtype.members if hasattr(vtype, 'members') else []
                    if len(members) > 0:
                        struct_res_with_members += 1
                        stride = _compute_struct_stride(members)
                        if stride > 0:
                            rname = res.name if res.name else "(unnamed)"
                            sig = _member_signature(members)
                            items = self._struct_layouts.setdefault(stride, [])
                            if not any(item['signature'] == sig for item in items):
                                items.append({
                                    'name': rname,
                                    'members': members,
                                    'signature': sig,
                                })
                                struct_added += 1
    def _cache_shader_metadata(self, pso_rid_int, shader_rid, entry_point, abbrev):
        if shader_rid is None:
            return None
        rid_s = rid_str(shader_rid)
        key = "%s_%s" % (rid_s, abbrev)
        if key in self._shader_cache:
            return self._shader_cache[key]
        if key in self._shader_cache_fail:
            return None

        pso_s = str(pso_rid_int) if pso_rid_int is not None else ""
        if not pso_s or pso_s not in self._res_descs:
            self._shader_cache_fail.add(key)
            return None

        try:
            pso_rid = self._res_descs[pso_s].resourceId
            refl = self.controller.GetShader(pso_rid, shader_rid, entry_point)
            if refl is None:
                self._shader_cache_fail.add(key)
                return None
            entry_name = ""
            if hasattr(refl, 'entryPoint') and refl.entryPoint:
                entry_name = refl.entryPoint
            elif hasattr(entry_point, 'name'):
                entry_name = str(entry_point.name)
            else:
                entry_name = "N/A"
            srvs, uavs, cbs = _extract_bindings(refl)
            self._cache_layouts_from_refl(refl)
            self._shader_cache[key] = (entry_name, srvs, uavs, cbs)
            return self._shader_cache[key]
        except Exception as e:
            self._shader_cache_fail.add(key)
            return None

    def _build_pso_creation_map(self):
        print("[rdc_export] Parsing PSO creation data from structured file ...")
        sfile = self.sfile
        count = 0
        for ci in range(len(sfile.chunks)):
            chunk = sfile.chunks[ci]
            if chunk.name in ('ID3D12Device::CreateGraphicsPipelineState',
                              'ID3D12Device::CreateComputePipelineState',
                              'ID3D12Device2::CreatePipelineState'):
                pso_rid_int = None
                pdesc_obj = None
                for i in range(chunk.NumChildren()):
                    child = chunk.GetChild(i)
                    if child.name == 'pPipelineState':
                        try:
                            pso_rid_int = int(child.data.basic.id)
                        except Exception:
                            pass
                    if child.name in ('pDesc', 'Descriptor'):
                        pdesc_obj = child
                if pso_rid_int is not None and pdesc_obj is not None:
                    self._pso_creation_data[pso_rid_int] = (chunk.name, pdesc_obj)
                    if 'CreateGraphicsPipelineState' in chunk.name:
                        self._pso_types[pso_rid_int] = 'graphics'
                    elif 'CreateComputePipelineState' in chunk.name:
                        self._pso_types[pso_rid_int] = 'compute'
                    count += 1
        print("[rdc_export]   Found %d PSO creation records" % count)

    def _build_event_resource_map(self, target_eids=None, batch_size=256):
        print("[rdc_export] Building per-event resource usage map (batched) ...")
        self._event_textures = {}
        self._event_buffers = {}
        skipped_tex_rids = set()
        skipped_buf_rids = set()
        included_tex_rids = set()
        included_buf_rids = set()
        target = set(target_eids) if target_eids else None
        if target is not None:
            print("[rdc_export]   Target events: %d" % len(target))
        target_min = min(target) if target else None
        target_max = max(target) if target else None

        tex_count = 0
        buf_count = 0
        tex_query_calls = 0
        buf_query_calls = 0
        tex_query_resources = 0
        buf_query_resources = 0
        tex_batch_calls = 0
        buf_batch_calls = 0
        tex_query_time = 0.0
        buf_query_time = 0.0

        get_usage = self.controller.GetUsage
        get_usage_batch = self.controller.GetUsageBatch if (
            self._has_usage_batch_api and not self._usage_batch_broken
        ) else None
        usage_names = _USAGE_NAMES
        tex_usage_codes = _ALL_TEX_USAGES
        buf_usage_codes = _ALL_BUF_USAGES

        def _fetch_usage_rows(batch):
            nonlocal get_usage_batch
            if get_usage_batch is not None:
                try:
                    ids = [obj.resourceId for _, obj in batch]
                    t0 = time.time()
                    usage_rows = get_usage_batch(ids)
                    elapsed = time.time() - t0
                    if usage_rows is None or len(usage_rows) != len(batch):
                        raise RuntimeError("GetUsageBatch returned unexpected result")
                    normalized_rows = []
                    for entry in usage_rows:
                        if entry is None:
                            normalized_rows.append(None)
                        elif hasattr(entry, "usages"):
                            normalized_rows.append(entry.usages)
                        else:
                            normalized_rows.append(entry)
                    return normalized_rows, elapsed, 1, len(batch), True
                except Exception as e:
                    if not self._usage_batch_broken:
                        print("[rdc_export]   WARNING: GetUsageBatch failed (%s), fallback to per-resource GetUsage." % e)
                    self._usage_batch_broken = True
                    get_usage_batch = None

            usage_rows = []
            t0 = time.time()
            for _, obj in batch:
                try:
                    usage_rows.append(get_usage(obj.resourceId))
                except Exception:
                    usage_rows.append(None)
            elapsed = time.time() - t0
            return usage_rows, elapsed, len(batch), len(batch), False

        tex_items_all = list(self._tex_descs.items())
        if self._enable_usage_prefilter and _TEX_USAGE_CATEGORY_MASK != 0:
            tex_items = []
            for rid_s, tex in tex_items_all:
                flags = _enum_to_int(getattr(tex, "creationFlags", 0), 0)
                if flags != 0 and (flags & _TEX_USAGE_CATEGORY_MASK) == 0:
                    continue
                tex_items.append((rid_s, tex))
            skipped = len(tex_items_all) - len(tex_items)
            if skipped > 0:
                print("[rdc_export]   Texture prefilter skipped %d/%d usage queries" % (
                    skipped, len(tex_items_all)))
        else:
            tex_items = tex_items_all

        for i in range(0, len(tex_items), batch_size):
            batch = tex_items[i:i + batch_size]
            usage_rows, elapsed, call_count, resource_count, used_batch = _fetch_usage_rows(batch)
            tex_query_time += elapsed
            tex_query_calls += call_count
            tex_query_resources += resource_count
            if used_batch:
                tex_batch_calls += 1

            for (rid_s, _), usages in zip(batch, usage_rows):
                if not usages:
                    continue
                for u in usages:
                    eid = u.eventId
                    ucode = u.usage
                    if ucode not in tex_usage_codes:
                        continue
                    if eid in self._skip_event_ids:
                        skipped_tex_rids.add(rid_s)
                        continue
                    if target is not None:
                        if (target_min is not None and (eid < target_min or eid > target_max)) or \
                           eid not in target:
                            continue
                    rid_map = self._event_textures.setdefault(eid, {})
                    usage_set = rid_map.setdefault(rid_s, set())
                    before = len(usage_set)
                    usage_set.add(usage_names.get(ucode, str(ucode)))
                    if len(usage_set) > before:
                        tex_count += 1
                    included_tex_rids.add(rid_s)
            if ((i // batch_size) + 1) % 8 == 0:
                print("[rdc_export]     texture usage %d/%d ..." % (
                    min(i + batch_size, len(tex_items)), len(tex_items)))

        buf_items_all = list(self._buf_descs.items())
        if self._enable_usage_prefilter and _BUF_USAGE_CATEGORY_MASK != 0:
            buf_items = []
            for rid_s, buf in buf_items_all:
                flags = _enum_to_int(getattr(buf, "creationFlags", 0), 0)
                if flags != 0 and (flags & _BUF_USAGE_CATEGORY_MASK) == 0:
                    continue
                buf_items.append((rid_s, buf))
            skipped = len(buf_items_all) - len(buf_items)
            if skipped > 0:
                print("[rdc_export]   Buffer prefilter skipped %d/%d usage queries" % (
                    skipped, len(buf_items_all)))
        else:
            buf_items = buf_items_all

        for i in range(0, len(buf_items), batch_size):
            batch = buf_items[i:i + batch_size]
            usage_rows, elapsed, call_count, resource_count, used_batch = _fetch_usage_rows(batch)
            buf_query_time += elapsed
            buf_query_calls += call_count
            buf_query_resources += resource_count
            if used_batch:
                buf_batch_calls += 1

            for (rid_s, _), usages in zip(batch, usage_rows):
                if not usages:
                    continue
                for u in usages:
                    eid = u.eventId
                    ucode = u.usage
                    if ucode not in buf_usage_codes:
                        continue
                    if eid in self._skip_event_ids:
                        skipped_buf_rids.add(rid_s)
                        continue
                    if target is not None:
                        if (target_min is not None and (eid < target_min or eid > target_max)) or \
                           eid not in target:
                            continue
                    rid_map = self._event_buffers.setdefault(eid, {})
                    usage_set = rid_map.setdefault(rid_s, set())
                    before = len(usage_set)
                    usage_set.add(usage_names.get(ucode, str(ucode)))
                    if len(usage_set) > before:
                        buf_count += 1
                    included_buf_rids.add(rid_s)
            if ((i // batch_size) + 1) % 8 == 0:
                print("[rdc_export]     buffer usage %d/%d ..." % (
                    min(i + batch_size, len(buf_items)), len(buf_items)))

        tex_avg_ms = (1000.0 * tex_query_time / tex_query_calls) if tex_query_calls else 0.0
        buf_avg_ms = (1000.0 * buf_query_time / buf_query_calls) if buf_query_calls else 0.0
        tex_avg_ms_per_res = (1000.0 * tex_query_time / tex_query_resources) if tex_query_resources else 0.0
        buf_avg_ms_per_res = (1000.0 * buf_query_time / buf_query_resources) if buf_query_resources else 0.0
        print("[rdc_export]   Usage query calls: textures=%d (batch=%d, resources=%d, avg %.2f ms/call, %.2f ms/res), buffers=%d (batch=%d, resources=%d, avg %.2f ms/call, %.2f ms/res)" % (
            tex_query_calls, tex_batch_calls, tex_query_resources, tex_avg_ms, tex_avg_ms_per_res,
            buf_query_calls, buf_batch_calls, buf_query_resources, buf_avg_ms, buf_avg_ms_per_res))
        print("[rdc_export]   %d texture refs, %d buffer refs across %d/%d events" % (
            tex_count, buf_count, len(self._event_textures), len(self._event_buffers)))
        self._excluded_tex_rids = skipped_tex_rids - included_tex_rids
        self._excluded_buf_rids = skipped_buf_rids - included_buf_rids
        if self._excluded_tex_rids or self._excluded_buf_rids:
            print("[rdc_export]   Skip-marker filtered resources: textures=%d buffers=%d" % (
                len(self._excluded_tex_rids), len(self._excluded_buf_rids)))

    def _infer_pso_type_from_shaders(self, pso_rid_int):
        shaders = self._pso_shaders.get(pso_rid_int, [])
        if not shaders:
            return 'unknown'
        has_compute = False
        has_graphics = False
        for _, stage, _ in shaders:
            if stage == rd.ShaderStage.Compute:
                has_compute = True
            elif stage in (rd.ShaderStage.Vertex, rd.ShaderStage.Hull, rd.ShaderStage.Domain,
                           rd.ShaderStage.Geometry, rd.ShaderStage.Pixel):
                has_graphics = True
        if has_compute and not has_graphics:
            return 'compute'
        if has_graphics:
            return 'graphics'
        return 'unknown'

    def _get_pso_type(self, pso_rid_int):
        if pso_rid_int is None:
            return 'unknown'
        if pso_rid_int not in self._pso_types:
            self._pso_types[pso_rid_int] = self._infer_pso_type_from_shaders(pso_rid_int)
        return self._pso_types[pso_rid_int]

    def _extract_setpso_rid(self, chunk, chunk_name=None):
        if chunk_name is None:
            chunk_name = chunk.name
        if chunk_name != 'ID3D12GraphicsCommandList::SetPipelineState':
            return None
        for ci in range(chunk.NumChildren()):
            child = chunk.GetChild(ci)
            if child.name == 'pPipelineState':
                try:
                    return int(child.data.basic.id)
                except Exception:
                    return None
        return None

    def _snapshot_chunk_fields(self, chunk, max_children=10, max_grandchildren=3):
        fields = []
        try:
            child_total = chunk.NumChildren()
            for i in range(min(child_total, max_children)):
                child = chunk.GetChild(i)
                fields.append({
                    "name": child.name,
                    "value": _sdobject_value_str(child),
                    "children": child.NumChildren(),
                })
                sub_total = child.NumChildren()
                if sub_total > 0:
                    for j in range(min(sub_total, max_grandchildren)):
                        sub = child.GetChild(j)
                        fields.append({
                            "name": "%s.%s" % (child.name, sub.name),
                            "value": _sdobject_value_str(sub),
                            "children": sub.NumChildren(),
                        })
        except Exception:
            pass
        return fields

    def _collect_buffer_usage_codes(self, rid_s, max_events=400):
        usage = set()
        hit_events = 0
        try:
            for _, rid_map in self._event_buffers.items():
                if rid_s in rid_map:
                    usage.update(rid_map[rid_s])
                    hit_events += 1
                    if hit_events >= max_events:
                        break
        except Exception:
            pass
        return sorted(usage), hit_events

    def _sd_get_child(self, parent, name):
        try:
            for i in range(parent.NumChildren()):
                c = parent.GetChild(i)
                if c.name == name:
                    return c
        except Exception:
            pass
        return None

    def _sd_to_int(self, obj):
        if obj is None:
            return None
        try:
            d = obj.data
            if hasattr(d, 'basic'):
                b = d.basic
                for attr in ('u', 'i', 'd', 'c'):
                    if hasattr(b, attr):
                        try:
                            return int(getattr(b, attr))
                        except Exception:
                            pass
                if hasattr(b, 'id'):
                    try:
                        return int(b.id)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            s = _sdobject_value_str(obj)
            if s is None or s == "":
                return None
            if isinstance(s, str) and (s.startswith("0x") or s.startswith("0X")):
                return int(s, 16)
            return int(s)
        except Exception:
            return None

    def _extract_ia_index_info(self, chunk, chunk_name=None):
        if chunk_name is None:
            chunk_name = chunk.name
        if chunk_name != 'ID3D12GraphicsCommandList::IASetIndexBuffer':
            return None
        view = self._sd_get_child(chunk, 'pView')
        if view is None:
            return None
        fmt_obj = self._sd_get_child(view, 'Format')
        size_obj = self._sd_get_child(view, 'SizeInBytes')
        fmt = self._sd_to_int(fmt_obj)
        size = self._sd_to_int(size_obj)
        if fmt is None and size is None:
            return None
        return {"format": fmt, "size": size}

    def _extract_ia_vertex_views(self, chunk, chunk_name=None):
        if chunk_name is None:
            chunk_name = chunk.name
        if chunk_name != 'ID3D12GraphicsCommandList::IASetVertexBuffers':
            return []
        start_slot = self._sd_to_int(self._sd_get_child(chunk, 'StartSlot'))
        if start_slot is None:
            start_slot = 0
        pviews = self._sd_get_child(chunk, 'pViews')
        if pviews is None:
            return []
        views = []
        try:
            for i in range(pviews.NumChildren()):
                view = pviews.GetChild(i)
                stride = self._sd_to_int(self._sd_get_child(view, 'StrideInBytes'))
                size = self._sd_to_int(self._sd_get_child(view, 'SizeInBytes'))
                if stride is None:
                    # Some captures may nest the view object one more level.
                    for j in range(view.NumChildren()):
                        sub = view.GetChild(j)
                        if stride is None and sub.name == 'StrideInBytes':
                            stride = self._sd_to_int(sub)
                        if size is None and sub.name == 'SizeInBytes':
                            size = self._sd_to_int(sub)
                views.append({
                    "slot": start_slot + i,
                    "stride": stride if stride is not None else 0,
                    "size": size if size is not None else 0,
                })
        except Exception:
            pass
        return views

    def _extract_root_cbv_binding(self, chunk, chunk_name=None):
        if chunk_name is None:
            chunk_name = chunk.name
        is_gfx = (chunk_name == 'ID3D12GraphicsCommandList::SetGraphicsRootConstantBufferView')
        is_comp = (chunk_name == 'ID3D12GraphicsCommandList::SetComputeRootConstantBufferView')
        if not (is_gfx or is_comp):
            return None

        root_idx = self._sd_to_int(self._sd_get_child(chunk, 'RootParameterIndex'))
        buf_loc = self._sd_get_child(chunk, 'BufferLocation')
        if buf_loc is None:
            return None
        buf_id = self._sd_to_int(self._sd_get_child(buf_loc, 'Buffer'))
        buf_off = self._sd_to_int(self._sd_get_child(buf_loc, 'Offset'))
        if buf_id is None:
            return None
        rid_s = str(int(buf_id))
        if rid_s not in self._buf_descs:
            return None
        return {
            "is_compute": bool(is_comp),
            "root_index": int(root_idx) if root_idx is not None else -1,
            "rid": rid_s,
            "offset": int(buf_off) if buf_off is not None else 0,
        }

    def _build_buffer_format_hints(self, actions):
        votes = {}  # rid_s -> {"ib_format": {fmt:cnt}, "vb_stride": {stride:cnt}}
        for action in actions:
            eid = action.eventId
            refs = self._event_buffers.get(eid, {})
            if not refs:
                continue
            ia = self._event_ia_state.get(eid, {})
            ib_format = ia.get("ib_format")
            vb_slots = ia.get("vb_slots", {})
            vb_strides = [s for s in vb_slots.values() if s and s > 0]

            ib_rids = [rid for rid, uses in refs.items() if "IB" in uses]
            vb_rids = [rid for rid, uses in refs.items() if "VB" in uses]

            if ib_format is not None and ib_format > 0:
                for rid in ib_rids:
                    m = votes.setdefault(rid, {"ib_format": {}, "vb_stride": {}})
                    m["ib_format"][ib_format] = m["ib_format"].get(ib_format, 0) + 1

            if vb_rids and vb_strides:
                if len(vb_rids) == 1:
                    stride = vb_slots.get(0)
                    if not stride:
                        try:
                            min_slot = sorted(vb_slots.keys())[0]
                            stride = vb_slots[min_slot]
                        except Exception:
                            stride = None
                    if stride and stride > 0:
                        rid = vb_rids[0]
                        m = votes.setdefault(rid, {"ib_format": {}, "vb_stride": {}})
                        m["vb_stride"][stride] = m["vb_stride"].get(stride, 0) + 1
                else:
                    uniq = sorted(set(vb_strides))
                    if len(uniq) == 1:
                        stride = uniq[0]
                        for rid in vb_rids:
                            m = votes.setdefault(rid, {"ib_format": {}, "vb_stride": {}})
                            m["vb_stride"][stride] = m["vb_stride"].get(stride, 0) + 1

        self._buffer_fmt_hints = {}
        for rid, m in votes.items():
            ib_format = None
            vb_stride = None
            if m["ib_format"]:
                ib_format = max(m["ib_format"].items(), key=lambda kv: kv[1])[0]
            if m["vb_stride"]:
                vb_stride = max(m["vb_stride"].items(), key=lambda kv: kv[1])[0]
            self._buffer_fmt_hints[rid] = {"ib_format": ib_format, "vb_stride": vb_stride}

    # -------------------------------------------------------------------
    # Directory / file helpers
    # -------------------------------------------------------------------
    def _ensure_dir(self, *parts):
        path = os.path.join(self.output_dir, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def _write_file(self, content, *parts):
        dir_path = os.path.join(self.output_dir, *parts[:-1])
        os.makedirs(dir_path, exist_ok=True)
        filepath = os.path.join(self.output_dir, *parts)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return filepath

    def _hash_file_sha1(self, filepath, chunk_size=1024 * 1024):
        h = hashlib.sha1()
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _hash_buffer_range_sha1(self, resource_id, start_offset, total_size):
        h = hashlib.sha1()
        dumped = 0
        if total_size <= 0:
            h.update(b"")
            return h.hexdigest(), dumped
        for rel_off, chunk in self._iter_buffer_chunks_range(resource_id, start_offset, total_size):
            if not chunk:
                continue
            h.update(chunk)
            dumped = rel_off + len(chunk)
        return h.hexdigest(), dumped

    def _snapshot_key_hash(self, *parts):
        h = hashlib.sha1()
        for part in parts:
            h.update(str(part).encode('utf-8', errors='replace'))
            h.update(b"\x00")
        return h.hexdigest()

    def _export_texture_snapshot(self, resource_id, subdir, eid, phase, role="tex"):
        if resource_id == rd.ResourceId.Null():
            return None
        rid_s = rid_str(resource_id)
        role_tag = safe_filename(str(role or "tex"))
        phase_tag = safe_filename(str(phase or "state"))
        temp_name = "__tmp_EID_%d_%s_%s_%s.png" % (
            int(eid), role_tag, rid_s, phase_tag)
        temp_path = self._save_texture_image(
            resource_id, subdir, temp_name, track_export=False)
        if not temp_path:
            return None
        if not os.path.isfile(temp_path) or os.path.getsize(temp_path) <= 0:
            return None

        try:
            data_hash = self._hash_file_sha1(temp_path)
        except Exception:
            try:
                data_hash = self._snapshot_key_hash(
                    rid_s, subdir, phase_tag, os.path.getsize(temp_path))
            except Exception:
                data_hash = self._snapshot_key_hash(rid_s, subdir, phase_tag, time.time())

        cache_key = (subdir, rid_s, phase_tag, data_hash)
        cached_name = self._texture_snapshot_cache.get(cache_key)
        if cached_name:
            cached_path = os.path.join(self.output_dir, subdir, cached_name)
            if os.path.isfile(cached_path) and os.path.getsize(cached_path) > 0:
                if os.path.abspath(cached_path) != os.path.abspath(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                return cached_name

        filename = "TEX_%s_%s_%s_%s.png" % (
            rid_s, role_tag, phase_tag, data_hash[:16])
        final_path = os.path.join(self.output_dir, subdir, filename)

        if os.path.abspath(final_path) != os.path.abspath(temp_path):
            if os.path.isfile(final_path) and os.path.getsize(final_path) > 0:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            else:
                try:
                    os.replace(temp_path, final_path)
                except Exception:
                    try:
                        shutil.copy2(temp_path, final_path)
                        os.remove(temp_path)
                    except Exception:
                        pass

        if os.path.isfile(final_path) and os.path.getsize(final_path) > 0:
            self._texture_snapshot_cache[cache_key] = filename
            self._snapshot_texture_files.add(filename)
            return filename

        return None

    def _res_debug_name(self, rid_s):
        """Return debug name for a resource, or empty string."""
        if rid_s in self._res_descs:
            n = self._res_descs[rid_s].name
            if n:
                return n
        return ""

    def _tex_info_str(self, rid_s):
        if rid_s in self._tex_descs:
            t = self._tex_descs[rid_s]
            return "%dx%d %s" % (t.width, t.height, str(t.format.Name()))
        return ""

    def _buf_info_str(self, rid_s):
        if rid_s in self._buf_descs:
            return "%d bytes" % self._buf_descs[rid_s].length
        return ""

    # -------------------------------------------------------------------
    # 1. Export Event List (to root)
    # -------------------------------------------------------------------
    def export_event_list(self, root_actions=None):
        print("[rdc_export] Exporting event list ...")
        rows = []
        if root_actions is None:
            root_actions = self.controller.GetRootActions()
        if self._skip_slateui_title and not self._skip_event_ids:
            self._build_skip_event_ids(root_actions)
        self._collect_event_rows(root_actions, 0, rows)
        lines = ["# Event List\n",
                 "| EID | Name | Type | Details |",
                 "|-----|------|------|---------|"]
        for eid, depth, name, typ, details, flags in rows:
            indent_str = "-- " * depth
            # Add link for Drawcall / Dispatch events
            if flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.Dispatch):
                if (not self._event_list_only_mode) and self._event_id_matches_filter(eid):
                    display = "%s[%s](events/EID_%d.md)" % (indent_str, name, eid)
                else:
                    display = "%s%s" % (indent_str, name)
            else:
                display = "%s%s" % (indent_str, name)
            lines.append("| %d | %s | %s | %s |" % (eid, display, typ, details))
        lines.append("")
        self._write_file("\n".join(lines), "event_list.md")

    def _collect_event_rows(self, actions, depth, rows):
        for action in actions:
            if action.eventId in self._skip_event_ids:
                continue
            name = action.GetName(self.sfile)
            typ = get_action_type_str(action.flags)
            details = get_action_details(action)
            rows.append((action.eventId, depth, name, typ, details, action.flags))
            if len(action.children) > 0:
                self._collect_event_rows(action.children, depth + 1, rows)

    # -------------------------------------------------------------------
    # 2. Parse per-event pipeline state from structured data
    # -------------------------------------------------------------------
    def _parse_structured_pipeline_state(self, actions):
        print("[rdc_export]   Parsing structured data for pipeline state ...")
        result = {}
        sfile = self.sfile
        chunk_total = len(sfile.chunks)
        indexed_actions = []
        for action in actions:
            end_chunk = -1
            for evt in action.events:
                if evt.chunkIndex > end_chunk:
                    end_chunk = evt.chunkIndex
            indexed_actions.append((end_chunk, action))
        indexed_actions.sort(key=lambda x: x[0])
        max_target_chunk = indexed_actions[-1][0] if indexed_actions else -1

        idx = 0
        current_graphics = None
        current_compute = None
        current_any = None
        current_ib_format = None
        current_vb_slots = {}
        event_ia_state = {}
        current_gfx_cbv = {}   # rootIndex -> {"rid": rid_s, "offset": int}
        current_comp_cbv = {}  # rootIndex -> {"rid": rid_s, "offset": int}
        event_cbv_state = {}   # eid -> {rootIndex: {"rid": rid_s, "offset": int}}
        cbv_len_votes = {}     # rid_s -> {delta: count}

        while idx < len(indexed_actions) and indexed_actions[idx][0] < 0:
            action = indexed_actions[idx][1]
            result[action.eventId] = {'pso_rid': None, 'shaders': []}
            event_ia_state[action.eventId] = {
                "ib_format": current_ib_format,
                "vb_slots": dict(current_vb_slots),
            }
            event_cbv_state[action.eventId] = {}
            idx += 1

        scan_chunk_count = chunk_total
        if max_target_chunk >= 0:
            scan_chunk_count = min(chunk_total, max_target_chunk + 1)
        if scan_chunk_count < chunk_total:
            print("[rdc_export]   Structured scan trimmed to %d/%d chunks" % (
                scan_chunk_count, chunk_total))

        for ci in range(scan_chunk_count):
            chunk = sfile.chunks[ci]
            chunk_name = chunk.name

            pso_rid = self._extract_setpso_rid(chunk, chunk_name)
            if pso_rid is not None:
                current_any = pso_rid
                ptype = self._get_pso_type(pso_rid)
                if ptype == 'graphics':
                    current_graphics = pso_rid
                elif ptype == 'compute':
                    current_compute = pso_rid

            ib_info = self._extract_ia_index_info(chunk, chunk_name)
            if ib_info is not None and ib_info.get("format") is not None:
                current_ib_format = ib_info.get("format")
            vb_views = self._extract_ia_vertex_views(chunk, chunk_name)
            if vb_views:
                for v in vb_views:
                    slot = v.get("slot")
                    stride = v.get("stride", 0)
                    if slot is None:
                        continue
                    if stride and stride > 0:
                        current_vb_slots[slot] = stride
            root_cbv = self._extract_root_cbv_binding(chunk, chunk_name)
            if root_cbv is not None:
                state_map = current_comp_cbv if root_cbv.get("is_compute") else current_gfx_cbv
                root_idx = int(root_cbv.get("root_index", -1))
                rid_s = root_cbv.get("rid")
                offset = int(root_cbv.get("offset", 0))
                prev = state_map.get(root_idx)
                if prev and prev.get("rid") == rid_s:
                    delta = abs(offset - int(prev.get("offset", 0)))
                    if delta > 0:
                        votes = cbv_len_votes.setdefault(rid_s, {})
                        votes[delta] = votes.get(delta, 0) + 1
                state_map[root_idx] = {"rid": rid_s, "offset": offset}
            while idx < len(indexed_actions) and indexed_actions[idx][0] <= ci:
                action = indexed_actions[idx][1]
                if action.flags & rd.ActionFlags.Dispatch:
                    pso_rid_int = current_compute if current_compute is not None else current_any
                    cbv_state = current_comp_cbv
                else:
                    pso_rid_int = current_graphics if current_graphics is not None else current_any
                    cbv_state = current_gfx_cbv
                shaders = self._pso_shaders.get(pso_rid_int, []) if pso_rid_int is not None else []
                result[action.eventId] = {'pso_rid': pso_rid_int, 'shaders': shaders}
                event_ia_state[action.eventId] = {
                    "ib_format": current_ib_format,
                    "vb_slots": dict(current_vb_slots),
                }
                event_cbv_state[action.eventId] = {
                    idx_key: {"rid": item.get("rid"), "offset": int(item.get("offset", 0))}
                    for idx_key, item in cbv_state.items()
                }
                idx += 1

        while idx < len(indexed_actions):
            action = indexed_actions[idx][1]
            if action.flags & rd.ActionFlags.Dispatch:
                pso_rid_int = current_compute if current_compute is not None else current_any
                cbv_state = current_comp_cbv
            else:
                pso_rid_int = current_graphics if current_graphics is not None else current_any
                cbv_state = current_gfx_cbv
            shaders = self._pso_shaders.get(pso_rid_int, []) if pso_rid_int is not None else []
            result[action.eventId] = {'pso_rid': pso_rid_int, 'shaders': shaders}
            event_ia_state[action.eventId] = {
                "ib_format": current_ib_format,
                "vb_slots": dict(current_vb_slots),
            }
            event_cbv_state[action.eventId] = {
                idx_key: {"rid": item.get("rid"), "offset": int(item.get("offset", 0))}
                for idx_key, item in cbv_state.items()
            }
            idx += 1

        found = sum(1 for v in result.values() if v['pso_rid'] is not None)
        self._event_ia_state = event_ia_state
        self._event_cbv_state = event_cbv_state
        self._cbv_length_hints = {}
        for rid_s, votes in cbv_len_votes.items():
            if not votes:
                continue
            length = max(votes.items(), key=lambda kv: kv[1])[0]
            if length > 0:
                self._cbv_length_hints[rid_s] = int(length)
        print("[rdc_export]   Parsed %d actions, %d with PSO identified (%.1f%%)" % (
            len(result), found, (100.0 * found / max(1, len(result)))))
        return result

    # -------------------------------------------------------------------
    # 3. Export PSO assets (shaders exported here too for linking)
    # -------------------------------------------------------------------
    def export_psos(self):
        print("[rdc_export] Exporting PSO assets ...")
        self._ensure_dir("pso")
        count = 0
        for pso_rid_int, (chunk_name, pdesc_obj) in self._pso_creation_data.items():
            self._export_single_pso(pso_rid_int, chunk_name, pdesc_obj)
            count += 1
        for pso_rid_int in self._pso_shaders:
            pso_s = str(pso_rid_int)
            if pso_s not in self.exported_psos:
                self._export_pso_minimal(pso_rid_int)
                count += 1
        print("[rdc_export]   Exported %d PSOs" % count)

    def _export_single_pso(self, pso_rid_int, chunk_name, pdesc_obj):
        pso_s = str(pso_rid_int)
        if pso_s in self.exported_psos:
            return self.exported_psos[pso_s]

        filename = self._res_filename(pso_s, ".md", "_PSO")
        filepath = os.path.join(self.output_dir, "pso", filename)

        is_gfx = "Graphics" in chunk_name
        pso_type = "Graphics" if is_gfx else "Compute"
        pso_name = self._res_debug_name(pso_s)

        md = ["# PSO: %s\n" % pso_s]
        md.append("| Property | Value |")
        md.append("|----------|-------|")
        md.append("| Type | %s |" % pso_type)
        if pso_name:
            md.append("| Name | %s |" % pso_name)
        md.append("")

        # Shaders -- export them and create links
        shaders = self._pso_shaders.get(pso_rid_int, [])
        if shaders:
            md.append("## Shaders\n")
            md.append("| Stage | Resource ID | File |")
            md.append("|-------|-------------|------|")
            for shader_rid, stage, entry in shaders:
                s_rid_s = rid_str(shader_rid)
                abbrev = STAGE_ABBREV.get(stage, "??")
                stage_name = STAGE_NAME.get(stage, str(stage))
                # Export shader file to ensure it exists
                shader_file = self._export_shader_direct(pso_rid_int, shader_rid, entry, abbrev)
                if shader_file:
                    fname = os.path.basename(shader_file)
                    md.append("| %s | %s | [%s](../shaders/%s) |" % (stage_name, s_rid_s, fname, fname))
                else:
                    md.append("| %s | %s | *(not cached)* |" % (stage_name, s_rid_s))
            md.append("")

        # Pipeline state parameters from pDesc
        if pdesc_obj is not None:
            rows = _sdobject_to_md_rows(pdesc_obj)
            if rows:
                md.append("## Pipeline State Parameters\n")
                md.append("| Parameter | Value |")
                md.append("|-----------|-------|")
                md.extend(rows)
                md.append("")

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(md))
            self.exported_psos[pso_s] = filepath
        except Exception as e:
            print("[rdc_export]   WARNING: Failed to write PSO %s: %s" % (pso_s, e))
        return filepath

    def _export_pso_minimal(self, pso_rid_int):
        pso_s = str(pso_rid_int)
        if pso_s in self.exported_psos:
            return
        filename = self._res_filename(pso_s, ".md", "_PSO")
        filepath = os.path.join(self.output_dir, "pso", filename)
        pso_name = self._res_debug_name(pso_s)

        md = ["# PSO: %s\n" % pso_s]
        md.append("| Property | Value |")
        md.append("|----------|-------|")
        if pso_name:
            md.append("| Name | %s |" % pso_name)
        md.append("| Note | PSO creation data not found in structured file |")
        md.append("")

        shaders = self._pso_shaders.get(pso_rid_int, [])
        if shaders:
            md.append("## Shaders\n")
            md.append("| Stage | Resource ID | File |")
            md.append("|-------|-------------|------|")
            for shader_rid, stage, entry in shaders:
                s_rid_s = rid_str(shader_rid)
                abbrev = STAGE_ABBREV.get(stage, "??")
                stage_name = STAGE_NAME.get(stage, str(stage))
                shader_file = self._export_shader_direct(pso_rid_int, shader_rid, entry, abbrev)
                if shader_file:
                    fname = os.path.basename(shader_file)
                    md.append("| %s | %s | [%s](../shaders/%s) |" % (stage_name, s_rid_s, fname, fname))
                else:
                    md.append("| %s | %s | |" % (stage_name, s_rid_s))
            md.append("")

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(md))
            self.exported_psos[pso_s] = filepath
        except Exception:
            pass

    # -------------------------------------------------------------------
    # 4. Export events (Drawcall / Dispatch) -> events/EID_{n}.md
    # -------------------------------------------------------------------
    def export_events(self, root_actions=None):
        print("[rdc_export] Exporting events ...")
        export_t0 = time.time()

        t0 = time.time()
        if root_actions is None:
            root_actions = self.controller.GetRootActions()
        if self._skip_slateui_title and not self._skip_event_ids:
            self._build_skip_event_ids(root_actions)
        actions = []
        self._collect_draw_dispatch(root_actions, actions)
        if self._eid_min is not None and self._eid_max is not None:
            if self._eid_min == self._eid_max:
                print("[rdc_export]   EID filter: %d" % self._eid_min)
            else:
                print("[rdc_export]   EID filter: %d-%d" % (self._eid_min, self._eid_max))
        collect_dt = time.time() - t0
        total = len(actions)
        if total == 0:
            print("[rdc_export]   No drawcall/dispatch actions matched current filters.")
            return
        target_eids = set(a.eventId for a in actions)
        frame_end_eid = self._max_event_id(root_actions)

        t0 = time.time()
        if self._enable_event_usage_map:
            self._build_event_resource_map(target_eids=target_eids, batch_size=256)
        else:
            print("[rdc_export]   Skipping event usage map (RDC_EXPORT_EVENT_USAGE_MAP=0)")
            self._event_textures = {}
            self._event_buffers = {}
            self._excluded_tex_rids = set()
            self._excluded_buf_rids = set()
        usage_map_dt = time.time() - t0

        t0 = time.time()
        pipe_states = self._parse_structured_pipeline_state(actions)
        parse_state_dt = time.time() - t0

        t0 = time.time()
        self._build_buffer_format_hints(actions)
        build_hints_dt = time.time() - t0

        print("[rdc_export]   Writing %d event files ..." % total)
        self._ensure_dir("events")
        t0 = time.time()
        for i, action in enumerate(actions):
            eid = action.eventId
            action_name = action.GetName(self.sfile)
            if (i + 1) % 100 == 0 or i == 0:
                print("[rdc_export]     %d/%d : EID %d %s" % (
                    i + 1, total, eid, action_name))
            pstate = pipe_states.get(eid, {'pso_rid': None, 'shaders': []})
            try:
                self._export_event_file(action, pstate, action_name=action_name)
            except Exception as e:
                print("[rdc_export]   ERROR: EID %d export failed: %s" % (eid, e))
        write_files_dt = time.time() - t0

        # Restore replay state to frame end.
        if frame_end_eid > 0:
            self._set_frame_event(frame_end_eid, force=True)

        print("[rdc_export]   Stage timing: collect=%.2fs usage_map=%.2fs parse_state=%.2fs hints=%.2fs write=%.2fs total=%.2fs" % (
            collect_dt,
            usage_map_dt,
            parse_state_dt,
            build_hints_dt,
            write_files_dt,
            time.time() - export_t0,
        ))
        # Release usage maps after event export to reduce peak memory
        self._event_textures = {}
        self._event_buffers = {}
        self._event_ia_state = {}
        self._event_cbv_state = {}
        self._buffer_fmt_hints = {}
        self._cbv_length_hints = {}

    def _max_event_id(self, actions):
        max_eid = 0
        stack = list(actions)
        while stack:
            action = stack.pop()
            if action.eventId > max_eid:
                max_eid = action.eventId
            if len(action.children) > 0:
                stack.extend(action.children)
        return max_eid

    def _precache_event_texture_snapshots(self, actions):
        wanted = set()

        for rid_map in self._event_textures.values():
            for rid_s in rid_map.keys():
                wanted.add(rid_s)

        for action in actions:
            for out in action.outputs:
                if out != rd.ResourceId.Null():
                    wanted.add(rid_str(out))
            if action.depthOut != rd.ResourceId.Null():
                wanted.add(rid_str(action.depthOut))

        if not wanted:
            return

        cached = 0
        for rid_s in sorted(wanted):
            tex = self._tex_descs.get(rid_s)
            if tex is None:
                continue
            if tex.width <= 0 or tex.height <= 0:
                continue
            dbg_name = self._res_debug_name(rid_s)
            fn = "%s_%s.png" % (safe_filename(dbg_name or "Texture"), rid_s)
            if self._save_texture_image(tex.resourceId, "textures", fn, track_export=True):
                cached += 1

        print("[rdc_export]   Cached %d/%d texture snapshots for event fallback" % (cached, len(wanted)))

    def _set_frame_event(self, eid, force=False):
        if eid is None:
            return False
        if not force and self._current_event_id == eid:
            return True

        def _set_event_call_succeeded(ret):
            if ret is None:
                return True
            if isinstance(ret, bool):
                return ret
            try:
                if hasattr(rd, "ResultCode") and ret == rd.ResultCode.Succeeded:
                    return True
            except Exception:
                pass
            try:
                if hasattr(rd, "ResultCode") and int(ret) == int(rd.ResultCode.Succeeded):
                    return True
            except Exception:
                pass
            s = str(ret)
            if "Succeeded" in s:
                return True
            return False

        replay_force = force
        if self._current_event_id is None or eid < self._current_event_id:
            replay_force = True

        if self._set_frame_event_one_arg:
            try:
                ret = self.controller.SetFrameEvent(eid)
                if not _set_event_call_succeeded(ret):
                    print("[rdc_export]   WARNING: SetFrameEvent(%d) returned failure: %s" % (eid, ret))
                    return False
                self._current_event_id = eid
                return True
            except Exception as e:
                print("[rdc_export]   WARNING: SetFrameEvent(%d) failed: %s" % (eid, e))
                return False

        try:
            ret = self.controller.SetFrameEvent(eid, replay_force)
            if not _set_event_call_succeeded(ret):
                if not replay_force:
                    try:
                        ret_force = self.controller.SetFrameEvent(eid, True)
                        if _set_event_call_succeeded(ret_force):
                            self._current_event_id = eid
                            return True
                        print("[rdc_export]   WARNING: SetFrameEvent(%d, False) returned failure: %s; retry force=True returned: %s" % (
                            eid, ret, ret_force))
                        return False
                    except Exception as force_err:
                        print("[rdc_export]   WARNING: SetFrameEvent(%d, False) returned failure: %s; retry force=True failed: %s" % (
                            eid, ret, force_err))
                        return False
                print("[rdc_export]   WARNING: SetFrameEvent(%d, force=%s) returned failure: %s" % (
                    eid, "True" if replay_force else "False", ret))
                return False
            self._current_event_id = eid
            return True
        except TypeError:
            # Compatibility path for bindings that expose SetFrameEvent(eventId) only.
            self._set_frame_event_one_arg = True
            try:
                ret = self.controller.SetFrameEvent(eid)
                if not _set_event_call_succeeded(ret):
                    print("[rdc_export]   WARNING: SetFrameEvent(%d) returned failure: %s" % (eid, ret))
                    return False
                self._current_event_id = eid
                return True
            except Exception as e:
                print("[rdc_export]   WARNING: SetFrameEvent(%d) failed: %s" % (eid, e))
                return False
        except Exception as e:
            if not replay_force:
                try:
                    self.controller.SetFrameEvent(eid, True)
                    self._current_event_id = eid
                    return True
                except Exception as force_err:
                    print("[rdc_export]   WARNING: SetFrameEvent(%d, False) failed: %s; retry force=True failed: %s" % (
                        eid, e, force_err))
                    return False
            print("[rdc_export]   WARNING: SetFrameEvent(%d, force=%s) failed: %s" % (
                eid, "True" if replay_force else "False", e))
            return False

    def _event_id_matches_filter(self, eid):
        if self._eid_min is None or self._eid_max is None:
            return True
        return self._eid_min <= eid <= self._eid_max

    def _collect_subtree_event_ids(self, action, out_set):
        stack = [action]
        while stack:
            cur = stack.pop()
            out_set.add(cur.eventId)
            if len(cur.children) > 0:
                stack.extend(cur.children)

    def _build_skip_event_ids(self, actions):
        self._skip_event_ids = set()
        if not self._skip_slateui_title:
            return
        marker_name = re.sub(r"\s+", " ", self._skip_marker_name.strip().lower())
        if not marker_name:
            return

        def _walk(nodes):
            for action in nodes:
                if action.eventId in self._skip_event_ids:
                    continue
                try:
                    name = action.GetName(self.sfile)
                except Exception:
                    name = ""
                name_norm = re.sub(r"\s+", " ", str(name).strip().lower())
                name_match = name_norm.startswith(marker_name) or (marker_name in name_norm)
                if name_match and len(action.children) > 0:
                    self._collect_subtree_event_ids(action, self._skip_event_ids)
                    continue
                if len(action.children) > 0:
                    _walk(action.children)

        _walk(actions)
        if self._skip_event_ids:
            print("[rdc_export]   Ignoring %d events under marker '%s'" % (
                len(self._skip_event_ids), self._skip_marker_name))

    def _get_pre_event_id(self, action):
        prev = getattr(action, "previous", None)
        if prev is not None:
            try:
                return max(0, int(prev.eventId))
            except Exception:
                pass
        return 0

    def _get_post_event_id(self, action):
        try:
            return int(action.eventId)
        except Exception:
            return 0

    def _get_buffer_total_size(self, resource_id):
        rid_s = rid_str(resource_id)
        if rid_s in self._buffer_size_cache:
            return self._buffer_size_cache[rid_s]
        total_size = 0
        if rid_s in self._buf_descs:
            try:
                total_size = int(self._buf_descs[rid_s].length)
            except Exception:
                total_size = 0
        if total_size <= 0:
            total_size = self._detect_buffer_size(resource_id)
        self._buffer_size_cache[rid_s] = max(0, int(total_size))
        return self._buffer_size_cache[rid_s]

    def _normalize_bound_range(self, resource_id, byte_offset, byte_size):
        total_size = self._get_buffer_total_size(resource_id)
        try:
            offset = int(byte_offset)
        except Exception:
            offset = 0
        try:
            size = int(byte_size)
        except Exception:
            size = 0
        if offset < 0:
            offset = 0
        if total_size > 0 and offset > total_size:
            offset = total_size

        whole_markers = (0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)
        if total_size > 0:
            max_len = max(0, total_size - offset)
            if size in whole_markers or size <= 0:
                size = max_len
            else:
                size = min(size, max_len)
        else:
            if size in whole_markers or size <= 0:
                size = 0

        return offset, max(0, size), total_size

    def _merge_bound_range(self, merged, rid_s, offset, length, source):
        if length <= 0:
            return
        end = offset + length
        entry = merged.setdefault(rid_s, {"start": offset, "end": end, "sources": set()})
        if offset < entry["start"]:
            entry["start"] = offset
        if end > entry["end"]:
            entry["end"] = end
        if source:
            entry["sources"].add(source)

    def _refine_cb_bound_range(self, eid, resource_id, rid_s, usages, bind_sources, bind_off, bind_len):
        total_size = self._get_buffer_total_size(resource_id)
        usage_set = set(usages or [])
        source_list = list(bind_sources or [])
        cb_usage = any(str(u).endswith("_CB") for u in usage_set) or \
            any(str(s).endswith("_CB") for s in source_list)
        if not cb_usage:
            return bind_off, bind_len, ""

        new_off = int(bind_off)
        new_len = int(bind_len)
        reason = ""

        cbv_map = self._event_cbv_state.get(eid, {})
        offsets = []
        for item in cbv_map.values():
            if item.get("rid") == rid_s:
                try:
                    offsets.append(int(item.get("offset", 0)))
                except Exception:
                    pass

        if offsets:
            cbv_off = max(0, min(offsets))
            if total_size > 0 and cbv_off > total_size:
                cbv_off = total_size
            hint_len = int(self._cbv_length_hints.get(rid_s, 0) or 0)
            if hint_len > 0 and total_size > 0:
                new_off = cbv_off
                max_len = max(0, total_size - new_off)
                new_len = min(hint_len, max_len)
                reason = "cbv-offset+hint-len"
            elif total_size > 0 and (new_len <= 0 or new_len >= total_size):
                new_off = cbv_off
                reason = "cbv-offset"

        if total_size > 0:
            if new_off < 0:
                new_off = 0
            if new_off > total_size:
                new_off = total_size
            max_len = max(0, total_size - new_off)
            if new_len <= 0 or new_len > max_len:
                new_len = max_len

        return new_off, new_len, reason

    def _buffer_needs_dual_snapshot(self, usages, bind_sources=None):
        usage_set = set(str(u) for u in (usages or []))
        source_set = set(str(s) for s in (bind_sources or []))
        all_tags = usage_set | source_set
        if not all_tags:
            return False

        # UAV binding is read-write by definition for event-level inspection.
        if any(tag.endswith("_UAV") for tag in all_tags):
            return True

        has_write = any(
            tag.endswith("_UAV") or tag == "CopyDst"
            for tag in all_tags
        )
        has_read = any(
            tag.endswith("_SRV") or tag.endswith("_CB") or
            tag == "VB" or tag == "IB" or tag == "Indirect" or tag == "CopySrc"
            for tag in all_tags
        )
        return has_read and has_write

    def _collect_event_bound_resources(self):
        merged_ranges = {}
        tex_rids = set()
        tex_sources = {}  # rid_s -> set(source tags)
        rt_slots = {}     # slot -> rid_s
        depth_rid = None  # rid_s or None
        other_rids = set()

        def _classify_descriptor(desc, source):
            nonlocal depth_rid
            if desc is None:
                return
            rid = getattr(desc, "resource", rd.ResourceId.Null())
            if rid == rd.ResourceId.Null():
                return
            rid_s = rid_str(rid)
            if rid_s in self._buf_descs:
                off = getattr(desc, "byteOffset", 0)
                size = getattr(desc, "byteSize", 0)
                norm_off, norm_len, total_size = self._normalize_bound_range(rid, off, size)
                if norm_len <= 0 and total_size > 0:
                    norm_off = 0
                    norm_len = total_size
                self._merge_bound_range(merged_ranges, rid_s, norm_off, norm_len, source)
            elif rid_s in self._tex_descs:
                tex_rids.add(rid_s)
                src_set = tex_sources.setdefault(rid_s, set())
                src_set.add(str(source))
                src = str(source)
                if src.startswith("RT"):
                    try:
                        slot = int(src[2:])
                        rt_slots[slot] = rid_s
                    except Exception:
                        pass
                elif src == "Depth":
                    depth_rid = rid_s
            else:
                other_rids.add(rid_s)

        try:
            pipe = self.controller.GetPipelineState()
        except Exception:
            pipe = None

        if pipe is not None:
            try:
                ib = pipe.GetIBuffer()
                if getattr(ib, "resourceId", rd.ResourceId.Null()) != rd.ResourceId.Null():
                    norm_off, norm_len, total_size = self._normalize_bound_range(
                        ib.resourceId, getattr(ib, "byteOffset", 0), getattr(ib, "byteSize", 0))
                    if norm_len <= 0 and total_size > 0:
                        norm_off = 0
                        norm_len = total_size
                    self._merge_bound_range(merged_ranges, rid_str(ib.resourceId), norm_off, norm_len, "IB")
            except Exception:
                pass

            try:
                vbs = pipe.GetVBuffers()
                for slot, vb in enumerate(vbs):
                    if getattr(vb, "resourceId", rd.ResourceId.Null()) == rd.ResourceId.Null():
                        continue
                    norm_off, norm_len, total_size = self._normalize_bound_range(
                        vb.resourceId, getattr(vb, "byteOffset", 0), getattr(vb, "byteSize", 0))
                    if norm_len <= 0 and total_size > 0:
                        norm_off = 0
                        norm_len = total_size
                    self._merge_bound_range(
                        merged_ranges, rid_str(vb.resourceId), norm_off, norm_len, "VB%d" % slot)
            except Exception:
                pass

            for stage, abbrev, _ in SHADER_STAGES:
                stage_queries = [
                    ("CB", pipe.GetConstantBlocks),
                    ("SRV", pipe.GetReadOnlyResources),
                    ("UAV", pipe.GetReadWriteResources),
                ]
                for suffix, query_fn in stage_queries:
                    used_descs = []
                    try:
                        used_descs = query_fn(stage, True)
                    except TypeError:
                        try:
                            used_descs = query_fn(stage)
                        except Exception:
                            used_descs = []
                    except Exception:
                        used_descs = []
                    for used in used_descs:
                        _classify_descriptor(getattr(used, "descriptor", None), "%s_%s" % (abbrev, suffix))

            try:
                outputs = pipe.GetOutputTargets()
                for i, desc in enumerate(outputs):
                    _classify_descriptor(desc, "RT%d" % i)
            except Exception:
                pass
            try:
                _classify_descriptor(pipe.GetDepthTarget(), "Depth")
            except Exception:
                pass

        ranges = {}
        for rid_s, item in merged_ranges.items():
            start = max(0, int(item["start"]))
            end = max(start, int(item["end"]))
            ranges[rid_s] = {
                "offset": start,
                "length": end - start,
                "sources": sorted(item["sources"]),
            }
        tex_sources_out = {}
        for rid_s, srcs in tex_sources.items():
            tex_sources_out[rid_s] = sorted(list(srcs))

        return {
            "textures": tex_rids,
            "texture_sources": tex_sources_out,
            "rt_slots": rt_slots,
            "depth_rid": depth_rid,
            "buffers": ranges,
            "others": other_rids,
        }

    def _choose_cb_layout(self, rid_s, cb_size):
        try:
            cb_size = int(cb_size)
        except Exception:
            return None, "invalid-size", 0, 0
        if cb_size <= 0:
            return None, "invalid-size", 0, 0

        def _pick(layouts):
            if not layouts:
                return None
            if len(layouts) == 1:
                return layouts[0]
            debug_name_norm = _normalize_name(self._res_debug_name(rid_s))
            if debug_name_norm:
                for cb in layouts:
                    try:
                        cb_name = cb.name if cb.name else ""
                    except Exception:
                        cb_name = ""
                    cb_name_norm = _normalize_name(cb_name)
                    if cb_name_norm and (cb_name_norm in debug_name_norm or debug_name_norm in cb_name_norm):
                        return cb
            return layouts[0]

        layouts = self._cb_layouts.get(cb_size, [])
        if not layouts:
            cb_sizes = sorted([int(s) for s in self._cb_layouts.keys() if int(s) > 0])
            if not cb_sizes:
                return None, "no-layout", 0, 0
            le_sizes = [s for s in cb_sizes if s < cb_size]
            if le_sizes:
                use_size = le_sizes[-1]
                picked = _pick(self._cb_layouts.get(use_size, []))
                if picked is not None:
                    return picked, "fallback-le", use_size, len(self._cb_layouts.get(use_size, []))
            gt_sizes = [s for s in cb_sizes if s > cb_size]
            if gt_sizes:
                use_size = gt_sizes[0]
                picked = _pick(self._cb_layouts.get(use_size, []))
                if picked is not None:
                    return picked, "fallback-gt", use_size, len(self._cb_layouts.get(use_size, []))
            return None, "no-layout", 0, 0

        picked = _pick(layouts)
        if picked is None:
            return None, "exact-empty", cb_size, 0
        if len(layouts) == 1:
            return picked, "exact-single", cb_size, 1
        return picked, "exact-multi", cb_size, len(layouts)

    def _iter_buffer_chunks_range(self, resource_id, start_offset, total_size, chunk_size=4 * 1024 * 1024):
        if total_size <= 0:
            return
        consumed = 0
        while consumed < total_size:
            read_size = min(chunk_size, total_size - consumed)
            if read_size <= 0:
                break
            chunk = self._read_buffer_slice(resource_id, start_offset + consumed, read_size)
            if len(chunk) == 0:
                break
            yield consumed, chunk
            consumed += len(chunk)
            if len(chunk) < read_size:
                break

    def _export_buffer_snapshot(self, resource_id, eid, phase, bind_offset, bind_length,
                                usages=None, bind_sources=None):
        rid_s = rid_str(resource_id)
        bound_off, bound_len, total_size = self._normalize_bound_range(resource_id, bind_offset, bind_length)
        if bound_len <= 0 and total_size > 0:
            bound_off = 0
            bound_len = total_size
        usage_set = set(str(u) for u in (usages or []))
        source_list = [str(s) for s in (bind_sources or [])]
        cb_usage = any(u.endswith("_CB") for u in usage_set) or \
            any(s.endswith("_CB") for s in source_list)
        srv_uav_usage = any(u.endswith("_SRV") or u.endswith("_UAV") for u in usage_set) or \
            any(s.endswith("_SRV") or s.endswith("_UAV") for s in source_list)
        ib_usage = ("IB" in usage_set) or any(s == "IB" for s in source_list)
        vb_usage = ("VB" in usage_set) or any(s.startswith("VB") for s in source_list)

        cb_layout = None
        cb_layout_reason = ""
        cb_layout_size = 0
        cb_layout_count = 0
        if cb_usage and bound_len > 0:
            cb_layout, cb_layout_reason, cb_layout_size, cb_layout_count = self._choose_cb_layout(rid_s, bound_len)

        struct_stride = None
        struct_layout = None
        struct_reason = ""
        if cb_layout is None and srv_uav_usage and bound_len > 0:
            struct_stride, struct_layout, struct_reason = self._choose_struct_layout(rid_s, bound_len)

        ia_hint = self._buffer_fmt_hints.get(rid_s, {})
        ia_ib_format = ia_hint.get("ib_format") if ib_usage else None
        ia_vb_stride = ia_hint.get("vb_stride") if vb_usage else None

        fmt_key = "hex"
        if cb_layout is not None:
            cb_sig = ""
            try:
                cb_sig = repr(_member_signature(cb_layout.variables))
            except Exception:
                cb_sig = "nosig"
            fmt_key = "cb:%s:%s:%s" % (int(cb_layout_size), cb_layout_reason, cb_sig)
        elif struct_layout is not None and struct_stride is not None and struct_stride > 0:
            fmt_key = "struct:%d:%s:%s" % (
                int(struct_stride),
                struct_layout.get("name", ""),
                repr(struct_layout.get("signature", "")),
            )
        elif ia_ib_format is not None:
            fmt_key = "ia_ib:%d" % int(ia_ib_format)
        elif ia_vb_stride is not None:
            fmt_key = "ia_vb:%d" % int(ia_vb_stride)
        elif cb_usage:
            fmt_key = "hex:cb-no-layout:%s" % cb_layout_reason
        elif srv_uav_usage:
            fmt_key = "hex:struct-%s" % (struct_reason or "none")

        data_hash, dumped = self._hash_buffer_range_sha1(resource_id, bound_off, bound_len)
        phase_tag = safe_filename(str(phase or "state"))
        state_hash = self._snapshot_key_hash(
            rid_s, phase_tag, int(bound_off), int(bound_len), fmt_key, data_hash, int(dumped))
        cache_key = (
            rid_s, phase_tag, int(bound_off), int(bound_len), fmt_key, data_hash, int(dumped))
        cached_name = self._buffer_snapshot_cache.get(cache_key)
        if cached_name:
            cached_path = os.path.join(self.output_dir, "buffers", cached_name)
            if os.path.isfile(cached_path) and os.path.getsize(cached_path) > 0:
                return cached_name

        filename = "BUF_%s_O%d_L%d_%s_%s.md" % (
            rid_s, int(bound_off), int(bound_len), phase_tag, state_hash[:16])
        filepath = os.path.join(self.output_dir, "buffers", filename)
        if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
            self._buffer_snapshot_cache[cache_key] = filename
            self._snapshot_buffer_files.add(filename)
            return filename

        self._ensure_dir("buffers")
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("# Buffer Snapshot: %s\n\n" % rid_s)
                f.write("| Property | Value |\n")
                f.write("|----------|-------|\n")
                name = self._res_debug_name(rid_s)
                if name:
                    f.write("| Name | %s |\n" % name)
                f.write("| First Seen Event | %d |\n" % int(eid))
                f.write("| Phase | %s |\n" % phase)
                f.write("| Full Size | %d bytes |\n" % total_size)
                f.write("| Bound Offset | %d |\n" % int(bound_off))
                f.write("| Bound Length | %d |\n" % int(bound_len))
                f.write("| Bound End | %d |\n" % int(bound_off + bound_len))
                f.write("| State Hash | `%s` |\n" % state_hash[:20])
                if usages:
                    f.write("| Usage | %s |\n" % ", ".join(sorted(usage_set)))
                if bind_sources:
                    f.write("| Bind Sources | %s |\n" % ", ".join(source_list))
                f.write("\n")

                if cb_layout is not None:
                    cb_name = cb_layout.name if hasattr(cb_layout, "name") and cb_layout.name else "unnamed"
                    f.write("## Constant Buffer (%s)\n\n" % cb_name)
                    f.write("_Layout size: %d, bound length: %d, match: %s_\n\n" % (
                        int(cb_layout_size), int(bound_len), cb_layout_reason))
                    chunk_cache = {}
                    decode_limit = total_size
                    try:
                        decode_limit = min(total_size, int(bound_off) + int(bound_len))
                    except Exception:
                        decode_limit = total_size
                    decode_stats = {"ok": 0, "fail": 0}
                    cols = _build_struct_columns(cb_layout.variables)
                    vals = []
                    for _, col_rel, col_stype in cols:
                        val = self._decode_value_from_buffer(
                            resource_id, int(bound_off) + int(col_rel), col_stype, decode_limit, chunk_cache)
                        if val is None:
                            decode_stats["fail"] = int(decode_stats.get("fail", 0)) + 1
                        else:
                            decode_stats["ok"] = int(decode_stats.get("ok", 0)) + 1
                        vals.append(_md_escape_cell(_format_value(val)))

                    if decode_stats.get("ok", 0) > 0 and cols:
                        f.write("| Index | %s |\n" % " | ".join(_md_escape_cell(c[0]) for c in cols))
                        f.write("|-------|%s|\n" % "|".join(["---"] * len(cols)))
                        f.write("| 0 | %s |\n\n" % " | ".join(vals))
                    else:
                        f.write("*(warning: constant buffer decode failed for all fields, fallback to hex dump)*\n\n")
                        f.write("## Data (Hex, bound range)\n\n")
                        f.write("```\n")
                        dumped_local = 0
                        for rel_off, chunk in self._iter_buffer_chunks_range(
                                resource_id, bound_off, bound_len):
                            abs_off = bound_off + rel_off
                            f.write(hex_dump(chunk, abs_off))
                            f.write("\n")
                            dumped_local = rel_off + len(chunk)
                        if dumped_local < bound_len:
                            f.write("... (warning: expected %d bytes, dumped %d bytes) ...\n" % (
                                bound_len, dumped_local))
                        f.write("```\n")

                elif struct_layout is not None and struct_stride is not None and struct_stride > 0:
                    members = struct_layout.get('members', [])
                    sname = struct_layout.get('name', 'unnamed')
                    num_elements = int(bound_len) // int(struct_stride)
                    f.write("\n".join(_format_struct_definition(sname, members)))
                    f.write("\n")
                    f.write("## Data (%d elements, stride %d, bound range)\n\n" % (
                        num_elements, struct_stride))

                    cols = _build_struct_columns(members)
                    if cols:
                        f.write("| Index | %s |\n" % " | ".join(_md_escape_cell(c[0]) for c in cols))
                        f.write("|-------|%s|\n" % "|".join(["---"] * len(cols)))
                    else:
                        f.write("*(warning: no leaf members found in struct layout, fallback to hex dump)*\n\n")
                        f.write("## Data (Hex, bound range)\n\n")
                        f.write("```\n")
                        dumped_local = 0
                        for rel_off, chunk in self._iter_buffer_chunks_range(
                                resource_id, bound_off, bound_len):
                            abs_off = bound_off + rel_off
                            f.write(hex_dump(chunk, abs_off))
                            f.write("\n")
                            dumped_local = rel_off + len(chunk)
                        if dumped_local < bound_len:
                            f.write("... (warning: expected %d bytes, dumped %d bytes) ...\n" % (
                                bound_len, dumped_local))
                        f.write("```\n")
                        cols = []

                    chunk_bytes = max(
                        struct_stride, (4 * 1024 * 1024 // struct_stride) * struct_stride)
                    if chunk_bytes <= 0:
                        chunk_bytes = struct_stride

                    processed = bound_len if not cols else 0
                    if cols:
                        chunk_iter = self._iter_buffer_chunks_range(
                            resource_id, bound_off, bound_len, chunk_bytes)
                        for rel_off, chunk in chunk_iter:
                            valid_len = len(chunk) - (len(chunk) % struct_stride)
                            if valid_len <= 0:
                                continue
                            processed = max(processed, rel_off + valid_len)
                            elem_base = rel_off // struct_stride
                            elem_count = valid_len // struct_stride
                            for local_idx in range(elem_count):
                                global_idx = elem_base + local_idx
                                local_offset = local_idx * struct_stride
                                vals = []
                                for _, col_rel, col_stype in cols:
                                    val = _decode_value(chunk, local_offset + col_rel, col_stype)
                                    vals.append(_md_escape_cell(_format_value(val)))
                                f.write("| %d | %s |\n" % (global_idx, " | ".join(vals)))
                    if cols:
                        f.write("\n")
                    if cols and processed < bound_len:
                        f.write("*(warning: expected %d bytes, parsed %d bytes)*\n\n" % (
                            bound_len, processed))

                elif ia_ib_format is not None and self._write_index_data_formatted(
                        f, resource_id, bound_len, ia_ib_format, start_offset=bound_off):
                    f.write("*(info: format inferred from IA index binding)*\n\n")

                elif ia_vb_stride is not None and self._write_vertex_data_formatted(
                        f, resource_id, bound_len, ia_vb_stride, start_offset=bound_off):
                    f.write("*(info: format inferred from IA vertex binding stride)*\n\n")

                else:
                    if struct_reason == "ambiguous":
                        f.write("*(info: structured layout ambiguous in this bound range, fallback to hex dump)*\n\n")
                    elif srv_uav_usage:
                        f.write("*(info: no structured shader layout matched this bound range, fallback to hex dump)*\n\n")
                    f.write("## Data (Hex, bound range)\n\n")
                    f.write("```\n")
                    dumped_local = 0
                    for rel_off, chunk in self._iter_buffer_chunks_range(
                            resource_id, bound_off, bound_len):
                        abs_off = bound_off + rel_off
                        f.write(hex_dump(chunk, abs_off))
                        f.write("\n")
                        dumped_local = rel_off + len(chunk)
                    if dumped_local < bound_len:
                        f.write("... (warning: expected %d bytes, dumped %d bytes) ...\n" % (
                            bound_len, dumped_local))
                    f.write("```\n")

            self._buffer_snapshot_cache[cache_key] = filename
            self._snapshot_buffer_files.add(filename)
            return filename
        except Exception as e:
            print("[rdc_export]   WARNING: Failed to export buffer snapshot %s: %s" % (rid_s, e))
            return None

    def _export_other_resource_snapshot(self, rid_s, eid, phase):
        filename = "EID_%d_RES_%s_%s.md" % (eid, rid_s, phase)
        filepath = os.path.join(self.output_dir, "resources", filename)
        if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
            return filename
        self._ensure_dir("resources")
        try:
            name = self._res_debug_name(rid_s)
            rtype = ""
            if rid_s in self._res_descs:
                try:
                    rtype = str(self._res_descs[rid_s].type)
                except Exception:
                    rtype = ""
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("# Resource Snapshot: %s\n\n" % rid_s)
                f.write("| Property | Value |\n")
                f.write("|----------|-------|\n")
                f.write("| Event | %d |\n" % eid)
                f.write("| Phase | %s |\n" % phase)
                if name:
                    f.write("| Name | %s |\n" % name)
                if rtype:
                    f.write("| Type | %s |\n" % rtype)
                f.write("\n")
                f.write("Binary state export is not available for this resource type in this script.\n")
            return filename
        except Exception as e:
            print("[rdc_export]   WARNING: Failed to export resource snapshot %s: %s" % (rid_s, e))
            return None

    def _collect_draw_dispatch(self, actions, out):
        for action in actions:
            if action.eventId in self._skip_event_ids:
                continue
            if (action.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.Dispatch)) and \
               self._event_id_matches_filter(action.eventId):
                out.append(action)
            if len(action.children) > 0:
                self._collect_draw_dispatch(action.children, out)

    def _export_event_file(self, action, pstate, action_name=None):
        eid = action.eventId
        pre_eid = self._get_pre_event_id(action)
        post_eid = self._get_post_event_id(action)
        name = action_name if action_name is not None else action.GetName(self.sfile)
        is_compute = bool(action.flags & rd.ActionFlags.Dispatch)
        pso_rid = pstate.get('pso_rid')
        shaders = pstate.get('shaders', [])

        if pso_rid is not None and str(pso_rid) not in self.exported_psos:
            try:
                self._export_pso_minimal(pso_rid)
            except Exception as e:
                print("[rdc_export]   WARNING: Failed to export minimal PSO %s: %s" % (pso_rid, e))

        # Prime shader reflection metadata before buffer snapshot export so
        # CB/struct layouts are available for this event's bound ranges.
        for shader_rid, stage, entry in shaders:
            try:
                abbrev = STAGE_ABBREV.get(stage, "??")
                self._cache_shader_metadata(pso_rid, shader_rid, entry, abbrev)
            except Exception:
                pass

        set_event_ok = self._set_frame_event(eid)
        if not set_event_ok:
            print("[rdc_export]   WARNING: EID %d export may use stale replay state." % eid)
        bound_info = self._collect_event_bound_resources()

        tex_refs = {}
        for rid_s, usages in self._event_textures.get(eid, {}).items():
            tex_refs[rid_s] = set(usages)

        buf_refs = {}
        for rid_s, usages in self._event_buffers.get(eid, {}).items():
            buf_refs[rid_s] = set(usages)

        # Prefer usage-map references, but always merge current pipeline bindings as
        # a safety net since GetUsage(eventId) can miss bindings on some captures.
        other_refs = set()
        if not self._enable_event_usage_map:
            for rid_s in bound_info.get("buffers", {}).keys():
                buf_refs.setdefault(rid_s, set()).add("Bound")
            other_refs.update(bound_info.get("others", set()))

        bound_tex_sources = bound_info.get("texture_sources", {})
        for rid_s, srcs in bound_tex_sources.items():
            if rid_s not in self._tex_descs:
                continue
            tags = set(str(s) for s in (srcs or []))
            if not tags:
                tex_refs.setdefault(rid_s, set()).add("Bound")
                continue
            for src in tags:
                if src.startswith("RT") or src == "Depth":
                    continue
                if src.endswith("_SRV"):
                    tex_refs.setdefault(rid_s, set()).add("BoundSRV")
                elif src.endswith("_UAV"):
                    tex_refs.setdefault(rid_s, set()).add("BoundUAV")
                else:
                    tex_refs.setdefault(rid_s, set()).add("Bound")

        # Ensure non-texture resources discovered from current pipeline are still listed.
        other_refs.update(bound_info.get("others", set()))

        def _append_resource_ref(resource_id, usage_tag):
            if resource_id == rd.ResourceId.Null():
                return
            rid_s = rid_str(resource_id)
            if rid_s in self._tex_descs:
                tex_refs.setdefault(rid_s, set()).add(usage_tag)
            elif rid_s in self._buf_descs:
                buf_refs.setdefault(rid_s, set()).add(usage_tag)
            else:
                other_refs.add(rid_s)

        _append_resource_ref(action.copySource, "CopySrc")
        _append_resource_ref(action.copyDestination, "CopyDst")

        # Build RT/depth bindings with fallbacks:
        # - primary: action outputs/depth
        # - fallback: current pipeline state bindings for this event
        rt_slot_resources = {}  # slot -> rd.ResourceId
        for i, out_rid in enumerate(action.outputs):
            if out_rid != rd.ResourceId.Null():
                rt_slot_resources[i] = out_rid

        for slot, rid_s in bound_info.get("rt_slots", {}).items():
            if slot in rt_slot_resources:
                continue
            tex = self._tex_descs.get(rid_s)
            if tex is not None and tex.resourceId != rd.ResourceId.Null():
                rt_slot_resources[int(slot)] = tex.resourceId

        depth_resource = action.depthOut
        if depth_resource == rd.ResourceId.Null():
            depth_rid_s = bound_info.get("depth_rid")
            if depth_rid_s:
                tex = self._tex_descs.get(depth_rid_s)
                if tex is not None:
                    depth_resource = tex.resourceId

        rt_after = {}
        depth_after = None
        tex_files = {}   # rid_s -> {"before": str|None, "after": str|None}
        buf_files = {}   # rid_s -> {"before": str|None, "after": str|None, "offset": int, "length": int, "dual_phase": bool}
        other_files = {} # rid_s -> {"before": str|None, "after": str|None}

        def _rid_sort_key(rid_s):
            try:
                return (0, int(rid_s))
            except Exception:
                return (1, rid_s)

        for rid_s in sorted(tex_refs.keys(), key=_rid_sort_key):
            tex_files[rid_s] = {"before": None, "after": None}

        for rid_s in sorted(buf_refs.keys(), key=_rid_sort_key):
            if rid_s not in self._buf_descs:
                buf_files[rid_s] = {"before": None, "after": None, "offset": 0, "length": 0, "dual_phase": False}
                continue
            buf = self._buf_descs[rid_s]
            bind = bound_info.get("buffers", {}).get(rid_s, {})
            bind_off = int(bind.get("offset", 0) or 0)
            bind_len = int(bind.get("length", 0) or 0)
            bind_sources = bind.get("sources", [])
            if bind_len <= 0:
                bind_len = self._get_buffer_total_size(buf.resourceId)
            bind_off, bind_len, _ = self._refine_cb_bound_range(
                eid, buf.resourceId, rid_s, buf_refs.get(rid_s, set()), bind_sources, bind_off, bind_len)
            dual_phase = self._buffer_needs_dual_snapshot(
                buf_refs.get(rid_s, set()), bind_sources)
            buf_files[rid_s] = {
                "before": None,
                "after": None,
                "offset": bind_off,
                "length": bind_len,
                "dual_phase": dual_phase,
            }

        for rid_s in sorted(other_refs, key=_rid_sort_key):
            other_files[rid_s] = {"before": None, "after": None}

        dual_phase_buffers = set(
            rid_s for rid_s, item in buf_files.items() if item.get("dual_phase"))

        # Only keep pre/post dual snapshots for buffers that are both input and output.
        if dual_phase_buffers:
            if not self._set_frame_event(pre_eid, force=(pre_eid == 0)):
                print("[rdc_export]   WARNING: Failed to replay pre-event state for EID %d (pre=%d)" % (
                    eid, pre_eid))

            for rid_s in sorted(dual_phase_buffers, key=_rid_sort_key):
                if rid_s not in self._buf_descs:
                    continue
                buf = self._buf_descs[rid_s]
                item = buf_files.get(rid_s, {})
                bind = bound_info.get("buffers", {}).get(rid_s, {})
                bind_sources = bind.get("sources", [])
                bind_off = int(item.get("offset", bind.get("offset", 0) or 0))
                bind_len = int(item.get("length", bind.get("length", 0) or 0))
                if bind_len <= 0:
                    bind_len = self._get_buffer_total_size(buf.resourceId)
                bind_off, bind_len, _ = self._refine_cb_bound_range(
                    eid, buf.resourceId, rid_s, buf_refs.get(rid_s, set()), bind_sources, bind_off, bind_len)
                item["offset"] = bind_off
                item["length"] = bind_len
                item["before"] = self._export_buffer_snapshot(
                    buf.resourceId, eid, "before", bind_off, bind_len,
                    usages=buf_refs.get(rid_s, set()), bind_sources=bind_sources)
                buf_files[rid_s] = item

        # Snapshot "after drawcall" state (current event).
        post_event_ok = self._set_frame_event(post_eid)
        if not post_event_ok:
            print("[rdc_export]   WARNING: Failed to replay event state for EID %d (post=%d)" % (
                eid, post_eid))

        for i in sorted(rt_slot_resources.keys()):
            out_rid = rt_slot_resources.get(i, rd.ResourceId.Null())
            if out_rid == rd.ResourceId.Null():
                continue
            post_fn = self._export_texture_snapshot(
                out_rid, "render_targets", eid, "after", role="rt%d" % i)
            rt_after[i] = post_fn
        if depth_resource != rd.ResourceId.Null():
            depth_after = self._export_texture_snapshot(
                depth_resource, "render_targets", eid, "after", role="depth")

        for rid_s in sorted(tex_refs.keys(), key=_rid_sort_key):
            if rid_s not in self._tex_descs:
                tex_files.setdefault(rid_s, {"before": None, "after": None})
                continue
            tex = self._tex_descs[rid_s]
            if tex.width <= 0 or tex.height <= 0:
                tex_files.setdefault(rid_s, {"before": None, "after": None})
                continue
            post_fn = self._export_texture_snapshot(
                tex.resourceId, "textures", eid, "after", role="tex")
            tex_files.setdefault(rid_s, {"before": None, "after": None})
            tex_files[rid_s]["after"] = post_fn

        for rid_s in sorted(buf_refs.keys(), key=_rid_sort_key):
            if rid_s not in self._buf_descs:
                continue
            buf = self._buf_descs[rid_s]
            item = buf_files.setdefault(
                rid_s, {"before": None, "after": None, "offset": 0, "length": 0, "dual_phase": False})
            bind = bound_info.get("buffers", {}).get(rid_s, {})
            bind_off = int(item.get("offset", bind.get("offset", 0) or 0))
            bind_len = int(item.get("length", bind.get("length", 0) or 0))
            if bind_len <= 0:
                bind_len = self._get_buffer_total_size(buf.resourceId)
                item["length"] = bind_len
            bind_sources = bind.get("sources", [])
            bind_off, bind_len, _ = self._refine_cb_bound_range(
                eid, buf.resourceId, rid_s, buf_refs.get(rid_s, set()), bind_sources, bind_off, bind_len)
            item["offset"] = bind_off
            item["length"] = bind_len
            post_fn = self._export_buffer_snapshot(
                buf.resourceId, eid, "after", bind_off, bind_len,
                usages=buf_refs.get(rid_s, set()), bind_sources=bind_sources)
            item["after"] = post_fn

        for rid_s in sorted(other_refs, key=_rid_sort_key):
            post_fn = self._export_other_resource_snapshot(rid_s, eid, "after")
            other_files.setdefault(rid_s, {"before": None, "after": None})
            other_files[rid_s]["after"] = post_fn

        md = ["# EID %d: %s\n" % (eid, name)]

        # ---- Pipeline ----
        md.append("## Pipeline\n")
        md.append("| Property | Value |")
        md.append("|----------|-------|")
        md.append("| Pre-Event | %d |" % pre_eid)
        if pso_rid is not None:
            pso_s = str(pso_rid)
            if pso_s in self.exported_psos:
                pso_fn = os.path.basename(self.exported_psos[pso_s])
                md.append("| PSO | [%s](../pso/%s) |" % (pso_s, pso_fn))
            else:
                md.append("| PSO | %s |" % pso_s)
        if is_compute:
            md.append("| Dispatch | %dx%dx%d |" % action.dispatchDimension)
        else:
            md.append("| Indices | %d |" % action.numIndices)
            md.append("| Instances | %d |" % action.numInstances)
        md.append("")

        # ---- Shaders ----
        md.append("## Shaders\n")
        md.append("| Stage | Resource ID | File |")
        md.append("|-------|-------------|------|")
        if shaders:
            for shader_rid, stage, entry in shaders:
                rid_s = rid_str(shader_rid)
                abbrev = STAGE_ABBREV.get(stage, "??")
                stage_name = STAGE_NAME.get(stage, str(stage))
                shader_file = self._export_shader_direct(pso_rid, shader_rid, entry, abbrev)
                if shader_file:
                    fname = os.path.basename(shader_file)
                    md.append("| %s | %s | [%s](../shaders/%s) |" % (stage_name, rid_s, fname, fname))
                else:
                    md.append("| %s | %s | *(export failed)* |" % (stage_name, rid_s))
        else:
            md.append("| *(none)* | | |")
        md.append("")

        # ---- Shader Bindings ----
        has_bindings = False
        binding_lines = []
        if shaders:
            for shader_rid, stage, entry in shaders:
                rid_s = rid_str(shader_rid)
                abbrev = STAGE_ABBREV.get(stage, "??")
                cached = self._cache_shader_metadata(pso_rid, shader_rid, entry, abbrev)
                if cached is not None:
                    _, srvs, uavs, cbs = cached
                    all_binds = []
                    for bname, reg in srvs:
                        all_binds.append((reg, bname, "SRV"))
                    for bname, reg in uavs:
                        all_binds.append((reg, bname, "UAV"))
                    for bname, reg in cbs:
                        all_binds.append((reg, bname, "CB"))
                    if all_binds:
                        has_bindings = True
                        binding_lines.append("### %s Bindings\n" % abbrev)
                        binding_lines.append("| Register | Name | Type |")
                        binding_lines.append("|----------|------|------|")
                        for reg, bname, btype in all_binds:
                            binding_lines.append("| %s | %s | %s |" % (reg, bname, btype))
                        binding_lines.append("")
        if has_bindings:
            md.extend(binding_lines)

        # ---- Render Targets ----
        has_rts = False
        rt_lines = ["## Render Targets\n",
                     "| Slot | Resource ID | Name | Format | Snapshot |",
                     "|------|-------------|------|--------|----------|"]
        for i in sorted(rt_slot_resources.keys()):
            out_rid = rt_slot_resources.get(i, rd.ResourceId.Null())
            if out_rid == rd.ResourceId.Null():
                continue
            has_rts = True
            rid_s = rid_str(out_rid)
            dname = self._res_debug_name(rid_s)
            tex_info = self._tex_info_str(rid_s)
            post_fn = rt_after.get(i)
            post_link = "[%s](../render_targets/%s)" % (post_fn, post_fn) if post_fn else ""
            rt_lines.append("| RT%d | %s | %s | %s | %s |" % (
                i, rid_s, dname, tex_info, post_link))
        if depth_resource != rd.ResourceId.Null():
            has_rts = True
            rid_s = rid_str(depth_resource)
            dname = self._res_debug_name(rid_s)
            tex_info = self._tex_info_str(rid_s)
            post_link = "[%s](../render_targets/%s)" % (depth_after, depth_after) if depth_after else ""
            rt_lines.append("| Depth | %s | %s | %s | %s |" % (
                rid_s, dname, tex_info, post_link))
        if has_rts:
            md.extend(rt_lines)
            md.append("")

        # ---- Textures ----
        if tex_refs:
            md.append("## Textures\n")
            md.append("| Resource ID | Name | Usage | Format | Snapshot |")
            md.append("|-------------|------|-------|--------|----------|")
            for rid_s in sorted(tex_refs.keys(), key=_rid_sort_key):
                usages = tex_refs.get(rid_s, set())
                uname = ", ".join(sorted(usages))
                dname = self._res_debug_name(rid_s)
                tex_info = self._tex_info_str(rid_s)
                files = tex_files.get(rid_s, {"before": None, "after": None})
                post_fn = files.get("after")
                post_link = "[%s](../textures/%s)" % (post_fn, post_fn) if post_fn else ""
                if rid_s in self._tex_descs:
                    tex = self._tex_descs[rid_s]
                    if tex.width > 0 and tex.height > 0:
                        md.append("| %s | %s | %s | %s | %s |" % (
                            rid_s, dname, uname, tex_info, post_link))
                    else:
                        md.append("| %s | %s | %s | %s | |" % (rid_s, dname, uname, tex_info))
                else:
                    md.append("| %s | %s | %s | | |" % (rid_s, dname, uname))
            md.append("")

        # ---- Buffers ----
        if buf_refs:
            md.append("## Buffers\n")
            md.append("| Resource ID | Name | Usage | Size | Bind Offset | Bind Length | Before | After |")
            md.append("|-------------|------|-------|------|-------------|-------------|--------|-------|")
            for rid_s in sorted(buf_refs.keys(), key=_rid_sort_key):
                usages = buf_refs.get(rid_s, set())
                uname = ", ".join(sorted(usages))
                dname = self._res_debug_name(rid_s)
                buf_info = self._buf_info_str(rid_s)
                b = buf_files.get(rid_s, {"before": None, "after": None, "offset": 0, "length": 0})
                bind_off = int(b.get("offset", 0) or 0)
                bind_len = int(b.get("length", 0) or 0)
                pre_fn = b.get("before")
                post_fn = b.get("after")
                pre_link = "[%s](../buffers/%s)" % (pre_fn, pre_fn) if pre_fn else ""
                post_link = "[%s](../buffers/%s)" % (post_fn, post_fn) if post_fn else ""
                if rid_s in self._buf_descs:
                    buf = self._buf_descs[rid_s]
                    if buf.length > 0:
                        md.append("| %s | %s | %s | %s | %d | %d | %s | %s |" % (
                            rid_s, dname, uname, buf_info, bind_off, bind_len, pre_link, post_link))
                    else:
                        md.append("| %s | %s | %s | 0 bytes | %d | %d | %s | %s |" % (
                            rid_s, dname, uname, bind_off, bind_len, pre_link, post_link))
                else:
                    md.append("| %s | %s | %s | | %d | %d | %s | %s |" % (
                        rid_s, dname, uname, bind_off, bind_len, pre_link, post_link))
            md.append("")

        # ---- Other resources ----
        if other_refs:
            md.append("## Other Resources\n")
            md.append("| Resource ID | Name | Type | Snapshot |")
            md.append("|-------------|------|------|----------|")
            for rid_s in sorted(other_refs, key=_rid_sort_key):
                dname = self._res_debug_name(rid_s)
                rtype = ""
                if rid_s in self._res_descs:
                    try:
                        rtype = str(self._res_descs[rid_s].type)
                    except Exception:
                        rtype = ""
                files = other_files.get(rid_s, {"before": None, "after": None})
                post_fn = files.get("after")
                post_link = "[%s](../resources/%s)" % (post_fn, post_fn) if post_fn else ""
                md.append("| %s | %s | %s | %s |" % (
                    rid_s, dname, rtype, post_link))
            md.append("")

        self._write_file("\n".join(md), "events", "EID_%d.md" % eid)

    # -------------------------------------------------------------------
    # 5. Export Shader (with DebugName_ID_Stage.md naming)
    # -------------------------------------------------------------------
    def _export_shader_direct(self, pso_rid_int, shader_rid, entry_point, abbrev):
        if shader_rid is None:
            return None
        rid_s = rid_str(shader_rid)
        key = "%s_%s" % (rid_s, abbrev)
        if key in self.exported_shaders:
            return self.exported_shaders[key]
        cached = self._cache_shader_metadata(pso_rid_int, shader_rid, entry_point, abbrev)
        if cached is None:
            return None
        entry_name, srvs, uavs, cbs = cached
        self._ensure_dir("shaders")
        filename = self._res_filename(rid_s, ".md", "_%s" % abbrev)
        filepath = os.path.join(self.output_dir, "shaders", filename)
        try:
            pso_s = str(pso_rid_int) if pso_rid_int is not None else ""
            if not pso_s or pso_s not in self._res_descs:
                return None
            pso_rid = self._res_descs[pso_s].resourceId
            refl = self.controller.GetShader(pso_rid, shader_rid, entry_point)
            if refl is None:
                return None
            self._cache_layouts_from_refl(refl)
            source_files, source_encoding, source_kind = self._extract_shader_sources(refl)
            source_encoding_name = self._shader_encoding_name(source_encoding)
            source_lang = self._shader_code_lang(source_encoding_name)

            target_label = ""
            disasm = ""
            disasm_lang = "txt"
            if not source_files:
                target = self._preferred_disasm_target
                disasm = None
                if target:
                    disasm = self.controller.DisassembleShader(pso_rid, refl, target)
                if (disasm is None or disasm == "") and target != "":
                    target = ""
                    disasm = self.controller.DisassembleShader(pso_rid, refl, target)
                if (disasm is None or disasm == "") and len(self._disasm_targets) > 0:
                    fallback_target = str(self._disasm_targets[0])
                    if fallback_target != target:
                        target = fallback_target
                        disasm = self.controller.DisassembleShader(pso_rid, refl, target)
                if disasm is None:
                    disasm = ""
                target_label = target if target else "Default"
                disasm_lang = "hlsl" if (target == "" or "hlsl" in target.lower()) else "txt"

            md = ["# Shader: %s (%s)\n" % (rid_s, abbrev),
                  "| Property | Value |",
                  "|----------|-------|",
                  "| Stage | %s |" % abbrev,
                  "| Entry Point | %s |" % (entry_name or "N/A")]
            if source_files:
                md.append("| Content | Source |")
                md.append("| Source Encoding | %s |" % source_encoding_name)
                md.append("| Source Kind | %s |" % source_kind)
            else:
                md.append("| Content | Disassembly |")
                md.append("| Disassembly Target | %s |" % target_label)
            md.append("")

            # Resource bindings
            all_binds = []
            for bname, reg in srvs:
                all_binds.append((reg, bname, "SRV"))
            for bname, reg in uavs:
                all_binds.append((reg, bname, "UAV"))
            for bname, reg in cbs:
                all_binds.append((reg, bname, "CB"))
            if all_binds:
                md.append("## Resource Bindings\n")
                md.append("| Register | Name | Type |")
                md.append("|----------|------|------|")
                for reg, bname, btype in all_binds:
                    md.append("| %s | %s | %s |" % (reg, bname, btype))
                md.append("")

            if source_files:
                md.append("## Source\n")
                md.append("_Source is preferred over disassembly when available._\n")
                for i, (src_name, src_text) in enumerate(source_files):
                    if len(source_files) > 1:
                        md.append("### File %d: %s\n" % (i, src_name))
                    md.append("```%s" % source_lang)
                    md.append(src_text)
                    md.append("```\n")
            else:
                md.append("## Disassembly\n")
                md.append("```%s" % disasm_lang)
                md.append(disasm)
                md.append("```\n")

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(md))
            self.exported_shaders[key] = filepath
            return filepath
        except Exception as e:
            print("[rdc_export]   WARNING: Failed to write shader %s: %s" % (key, e))
            return None

    # -------------------------------------------------------------------
    # 6. Save texture image
    # -------------------------------------------------------------------
    def _save_texture_image(self, resource_id, subdir, filename, mip=0, track_export=True):
        if resource_id == rd.ResourceId.Null():
            return None
        rid_s = rid_str(resource_id)
        filepath = os.path.join(self.output_dir, subdir, filename)
        if os.path.isfile(filepath):
            existing_size = 0
            try:
                existing_size = int(os.path.getsize(filepath))
            except Exception:
                existing_size = -1
            return filepath
        self._ensure_dir(subdir)
        try:
            texsave = rd.TextureSave()
            texsave.resourceId = resource_id
            texsave.mip = mip
            texsave.slice.sliceIndex = 0
            texsave.comp.blackPoint = 0.0
            texsave.comp.whitePoint = 1.0
            texsave.destType = rd.FileType.PNG

            # Try multiple save strategies. Some captures/drivers only succeed with Preserve alpha,
            # and in some setups non-ASCII destination paths fail unless saving to a temp path first.
            has_non_ascii = any(ord(ch) > 127 for ch in filepath)
            tmp_path = None
            if has_non_ascii:
                tmp_path = os.path.join(
                    tempfile.gettempdir(),
                    "rdc_export_tex_%d_%d.png" % (os.getpid(), int(time.time() * 1000)),
                )

            def _run_save_attempts(tag_prefix=""):
                attempts = [(tag_prefix + "png_preserve", rd.AlphaMapping.Preserve, filepath)]
                if hasattr(rd, "AlphaMapping"):
                    attempts.append((tag_prefix + "png_checker", rd.AlphaMapping.BlendToCheckerboard, filepath))
                if tmp_path:
                    attempts.append((tag_prefix + "png_preserve_tmp", rd.AlphaMapping.Preserve, tmp_path))
                    if hasattr(rd, "AlphaMapping"):
                        attempts.append((tag_prefix + "png_checker_tmp", rd.AlphaMapping.BlendToCheckerboard, tmp_path))

                results_local = []

                for tag, alpha_mode, out_path in attempts:
                    texsave.alpha = alpha_mode
                    save_ret = self.controller.SaveTexture(texsave, out_path)
                    results_local.append("%s=%s" % (tag, str(save_ret)))

                    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                        if out_path != filepath:
                            try:
                                if os.path.isfile(filepath):
                                    os.remove(filepath)
                                shutil.move(out_path, filepath)
                            except Exception:
                                try:
                                    shutil.copy2(out_path, filepath)
                                    os.remove(out_path)
                                except Exception:
                                    pass

                        if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                            return filepath, results_local

                    if out_path != filepath and os.path.isfile(out_path):
                        try:
                            os.remove(out_path)
                        except Exception:
                            pass

                return None, results_local

            saved_path, results = _run_save_attempts()
            if saved_path:
                if track_export:
                    self.exported_textures[rid_s] = saved_path
                return saved_path

            # If readback data was unavailable, force-replay current event once and retry.
            # This helps when incremental replay didn't materialize CPU-readable texture data.
            if self._current_event_id is not None and any("Data was requested through RenderDoc's API which is not available" in r for r in results):
                if self._set_frame_event(self._current_event_id, force=True):
                    saved_path, retry_results = _run_save_attempts("force_")
                    results.extend(retry_results)
                    if saved_path:
                        if track_export:
                            self.exported_textures[rid_s] = saved_path
                        return saved_path

            # As a last resort, reuse an already exported frame-end snapshot for this
            # texture if present. Restrict this fallback to global/trackable exports:
            # event snapshots must reflect exact pre/post event state.
            if track_export:
                cached = self.exported_textures.get(rid_s)
                if cached and os.path.isfile(cached):
                    try:
                        if os.path.abspath(cached) != os.path.abspath(filepath):
                            if os.path.isfile(filepath):
                                os.remove(filepath)
                            try:
                                os.link(cached, filepath)
                            except Exception:
                                shutil.copy2(cached, filepath)
                        if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                            return filepath
                    except Exception:
                        pass

            if self._texture_save_warned < 20:
                self._texture_save_warned += 1
                print("[rdc_export]   WARNING: SaveTexture produced no file for texture %s (%s), attempts: %s" % (
                    rid_s, filepath, ", ".join(results)))
            return None
        except Exception as e:
            print("[rdc_export]   WARNING: Failed to save texture %s: %s" % (rid_s, e))
            return None

    # -------------------------------------------------------------------
    # 7. Export Buffer (DebugName_ID.md, structured CB / hex dump)
    # -------------------------------------------------------------------
    def _read_buffer_slice(self, resource_id, offset, size):
        data = self.controller.GetBufferData(resource_id, offset, size)
        return bytes(data) if data is not None else b""

    def _iter_buffer_chunks(self, resource_id, total_size=None, chunk_size=4 * 1024 * 1024):
        offset = 0
        while True:
            if total_size is not None and offset >= total_size:
                break
            read_size = chunk_size if total_size is None else min(chunk_size, total_size - offset)
            if read_size <= 0:
                break
            chunk = self._read_buffer_slice(resource_id, offset, read_size)
            if len(chunk) == 0:
                break
            yield offset, chunk
            offset += len(chunk)
            if len(chunk) < read_size:
                break

    def _detect_buffer_size(self, resource_id, chunk_size=4 * 1024 * 1024):
        total = 0
        for chunk_offset, chunk in self._iter_buffer_chunks(resource_id, None, chunk_size):
            total = chunk_offset + len(chunk)
        return total

    def _dxgi_format_name(self, value):
        try:
            v = int(value)
        except Exception:
            return "UNKNOWN"
        known = {
            42: "R32_UINT",
            57: "R16_UINT",
        }
        return known.get(v, "DXGI_%d" % v)

    def _write_index_data_formatted(self, f, resource_id, total_size, fmt_value, start_offset=0):
        fmt_value = int(fmt_value)
        if fmt_value == 42:   # DXGI_FORMAT_R32_UINT
            elem_size = 4
            unpack_fmt = "<I"
        elif fmt_value == 57: # DXGI_FORMAT_R16_UINT
            elem_size = 2
            unpack_fmt = "<H"
        else:
            return False

        try:
            total_size = int(total_size)
        except Exception:
            return False
        try:
            start_offset = int(start_offset)
        except Exception:
            start_offset = 0
        if total_size <= 0:
            return False
        if start_offset < 0:
            start_offset = 0

        fmt_name = self._dxgi_format_name(fmt_value)
        f.write("## Data (Index Buffer: %s)\n\n" % fmt_name)
        if start_offset > 0:
            f.write("_Bound range: [%d, %d)_\n\n" % (start_offset, start_offset + total_size))
        f.write("| Index | Offset | Value |\n")
        f.write("|-------|--------|-------|\n")

        idx = 0
        dumped_end = start_offset
        for rel_off, chunk in self._iter_buffer_chunks_range(resource_id, start_offset, total_size):
            chunk_offset = start_offset + rel_off
            valid = len(chunk) - (len(chunk) % elem_size)
            if valid <= 0:
                continue
            dumped_end = max(dumped_end, chunk_offset + valid)
            for off in range(0, valid, elem_size):
                val = struct.unpack_from(unpack_fmt, chunk, off)[0]
                f.write("| %d | %d | %d |\n" % (idx, chunk_offset + off, val))
                idx += 1
        expected_end = start_offset + total_size
        if dumped_end < expected_end:
            f.write("\n*(warning: expected %d bytes, parsed %d bytes)*\n" % (
                total_size, max(0, dumped_end - start_offset)))
        f.write("\n")
        return True

    def _write_vertex_data_formatted(self, f, resource_id, total_size, stride, start_offset=0):
        try:
            stride = int(stride)
        except Exception:
            return False
        if stride <= 0:
            return False
        try:
            total_size = int(total_size)
        except Exception:
            return False
        try:
            start_offset = int(start_offset)
        except Exception:
            start_offset = 0
        if total_size <= 0:
            return False
        if start_offset < 0:
            start_offset = 0

        f.write("## Data (Vertex Buffer: stride %d)\n\n" % stride)
        if start_offset > 0:
            f.write("_Bound range: [%d, %d)_\n\n" % (start_offset, start_offset + total_size))
        f.write("| Vertex | Offset | Bytes |\n")
        f.write("|--------|--------|-------|\n")
        vidx = 0
        dumped_end = start_offset
        for rel_off, chunk in self._iter_buffer_chunks_range(resource_id, start_offset, total_size):
            chunk_offset = start_offset + rel_off
            valid = len(chunk) - (len(chunk) % stride)
            if valid <= 0:
                continue
            dumped_end = max(dumped_end, chunk_offset + valid)
            for off in range(0, valid, stride):
                raw = chunk[off:off + stride]
                hx = raw.hex()
                f.write("| %d | %d | `%s` |\n" % (vidx, chunk_offset + off, hx))
                vidx += 1
        expected_end = start_offset + total_size
        if dumped_end < expected_end:
            f.write("\n*(warning: expected %d bytes, parsed %d bytes)*\n" % (
                total_size, max(0, dumped_end - start_offset)))
        f.write("\n")
        return True

    def _struct_candidates_for_size(self, total_size):
        candidates = []
        for stride, layouts in self._struct_layouts.items():
            if stride <= 0 or total_size % stride != 0:
                continue
            for layout in layouts:
                candidates.append((stride, layout))
        return candidates

    def _choose_struct_layout(self, rid_s, total_size):
        if total_size <= 0:
            return None, None, "size-zero"

        candidates = self._struct_candidates_for_size(total_size)

        if not candidates:
            return None, None, "no-layout"
        if len(candidates) == 1:
            return candidates[0][0], candidates[0][1], ""

        debug_name_norm = _normalize_name(self._res_debug_name(rid_s))
        if debug_name_norm:
            scored = []
            for stride, layout in candidates:
                lname_norm = _normalize_name(layout.get('name', ''))
                score = 0
                if lname_norm:
                    if lname_norm in debug_name_norm or debug_name_norm in lname_norm:
                        score = 2
                    elif len(lname_norm) >= 4 and lname_norm[:8] in debug_name_norm:
                        score = 1
                scored.append((score, stride, layout))
            best_score = max(x[0] for x in scored)
            best = [x for x in scored if x[0] == best_score]
            if best_score > 0 and len(best) == 1:
                _, stride, layout = best[0]
                return stride, layout, ""

        return None, None, "ambiguous"

    def _decode_value_from_buffer(self, resource_id, absolute_offset, stype, total_size,
                                  chunk_cache, chunk_size=64 * 1024):
        if stype.baseType not in _VARTYPE_FMT:
            return None
        fmt_char, elem_size = _VARTYPE_FMT[stype.baseType]
        rows = max(stype.rows, 1)
        cols = max(stype.columns, 1)
        total_elems = rows * cols
        byte_count = total_elems * elem_size

        if absolute_offset < 0 or absolute_offset + byte_count > total_size:
            return None

        # Prefer direct ranged reads first. Some resources only expose data for
        # exact queried ranges, while coarse chunk probing may return empty.
        direct_key = ("direct", int(absolute_offset), int(byte_count))
        if direct_key not in chunk_cache:
            chunk_cache[direct_key] = self._read_buffer_slice(resource_id, absolute_offset, byte_count)
        direct = chunk_cache.get(direct_key, b"")
        if len(direct) >= byte_count:
            try:
                vals = list(struct.unpack("<%d%s" % (total_elems, fmt_char), bytes(direct[:byte_count])))
                if rows == 1 and cols == 1:
                    return vals[0]
                if rows == 1:
                    return vals
                return [vals[r * cols:(r + 1) * cols] for r in range(rows)]
            except Exception:
                pass

        raw = bytearray()
        pos = absolute_offset
        while len(raw) < byte_count:
            chunk_base = (pos // chunk_size) * chunk_size
            if chunk_base not in chunk_cache:
                read_len = min(chunk_size, total_size - chunk_base)
                if read_len <= 0:
                    return None
                # Avoid unbounded cache growth on huge buffers
                if len(chunk_cache) >= 128:
                    chunk_cache.clear()
                chunk_cache[chunk_base] = self._read_buffer_slice(resource_id, chunk_base, read_len)
            chunk = chunk_cache.get(chunk_base, b"")
            if not chunk:
                return None
            inner_off = pos - chunk_base
            take = min(byte_count - len(raw), len(chunk) - inner_off)
            if take <= 0:
                return None
            raw.extend(chunk[inner_off:inner_off + take])
            pos += take

        try:
            vals = list(struct.unpack("<%d%s" % (total_elems, fmt_char), bytes(raw)))
            if rows == 1 and cols == 1:
                return vals[0]
            if rows == 1:
                return vals
            return [vals[r * cols:(r + 1) * cols] for r in range(rows)]
        except Exception:
            return None

    def _format_constants_from_buffer(self, variables, resource_id, decode_base, display_base,
                                      indent, total_size, chunk_cache, decode_stats=None):
        rows = []
        prefix = "&ensp;" * (indent * 2)
        stats = decode_stats if decode_stats is not None else {"ok": 0, "fail": 0}
        for var in variables:
            name = var.name
            decode_off = decode_base + var.byteOffset
            display_off = display_base + var.byteOffset
            stype = var.type
            members = stype.members if hasattr(stype, 'members') else []
            if len(members) > 0:
                rows.append("| %s**%s** | %d | struct | |" % (prefix, name, display_off))
                rows.extend(self._format_constants_from_buffer(
                    members, resource_id, decode_off, display_off, indent + 1,
                    total_size, chunk_cache, decode_stats=stats))
            else:
                val = self._decode_value_from_buffer(
                    resource_id, decode_off, stype, total_size, chunk_cache)
                if val is None:
                    stats["fail"] = int(stats.get("fail", 0)) + 1
                else:
                    stats["ok"] = int(stats.get("ok", 0)) + 1
                rows.append("| %s%s | %d | %s | %s |" % (
                    prefix, name, display_off, _type_name_str(stype), _format_value(val)))
        return rows

    def _export_buffer_get_filename(self, resource_id):
        """Export buffer and return filename (not full path)."""
        rid_s = rid_str(resource_id)
        if rid_s in self.exported_buffers:
            return os.path.basename(self.exported_buffers[rid_s])
        self._export_buffer(resource_id)
        if rid_s in self.exported_buffers:
            return os.path.basename(self.exported_buffers[rid_s])
        return "%s.md" % rid_s

    def _export_buffer(self, resource_id):
        rid_s = rid_str(resource_id)
        if rid_s in self.exported_buffers:
            return self.exported_buffers[rid_s]

        self._ensure_dir("buffers")
        filename = self._res_filename(rid_s, ".md")
        filepath = os.path.join(self.output_dir, "buffers", filename)

        try:
            total_size = 0
            if rid_s in self._buf_descs:
                total_size = self._buf_descs[rid_s].length
            if total_size <= 0:
                total_size = self._detect_buffer_size(resource_id)

            res_name = self._res_debug_name(rid_s)
            header = ["# Buffer: %s\n" % rid_s,
                      "| Property | Value |",
                      "|----------|-------|"]
            if res_name:
                header.append("| Name | %s |" % res_name)
            header.append("| Size | %d bytes |" % total_size)
            header.append("")

            cb_layout = None
            if total_size > 0 and total_size in self._cb_layouts and len(self._cb_layouts[total_size]) > 0:
                cb_layout = self._cb_layouts[total_size][0]

            struct_stride = None
            struct_layout = None
            struct_reason = ""
            ambiguous_candidates = []
            usage_codes = []
            usage_hit_events = 0
            ia_hint = self._buffer_fmt_hints.get(rid_s, {})
            ia_ib_format = None
            ia_vb_stride = None
            if cb_layout is None:
                struct_stride, struct_layout, struct_reason = self._choose_struct_layout(rid_s, total_size)
                if struct_layout is None and struct_reason == "ambiguous":
                    ambiguous_candidates = self._struct_candidates_for_size(total_size)
                    ambiguous_candidates.sort(
                        key=lambda x: (x[0], x[1].get('name', '').lower()))
                    usage_codes, usage_hit_events = self._collect_buffer_usage_codes(rid_s)
                    if "IB" in usage_codes:
                        ia_ib_format = ia_hint.get("ib_format")
                    if "VB" in usage_codes:
                        ia_vb_stride = ia_hint.get("vb_stride")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(header))
                f.write("\n")

                if cb_layout is not None:
                    f.write("## Constant Buffer: %s\n\n" % (cb_layout.name if cb_layout.name else "unnamed"))
                    chunk_cache = {}
                    decode_stats = {"ok": 0, "fail": 0}
                    cols = _build_struct_columns(cb_layout.variables)
                    vals = []
                    for _, col_rel, col_stype in cols:
                        val = self._decode_value_from_buffer(
                            resource_id, int(col_rel), col_stype, total_size, chunk_cache)
                        if val is None:
                            decode_stats["fail"] = int(decode_stats.get("fail", 0)) + 1
                        else:
                            decode_stats["ok"] = int(decode_stats.get("ok", 0)) + 1
                        vals.append(_md_escape_cell(_format_value(val)))
                    if decode_stats.get("ok", 0) > 0 and cols:
                        f.write("| Index | %s |\n" % " | ".join(_md_escape_cell(c[0]) for c in cols))
                        f.write("|-------|%s|\n" % "|".join(["---"] * len(cols)))
                        f.write("| 0 | %s |\n\n" % " | ".join(vals))
                    else:
                        f.write("*(warning: constant buffer decode failed for all fields, fallback to hex dump)*\n\n")
                        f.write("## Data (Hex)\n\n")
                        f.write("```\n")
                        dumped = 0
                        for chunk_offset, chunk in self._iter_buffer_chunks(resource_id, total_size):
                            f.write(hex_dump(chunk, chunk_offset))
                            f.write("\n")
                            dumped = chunk_offset + len(chunk)
                        if dumped < total_size:
                            f.write("... (warning: expected %d bytes, dumped %d bytes) ...\n" % (
                                total_size, dumped))
                        f.write("```\n")

                elif struct_layout is not None:
                    members = struct_layout['members']
                    sname = struct_layout['name']
                    num_elements = total_size // struct_stride
                    f.write("\n".join(_format_struct_definition(sname, members)))
                    f.write("\n")
                    f.write("## Data (%d elements, stride %d)\n\n" % (num_elements, struct_stride))

                    cols = _build_struct_columns(members)
                    if cols:
                        f.write("| Index | %s |\n" % " | ".join(_md_escape_cell(c[0]) for c in cols))
                        f.write("|-------|%s|\n" % "|".join(["---"] * len(cols)))
                    else:
                        f.write("*(warning: no leaf members found in struct layout, fallback to hex dump)*\n\n")
                        f.write("## Data (Hex)\n\n")
                        f.write("```\n")
                        dumped = 0
                        for chunk_offset, chunk in self._iter_buffer_chunks(resource_id, total_size):
                            f.write(hex_dump(chunk, chunk_offset))
                            f.write("\n")
                            dumped = chunk_offset + len(chunk)
                        if dumped < total_size:
                            f.write("... (warning: expected %d bytes, dumped %d bytes) ...\n" % (
                                total_size, dumped))
                        f.write("```\n")
                        cols = []

                    chunk_bytes = max(struct_stride, (4 * 1024 * 1024 // struct_stride) * struct_stride)
                    if chunk_bytes <= 0:
                        chunk_bytes = struct_stride

                    processed = total_size if not cols else 0
                    if cols:
                        chunk_iter = self._iter_buffer_chunks(resource_id, total_size, chunk_bytes)
                        for chunk_offset, chunk in chunk_iter:
                            valid_len = len(chunk) - (len(chunk) % struct_stride)
                            if valid_len <= 0:
                                continue
                            processed = max(processed, chunk_offset + valid_len)
                            elem_base = chunk_offset // struct_stride
                            elem_count = valid_len // struct_stride
                            for local_idx in range(elem_count):
                                global_idx = elem_base + local_idx
                                local_offset = local_idx * struct_stride
                                vals = []
                                for _, col_rel, col_stype in cols:
                                    val = _decode_value(chunk, local_offset + col_rel, col_stype)
                                    vals.append(_md_escape_cell(_format_value(val)))
                                f.write("| %d | %s |\n" % (global_idx, " | ".join(vals)))
                    if cols:
                        f.write("\n")
                    if cols and processed < total_size:
                        f.write("*(warning: expected %d bytes, parsed %d bytes)*\n\n" % (
                            total_size, processed))

                elif ia_ib_format is not None and self._write_index_data_formatted(
                        f, resource_id, total_size, ia_ib_format):
                    f.write("*(info: format inferred from IA index binding)*\n\n")

                elif ia_vb_stride is not None and self._write_vertex_data_formatted(
                        f, resource_id, total_size, ia_vb_stride):
                    f.write("*(info: format inferred from IA vertex binding stride)*\n\n")

                else:
                    if struct_reason == "ambiguous":
                        f.write("*(info: structured layout ambiguous, exporting candidate formats; data section falls back to full hex dump)*\n\n")
                        if ambiguous_candidates:
                            f.write("## Candidate Structures (Ambiguous)\n\n")
                            f.write("| # | Stride | Name | Fields |\n")
                            f.write("|---|--------|------|--------|\n")
                            for idx, (cand_stride, cand_layout) in enumerate(ambiguous_candidates, 1):
                                f.write("| %d | %d | %s | %d |\n" % (
                                    idx,
                                    cand_stride,
                                    cand_layout.get("name", ""),
                                    len(cand_layout.get("members", [])),
                                ))
                            f.write("\n")
                            for idx, (cand_stride, cand_layout) in enumerate(ambiguous_candidates, 1):
                                f.write("### Candidate %d: %s (stride %d)\n\n" % (
                                    idx,
                                    cand_layout.get("name", ""),
                                    cand_stride,
                                ))
                                f.write("\n".join(_format_struct_fields_table(cand_layout.get("members", []))))
                                f.write("\n")
                    f.write("## Data (Hex)\n\n")
                    f.write("```\n")
                    dumped = 0
                    for chunk_offset, chunk in self._iter_buffer_chunks(resource_id, total_size):
                        f.write(hex_dump(chunk, chunk_offset))
                        f.write("\n")
                        dumped = chunk_offset + len(chunk)
                    if dumped < total_size:
                        f.write("... (warning: expected %d bytes, dumped %d bytes) ...\n" % (
                            total_size, dumped))
                    f.write("```\n")

            self.exported_buffers[rid_s] = filepath
            return filepath
        except Exception as e:
            print("[rdc_export]   WARNING: Failed to export buffer %s: %s" % (rid_s, e))
            return None

    # -------------------------------------------------------------------
    # 8. Bulk export remaining textures / buffers
    # -------------------------------------------------------------------
    def export_all_textures(self):
        print("[rdc_export] Exporting remaining textures ...")
        count_new = 0
        total = len(self._tex_descs)
        for i, (rid_s, tex) in enumerate(self._tex_descs.items()):
            if rid_s in self._excluded_tex_rids:
                continue
            if rid_s in self.exported_textures:
                continue
            if tex.width == 0 or tex.height == 0:
                continue
            fn = self._res_filename(rid_s, ".png")
            result = self._save_texture_image(tex.resourceId, "textures", fn)
            if result:
                count_new += 1
            if (i + 1) % 200 == 0:
                print("[rdc_export]     %d/%d textures ..." % (i + 1, total))
        print("[rdc_export]   %d new textures exported" % count_new)

    def export_all_buffers(self):
        print("[rdc_export] Exporting remaining buffers ...")
        count_new = 0
        total = len(self._buf_descs)
        for i, (rid_s, buf) in enumerate(self._buf_descs.items()):
            if rid_s in self._excluded_buf_rids:
                continue
            if rid_s in self.exported_buffers:
                continue
            if buf.length == 0:
                continue
            self._export_buffer(buf.resourceId)
            if rid_s in self.exported_buffers:
                count_new += 1
            if (i + 1) % 500 == 0:
                print("[rdc_export]     %d/%d buffers ..." % (i + 1, total))
        print("[rdc_export]   %d new buffers exported" % count_new)

    # -------------------------------------------------------------------
    # Main export entry point
    # -------------------------------------------------------------------
    def export_all(self):
        print("[rdc_export] Output directory: %s" % self.output_dir)
        self._ensure_dir()

        root_actions = self.controller.GetRootActions()
        self._build_skip_event_ids(root_actions)

        if self._event_list_only_mode:
            print("[rdc_export] EID filter=-1, export event_list only.")
            self.export_event_list(root_actions)
            print("[rdc_export] Export complete!")
            print("[rdc_export]   event_list exported only")
            return

        self.export_event_list(root_actions)
        # Event-driven export: select events first (respecting skip marker / EID filters),
        # then export only resources bound by those events.
        self.export_events(root_actions)
        if _env_flag("RDC_EXPORT_ALL_PSOS", False):
            print("[rdc_export] RDC_EXPORT_ALL_PSOS=1, exporting all PSOs additionally.")
            self.export_psos()

        print("[rdc_export] Export complete!")
        print("[rdc_export]   PSOs exported:     %d" % len(self.exported_psos))
        print("[rdc_export]   Shaders exported:  %d" % len(self.exported_shaders))
        print("[rdc_export]   Texture snapshots: %d" % len(self._snapshot_texture_files))
        print("[rdc_export]   Buffer snapshots:  %d" % len(self._snapshot_buffer_files))


# ===========================================================================
# Capture loading (standalone mode)
# ===========================================================================

def load_capture(filename):
    cap = rd.OpenCaptureFile()
    result = cap.OpenFile(filename, '', None)
    if result != rd.ResultCode.Succeeded:
        raise RuntimeError("Couldn't open file '%s': %s" % (filename, str(result)))
    if not cap.LocalReplaySupport():
        raise RuntimeError("Capture '%s' cannot be replayed locally" % filename)
    opts = rd.ReplayOptions()
    replay_api_validation = _env_flag("RDC_REPLAY_API_VALIDATION", False)
    if replay_api_validation:
        opts.apiValidation = True
    force_sw_replay = _env_flag("RDC_REPLAY_FORCE_SOFTWARE", False)
    if force_sw_replay:
        opts.forceGPUVendor = rd.GPUVendor.Software
    result, controller = cap.OpenCapture(opts, None)
    if result != rd.ResultCode.Succeeded:
        raise RuntimeError("Couldn't initialise replay for '%s': %s" % (filename, str(result)))
    stage_file = os.environ.get("RDC_WORKER_STAGE_FILE", "")
    if stage_file:
        try:
            with open(stage_file, "w", encoding="utf-8") as f:
                f.write("open_capture_done\n")
        except Exception:
            pass
    return cap, controller


def compute_output_dir(rdc_path):
    return os.path.splitext(rdc_path)[0]


def _run_worker_export(rdc_path, renderdoc_path=None, skip_slateui_title=None, eid_filter_spec=None):
    timeout_sec = float(os.environ.get("RDC_WORKER_TIMEOUT_SEC", "6000"))
    max_ws_gb = float(os.environ.get("RDC_WORKER_MAX_WS_GB", "128"))
    max_ws_bytes = int(max_ws_gb * 1024 * 1024 * 1024) if max_ws_gb > 0 else 0
    script_path = os.path.abspath(__file__)
    cmd = [sys.executable, script_path, "--worker-export"]
    if renderdoc_path:
        cmd.extend(["--renderdoc-path", renderdoc_path])
    if skip_slateui_title is False:
        cmd.append("--no-skip-slateui-title")
    if eid_filter_spec is not None and str(eid_filter_spec).strip() != "":
        cmd.extend(["--eid", str(eid_filter_spec).strip()])
    cmd.append(rdc_path)
    print("[rdc_export] Worker guard: max_ws=%.2fGB timeout=%.0fs" % (max_ws_gb, timeout_sec))
    stage_file = os.path.join(
        tempfile.gettempdir(),
        "rdc_export_stage_%d_%d.flag" % (os.getpid(), int(time.time() * 1000)),
    )
    if os.path.isfile(stage_file):
        try:
            os.remove(stage_file)
        except Exception:
            pass

    env = os.environ.copy()
    env["RDC_WORKER_STAGE_FILE"] = stage_file
    proc = subprocess.Popen(cmd, cwd=os.path.dirname(script_path), env=env)

    open_capture_done = False
    start_t = time.time()
    try:
        while proc.poll() is None:
            if (not open_capture_done) and os.path.isfile(stage_file):
                open_capture_done = True
                try:
                    os.remove(stage_file)
                except Exception:
                    pass

            elapsed = time.time() - start_t
            ws_bytes = _get_process_working_set_bytes(proc.pid)

            # Guard only the OpenCapture phase to avoid killing long but healthy exports.
            if (not open_capture_done) and max_ws_bytes > 0 and ws_bytes > max_ws_bytes:
                proc.kill()
                raise RuntimeError(
                    "Export worker aborted during OpenCapture: memory usage exceeded %.2f GB (current %.2f GB). "
                    "Set RDC_WORKER_MAX_WS_GB to tune this guard." %
                    (max_ws_gb, float(ws_bytes) / (1024 * 1024 * 1024))
                )
            if (not open_capture_done) and timeout_sec > 0 and elapsed > timeout_sec:
                proc.kill()
                raise RuntimeError(
                    "Export worker timed out during OpenCapture after %.1f seconds. "
                    "Set RDC_WORKER_TIMEOUT_SEC to tune timeout." % timeout_sec
                )
            time.sleep(1.0)
    finally:
        if os.path.isfile(stage_file):
            try:
                os.remove(stage_file)
            except Exception:
                pass

    if proc.returncode != 0:
        raise RuntimeError("Export worker failed with exit code %d" % proc.returncode)


# ===========================================================================
# Entry point
# ===========================================================================

def export_capture_data(controller, output_dir=None, skip_slateui_title=None, eid_filter_spec=None):
    if output_dir is None:
        if 'pyrenderdoc' in globals():
            rdc_path = pyrenderdoc.GetCaptureFilename()
            output_dir = compute_output_dir(rdc_path)
        else:
            raise ValueError("output_dir must be specified")

    raw_skip_env = os.environ.get("RDC_EXPORT_SKIP_SLATEUI_TITLE")
    if skip_slateui_title is None:
        skip_slateui_title = _env_flag("RDC_EXPORT_SKIP_SLATEUI_TITLE", True)
        if raw_skip_env is None:
            skip_slateui_title_source = "default(True)"
        else:
            skip_slateui_title_source = "env(RDC_EXPORT_SKIP_SLATEUI_TITLE=%s)" % raw_skip_env
    else:
        skip_slateui_title_source = "arg"

    raw_marker_env = os.environ.get("RDC_EXPORT_SKIP_MARKER_NAME")
    skip_marker_name = raw_marker_env if raw_marker_env is not None else "SlateUI Title"
    if raw_marker_env is None:
        skip_marker_source = "default(SlateUI Title)"
    else:
        skip_marker_source = "env(RDC_EXPORT_SKIP_MARKER_NAME=%s)" % raw_marker_env

    raw_eid_env = os.environ.get("RDC_EXPORT_EID", None)
    if eid_filter_spec is None:
        eid_filter_spec = raw_eid_env
        if raw_eid_env is None:
            eid_filter_source = "default(None)"
        else:
            eid_filter_source = "env(RDC_EXPORT_EID=%s)" % raw_eid_env
    else:
        eid_filter_source = "arg"
    try:
        eid_filter = _parse_eid_filter_spec(eid_filter_spec)
    except Exception as e:
        raise RuntimeError("Invalid EID filter: %s" % e)

    if eid_filter is not None and os.environ.get("RDC_SETFRAME_FULL_REPLAY") is None:
        # For event-filtered export, prefer one-pass full replay to avoid
        # split replay paths that can trigger driver removal on some captures.
        os.environ["RDC_SETFRAME_FULL_REPLAY"] = "1"

    if eid_filter is not None and os.environ.get("RDC_SKIP_QUEUE_SWITCH_IDLE") is None:
        # Queue-switch idle sync during D3D12 replay can trigger invalid-call/device-lost
        # on some captures. Keep this override scoped to event-filtered export debugging.
        os.environ["RDC_SKIP_QUEUE_SWITCH_IDLE"] = "1"

    if eid_filter is not None and os.environ.get("RDC_CMDLIST_RESET_NULL_PSO") is None:
        # Some captures can trigger device removal during command list Reset when
        # replaying with an initial pipeline state argument.
        os.environ["RDC_CMDLIST_RESET_NULL_PSO"] = "1"

    if eid_filter is not None and os.environ.get("RDC_SKIP_QUERY_REPLAY") is None:
        # Query replay can emit invalid EndQuery/Close paths on some captures
        # (especially with diagnostics/profiling query streams). For event-filtered
        # export, skip query replay to keep graphics state reconstruction stable.
        os.environ["RDC_SKIP_QUERY_REPLAY"] = "1"

    mode_name = "renderdoc-ui" if 'pyrenderdoc' in globals() else "worker-export"
    _print_effective_branch_status(
        mode_name=mode_name,
        output_dir=output_dir,
        skip_slateui_title=skip_slateui_title,
        skip_slateui_title_source=skip_slateui_title_source,
        skip_marker_name=skip_marker_name,
        skip_marker_source=skip_marker_source,
        eid_filter_spec=eid_filter_spec,
        eid_filter=eid_filter,
        eid_filter_source=eid_filter_source,
    )

    eid_sig = ""
    if eid_filter:
        if eid_filter.get("event_list_only"):
            eid_sig = "-1"
        else:
            eid_sig = "%s-%s" % (eid_filter.get("min_eid"), eid_filter.get("max_eid"))
    config_sig = "skip=%s;marker=%s;eid=%s" % (
        "1" if skip_slateui_title else "0",
        skip_marker_name,
        eid_sig,
    )

    # Version check
    current_sha1 = _compute_script_sha1()
    version_match = _check_version(output_dir, current_sha1, config_sig)
    if version_match:
        print("[rdc_export] Output already up-to-date (SHA1: %s matches, config unchanged), skipping." % current_sha1[:12])
        return

    # Version mismatch or no previous export -- clean and re-export
    if os.path.isdir(output_dir):
        print("[rdc_export] Version mismatch, cleaning old output: %s" % output_dir)
        _cleanup_output_dir(output_dir)

    exporter = RDCExporter(
        controller,
        output_dir,
        skip_slateui_title=skip_slateui_title,
        skip_marker_name=skip_marker_name,
        eid_filter=eid_filter,
    )
    exporter.export_all()

    # Write version stamp
    _write_version(output_dir, current_sha1, config_sig)
    print("[rdc_export] Version stamp written (SHA1: %s)" % current_sha1[:12])


if 'pyrenderdoc' in globals():
    print("[rdc_export] Startup mode: renderdoc-ui")
    print("[rdc_export]   CLI argument branches are not used in this mode.")
    pyrenderdoc.Replay().BlockInvoke(export_capture_data)
else:
    worker_mode = False
    renderdoc_path_arg = None
    skip_slateui_title_arg = True
    eid_filter_arg = None
    filtered_args = []
    skip_next = False
    for i, arg in enumerate(sys.argv[1:], 1):
        if skip_next:
            skip_next = False
            continue
        arg_norm = str(arg).strip()
        arg_l = arg_norm.lower()
        if arg_l.startswith('--renderdoc-path='):
            renderdoc_path_arg = arg_norm.split('=', 1)[1]
            continue
        if arg_l == '--renderdoc-path':
            skip_next = True
            if i + 1 < len(sys.argv):
                renderdoc_path_arg = sys.argv[i + 1]
            continue
        if arg_l == '--worker-export':
            worker_mode = True
            continue
        if arg_l == '--no-skip-slateui-title':
            skip_slateui_title_arg = False
            continue
        if arg_l.startswith('--eid=') or arg_l.startswith('-eid='):
            eid_filter_arg = arg_norm.split('=', 1)[1]
            if str(eid_filter_arg).strip() == "":
                print("Error: --eid/-eid requires a value")
                sys.exit(1)
            continue
        if arg_l in ('--eid', '-eid'):
            skip_next = True
            if i + 1 < len(sys.argv):
                eid_filter_arg = sys.argv[i + 1]
            else:
                print("Error: --eid/-eid requires a value")
                sys.exit(1)
            continue
        if arg_norm.startswith('-'):
            print("Error: Unknown option: %s" % arg)
            print("Usage: python %s [--renderdoc-path <path>] [--no-skip-slateui-title] [--eid|-eid <eid|-1|start-end>] <capture.rdc>" % sys.argv[0])
            sys.exit(1)
        filtered_args.append(arg)

    capture_arg = filtered_args[0] if filtered_args else None
    _print_cli_branch_status(
        worker_mode=worker_mode,
        renderdoc_path_arg=renderdoc_path_arg,
        skip_slateui_title_arg=skip_slateui_title_arg,
        eid_filter_arg=eid_filter_arg,
        capture_arg=capture_arg,
    )

    if len(filtered_args) < 1:
        print("Usage: python %s [--renderdoc-path <path>] [--no-skip-slateui-title] [--eid|-eid <eid|-1|start-end>] <capture.rdc>" % sys.argv[0])
        sys.exit(0)

    rdc_path = filtered_args[0]
    if not os.path.isfile(rdc_path):
        print("Error: File not found: %s" % rdc_path)
        sys.exit(1)

    if not worker_mode:
        _run_worker_export(
            os.path.abspath(rdc_path),
            renderdoc_path_arg,
            skip_slateui_title=skip_slateui_title_arg,
            eid_filter_spec=eid_filter_arg,
        )
        sys.exit(0)

    output_dir = compute_output_dir(os.path.abspath(rdc_path))
    print("[rdc_export] Loading capture: %s" % rdc_path)
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cap, controller = load_capture(rdc_path)
    export_capture_data(
        controller,
        output_dir,
        skip_slateui_title=skip_slateui_title_arg,
        eid_filter_spec=eid_filter_arg,
    )
    controller.Shutdown()
    cap.Shutdown()
    rd.ShutdownReplay()
