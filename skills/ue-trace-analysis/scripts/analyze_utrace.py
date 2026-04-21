#!/usr/bin/env python3
"""Analyze Unreal .utrace files and summarize GPU hotspots."""

import argparse
import ctypes
import json
import os
import shutil
import statistics
import struct
import sys
from collections import Counter
from pathlib import Path


TRACE_DECODE = "?Decode@Private@Trace@UE@@YAHPEBXHPEAXH@Z"
DEFAULT_TRACE_DLL_CANDIDATES = [
    r"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealInsights-TraceLog.dll",
    r"C:\Program Files\Epic Games\UE_5.4\Engine\Binaries\Win64\UnrealInsights-TraceLog.dll",
    r"C:\Program Files\Epic Games\UE_5.3\Engine\Binaries\Win64\UnrealInsights-TraceLog.dll",
]

MAGIC_TRC = 1414677317
MAGIC_TRC2 = 1414677298

FLAG_IMPORTANT = 1 << 0
FLAG_MAYBE_HAS_AUX = 1 << 1
FLAG_NO_SYNC = 1 << 2

TYPE_BOOL = 0
TYPE_UINT8 = 0
TYPE_UINT16 = 1
TYPE_UINT32 = 2
TYPE_UINT64 = 3
TYPE_POINTER = 3
TYPE_INT8 = 16
TYPE_INT16 = 17
TYPE_INT32 = 18
TYPE_INT64 = 19
TYPE_FLOAT32 = 66
TYPE_FLOAT64 = 67
TYPE_ANSI_STRING = 136
TYPE_WIDE_STRING = 137
TYPE_ARRAY = 128

PREDEFINED_NEW_EVENT = 0
PREDEFINED_AUXDATA = 1
PREDEFINED_AUXDATA_TERMINAL = 3
PREDEFINED_WELLKNOWN_NUM = 16


class EventTypeField:
    def __init__(self, offset, size, typeinfo, name):
        self.offset = offset
        self.size = size
        self.typeinfo = typeinfo
        self.name = name


class EventType:
    def __init__(self, uid, logger, event, flags, fields):
        self.uid = uid
        self.logger = logger
        self.event = event
        self.flags = flags
        self.fields = fields
        self.name = f"{logger}.{event}"

    @property
    def is_important(self):
        return (self.flags & FLAG_IMPORTANT) != 0

    @property
    def maybe_has_aux(self):
        return (self.flags & FLAG_MAYBE_HAS_AUX) != 0

    @property
    def is_no_sync(self):
        return (self.flags & FLAG_NO_SYNC) != 0

    @property
    def has_serial(self):
        return not self.is_important and not self.is_no_sync


def is_array_type(typeinfo):
    return (typeinfo & TYPE_ARRAY) != 0


class BufferReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def eof(self):
        return self.pos >= len(self.data)

    def tell(self):
        return self.pos

    def seek(self, pos):
        self.pos = pos

    def read(self, n):
        out = self.data[self.pos:self.pos + n]
        if len(out) != n:
            raise EOFError(f"wanted {n} bytes at {self.pos}, got {len(out)}")
        self.pos += n
        return out

    def u8(self):
        return self.read(1)[0]

    def u16(self):
        return struct.unpack_from("<H", self.read(2))[0]

    def u32(self):
        return struct.unpack_from("<I", self.read(4))[0]

    def u64(self):
        return struct.unpack_from("<Q", self.read(8))[0]

    def f32(self):
        return struct.unpack_from("<f", self.read(4))[0]

    def f64(self):
        return struct.unpack_from("<d", self.read(8))[0]

    def read7bit(self):
        value = 0
        shift = 0
        while True:
            byte = self.u8()
            value |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                return value
            shift += 7

    def read_packed_uid(self):
        low = self.u8()
        if low & 1:
            high = self.u8()
        else:
            high = 0
        return (low >> 1) | (high << 8)


