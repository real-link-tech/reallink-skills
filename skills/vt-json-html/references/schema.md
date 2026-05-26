# VT NDJSON Schema

Observed report rows:

```json
{"type":"start","name":"Console","startFrame":50266}
{"type":"pool_meta","poolId":0,"poolKey":"DXT1_sRGB | Tile=136 Dim=2 Layers=1 CanSplit=1 Bias=1 Group=0","format":"DXT1","tileSize":136,"dimensions":2,"numLayers":1,"canSplit":true,"tileWidthHeight":120,"poolCount":1,"textureSize":16320,"numTiles":14400,"tileSizeBytes":9248,"capacityMB":127.001953}
{"t":"s","f":50266,"e":0.008,"id":0,"ap":14399,"apr":14400,"mp":16216,"lp":3057,"vp":3057,"bias":0.0,"ref":5321,"rref":2725}
{"type":"stop","name":"Console","startFrame":50266,"endFrame":51828,"durationSeconds":25.384}
```

Field groups:

- Run markers: `type`, `name`, `startFrame`, `endFrame`, `durationSeconds`.
- Pool metadata: `poolId`, `poolKey`, `format`, `tileSize`, `dimensions`, `numLayers`, `canSplit`, `tileWidthHeight`, `poolCount`, `textureSize`, `numTiles`, `tileSizeBytes`, `capacityMB`.
- Samples: `t`, `f`, `e`, `id`, `ap`, `apr`, `mp`, `lp`, `vp`, `bias`, `ref`, `rref`.

Charting guidance:

- Group sample rows by `id`.
- Label each series with pool id plus compact pool metadata.
- Use `e` as elapsed seconds for the x-axis. If absent, use `f`.
- Generate one chart per pool.
- Use green for pool size in MB, field `pool_meta.capacityMB`.
- Use yellow for visible usage in MB, default sample field `vp` multiplied by `pool_meta.tileSizeBytes / 1024 / 1024`.
- `vp` should match the in-game `VisiblePool` HUD path: `GetNumVisiblePages(Frame - PageFreeThreshold)`.
- Older reports written with `GetNumVisiblePages(Frame)` can undercount visible pages and often collapse to locked-page count, producing a flat yellow line.
- `ap` is allocated pages minus one reserved page; `apr` is raw allocated pages.
- `bias`, `ref`, and `rref` may have different scales, so they are better selected explicitly when needed.
