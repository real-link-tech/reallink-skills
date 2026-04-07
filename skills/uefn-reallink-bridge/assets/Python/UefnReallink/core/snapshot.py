"""core/snapshot.py — Layout 数据快照 save / load"""

from __future__ import annotations

import json
from .common import ActorDesc, CellActor, Cell


# ─── Serialization helpers ────────────────────────────────────────────────────

def _actor_to_dict(ad: ActorDesc) -> dict:
    return {
        "guid": ad.guid, "name": ad.name, "label": ad.label,
        "native_class": ad.native_class, "base_class": ad.base_class,
        "spatially_loaded": ad.spatially_loaded, "hlod_relevant": ad.hlod_relevant,
        "bounds_min": list(ad.bounds_min), "bounds_max": list(ad.bounds_max),
        "runtime_grid": ad.runtime_grid,
    }


def _dict_to_actor(d: dict) -> ActorDesc:
    return ActorDesc(
        guid=d.get("guid", ""), name=d.get("name", ""), label=d.get("label", ""),
        native_class=d.get("native_class", ""), base_class=d.get("base_class", ""),
        spatially_loaded=d.get("spatially_loaded", True),
        hlod_relevant=d.get("hlod_relevant", False),
        bounds_min=tuple(d.get("bounds_min", (0, 0, 0))),
        bounds_max=tuple(d.get("bounds_max", (0, 0, 0))),
        runtime_grid=d.get("runtime_grid", "None"),
    )


def _cell_actor_to_dict(ca: CellActor) -> dict:
    return {"path": ca.path, "label": ca.label,
            "instance_guid": ca.instance_guid, "package": ca.package}


def _dict_to_cell_actor(d: dict) -> CellActor:
    return CellActor(path=d.get("path", ""), label=d.get("label", ""),
                     instance_guid=d.get("instance_guid", ""),
                     package=d.get("package", ""))


def _cell_to_dict(c: Cell) -> dict:
    return {
        "name": c.name, "short_id": c.short_id,
        "actor_count": c.actor_count, "always_loaded": c.always_loaded,
        "spatially_loaded": c.spatially_loaded,
        "content_bounds_min": list(c.content_bounds_min),
        "content_bounds_max": list(c.content_bounds_max),
        "cell_bounds_min": list(c.cell_bounds_min),
        "cell_bounds_max": list(c.cell_bounds_max),
        "is_2d": c.is_2d, "grid_name": c.grid_name, "level": c.level,
        "grid_x": c.grid_x, "grid_y": c.grid_y, "data_layer": c.data_layer,
        "actors": [_cell_actor_to_dict(a) for a in c.actors],
    }


def _dict_to_cell(d: dict) -> Cell:
    return Cell(
        name=d.get("name", ""), short_id=d.get("short_id", ""),
        actor_count=d.get("actor_count", 0),
        always_loaded=d.get("always_loaded", False),
        spatially_loaded=d.get("spatially_loaded", True),
        content_bounds_min=tuple(d.get("content_bounds_min", (0, 0, 0))),
        content_bounds_max=tuple(d.get("content_bounds_max", (0, 0, 0))),
        cell_bounds_min=tuple(d.get("cell_bounds_min", (0, 0, 0))),
        cell_bounds_max=tuple(d.get("cell_bounds_max", (0, 0, 0))),
        is_2d=d.get("is_2d", True), grid_name=d.get("grid_name", ""),
        level=d.get("level", 0), grid_x=d.get("grid_x", 0),
        grid_y=d.get("grid_y", 0), data_layer=d.get("data_layer", ""),
        actors=[_dict_to_cell_actor(a) for a in d.get("actors", [])],
    )


# ─── Public API ───────────────────────────────────────────────────────────────

def save_snapshot(path: str, actors: dict[str, ActorDesc], cells: list[Cell],
                  log_path: str):
    """Save parsed layout data to a JSON snapshot file."""
    data = {
        "version": 1,
        "log_path": log_path,
        "actors": {guid: _actor_to_dict(ad) for guid, ad in actors.items()},
        "cells": [_cell_to_dict(c) for c in cells],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[snapshot] Saved {len(actors)} actors, {len(cells)} cells → {path}")


def load_snapshot(path: str) -> tuple[dict[str, ActorDesc], list[Cell], str]:
    """Load layout data from a JSON snapshot file. Returns (actors, cells, log_path)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    actors = {guid: _dict_to_actor(d) for guid, d in data.get("actors", {}).items()}
    cells = [_dict_to_cell(d) for d in data.get("cells", [])]
    log_path = data.get("log_path", path)
    print(f"[snapshot] Loaded {len(actors)} actors, {len(cells)} cells ← {path}")
    return actors, cells, log_path