def resolve_decoder_path(explicit_path=None):
    checked = []
    if explicit_path:
        candidate = os.path.abspath(explicit_path)
        if os.path.isfile(candidate):
            return candidate
        raise FileNotFoundError(f"decoder dll not found: {candidate}")

    env_candidate = os.environ.get("UE_TRACE_LOG_DLL")
    if env_candidate:
        checked.append(env_candidate)
        if os.path.isfile(env_candidate):
            return os.path.abspath(env_candidate)

    for candidate in DEFAULT_TRACE_DLL_CANDIDATES:
        checked.append(candidate)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    lines = "\n".join(f"  - {item}" for item in checked)
    raise FileNotFoundError(
        "could not find UnrealInsights-TraceLog.dll.\n"
        "Pass --decoder-dll, set UE_TRACE_LOG_DLL, or install UE to a default path.\n"
        f"Checked:\n{lines}"
    )


def load_decoder(decoder_path=None):
    resolved_path = resolve_decoder_path(decoder_path)
    dll = ctypes.WinDLL(resolved_path)
    fn = getattr(dll, TRACE_DECODE)
    fn.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32]
    fn.restype = ctypes.c_int32
    fn._trace_dll = dll
    return fn, resolved_path


def decode_block(fn, payload, decoded_size):
    src = ctypes.create_string_buffer(payload)
    dst = ctypes.create_string_buffer(decoded_size)
    result = fn(src, len(payload), dst, decoded_size)
    if result != decoded_size:
        raise RuntimeError(f"decode failed, expected {decoded_size}, got {result}")
    return dst.raw[:decoded_size]


def parse_header(fh):
    magic = struct.unpack("<I", fh.read(4))[0]
    if magic not in (MAGIC_TRC, MAGIC_TRC2):
        raise RuntimeError(f"bad magic {magic}")
    if magic == MAGIC_TRC2:
        metadata_size = struct.unpack("<H", fh.read(2))[0]
        fh.read(metadata_size)
    transport_version = struct.unpack("<B", fh.read(1))[0]
    protocol_version = struct.unpack("<B", fh.read(1))[0]
    return transport_version, protocol_version


def demux_trace(path, out_dir, decode_fn):
    thread_paths = {}
    thread_handles = {}
    packet_counts = Counter()
    decoded_sizes = Counter()
    encoded_packets = 0
    total_packets = 0

    with open(path, "rb") as fh:
        transport_version, protocol_version = parse_header(fh)
        while True:
            hdr = fh.read(4)
            if not hdr:
                break
            if len(hdr) != 4:
                raise RuntimeError("truncated packet header")
            packet_size, thread_markers = struct.unpack("<HH", hdr)
            total_packets += 1
            thread_id = thread_markers & 0x3FFF
            encoded = (thread_markers & 0x8000) != 0
            if encoded:
                encoded_packets += 1
                decoded_size = struct.unpack("<H", fh.read(2))[0]
                payload = fh.read(packet_size - 6)
                data = decode_block(decode_fn, payload, decoded_size)
            else:
                data = fh.read(packet_size - 4)

            packet_counts[thread_id] += 1
            decoded_sizes[thread_id] += len(data)

            out_path = thread_paths.get(thread_id)
            if out_path is None:
                out_path = os.path.join(out_dir, f"thread_{thread_id}.bin")
                thread_paths[thread_id] = out_path
                thread_handles[thread_id] = open(out_path, "wb")
            thread_handles[thread_id].write(data)

    for handle in thread_handles.values():
        handle.close()

    return {
        "transport_version": transport_version,
        "protocol_version": protocol_version,
        "thread_paths": thread_paths,
        "packet_counts": packet_counts,
        "decoded_sizes": decoded_sizes,
        "encoded_packets": encoded_packets,
        "total_packets": total_packets,
    }


def parse_event_type(reader):
    new_uid = reader.u16()
    field_count = reader.u8()
    flags = reader.u8()
    logger_size = reader.u8()
    event_size = reader.u8()
    raw_fields = []
    for _ in range(field_count):
        field_family = reader.u8()
        _padding = reader.u8()
        offset = reader.u16()
        size_or_ref = reader.u16()
        typeinfo = reader.u8()
        name_size = reader.u8()
        raw_fields.append([field_family, offset, size_or_ref, typeinfo, name_size])
    logger = reader.read(logger_size).decode("utf-8", "replace")
    event = reader.read(event_size).decode("utf-8", "replace")
    fields = []
    for field_family, offset, size_or_ref, typeinfo, name_size in raw_fields:
        name = reader.read(name_size).decode("utf-8", "replace")
        size = 0 if is_array_type(typeinfo) else size_or_ref
        fields.append(EventTypeField(offset, size, typeinfo, name))
    return new_uid, EventType(new_uid, logger, event, flags, fields)


def parse_generic_event(reader, event_type):
    fields = {}
    if event_type.has_serial:
        serial_low = reader.u8()
        serial_high = reader.u16()
        fields["_serial"] = serial_low | (serial_high << 16)

    aux_slots = {}
    for index, field in enumerate(event_type.fields):
        typeinfo = field.typeinfo
        if typeinfo in (TYPE_BOOL, TYPE_UINT8, TYPE_INT8):
            fields[field.name] = reader.u8()
        elif typeinfo in (TYPE_UINT16, TYPE_INT16):
            fields[field.name] = reader.u16()
        elif typeinfo in (TYPE_UINT32, TYPE_INT32):
            fields[field.name] = reader.u32()
        elif typeinfo in (TYPE_UINT64, TYPE_INT64, TYPE_POINTER):
            fields[field.name] = reader.u64()
        elif typeinfo == TYPE_FLOAT32:
            fields[field.name] = reader.f32()
        elif typeinfo == TYPE_FLOAT64:
            fields[field.name] = reader.f64()
        elif is_array_type(typeinfo):
            aux_slots[index] = field
            fields[field.name] = None
        else:
            raise RuntimeError(f"unsupported typeinfo {typeinfo} for {event_type.name}.{field.name}")

    if event_type.maybe_has_aux:
        while True:
            aux_start = reader.tell()
            aux_uid = reader.u8()
            if not event_type.is_important:
                aux_uid >>= 1
            if aux_uid == PREDEFINED_AUXDATA_TERMINAL:
                break
            if aux_uid != PREDEFINED_AUXDATA:
                raise RuntimeError(f"bad aux uid {aux_uid} for {event_type.name} at {aux_start}")
            reader.seek(aux_start)
            header = reader.u32()
            field_index = (header >> 8) & 0x1F
            size = (header >> 13) & 0x7FFFF
            payload = reader.read(size)
            if field_index not in aux_slots:
                raise RuntimeError(
                    f"missing aux slot {field_index} for {event_type.name} at {aux_start}"
                )
            field = aux_slots[field_index]
            if field.typeinfo == TYPE_ANSI_STRING:
                fields[field.name] = payload.decode("ascii", "replace")
            elif field.typeinfo == TYPE_WIDE_STRING:
                fields[field.name] = payload.decode("utf-16-le", "replace")
            else:
                fields[field.name] = payload

    return fields


def parse_thread_events(path, event_types, important=False):
    with open(path, "rb") as fh:
        reader = BufferReader(fh.read())

    while not reader.eof():
        if important:
            uid = reader.u16()
            size = reader.u16()
            payload_start = reader.tell()
        else:
            uid = reader.read_packed_uid()
            size = None
            payload_start = reader.tell()

        if uid >= PREDEFINED_WELLKNOWN_NUM:
            event_type = event_types[uid]
            fields = parse_generic_event(reader, event_type)
            if important and size is not None:
                reader.seek(payload_start + size)
            yield uid, event_type, fields
            continue

        if uid == PREDEFINED_NEW_EVENT:
            new_uid, event_type = parse_event_type(reader)
            event_types[new_uid] = event_type
            if important and size is not None:
                reader.seek(payload_start + size)
            yield PREDEFINED_NEW_EVENT, None, {"uid": new_uid, "name": event_type.name}
            continue

        if uid in (4, 5):
            if important and size is not None:
                reader.seek(payload_start + size)
            continue

        if uid in (6, 7):
            if important and size is not None:
                reader.seek(payload_start + size)
            else:
                reader.read(8)
            continue

        if uid in (8, 9):
            if important and size is not None:
                reader.seek(payload_start + size)
            else:
                reader.read(7)
            continue

        raise RuntimeError(f"unsupported well-known uid {uid} in {path}")


def parse_gpu_buffer(data, timestamp_base, calibration_bias, event_name_map):
    reader = BufferReader(data)
    stack = []
    last_timestamp = timestamp_base
    events = []
    first_time = None
    last_time = None
    while not reader.eof():
        decoded = reader.read7bit()
        actual = (decoded >> 1) + last_timestamp
        last_timestamp = actual
        time_us = actual + calibration_bias
        if first_time is None:
            first_time = time_us
        last_time = time_us
        if decoded & 1:
            if reader.tell() + 4 > len(reader.data):
                break
            event_type = reader.u32()
            stack.append(
                {
                    "event_type": event_type,
                    "name": event_name_map.get(event_type, f"<unknown:{event_type}>"),
                    "start": time_us,
                    "child": 0,
                }
            )
        elif stack:
            item = stack.pop()
            dur = time_us - item["start"]
            exclusive = dur - item["child"]
            event = {
                "event_type": item["event_type"],
                "name": item["name"],
                "start_us": item["start"],
                "end_us": time_us,
                "dur_us": dur,
                "exclusive_us": exclusive,
                "depth": len(stack),
            }
            events.append(event)
            if stack:
                stack[-1]["child"] += dur

    total_us = 0 if first_time is None or last_time is None else max(0, last_time - first_time)
    return total_us, events


def percentile(values, p):
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def ms(value):
    return value / 1000.0


def summarize_top(counter, total_value, frame_count, limit=12):
    rows = []
    for name, value in counter.most_common(limit):
        rows.append(
            {
                "name": name,
                "total_ms": ms(value),
                "avg_ms_per_frame": ms(value / max(frame_count, 1)),
                "share": 0.0 if total_value == 0 else (value * 100.0 / total_value),
            }
        )
    return rows


def analyze_trace(path, decoder_path=None, work_dir=None, keep_demux=False):
    trace_path = os.path.abspath(path)
    if not os.path.isfile(trace_path):
        raise FileNotFoundError(f"trace not found: {trace_path}")

    decode_fn, resolved_decoder = load_decoder(decoder_path)
    if work_dir:
        temp_root = os.path.abspath(work_dir)
    else:
        # Default beside the trace so the script works in workspace-restricted sandboxes.
        temp_root = os.path.join(os.path.dirname(trace_path), "_ue_trace_analysis_tmp")
    os.makedirs(temp_root, exist_ok=True)
    trace_stem = Path(trace_path).stem
    tmp_dir = os.path.join(temp_root, f"{trace_stem}_demux")
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        demux = demux_trace(trace_path, tmp_dir, decode_fn)
        event_types = {}

        thread0 = demux["thread_paths"].get(0)
        if not thread0:
            raise RuntimeError("missing thread 0 event stream")
        for _uid, _etype, _fields in parse_thread_events(thread0, event_types, important=True):
            pass

        thread1 = demux["thread_paths"].get(1)
        if not thread1:
            raise RuntimeError("missing thread 1 important stream")

        thread_names = {}
        gpu_name_map = {}
        cycle_frequency = None
        trace_start_cycle = None
        important_counts = Counter()
        for uid, etype, fields in parse_thread_events(thread1, event_types, important=True):
            if etype is None:
                continue
            important_counts[etype.name] += 1
            if etype.name == "$Trace.NewTrace":
                cycle_frequency = fields.get("CycleFrequency")
                trace_start_cycle = fields.get("StartCycle")
            elif etype.name == "$Trace.ThreadInfo":
                thread_names[fields["ThreadId"]] = fields.get("Name", f"Thread{fields['ThreadId']}")
            elif etype.name == "GpuProfiler.EventSpec":
                gpu_name = fields.get("Name")
                if isinstance(gpu_name, (bytes, bytearray)):
                    gpu_name = gpu_name.decode("utf-16-le", "replace").rstrip("\x00")
                gpu_name_map[fields["EventType"]] = gpu_name or f"<gpu:{fields['EventType']}>"

        gpu_results = {
            "GpuProfiler.Frame": [],
            "GpuProfiler.Frame2": [],
        }
        gpu_totals = {
            "GpuProfiler.Frame": Counter(),
            "GpuProfiler.Frame2": Counter(),
        }
        gpu_exclusive = {
            "GpuProfiler.Frame": Counter(),
            "GpuProfiler.Frame2": Counter(),
        }
        event_counts = Counter()

        for thread_id, thread_path in sorted(demux["thread_paths"].items()):
            if thread_id in (0, 1):
                continue
            try:
                for uid, etype, fields in parse_thread_events(thread_path, event_types, important=False):
                    if etype is None:
                        continue
                    event_counts[etype.name] += 1
                    if etype.name not in gpu_results:
                        continue
                    total_us, events = parse_gpu_buffer(
                        fields["Data"],
                        fields["TimestampBase"],
                        fields["CalibrationBias"],
                        gpu_name_map,
                    )
                    inclusive = Counter()
                    exclusive = Counter()
                    for event in events:
                        inclusive[event["name"]] += event["dur_us"]
                        exclusive[event["name"]] += event["exclusive_us"]
                        gpu_totals[etype.name][event["name"]] += event["dur_us"]
                        gpu_exclusive[etype.name][event["name"]] += event["exclusive_us"]
                    gpu_results[etype.name].append(
                        {
                            "thread_id": thread_id,
                            "thread_name": thread_names.get(thread_id, f"Thread{thread_id}"),
                            "total_us": total_us,
                            "events": events,
                            "top_inclusive": inclusive.most_common(8),
                            "top_exclusive": exclusive.most_common(8),
                        }
                    )
            except Exception as exc:
                thread_name = thread_names.get(thread_id, "?")
                raise RuntimeError(f"failed parsing thread {thread_id} ({thread_name}): {exc}") from exc

        summary = {
            "trace": {
                "path": trace_path,
                "transport_version": demux["transport_version"],
                "protocol_version": demux["protocol_version"],
                "packet_count": demux["total_packets"],
                "encoded_packets": demux["encoded_packets"],
                "decoded_size_bytes": sum(demux["decoded_sizes"].values()),
                "thread_count": len(demux["thread_paths"]),
                "cycle_frequency": cycle_frequency,
                "trace_start_cycle": trace_start_cycle,
                "decoder_path": resolved_decoder,
                "demux_dir": tmp_dir if keep_demux else None,
            },
            "thread_names": thread_names,
            "event_types": {uid: etype.name for uid, etype in event_types.items()},
            "important_counts": important_counts,
            "event_counts": event_counts,
            "gpu": {},
        }

        for timeline_name, frames in gpu_results.items():
            totals = [frame["total_us"] for frame in frames if frame["total_us"] > 0]
            worst = max(frames, key=lambda item: item["total_us"], default=None)
            summary["gpu"][timeline_name] = {
                "frame_count": len(frames),
                "avg_ms": ms(sum(totals) / len(totals)) if totals else 0.0,
                "median_ms": ms(statistics.median(totals)) if totals else 0.0,
                "p95_ms": ms(percentile(totals, 0.95)) if totals else 0.0,
                "max_ms": ms(max(totals)) if totals else 0.0,
                "top_inclusive": summarize_top(gpu_totals[timeline_name], sum(totals), len(frames)),
                "top_exclusive": summarize_top(gpu_exclusive[timeline_name], sum(totals), len(frames)),
                "worst_frame": {
                    "thread_id": None if worst is None else worst["thread_id"],
                    "thread_name": None if worst is None else worst["thread_name"],
                    "total_ms": 0.0 if worst is None else ms(worst["total_us"]),
                    "top_inclusive": [] if worst is None else [
                        {"name": name, "ms": ms(value)} for name, value in worst["top_inclusive"]
                    ],
                    "top_exclusive": [] if worst is None else [
                        {"name": name, "ms": ms(value)} for name, value in worst["top_exclusive"]
                    ],
                },
            }

        return summary
    finally:
        if not keep_demux:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def print_summary(summary):
    trace = summary["trace"]
    print("TRACE")
    print(f"  path: {trace['path']}")
    print(f"  transport/protocol: {trace['transport_version']}/{trace['protocol_version']}")
    print(f"  packets: {trace['packet_count']} (encoded {trace['encoded_packets']})")
    print(f"  decoded size: {trace['decoded_size_bytes'] / 1024 / 1024:.1f} MiB")
    print(f"  threads: {trace['thread_count']}")
    print(f"  decoder dll: {trace['decoder_path']}")
    if trace["cycle_frequency"]:
        print(f"  cycle frequency: {trace['cycle_frequency']}")
    if trace.get("demux_dir"):
        print(f"  demux dir: {trace['demux_dir']}")
    print()

    for timeline_name, data in summary["gpu"].items():
        if data["frame_count"] == 0:
            continue
        print(timeline_name)
        print(
            f"  frames: {data['frame_count']} avg {data['avg_ms']:.2f} ms "
            f"median {data['median_ms']:.2f} ms p95 {data['p95_ms']:.2f} ms max {data['max_ms']:.2f} ms"
        )
        worst_frame = data["worst_frame"]
        print(
            f"  worst frame: {worst_frame['total_ms']:.2f} ms on thread "
            f"{worst_frame['thread_id']} ({worst_frame['thread_name']})"
        )
        print("  top inclusive:")
        for row in data["top_inclusive"][:10]:
            print(
                f"    {row['name']}: total {row['total_ms']:.2f} ms "
                f"avg/frame {row['avg_ms_per_frame']:.2f} ms share {row['share']:.1f}%"
            )
        print("  top exclusive:")
        for row in data["top_exclusive"][:10]:
            print(
                f"    {row['name']}: total {row['total_ms']:.2f} ms "
                f"avg/frame {row['avg_ms_per_frame']:.2f} ms share {row['share']:.1f}%"
            )
        print("  worst frame contributors:")
        for row in worst_frame["top_inclusive"][:8]:
            print(f"    {row['name']}: {row['ms']:.2f} ms")
        print()


def write_json(path, payload):
    out_path = Path(path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Analyze Unreal .utrace files and summarize GPU hotspot frames.",
    )
    parser.add_argument("trace_path", help="Path to the .utrace file to inspect.")
    parser.add_argument(
        "--decoder-dll",
        help="Path to UnrealInsights-TraceLog.dll. Defaults to UE_TRACE_LOG_DLL or common UE install paths.",
    )
    parser.add_argument(
        "--json-out",
        help="Optional path to write the full summary as JSON.",
    )
    parser.add_argument(
        "--work-dir",
        help="Optional directory for temporary demux output.",
    )
    parser.add_argument(
        "--keep-demux",
        action="store_true",
        help="Keep the demux directory instead of deleting it after analysis.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the JSON summary to stdout instead of the text report.",
    )
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    try:
        summary = analyze_trace(
            args.trace_path,
            decoder_path=args.decoder_dll,
            work_dir=args.work_dir,
            keep_demux=args.keep_demux,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json_out:
        out_path = write_json(args.json_out, summary)
        if not args.print_json:
            print(f"wrote json summary: {out_path}")

    if args.print_json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print_summary(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
