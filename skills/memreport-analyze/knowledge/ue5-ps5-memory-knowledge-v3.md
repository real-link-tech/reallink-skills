# UE5 PS5 Memory Knowledge Base v3

> Cross-project UE5 PS5 memory analysis knowledge base
> Updated: 2026-03-16
> v3.5: Major expansion of §3.10 AgcTransientHeaps — added transient classification logic, FastVRAM forced-transient list, PS5 virtual heap mechanism, stat relationships, three-type accounting model, memreport analysis strategy
> v3.4: Top assets: RHI same-name aggregation (VT pools ×N), UAV category separates engine-internal textures from game textures
> v3.3: Added RHI × listtextures deduplication documentation (§3.1)
> v3.2: Major expansion of §3.1 Textures — added Streaming Pool mechanism (RHI classification, pool budget calculation, NeverStream impact), NeverStream×Uncompressed cross-matrix analysis, Textures LLM composition tree methodology, data source cross-reference, enhanced §4.5 listtextures with full analysis workflow
> v3.1: Added Hair/Groom system §3.15, reference memory ranges, engine version annotation
> v3: Four-layer structure reorganization, removed project-specific data, added Audio/RHIMisc/Summary Bug universal warnings, added memreport parsing guide
>
> **Engine source line number baseline**: ue5-main branch @ 2026-03 (CL ~33xxx). Line numbers may shift with engine updates; function names and logic remain stable.

---

## Table of Contents

1. [PS5 Hardware Architecture](#1-ps5-hardware-architecture)
2. [Memory Tracking Internals](#2-memory-tracking-internals)
3. [LLM Tag Hierarchy and Analysis](#3-llm-tag-hierarchy-and-analysis)
4. [Memreport Section Parsing Guide](#4-memreport-section-parsing-guide)
5. [Engine Source Code Index](#5-engine-source-code-index)

---

## 1. PS5 Hardware Architecture

### 1.1 UMA (Unified Memory Architecture)

PS5 uses a **Unified Memory Architecture (UMA)** where CPU and GPU share the same physical memory pool — there is no separate VRAM. All CPU allocations and GPU resource allocations occur in the same physical memory.

This means:
- Texture data does not need to be copied from a CPU staging buffer to GPU VRAM (the PC discrete GPU workflow); the GPU directly accesses physical pages
- The same physical page can be accessed by both CPU and GPU simultaneously (no explicit transfer needed)
- Memory pressure comes from both CPU and GPU consumption combined; optimization must consider both

### 1.2 CPU / GPU / OS: Three Statistical Perspectives

Three different memory accounting dimensions exist on PS5. They **cannot be directly summed**:

| Perspective | Source | Meaning |
|---|---|---|
| OS Process Physical | OS process view | All physical page mappings actually held by the process |
| LLM Total (`STAT_UsedPhysical`) | UE5 LLM tracking | Total memory usage as tracked by UE5 |
| AGC GPU Total | GPU RHI view | Total as seen by the GPU resource allocator |

**Relationship logic:**

- **AGC GPU Total and FMalloc stats have a "partially overlapping, partially independent" relationship**:
  - **Overlapping part**: Regular GPU resources (textures, buffers) allocated through `FAgcMemory::Allocate` go through FMalloc bookkeeping → the same physical page is counted in both AGC and FMalloc
  - **Independent part**: AgcTransientHeaps (TSR/Lumen per-frame transient resources) completely bypass FMalloc, injected directly into LLM via `OnLowLevelChangeInMemoryUse` → invisible in FMalloc stats
- **OS Process Physical vs LLM Total difference** comes from: allocations LLM cannot track (Wwise and other middleware calling OS directly) and GPU mapped page calibration differences

> **Key conclusion**: Do not try to make these three numbers add up or derive from each other — they are different views under different accounting methods. Use data from the same snapshot for reconciliation, and tolerate ±100 MB calibration differences.

---

## 2. Memory Tracking Internals

### 2.1 OS Physical Memory Composition Formula

PS5 process OS physical memory is composed of (**FMalloc level only**):

```
OS Process Physical = FMalloc + ProgramSize + LLMOverhead + Untracked + OOMBackupPool + LLM-tracked bypassing FMalloc (AgcTransientHeaps etc.) ± calibration gap
```

| Component | Description |
|---|---|
| FMalloc | Total physical pages requested from OS by FMallocBinned2 (including used + cached free + fragmentation) |
| ProgramSize | Executable segments (code + read-only data) |
| LLMOverhead | LLM tracking system's own data structure overhead |
| Untracked | Allocations completely bypassing LLM (Wwise and other middleware calling OS directly) |
| OOMBackupPool | Pre-reserved OOM emergency pool |
| LLM-tracked bypassing FMalloc | AgcTransientHeaps and other allocations not going through FMalloc but recorded via LLM |
| Calibration gap | Statistical calibration differences between OS and LLM for GPU mapped pages |

**Verification formula template** (fill in values from the same snapshot):
```
FMalloc OS Total            _____ MB  ← "OS Total" line from FMallocBinned2
+ LLM-tracked bypassing FMalloc _____ MB  ← AgcTransientHeaps + other GPU direct LLM
+ Program Size               _____ MB
+ LLM Overhead               _____ MB
+ Untracked                  _____ MB
─────────────────────────────────
≈ LLM Total (STAT_UsedPhysical)
  ± calibration gap           ~___  MB
─────────────────────────────────
≈ OS Process Physical         _____ MB  ✓
```

> **Note**: `FMalloc Total` in memreport and FMallocBinned2's `OS Total` have calibration differences — the former is FMalloc's internal accounting view, the latter is the OS request amount. Use the same source for reconciliation.

### 2.2 FMallocBinned2 Structure

FMallocBinned2 is the default memory allocator for UE5 on PS5, divided internally into:

| Partition | Description |
|---|---|
| Small Pool OS | Small object allocation pool (fixed-size bins), handles allocations below threshold |
| Large Pool OS | Large object allocation pool, handles allocations exceeding Small Pool threshold |
| Cached free OS pages | Pages held by FMalloc but unused, returnable to OS |

**LLM FMalloc Unused tag composition**:

| Source | Description |
|---|---|
| Cached free OS pages | Recoverable via `FMalloc::TrimMemory()` |
| Small Pool bin internal fragmentation | Unused tail space within each bin's allocations |
| Large Pool alignment waste | Waste due to alignment |
| Other allocator overhead | Bookkeeping, page headers, uncategorized fragmentation |

**Fragmentation analysis method**: The memreport's FMallocBinned2 section outputs used/allocated/fragmentation rate for each bin. Focus on bins with fragmentation rate exceeding 30% — they correspond to specific-sized high-frequency allocation objects worth investigating for layout optimization.

### 2.3 LLM Tracking Architecture

LLM (Low Level Memory Tracker) is the core of UE5 runtime memory tracking.

#### Memory Allocation Paths

```
Memory Allocation
├── Through FMalloc (CPU heap)
│   └── Automatically hooked by LLM, controlled by current thread's LLM_SCOPE
│
├── RHI GPU resource allocation (AGC/sceKernelAllocateDirectMemory)
│   ├── GPU allocations through FMalloc (regular textures/buffers)
│   │   ├── Manual LLM_SCOPED_TAG (e.g., Nanite) → counted under corresponding tag
│   │   └── Default path: FAgcMemory::Allocate hardcodes ELLMTag::Untagged
│   │
│   └── GPU allocations bypassing FMalloc (AgcTransientHeaps)
│       └── Injected directly into LLM via OnLowLevelChangeInMemoryUse → counted under AgcTransientHeaps tag
│
└── Completely bypassing LLM (Wwise / some direct OS calls)
    └── Counted as Untracked (true blind spot)
```

#### LLM Scope Key Rules

1. **Inner scope overrides outer** — the innermost `LLM_SCOPE` on the same thread takes effect
2. **Thread-local** — Game Thread's scope does not propagate to Render Thread
3. **`LLM_REALLOC_SCOPE(ptr)`** — inherits the tag from the pointer's original allocation (used in realloc scenarios)
4. **Child tags bubble up** — `PropagateChildSizesToParents()` sums child tag values into parent tags each frame

### 2.4 Untracked Sources

Wwise and other middleware call OS allocation directly (`malloc`/`free` bypassing FMalloc hooks), completely bypassing LLM — this memory is invisible under any LLM tag.

Calculation: `Untracked = OS Process Physical − LLM Tracked Total` (read from the Platform layer in memreport).

### 2.5 stat LLM vs stat LLMFULL: Summary Bug Universal Warning

LLM has two reporting granularities:

| Command | Corresponds to | Meaning |
|---|---|---|
| `stat LLM` | `STATGROUP_LLM` | Summary layer (parent tag aggregation) |
| `stat LLMFULL` | `STATGROUP_LLMFULL` | Full layer (each child tag's independent value) |

#### ⚠️ Universal Warning: All `stat LLM` (Summary) values are unreliable

`PublishStats()` uses `SET_MEMORY_STAT_FName` (**overwrite, not accumulate**) to write tag values into Summary stats. When multiple child tags share the same Summary stat name, the last writer overwrites the previous ones, causing the Summary value to reflect only the last-written child tag.

**Confirmed affected Summary tags:**

| Summary stat | Displayed value | Actual value (LLMFULL) | Overwritten by | Difference factor |
|---|---|---|---|---|
| `STAT_TexturesSummaryLLM` | ~42 MB | ~2,088 MB | VirtualTextureSystem overwrites Textures | ~50x |
| `STAT_AudioSummaryLLM` | ~1.6 MB | ~600 MB | MetaSound overwrites Audio | ~364x |
| `STAT_UISummaryLLM` | ~0.9 MB | ~45 MB | UI_Style overwrites UI total | ~49x |

**Engine Summary suspicious**: `STAT_EngineSummaryLLM` may be identical to `STAT_AgcTransientHeapsLLM`. If Engine has only AgcTransientHeaps as a child tag, this is correct behavior; otherwise it may be the same bug. Source code verification needed to confirm which child tags are under Engine.

**Bug cause** (`LLM.cpp` in `PublishStats()`):
```cpp
// Pseudocode logic
for (each child tag sharing this summary stat) {
    SET_MEMORY_STAT_FName(SummaryStatName, ChildValue);  // Overwrite! Last one "wins"
}
```

**Status**: UE5 engine bug, unfixed as of March 2026 on `ue5-main` (file moved to `Private/HAL/LLM/LLM.cpp` but logic unchanged).

**Conclusion: When analyzing memreport, always use `STATGROUP_LLMFULL` values. Never trust any `stat LLM` Summary aggregate values.**

---

## 3. LLM Tag Hierarchy and Analysis

### 3.0 Hierarchy Overview

LLM statistics have three layers:

#### Platform Layer (`STATGROUP_LLMPlatform`)

Top level, corresponding to the overall composition of OS process memory:

```
Platform Layer:
  FMalloc          ← All allocations managed by FMallocBinned2 (including GPU allocations through FMalloc)
+ ProgramSize      ← Executable code segments
+ LLMOverhead      ← LLM's own overhead
+ Untracked        ← Allocations bypassing LLM (Wwise etc.)
+ OOMBackupPool    ← OOM emergency reserve
= Total (STAT_UsedPhysical)
```

**Platform Untagged**: The sum of all FMalloc allocations **not marked by any `LLM_SCOPE`**. This is a "catch-all" category, typically hundreds of MB, reflecting incomplete LLM tag coverage in the engine.

#### Summary Layer (`STATGROUP_LLM`)

Aggregated parent tag values. **⚠️ Has Summary Bug, unreliable** (see §2.5).

#### Full Layer (`STATGROUP_LLMFULL`)

Precise values for each independent child tag. **This is the only reliable analysis data source**.

**Key equation**:
```
LLMFULL Tracked Total + Untracked = Total (STAT_UsedPhysical)
```

FMalloc (Platform layer) = sum of all LLMFULL tags for allocations going through FMalloc.

#### Complete Tag Hierarchy Tree

```
Platform Layer
├── FMalloc                          ← Sum of all tags going through FMalloc
│   ├── Textures                     ← GPU streaming texture mip physical pages + CPU metadata
│   ├── TextureMetaData
│   ├── VirtualTextureSystem
│   ├── Meshes                       ← Parent tag (child tags bubble up)
│   │   ├── StaticMesh
│   │   ├── SkeletalMesh
│   │   ├── InstancedMesh
│   │   └── Landscape
│   ├── Physics                      ← Parent tag
│   │   ├── ChaosTrimesh
│   │   ├── ChaosAcceleration
│   │   ├── ChaosGeometry
│   │   ├── ChaosUpdate
│   │   ├── ChaosBody
│   │   ├── ChaosActor
│   │   ├── ChaosConvex
│   │   └── Chaos (uncategorized)
│   ├── UObject                      ← UObject shell itself
│   ├── Shaders
│   ├── Nanite                       ← GPU cluster/page buffer (re-tagged from Untagged via UpdateAllocationTags)
│   ├── Audio                        ← Parent tag
│   │   └── MetaSound
│   │   └── (other unnamed child tags, e.g., Wwise allocations through FMalloc)
│   ├── RHIMisc                      ← RHI miscellaneous GPU resources
│   ├── Animation
│   ├── Navigation
│   ├── SceneRender
│   ├── RenderTargets
│   ├── Lumen
│   ├── DistanceFields
│   ├── UI                           ← Parent tag
│   │   ├── UI_Style
│   │   ├── UI_Texture
│   │   ├── UI_Text
│   │   ├── UI_UMG
│   │   └── UI_Slate
│   ├── Niagara
│   ├── AssetRegistry
│   ├── StreamingManager
│   ├── ConfigSystem
│   ├── FMallocUnused               ← Fragmentation + cached free pages
│   ├── Untagged (LLMFULL)          ← FMalloc allocations not marked by any LLM_SCOPE
│   └── (other minor items)
│
├── AgcTransientHeaps                ← Bypasses FMalloc, injected directly into LLM (PS5 exclusive)
├── ProgramSize
├── LLMOverhead
├── OOMBackupPool
└── Untracked                        ← Completely bypasses LLM
```

---

### 3.1 Textures

**Tracked content**: GPU streaming texture mip physical pages + CPU-side texture metadata (`UTexture2D` object itself, ~9 KB each).

**LLM tag**: `ELLMTag::Textures` (`STAT_TexturesLLM` in `STATGROUP_LLMFULL`)

#### Textures Summary Tag Hierarchy

Defined in `LowLevelMemTracker.h` (L211-213):

```
STAT_TexturesSummaryLLM
├── ELLMTag::Textures              Main texture memory (GPU texel data + CPU metadata)
├── ELLMTag::TextureMetaData       Texture2D serialized metadata (CPU)
└── ELLMTag::VirtualTextureSystem  VT system management overhead (CPU)
```

#### RHI-Layer LLM Tagging Mechanism

GPU texture memory is tagged at texture creation time via `CreateTextureInitializer()` (`RHICommandList.h:927`):

```cpp
LLM_SCOPE(EnumHasAnyFlags(CreateDesc.Flags,
    TexCreate_RenderTargetable | TexCreate_DepthStencilTargetable)
    ? ELLMTag::RenderTargets   // RT/DS → RenderTargets LLM tag
    : ELLMTag::Textures);      // Others (including UAV-only) → Textures LLM tag
```

This inner scope **overrides** any outer scope (e.g., `LLM_SCOPE_BYTAG(Lumen)`) because LLM scope stacking uses last-push-wins within the same `ELLMTagSet::None`.

D3D12 also explicitly calls `OnLowLevelAlloc(ELLMTracker::Default, ..., ELLMTag::Textures)` in `UpdateD3D12TextureStats()` (`D3D12Texture.cpp:104-105`), but this `DefaultTag` parameter is only a **fallback** when no scope is active — it does NOT override the scope from `CreateTextureInitializer()`.

#### Textures vs RenderTargets LLM Split (Critical)

**The LLM tag for a GPU texture is determined solely by its creation flags, NOT by which rendering system created it:**

| Creation Flag | LLM Tag | Examples |
|---|---|---|
| `TexCreate_RenderTargetable` | **RenderTargets** | Lumen.SceneFinalLighting, SceneColor, Translucency |
| `TexCreate_DepthStencilTargetable` | **RenderTargets** | SceneDepth |
| `TexCreate_UAV` (without RT/DS) | **Textures** | TSR.History, VT Physical, DF.BrickTexture, Shadow.Virtual.PagePool |
| No special flag | **Textures** | Regular Texture2D (streaming/NeverStream) |

**Key consequence**: A single rendering system's textures can be split across BOTH tags:
- Lumen: SceneFinalLighting (RT→RenderTargets) vs Radiosity atlas (UAV→Textures)
- Scene: SceneColor (RT→RenderTargets) vs various UAV textures (→Textures)

#### Per-System GPU Texture LLM Tag Assignment (Source-Verified)

| RHI Resource Name | Source File | Creation Flags | LLM Tag |
|---|---|---|---|
| **Lumen.SceneFinalLighting** | `LumenSurfaceCache.cpp:277` | `ShaderResource + RenderTargetable + UAV` | **RenderTargets** |
| **Lumen.SceneDirectLighting** | `LumenSurfaceCache.cpp:253` | `ShaderResource + RenderTargetable + UAV` | **RenderTargets** |
| **Lumen.SceneIndirectLighting** | `LumenSurfaceCache.cpp:261` | `ShaderResource + RenderTargetable + UAV` | **RenderTargets** |
| **Lumen.SurfaceCache Physical Atlas** | `LumenSurfaceCache.cpp:208-232` | Compression-dependent: 无压缩/FBC→`RT`; UAVAliasing→`UAV` only | **取决于压缩模式** |
| **Lumen.Radiosity.*Atlas** | `LumenRadiosity.cpp:630` | `ShaderResource + UAV` | **Textures** |
| **Lumen.ScreenProbeGather.*** | `LumenScreenProbeFiltering.cpp:425` | `ShaderResource + UAV` | **Textures** |
| **TSR.History.Color/Guide/Metadata** | `TemporalSuperResolution.cpp:2151` | `ShaderResource + UAV` | **Textures** |
| **Shadow.Virtual.PhysicalPagePool** | `VirtualShadowMapCacheManager.cpp:1174` | `ShaderResource + UAV + AtomicCompatible` | **Textures** |
| **DistanceFields.BrickTexture** | 3D UAV texture | `ShaderResource + UAV` | **Textures** |
| **VT Physical Pools** | VirtualTextureSystem UAV | `ShaderResource + UAV` | **Textures** |
| **Hair.VoxelPageTexture** | HairStrands UAV | `ShaderResource + UAV` | **Textures** |
| **SceneColor** | Post-process RT | `RenderTargetable` | **RenderTargets** |
| **SceneDepth** | Depth buffer | `DepthStencilTargetable` | **RenderTargets** |

#### What is NOT in Textures LLM

| Tag | What goes here |
|---|---|
| **RenderTargets** | ALL textures with `TexCreate_RenderTargetable` or `TexCreate_DepthStencilTargetable` (includes Lumen lighting atlases, SceneColor, SceneDepth, Translucency, Subsurface, etc.) |
| UI_Texture | Slate/UMG UI layer custom-tagged textures |
| Nanite | Primarily Buffers, not textures |

#### Allocation Path

**Streaming textures** use `TexCreate_ReservedResource` → `FAgcReservedResource` path:

1. `FAgcTexture` constructor (`AgcTexture.cpp:987`) creates `new FAgcReservedResource` within `ELLMTag::Textures` scope
2. When mips stream in, calls `FAgcReservedResource::Commit()` (`AgcReservedResource.cpp:73`)
3. Line 101: `LLM_REALLOC_SCOPE(this)` — inherits the Textures tag from object creation
4. `UpdateLLMTracking` calls `OnLowLevelAlloc(Default, VirtualPointer, CommittedSize)` → counted under Textures

**Non-streaming textures** go through `FAgcMemory::Allocate` (`AgcTexture.cpp:554`) → hardcoded `ELLMTag::Untagged` (NOT counted under Textures tag!).

#### PS5 UMA Texture Characteristics

| Platform | Flow |
|---|---|
| PC (discrete GPU) | Disk → CPU staging buffer → Copy → GPU VRAM (two copies) |
| PS5 (UMA) | Disk → Unified physical page → GPU reads directly (one copy) |

Textures LLM value composition = CPU metadata + texel GPU data. There is a brief double-copy during stream-in (IO buffer → decompress to target physical page → IO buffer released), but this is not a persistent double-copy.

#### Textures vs RenderTargets: Two Separate LLM Trees

**IMPORTANT**: RHI NonStreaming textures span TWO different LLM tags. The tree must NOT mix them.

- **RHI NonStreaming classification** (based on `RHICoreStats.h`): RT + UAV + ForceNonStreaming → all excluded from streaming pool
- **LLM tag classification** (based on `RHICommandList.h:927`): RT/DS → `RenderTargets`; UAV-only/other → `Textures`

These are **different axes**. UAV-only textures are NonStreaming in RHI but under `Textures` LLM. RT textures are NonStreaming in RHI but under `RenderTargets` LLM.

#### Textures LLM Composition Tree (Analysis Methodology)

When analyzing a memreport, decompose the Textures Summary LLM using ONLY resources that belong to the Textures tag:

```
Textures (Summary LLM)                                              Total MB
|
|-- TextureMetaData (LLMFULL)                                          ~1%
|-- VirtualTextureSystem (LLMFULL)                                     ~2%
|
|-- [NonStreaming UAV-only] (UAV flag, NO RT/DS flag → Textures LLM tag)
|   |-- VT Physical Pools (multiple UAV pools)                     ← largest item
|   |-- TSR.History.Color / Guide / Metadata (UAV)
|   |-- Shadow.Virtual.PhysicalPagePool (UAV)
|   |-- DistanceFields.BrickTexture (3D UAV)
|   |-- Hair.VoxelPageTexture (UAV)
|   |-- Lumen.Radiosity.*Atlas (UAV)                               ← Lumen partial
|   |-- Lumen.ScreenProbeGather.* (UAV)                            ← Lumen partial
|   |-- Lumen.SurfaceCache.* (ONLY in UAVAliasing compression mode)
|   |-- ShaderPrint.DepthTexture (Dev only, 0 in Test/Shipping)
|   +-- Other UAV-only engine internal textures
|
|-- [Streaming Pool] Non-RT Non-UAV textures (in streaming pool)
|   |
|   |   Pool budget: TexturePoolSize (from r.Streaming.PoolSize)
|   |   StreamingPool = PoolSize - NonStreamingMips - Safety - Temp
|   |
|   |-- NeverStream (Streaming=NO)     ← typically 80-90% of pool budget
|   |   |-- by TextureGroup: UI, World, 16BitData, RenderTarget, Effects, etc.
|   |   |-- [Compressed] vs [Uncompressed] sub-breakdown
|   |
|   +-- Streaming (Streaming=YES)      ← typically only 8-15% of OnDisk loaded
|       |-- by TextureGroup: World, WorldNormalMap, Effects, Character, etc.
|       |-- InMem vs OnDisk ratio indicates streaming pressure
```

#### RenderTargets LLM Composition Tree

RenderTargets is a **separate LLMFULL tag**, NOT a child of Textures. It contains all textures with `TexCreate_RenderTargetable` or `TexCreate_DepthStencilTargetable`:

```
RenderTargets (LLMFULL)                                             Total MB
|
|-- Lumen.SceneFinalLighting (RT+UAV)                              ← Lumen's largest RT
|-- Lumen.SceneDirectLighting (RT+UAV)
|-- Lumen.SceneIndirectLighting (RT+UAV)
|-- Lumen.SurfaceCache Physical Atlas (ONLY in non-compressed / FBC mode, RT)
|-- Lumen.SceneDirectLighting.DiffuseLightingAndSecondMomentHistory (RT+UAV)
|-- SceneColor (RT)
|-- SceneDepth (DepthStencil)
|-- Translucency / Subsurface (RT)
+-- Other render targets
```

**Key implications for analysis**:
1. `rhi.DumpResourceMemory` Texture entries include BOTH `Textures` and `RenderTargets` tagged resources — you CANNOT sum all RHI textures and compare against the Textures LLM value
2. RHI resources with names like `Lumen.*`, `SceneColor`, `Translucency.*` that have RT flags belong to **RenderTargets**, not Textures
3. When building the NonStreaming breakdown tree under Textures, you must **exclude RT-flagged resources** (see table above for per-resource classification)
4. Lumen's texture memory is split: lighting atlases (RT) → RenderTargets; radiosity/probe (UAV) → Textures

**Key insight**: `listtextures` InMem total is typically only ~30% of Textures LLM — the remaining ~70% is engine rendering pipeline internal UAV-only textures invisible to `listtextures`. The RT textures (Lumen lighting, SceneColor, etc.) are in a completely separate RenderTargets LLM tag.

#### RHI × listtextures Deduplication

**CRITICAL**: NeverStream (and Streaming) game textures appear in **both** `rhi.DumpResourceMemory` and `listtextures`. These are the **same physical memory** viewed from two different layers:

| Data source | Layer | Name format | Example |
|---|---|---|---|
| `rhi.DumpResourceMemory` | RHI (GPU) | Short name, no "/" prefix | `T_MapTest_DaYing_8k` |
| `listtextures` | UObject (Engine) | Full asset path | `/Game/.../T_MapTest_DaYing_8k.T_MapTest_DaYing_8k` |

If both are included in the breakdown tree, the same texture is **double-counted**. The parse script deduplicates by building a set of `listtextures` short names (extract filename before first ".") and excluding matching RHI entries from the NonStreaming/RenderTargets sections. The NeverStream/Streaming sections (sourced from `listtextures`) are the authoritative source for game textures.

**Which textures remain in NonStreaming (RHI-only)?** Engine internal textures that are invisible to `listtextures`: VT Physical Pools, TSR History, DistanceFields BrickTexture, Shadow Virtual PagePool, Hair VoxelPageTexture, ShaderPrint DepthTexture, etc. These have no UObject and only exist at the RHI layer.

#### Top Assets: RHI Same-Name Aggregation and UAV Category

RHI resources can have **multiple entries with the same name** (e.g., `VirtualTexture_Physical` appears as 11 separate pools). The top assets builder pre-aggregates by name, summing sizes and tracking count. Display: `VirtualTexture_Physical (×11) — 763.5 MB`.

Engine-internal textures (VirtualTexture*, ShaderPrint, Translucency, AgcBackBuffer, etc.) are classified under a separate **"UAV"** category in the top assets table, distinct from the **"Texture"** category which contains game asset textures from `listtextures`. This prevents engine overhead from inflating the game texture ranking.

#### Streaming Pool Mechanism (Source Code Analysis)

##### RHI-Layer Streaming / NonStreaming Classification

`RHICoreStats.h` (L73-87):

```cpp
const bool bAlwaysExcludedFromStreamingSize = EnumHasAnyFlags(TextureFlags,
    AllRenderTargetFlags
    | ETextureCreateFlags::UAV
    | ETextureCreateFlags::ForceIntoNonStreamingMemoryTracking
);

if (!bAlwaysExcludedFromStreamingSize && ...)
    → StreamingTextureMemorySizeInKB   // Counts toward pool budget
else
    → NonStreamingTextureMemorySizeInKB // Does NOT count toward pool budget
```

| RHI Classification | Counts Toward Pool Budget |
|---|:---:|
| Texture 2D (non-RT, non-UAV) | Yes |
| Texture Cube | Yes |
| Texture 3D | Yes |
| UAV Texture | No |
| Render Target 2D/Cube/3D | No |

##### Pool Budget Calculation

`AsyncTextureStreaming.cpp` (L634-635):

```cpp
NonStreamingRenderAssetMemory = AllocatedMemory - MemoryUsed + MemoryUsedByNonTextures;
AvailableMemoryForStreaming = PoolSize - NonStreamingRenderAssetMemory - MemoryMargin;
```

- `AllocatedMemory` = `Stats.StreamingMemorySize` = all non-RT, non-UAV texture allocated memory at RHI layer
- `NonStreamingRenderAssetMemory` = `AllocatedMemory` minus streaming assets' ResidentSize

**The Streaming Pool is NOT a pre-allocated physical memory block** — it is a budget calculated as `TexturePoolSize - NonStreamingMips - Safety - Temp`.

##### NeverStream Impact on Pool

`AsyncTextureStreaming.cpp` (L1114, L1193):

```cpp
Stats.NonStreamingMips = AllocatedMemory;  // Initialize to total

// Deduct for each streaming asset
Stats.NonStreamingMips -= ResidentSize * StreamingRenderAsset.IsTexture();
```

**NeverStream textures are not managed by the streamer, unconditionally load all mips, and directly consume pool budget.** Regardless of whether the UObject layer has streaming enabled, as long as it is a regular Texture2D (non-RT, non-UAV), it occupies pool budget.

#### Texture Streaming Budget Analysis Method

Read these values from memreport to evaluate streaming health:

| Statistic | Meaning | Location in memreport |
|---|---|---|
| `r.Streaming.PoolSize` | Streaming pool total budget | Config or memreport output |
| `StreamingPool` | Available streaming budget after deductions | `Texture Streaming` section |
| `NonStreamingMips` | Non-streamer-managed portion consuming budget | `Texture Streaming` section |
| `Required Pool` | Actual demand | `Texture Streaming` section |
| `Used` | Current usage and utilization % | `Texture Streaming` section |
| NeverStream texture total | Not managed by streaming but occupying budget | `NeverStream` flag in `listtextures` |

- **Budget headroom** = PoolSize − Required Pool. Below 50 MB risks streaming stalls
- **Pending stream-in** = Required Pool − Used. Reflects current streaming backlog
- **NeverStream pool occupation ratio** = NeverStream InMem / PoolSize. Above 80% is critical — streaming textures get severely starved
- **Streaming load ratio** = Streaming InMem / Streaming OnDisk. Below 10% indicates extreme streaming starvation

#### NeverStream × Uncompressed Cross-Matrix Analysis

These two attributes are independent and **cannot be simply summed** (there is overlap):

|  | Compressed | Uncompressed | Total |
|---|---:|---:|---:|
| **NeverStream** | N textures / A MB | M textures / B MB | X / C MB |
| **Streaming** | P textures / D MB | Q textures / E MB | Y / F MB |
| **Total** | | | All / G MB |

**Uncompressed format optimization targets** (common patterns):

| Format | Compressible To | Expected Savings |
|---|---|---|
| PF_B8G8R8A8 | BC7 or DXT5 | ~75% (4:1 compression) |
| PF_FloatRGBA | BC6H (evaluate VAT/lookup textures case-by-case) | ~50% (may lose precision) |
| PF_G8 | BC4 | ~50% (2:1 compression) |

**Dual penalty**: NeverStream + Uncompressed textures suffer both penalties — they permanently occupy pool budget AND use 2-4x more memory than compressed equivalents. Prioritize these for optimization.

**Analysis methodology**:
1. From `listtextures`, filter by `NeverStream` flag and `NoCompress` flag
2. Build the cross-matrix to identify the overlap zone
3. For NeverStream textures: evaluate if streaming can be enabled (especially for textures > 4 MB)
4. For Uncompressed textures: evaluate if compression is possible without quality loss (BC7 for color, BC6H for HDR, BC4 for grayscale)
5. Prioritize the NeverStream+Uncompressed intersection for maximum savings

#### Data Source Cross-Reference

When analyzing textures, multiple data sources report different values. Understanding their relationship is critical:

| Data Source | What It Measures | LLM Tag |
|---|---|---|
| LLM Textures (LLMFULL) | UAV-only + regular (non-RT/DS) GPU textures | `ELLMTag::Textures` |
| LLM Textures (Summary) | LLMFULL Textures + TextureMetaData + VirtualTextureSystem | Aggregated |
| LLM RenderTargets (LLMFULL) | ALL RT + DepthStencil textures (includes Lumen lighting, SceneColor, etc.) | `ELLMTag::RenderTargets` |
| `rhi.DumpResourceMemory` Texture | ALL GPU textures regardless of LLM tag — spans BOTH Textures and RenderTargets | Mixed! |
| `listtextures` InMem | UObject-layer textures only (excludes VT InMem=0 entries) | Subset of Textures |
| Streaming Pool | Budget headroom (not physical allocation) | Subset of Textures |

**Key reconciliation**:
- `listtextures` InMem total is only the UObject-visible portion (~30% of Textures LLM). The remaining ~70% is engine internal UAV-only textures (VT Physical Pools, TSR History, DF BrickTexture, VSM, Hair Voxel, etc.)
- `rhi.DumpResourceMemory` Texture entries include BOTH Textures-tagged and RenderTargets-tagged resources. **Do NOT sum all RHI textures and compare against Textures LLM** — the RT-flagged portion (Lumen lighting atlases, SceneColor, SceneDepth, etc.) belongs to the separate RenderTargets tag
- To validate: Textures LLMFULL ≈ (RHI Texture total) − (RHI resources with RT/DS flags) + TextureMetaData overhead

#### Locating Texture Assets in Memreport

- **LLM value**: `STAT_TexturesLLM` line (`STATGROUP_LLMFULL`)
- **Specific texture list**: `listtextures nonvt` command output, sorted by `CurrentKB`
- **RHI-side GPU textures**: Textures category in `rhi.DumpMemory`
- **By TextureGroup distribution**: `rhi.DumpResourceMemory summary name=TextureGroup` or Group column in `listtextures`
- **Engine internal textures**: `rhi.DumpResourceMemory` Top N list — look for VirtualTexture_Physical, TSR.History, DistanceFields.BrickTexture, Shadow.Virtual, Hair.Voxel, ShaderPrint.DepthTexture
- **NeverStream audit**: `listtextures nonvt` filtered by NeverStream flag, sorted by CurrentKB
- **Uncompressed audit**: `listtextures uncompressed` to find compression optimization candidates

---

### 3.2 Meshes

**Parent tag**, value aggregated from child tags via `PropagateChildSizesToParents()`.

Child tags: StaticMesh, SkeletalMesh, InstancedMesh, Landscape.

#### 3.2.1 StaticMesh

**LLM tag**: `ELLMTag::StaticMesh` (`STAT_StaticMeshSummaryLLM`)

**Tracked content**: UStaticMesh CPU-side data — metadata, Nanite CPU metadata (RootData/HierarchyNodes TArray), HLOD ISM instance data, component objects, etc.

**NOT included in LLM StaticMesh** (these go to other tags):
- Non-Nanite GPU vertex/index buffers → counted under LLM **Untagged** (`FAgcMemory` hardcoded)
- Nanite GPU cluster/page buffers → counted under LLM **Nanite** (`UpdateAllocationTags`)
- BodySetup collision data → counted under LLM **Physics**
- NavCollision data → counted under LLM **Navigation**

**LLM Scope covered code paths**:

| File | Function | Allocation content |
|---|---|---|
| `StaticMesh.cpp:7193` | `Serialize` | `LLM_SCOPE_BYNAME("StaticMesh/Serialize")` |
| `StaticMeshComponent.cpp:341` | `Serialize` | Component deserialization |
| `StaticMeshComponent.cpp:920` | `CreateRenderState_Concurrent` | SceneProxy creation |
| `StaticMesh.cpp:4762` | `InitResources` | Mesh resource initialization |
| `StaticMeshUpdate.cpp:526` | `SerializeLODData` | Streaming IO load (CPU TResourceArray) |
| `StaticMeshUpdate.cpp:158` | `CreateBuffers` | Streaming GPU buffer creation |
| `PrimitiveSceneInfo.cpp:1580` | `AddStaticMeshes` | MeshDrawCommand cache registration |
| `HierarchicalInstancedStaticMesh.cpp:2235` | — | HISM data |

**Three statistical values and their differences** (core analysis methodology):

| Source | Meaning | Accuracy |
|---|---|---|
| `STAT_StaticMeshTotalMemory` | ResourceSize snapshot taken at PostLoad, includes Nanite StreamablePages CPU copy | **Inaccurate**, permanently inflated |
| `obj list class=StaticMesh` ResExcKB | Real-time obj traversal result | **Accurate** (current moment) |
| LLM `ELLMTag::StaticMesh` | Malloc tracking within LLM scope | **Accurate** (but only covers allocations within LLM_SCOPE) |

**`STAT_StaticMeshTotalMemory` overestimation cause** (`NaniteResources.cpp:532-545`):

```cpp
if (StreamablePages.IsBulkDataLoaded())  // true at PostLoad
{
    CumulativeResourceSize.AddDedicatedSystemMemoryBytes(StreamablePages.GetBulkDataSize());
}
```

- At PostLoad: `IsBulkDataLoaded() = true` → STAT increment includes StreamablePages
- At memreport time: after Nanite streaming takes over, `IsBulkDataLoaded() = false` → obj list doesn't include it
- STAT only adds at PostLoad and removes at BeginDestroy, **never updates during streaming out** → permanently inflated

**Non-Nanite Mesh Streaming: CPU/GPU Double-Copy Window**

```
Timeline →
IO Thread:   [━━━ Disk → TResourceArray (CPU memory) ━━━]
Render Thread:                                             [Create GPU Buffer + Copy + Discard()]

CPU data:    [████████████████████████████████████████]
                                                          ↑ Discard() releases
GPU data:                                                [████████████→ Persistent
```

This double-copy window causes Peak Physical to be ~1.9–2.2 GB higher than Current Physical (large game scenes).

**`TResourceArray::Discard()` behavior** (`DynamicRHIResourceArray.h`):

```cpp
virtual void Discard() override
{
    if (!bNeedsCPUAccess && FPlatformProperties::RequiresCookedData() && !IsRunningCommandlet())
        this->Empty();  // Immediately releases CPU data
}
```

- `bAllowCPUAccess = false` (default): `Discard()` called immediately after GPU upload, no wait
- `bAllowCPUAccess = true`: CPU data persists until StreamOut (double memory!)

**Locating StaticMesh assets in memreport**:
- `obj list class=StaticMesh`: Per-asset list, note the `ResExcKB` column (exclusive resource size)
- Compare STAT vs obj list vs LLM three values to detect Nanite overestimation or tag gaps

#### 3.2.2 SkeletalMesh

**LLM tag**: `ELLMTag::SkeletalMesh` (`STAT_SkeletalMeshLLM`)

**Tracked content**: SkeletalMesh runtime buffers (bone transforms, animation evaluation, LOD streaming), Vertex/Index Buffers, SkinCache, Component objects, Asset CPU metadata, etc.

**LLM Scope covered paths**:

| File | Function | Sub-tag |
|---|---|---|
| `SkeletalMesh.cpp:1910` | `Serialize` | `SkeletalMesh/Serialize` |
| `SkeletalMesh.cpp:1039` | `InitResources` | `SkeletalMesh/InitResources` |
| `SkinnedMeshComponent.cpp:2839` | `AllocateTransformData` | `SkeletalMesh/TransformData` |
| `SkeletalMeshUpdate.cpp:544` | `SerializeLODData` | `SkeletalMesh/Serialize` |
| `SkinnedMeshComponent.cpp:4911` | `SetVertexColorOverride` | `SkeletalMesh/VertexColorOverride` |

**Locating SkeletalMesh assets in memreport**:
- `obj list class=SkeletalMesh`: Per-asset list
- Focus on Top N largest assets (a single character model can be tens of MB)

#### 3.2.3 InstancedMesh

**LLM tag**: `ELLMTag::InstancedMesh` (`STAT_InstancedMeshLLM`)

**Tracked content**: HLOD/ISM instance data. Primarily from World Partition's HLOD system and InstancedStaticMeshComponents in the scene.

#### 3.2.4 Landscape

**LLM tag**: `ELLMTag::Landscape`

Usually very small (<1 MB), because most of Landscape's GPU data goes through other paths.

---

### 3.3 FMalloc Unused

**LLM tag**: `ELLMTag::FMallocUnused`

**Tracked content**: FMallocBinned2 internal fragmentation + cached free pages. This is not "wasted" memory but buffer reserved by the allocator for performance.

**Fragmentation analysis methodology**:

1. Read each bin's statistics from the memreport's FMallocBinned2 section
2. Focus on Cached free OS pages (immediately recoverable via `FMalloc::TrimMemory()`)
3. Focus on bins with fragmentation rate exceeding 30%, investigate the corresponding size's high-frequency allocation objects
4. FMalloc Unused typically accounts for 8-12% of total FMalloc; above this range needs attention

---

### 3.4 Physics / Chaos

**LLM tag**: `ELLMTag::Physics` (parent tag, aggregated from child tags via bubble-up)

**Tracked content**: Chaos physics engine collision data, primarily from scene StaticMesh BodySetups.

**Child tag tree**:

| Sub-tag | Description |
|---|---|
| ChaosTrimesh | Collision triangle mesh (usually the largest child) |
| ChaosAcceleration | BVH acceleration structure |
| ChaosGeometry | Geometry data |
| ChaosUpdate | Physics simulation update buffers |
| ChaosBody | Physics body data |
| ChaosActor | Physics Actor data |
| ChaosConvex | Convex collision data |
| Chaos (uncategorized) | Chaos allocations not covered by child tags |

**Scene-dependent**: Menu scenes have Physics near 0, open world scenes can reach hundreds of MB to 1 GB, entirely from collision geometry.

---

### 3.5 UObject

**LLM tag**: `ELLMTag::UObject` (`STAT_UObjectSummaryLLM`)

**Tracked content**: Only the UObject shell itself (the fixed-size allocation from `UObjectBase::UObjectBase()`), **not resource data**.

Example: `UStaticMesh` object shell → UObject tag; its `StaticMaterials` TArray data → StaticMesh tag.

**Analysis method**: `obj list -resourcesizesort` shows all UObjects sorted by resource size, but note the ResExcKB column is resource data (not including the UObject shell itself).

---

### 3.6 Shaders

**LLM tag**: `ELLMTag::Shaders`

**Tracked content**: Shader bytecode / preloaded data (CPU side) + GPU Shader Binary (usually small).

CPU-side shader permutation data is the bulk. Outdoor scenes (Lumen/Nanite/Shadow passes) require more shader permutations, potentially adding hundreds of MB compared to menu scenes.

---

### 3.7 Nanite

**LLM tag**: Via `LLM_SCOPE_BYNAME("Nanite")`

**Tracked content**: Nanite GPU cluster/page buffer.

**Allocation mechanism**: Re-tagged from Untagged via `UpdateAllocationTags`:

`AgcBuffer.cpp:259-277` — `UpdateAllocationTags()` flow:
```
OnLowLevelFree(Untagged) + OnLowLevelAlloc(current LLM scope) → Re-categorized
```

`NaniteResources.cpp`'s `InitRHI` uses `LLM_SCOPE_BYNAME("Nanite")` + `AllocatePooledBufferCurrentLLMTag`, which is **the only path correctly using this re-tag mechanism**.

**Nanite StreamablePages = No persistent CPU copy**:

- `StreamablePages` BulkData is a file offset handle; normally `IsBulkDataLoaded() = false`
- Each page stream-in path: Disk → `PendingPage.RequestBuffer` (temporary) → GPU PagePool → CPU buffer immediately released
- GPU PagePool = fixed-size LRU circular buffer
- **No double-copy issue**

**Nanite data always on CPU side** (counted under StaticMesh tag, not Nanite tag):

| Data | LLM Tag |
|---|---|
| `RootData` — root page (hot data) | StaticMesh |
| `HierarchyNodes` — cluster hierarchy | StaticMesh |
| `PageStreamingStates` — per-page BulkOffset/Size | StaticMesh |

---

### 3.8 Audio

**LLM tag**: `ELLMTag::Audio` (`STAT_AudioLLM` in `STATGROUP_LLMFULL`)

**⚠️ `STAT_AudioSummaryLLM` has Summary Bug**, displayed value may be only 1/364th of actual (see §2.5). Always use LLMFULL.

**Tracked content**: Audio data managed through FMalloc.

**Known child tags**:
- MetaSound

**Analysis challenges**:

- Audio LLMFULL value is usually much larger than the sum of known child tags. The bulk of the difference likely comes from Wwise SoundEngine allocations through FMalloc that are not marked by child tags
- Wwise-related STATs in memreport may all be 0 (Wwise plugin does not report to UE STAT)
- Source code tracing of Audio-related `LLM_SCOPE` coverage is needed to confirm which allocations are attributed to the Audio tag

**Locating audio assets in memreport**:
- `obj list class=SoundWave`: SoundWave asset list
- Wwise memory stats require the Wwise Profiler tool separately; memreport usually doesn't show complete information

---

### 3.9 RHIMisc

**LLM tag**: `ELLMTag::RHIMisc`

**Tracked content**: RHI layer miscellaneous GPU resources — RHI allocations not belonging to other specific tags (Textures/Nanite/RenderTargets etc.).

This is a large tag (typically hundreds of MB) containing various GPU buffers and resources. Analysis requires combining `rhi.DumpMemory` and `rhi.DumpResourceMemory` to determine specific contents.

---

### 3.10 AgcTransientHeaps

**LLM tag**: `STAT_AgcTransientHeapsLLM` (PS5 platform exclusive)

**Tracked content**: RDG per-frame transient GPU resources — textures and buffers that are created and released within a single frame, sharing heap memory via aliasing.

**Allocation path**: Completely bypasses FMalloc, injected directly into LLM via `OnLowLevelChangeInMemoryUse` (`AgcSubmission.cpp:236-237`).

**Not in TexturesLLM** — this is an independent PS5 platform tag.

#### 3.10.1 Transient vs Non-Transient Classification

Classification is determined during RDG compilation by `FRDGBuilder::IsTransient()`:

**Texture classification**:
1. Platform must support transient textures
2. Must NOT have `Shared` flag
3. `IsTransientInternal()` check (see below)

**Buffer classification** (stricter):
1. Platform must support transient buffers
2. Must NOT have pending upload data (`bQueuedForUpload`)
3. `IsTransientInternal()` check
4. Must NOT be `DrawIndirect` when `r.RDG.TransientAllocator.IndirectArgumentBuffers=0`
5. **Must have `BUF_UnorderedAccess` (UAV) flag** — pure VB/IB/UB never transient

**Core internal check (`IsTransientInternal`)**:

| Condition | Result |
|---|---|
| FastVRAM flag + platform supports → | **Forced transient** (ignores Extract, ForceNonTransient) |
| Non-FastVRAM + not Extracted + not ForceNonTransient → | Transient |
| Non-FastVRAM + Extracted + `GRDGTransientExtractedResources=1` (default) → | Depends on `TransientExtractionHint` |
| Non-FastVRAM + `bForceNonTransient` → | Non-transient |

> Source: `Engine/Source/Runtime/RenderCore/Private/RenderGraphBuilder.cpp`

**Key CVars**:

| CVar | Default | Effect |
|---|---|---|
| `r.RDG.TransientAllocator` | 1 | 0=disable, 1=enable, 2=FastVRAM only |
| `r.RDG.TransientExtractedResources` | 1 | 0=Extracted always non-transient, 1=respect Hint, 2=force all transient |
| `r.RDG.TransientAllocator.IndirectArgumentBuffers` | 0 | 0=IndirectArg buffers non-transient (GPU crash workaround UE-115982) |

#### 3.10.2 FastVRAM — Primary Transient Entry Point

FastVRAM flag forces resources onto the transient path on PS5. Configured via `FFastVramConfig` (`SceneRendering.h/.cpp`).

**Textures with FastVRAM=1 by default** (forced transient on PS5):

SceneColor, SceneDepth, GBufferB, HZB, Bloom, BokehDOF, CircleDOF, DOFSetup, DOFReduce, DOFPostfilter, CombineLUTs, Downsample, EyeAdaptation, Histogram, HistogramReduce, VelocityFlat, VelocityMax, MotionBlur, Tonemap, Upscale, DistanceFieldNormal, DistanceFieldAOHistory, DistanceFieldAODownsampledBentNormal, DistanceFieldShadows, Distortion, ScreenSpaceShadowMask, VolumetricFog, PostProcessMaterial

**Textures with FastVRAM=0** (not forced transient): GBufferA/C/D/E/F/Velocity, SeparateTranslucency, SSAO, SSR, DBuffer, CustomDepth, Shadow maps

**Buffers with FastVRAM=1**: DistanceFieldCulledObjectBuffers, DistanceFieldTileIntersectionResources, DistanceFieldAOScreenGridResources, ForwardLightingCullingResources, GlobalDistanceFieldCullGridBuffers

> **Important**: FastVRAM forces transient even if the resource is Extracted. Such resources appear in the RT pool dump (via `FRDGTransientRenderTarget` wrapper) but their physical memory lives in the transient heap.

#### 3.10.3 Three Types of Resource Accounting

| Type | Memory source | In RT Pool dump? | In `rhi.DumpResourceMemory`? | In AgcTransientHeaps LLM? |
|---|---|---|---|---|
| **Pure transient** (not Extracted) | Transient heap | No | No (excluded as transient) | Yes |
| **Transient + Extracted** | Transient heap | Yes (via wrapper) | Possibly | Yes |
| **Pure Pooled** (non-transient) | Regular GPU memory | Yes | Yes | No |

> **No built-in UE5 command** lists individual transient resources. Use `r.RDG.DumpGraph`, Unreal Insights RDG channel, or disable transient allocation (`r.RDG.TransientAllocator=0`) and compare memory delta.

#### 3.10.4 Typical Transient Resource Composition

Resources created in-frame by RDG and meeting transient criteria. Sub-items may not sum to total due to aliasing:

| Category | Key resources | Notes |
|---|---|---|
| Post-processing (FastVRAM) | SceneColor, Tonemap, Bloom, DOF, MotionBlur, Upscale | Forced transient via FastVRAM |
| Depth / HZB | SceneDepth, HZB | Forced transient via FastVRAM |
| GBuffer | GBufferB (only B has FastVRAM=1) | Other GBuffers are non-transient |
| TSR | TSR.History.Color/Guide/Metadata | Extracted → appear in RT pool too |
| Lumen | Scene lighting intermediates | Non-history parts |
| Distance Fields | DF Normal/Shadow/AO intermediates | FastVRAM-flagged DF textures |
| VolumetricFog | Fog scattering/integration textures | FastVRAM=1 |
| Nanite/VSM intermediates | Culling/rasterization scratch buffers | UAV + not Extracted → pure transient |

#### 3.10.5 PS5 Virtual Heap Mechanism

> Source: `Engine/Platforms/PS5/Source/Runtime/AgcRHI/Private/AgcTransientResourceAllocator.h/.cpp`

When `AGC_ENABLE_VIRTUAL_TRANSIENT_HEAPS=1` (PS5 default):
- Virtual address reservation: **4 GB**
- Page size: **2 MB** (LargePage)
- First-Fit allocator with **fence-based aliasing** (Acquire/Discard fences per resource)
- Per-frame: Commit new 2MB pages if needed → update history → Trim excess pages

**LLM accounting** updates on Commit/Decommit via `OnLowLevelChangeInMemoryUse`.

#### 3.10.6 Stat Relationships

```
STAT_RHITransientMemoryRequested  (per-frame total resource requests, pre-alias)
        │
        │ − STAT_RHITransientMemoryAliased (saved by aliasing)
        ↓
STAT_RHITransientMemoryUsed       (actual heap occupancy)
        │
        │ ≈ (+ management overhead)
        ↓
STAT_AgcTransientHeapsLLM         (LLM accounting = committed pages)
        │
        │ (2MB page granularity, includes idle committed pages)
        ↓
STAT_Agc_TransientHeap            (total committed heap capacity)
```

| Observed relationship | Meaning |
|---|---|
| Used ≈ LLM | Normal, LLM slightly larger due to overhead |
| Agc_TransientHeap >> LLM | Many committed but idle pages, Trim not aggressive enough |
| Low Aliased/Requested ratio | Resource lifetimes overlap heavily, poor alias opportunity |
| Requested grows but Used stable | Good aliasing efficiency |

#### 3.10.7 Memreport Analysis Strategy

Since pure transient resources are invisible in standard memreport dumps, analysis relies on:
1. **LLM tag value** — total committed transient heap size
2. **RT pool cross-reference** — FastVRAM resources in RT pool likely backed by transient heap
3. **CVar experiment** — set `r.RDG.TransientAllocator=0`, re-capture, compare total memory increase (= former transient amount)
4. **RDG DumpGraph** — `r.RDG.DumpGraph 1` exports GraphViz with transient annotations

> **Note**: AGC's Transient Heap classification and LLM's AgcTransientHeaps tag accounting may differ. AGC snapshot Transient Heap values may be much larger than the LLM tag value.

---

### 3.11 Animation

**LLM tag**: `ELLMTag::Animation`

**Tracked content**: Animation system data (AnimationWarping, MotionWarping, animation curves, animation sequence CPU data, etc.).

---

### 3.12 Navigation

**LLM tag**: `ELLMTag::Navigation`

**Tracked content**: NavMesh (Recast + Detour) data.

**Statistical value analysis notes**:

Navigation-related statistics in memreport come from two **overlapping classification dimensions** (cannot be directly summed):

- **Recast Memory**: Total Recast library allocations (including PERM_TILE_DATA, PERM_TILES sub-category labels)
- **Detour Tile Memory**: Total Detour library allocations (partially overlaps with Recast)
- **LLM Navigation tag**: LLM scope tracking value (may have slight differences from the above due to sampling timing)

**Scene-dependent**: Menu scenes typically only a few MB, open world scenes can reach 200+ MB.

---

### 3.13 SceneRender / RenderTargets / Lumen / DistanceFields

These are smaller but important rendering-related tags:

| Tag | Description |
|---|---|
| SceneRender | Scene rendering data (MeshDrawCommands etc.) |
| RenderTargets | Non-transient Render Targets (accounted separately from AgcTransientHeaps) |
| Lumen | Lumen global illumination dedicated data |
| DistanceFields | Distance field data (used for Lumen/shadows etc.) |

---

### 3.15 Hair / Groom

**LLM tag**: The Hair/Groom system has no dedicated LLM tag; its memory is distributed across multiple tags:

| Data type | LLM Tag | Description |
|---|---|---|
| GroomAsset CPU data | UObject / Untagged | Asset metadata, guide curves |
| Hair GPU Buffers (strand data) | RHIMisc / Untagged | Allocated via `FAgcMemory::Allocate` |
| Hair.VoxelPageTexture | RenderTargets or Untagged | Voxelized lighting/shadow data |
| Hair.TransmittanceNodeData | RHIMisc / Untagged | Transmittance node data |
| SkinCache (hair binding) | RHIMisc | GPU skin cache buffer |

**Locating Hair resources in memreport**:
- `rhi.dumpresourcememory summary name=Hair`: GPU-side Hair resource summary
- `obj list class=GroomAsset`: Groom asset list
- `obj list class=GroomComponent`: Runtime Groom components
- `obj list class=GroomBindingAsset`: Binding assets

**Typical composition**:
- `Hair.VoxelPageTexture`: 3D voxel texture for hair-to-hair shadows. Resolution controlled by `r.HairStrands.Voxelization.PageResolution`
- `Hair.TransmittanceNodeData`: Per-pixel transmittance linked list. Size proportional to hair strand density and screen coverage
- `Hair.LUT(DualScattering)` / `Hair.LUT(MeanEnergy)`: Fixed-size lookup tables, ~0.5 MB each

**Optimization strategies**:
- Lower voxel resolution (`r.HairStrands.Voxelization.PageResolution`) — directly reduces VoxelPageTexture size
- Reduce strand count (LOD or decimation) — reduces TransmittanceNodeData and GPU buffers
- Disable Groom rendering for distant characters (use card-based substitute) — significantly reduces GPU buffers
- Limit simultaneous on-screen Groom character count

---

### 3.14 Other Minor Items

| Tag | Description |
|---|---|
| AssetRegistry | Asset registry |
| StreamingManager | Streaming manager metadata |
| VirtualTextureSystem | VT system data |
| TextureMetaData | Texture metadata |
| Niagara | Niagara particle system |
| ConfigSystem | Config system memory |
| UI | CommonUI/Slate/UMG UI system (⚠️ Summary Bug) |

**GPU Buffer LLM Tag Attribution Summary** (cross-tag reference):

| GPU Buffer type | LLM Tag | Reason |
|---|---|---|
| Non-Nanite vertex/index buffer | **Untagged** | `FAgcMemory::Allocate` hardcodes Untagged |
| Nanite GPU cluster/page buffer | **Nanite** | `LLM_SCOPE_BYNAME("Nanite")` + `UpdateAllocationTags` |
| Nanite CPU metadata (RootData etc.) | **StaticMesh** | `UStaticMesh::Serialize` scope |
| Streaming texture GPU mip physical pages | **Textures** | `FAgcReservedResource::Commit` + `LLM_REALLOC_SCOPE` |
| Non-streaming texture GPU data | **Untagged** | `FAgcMemory::Allocate` hardcoded |
| Transient RT/Buffer (TSR/Lumen etc.) | **AgcTransientHeaps** | `OnLowLevelChangeInMemoryUse` direct injection (bypasses FMalloc) |

**Untagged dual meaning**:
- **LLMFULL Untagged** (typically tens of MB): GPU non-Nanite buffers and other FMalloc allocations not marked by `LLM_SCOPE`
- **Platform Untagged** (typically hundreds of MB): Platform-layer view of all FMalloc allocations not covered by LLM tags

These are different layer concepts and must not be confused.

---

## 4. Memreport Section Parsing Guide

### 4.1 Execution

```
memreport -full
// PS5 output redirected to PC:
memreport -full > /hostfs0/memreport.txt
obj list class=Texture2D sort=size > /hostfs0/tex_list.txt
```

### 4.2 Mem FromReport (Platform + FMalloc + LLM)

This is the core memreport section, containing:
- **Platform memory statistics**: Process Physical Memory, Available Physical, Peak Physical, etc.
- **FMallocBinned2 statistics**: OS Total, Small Pool, Large Pool, Cached free, etc.
- **All LLM tags**: All values from `STATGROUP_LLMPlatform`, `STATGROUP_LLM`, `STATGROUP_LLMFULL`

**AI analysis purpose**: Global overview, obtain all LLM tag readings.

**Key fields**:

| Field | Meaning |
|---|---|
| `Process Physical Memory` | OS-view process actual physical memory usage |
| `STAT_UsedPhysical` | LLM Total, UE5's own tracked value |
| `Available Physical` | Currently remaining available |
| `FMalloc OS Total` | Total pages requested from OS by FMalloc |
| `Cached free OS pages` | Pages held by FMalloc but unused, returnable to OS |

### 4.3 obj list

`obj list` outputs memory information for all UObjects. Common usage:

| Command | Purpose |
|---|---|
| `obj list -resourcesizesort` | All UObjects sorted by ResourceSize, find largest asset classes |
| `obj list class=StaticMesh` | StaticMesh asset list |
| `obj list class=SkeletalMesh` | SkeletalMesh asset list |
| `obj list class=Texture2D` | Texture2D asset list |
| `obj list class=SoundWave` | Audio asset list |
| `obj list class=Material` | Material asset list |

**Column meanings** (key):

| Column | Meaning |
|---|---|
| `NumKB` | Object's own size (UObject shell + UPROPERTY data) |
| `MaxKB` | Maximum including dynamic allocations like TArray |
| `ResExcKB` | **Exclusive resource size** (excludes shared reference resource data, most commonly used analysis column) |
| `ResExcDedSysKB` | CPU-dedicated portion of exclusive resources |
| `ResExcDedVidKB` | GPU-dedicated portion of exclusive resources |
| `ResExcUnkKB` | Unknown attribution portion of exclusive resources |

> **Note**: `ResExcKB` = `ResExcDedSysKB` + `ResExcDedVidKB` + `ResExcUnkKB`

> **Note**: `obj list` ResExcKB and LLM tag values have systematic differences (e.g., StaticMesh's STAT vs obj list vs LLM three-value difference), because their accounting methods differ. Understand the source of differences during analysis; do not expect them to be equal.

**obj list line formats** (critical for parsing):

There are two distinct line formats in `obj list class=XXX -resourcesizesort`:

1. **Individual asset lines** — 6 numeric columns:
   ```
   ClassName /Path/To/Asset.Asset  NumKB  MaxKB  ResExcKB  ResExcDedSysKB  ResExcDedVidKB  ResExcUnkKB
   ```
2. **Class summary line** — 7 numeric columns (extra Count column):
   ```
   ClassName  Count  NumKB  MaxKB  ResExcKB  ResExcDedSysKB  ResExcDedVidKB  ResExcUnkKB
   ```

ResExcKB is always the **3rd numeric column from the left** (0-indexed: index 2). The summary line has an additional Count column before NumKB. When parsing from the right, distinguish them by: individual lines contain "/" in the name (asset path), summary lines do not.

> **Warning**: SoundWave assets typically show ResExcKB ≈ 0 because Wwise audio memory is allocated through Wwise's own memory manager (FMalloc path), not through UObject resource tracking. The Audio LLM tag (e.g., 599 MB) captures the true memory via LLM scope tagging on FMalloc allocations. Do not expect SoundWave obj list data to match Audio LLM tag values.

### 4.4 rhi.DumpMemory / rhi.DumpResourceMemory

| Command | Content | AI analysis purpose |
|---|---|---|
| `rhi.DumpMemory` | RHI type-dimension statistics (Textures/Buffers/RT etc.) | GPU resource distribution by type overview |
| `rhi.DumpResourceMemory` | Top N largest RHI resources (sorted by size) | Find the largest individual GPU resources |
| `rhi.DumpResourceMemory summary name=XXX` | Aggregated by name prefix | GPU resource summary per subsystem |

**AGC GPU statistical dimensions** (PS5 specific):

AGC in memreport summarizes GPU memory by these categories:

| AGC Category | Description |
|---|---|
| Textures | GPU textures |
| Buffers | GPU Buffers |
| Render Targets | Render targets |
| Transient Heap | Per-frame transient resources |
| Back Buffer | Back buffer |
| Shaders | GPU Shader Binary |
| Wasted | Alignment waste |

AGC Textures can be further decomposed into `STAT_UAVTextureMemory` (UAV textures), `STAT_TextureMemory2D` (Texture 2D), etc.

### 4.5 listtextures

| Command | Content |
|---|---|
| `listtextures` | Complete texture list (including VT) |
| `listtextures nonvt` | Non-VT texture list (primary analysis target) |
| `listtextures uncompressed` | Uncompressed texture list (compression optimization candidates) |

Sort by `CurrentKB` to quickly locate the largest textures. Watch for textures with the `NeverStream` flag — they are not managed by the streaming pool but persistently occupy memory.

**Key columns for analysis**:

| Column | Meaning |
|---|---|
| `CurrentKB` | Current in-memory size (sort by this) |
| `DesiredKB` / `OnDiskKB` | Full-resolution size on disk (streaming target) |
| `Format` | Pixel format (DXT1/DXT5/BC5/BC7/FloatRGBA/B8G8R8A8/G8 etc.) |
| `Group` | TextureGroup (World/UI/Effects/Character/WorldNormalMap/16BitData etc.) |
| `Streaming` | YES/NO — whether managed by streaming pool |
| `NeverStream` | Flag indicating texture will never stream, loads all mips unconditionally |
| `NoCompress` | Flag indicating uncompressed format (optimization target) |

**Texture analysis workflow**:

1. **Identify NeverStream population**: Filter `listtextures nonvt` by NeverStream flag. Calculate total NeverStream InMem and its ratio to TexturePoolSize. Above 80% means streaming textures are severely starved.

2. **Build NeverStream × Uncompressed cross-matrix**: Cross-reference NeverStream and NoCompress flags. The intersection (NeverStream + Uncompressed) suffers dual penalty and should be prioritized for optimization.

3. **Audit by TextureGroup**: Group NeverStream textures by their Group column. Common high-cost groups:
   - **UI**: Often the largest NeverStream group. Evaluate if distant/rare UI textures can enable streaming.
   - **16BitData**: Often FloatRGBA uncompressed. Evaluate BC6H compression or lower resolution.
   - **Effects**: VFX textures. Evaluate if streaming-safe and if compression is viable.
   - **World**: Large environment textures (e.g., 8K maps). Should almost always be streaming-enabled.

4. **Identify top single textures**: Sort by CurrentKB, focus on textures > 4 MB. Common optimization actions:
   - 8K textures (8192×8192): Reduce to 4K unless justified
   - FloatRGBA + NoCompress: Evaluate BC6H (for HDR/VAT, check precision needs)
   - B8G8R8A8 + NoCompress: Almost always compressible to BC7/DXT5 (~75% savings)
   - G8 + NoCompress: Compressible to BC4 (~50% savings)
   - NeverStream + large size (> 8 MB): Strong candidate for enabling streaming

5. **Evaluate streaming health**: Compare Streaming InMem vs Streaming OnDisk. If InMem/OnDisk < 10%, streaming is severely starved (textures are at minimum mip levels). This means pool budget needs relief (reduce NeverStream population or increase PoolSize).

**`listtextures` coverage limitation**: Only shows UObject-layer textures. Engine rendering pipeline internal textures (VT Physical Pools, TSR History, DF BrickTexture, VSM PhysicalPagePool, Hair VoxelPageTexture, ShaderPrint DepthTexture, etc.) are invisible here — use `rhi.DumpResourceMemory` to find those.

### 4.6 RenderTarget Pool

`r.DumpRenderTargetPoolMemory`: RenderTarget Pool detail, listing each RT's format, dimensions, and memory usage.

### 4.7 Other Sections

| Memreport Section / Command | Content | AI analysis purpose |
|---|---|---|
| `LogOutStatLevels` | Load status of each Level/sub-level | DataLayer/WorldPartition analysis |
| `ListSpawnedActors` | Runtime-spawned Actors | Find leaked dynamic Actors |
| `ListParticleSystems` | Particle system list | Niagara/Cascade memory analysis |
| `wp.DumpDataLayers` | World Partition DataLayer status | Verify DataLayer load/unload behavior |
| `ConfigMem` | Config system memory | Specific sources for ConfigSystem tag |

### 4.8 Unreal Insights Limitations

- Finest granularity: LLM Tag level or Callstack level
- **Cannot reach individual asset precision** — LLM_SCOPE only accepts compile-time constant enum tags, no runtime asset info
- Asset-level memory data requires `obj list` / `memreport`

### 4.9 PS5 Native Tools

| Tool | Purpose |
|---|---|
| Razor CPU/GPU Profiler Memory Viewer | Callstack for each allocation, can distinguish CPU/GPU pages |
| `orbis-analyzer` | Load PS5 coredump for heap analysis |
| Razor Memory Analyzer | Hardware-level page annotation, precise CPU/GPU boundary distinction |
| `sceGnmGetGpuMemoryFootprint` | Per-page CPU/GPU attribution (not available from memreport) |

### 4.10 PS5 Output Redirect to PC

```
obj list class=Texture2D sort=size > /hostfs0/tex_list.txt
memreport -full > /hostfs0/memreport.txt
```

---

## 5. Engine Source Code Index

> Engine layer only, no project layer — this knowledge base is reusable across projects.

| File | Key content |
|---|---|
| `Engine/Source/Runtime/Core/Public/HAL/LowLevelMemTracker.h` | LLM tag definitions, hierarchy macros (L207-269) |
| `Engine/Source/Runtime/Core/Private/HAL/LowLevelMemTracker.cpp` | `PropagateChildSizesToParents()` (L6022), `PublishStats()` (L5324, Summary Bug location) |
| `Engine/Source/Runtime/Core/Public/HAL/DynamicRHIResourceArray.h` | `TResourceArray::Discard()` |
| `Engine/Platforms/PS5/Source/Runtime/AgcRHI/Private/AgcBase.cpp` | GPU buffer allocation, hardcoded `ELLMTag::Untagged` (L90) |
| `Engine/Platforms/PS5/Source/Runtime/AgcRHI/Private/AgcBuffer.cpp` | `UpdateAllocationTags()` (L259-277) — only re-tag mechanism |
| `Engine/Platforms/PS5/Source/Runtime/AgcRHI/Private/AgcTexture.cpp` | GPU texture allocation (L554), streaming texture path (L537, L987) |
| `Engine/Platforms/PS5/Source/Runtime/AgcRHI/Private/AgcReservedResource.cpp` | `Commit()` + `LLM_REALLOC_SCOPE(this)` (L73, L101) |
| `Engine/Platforms/PS5/Source/Runtime/AgcRHI/Private/AgcSubmission.cpp` | AgcTransientHeaps `OnLowLevelChangeInMemoryUse` (L236-237) |
| `Engine/Platforms/PS5/Source/Runtime/Core/Private/PS5LLM.cpp` | AgcTransientHeaps tag registration (L23) |
| `Engine/Source/Runtime/Engine/Private/StaticMesh.cpp` | `STAT_StaticMeshTotalMemory` update (L4816-4822), Serialize LLM scope (L7193) |
| `Engine/Source/Runtime/Engine/Private/Rendering/NaniteResources.cpp` | `GetResourceSizeEx` IsBulkDataLoaded check (L532-545) |
| `Engine/Source/Runtime/Engine/Private/StaticMeshUpdate.cpp` | `CreateBuffers` LLM scope (L158), `SerializeLODData` (L526), StreamOut (L985) |
| `Engine/Source/Runtime/RHI/Private/RHITextureInitializer.cpp` | RT vs Texture LLM branch (L28) |
| `Engine/Source/Runtime/RHICore/Internal/RHICoreStats.h` | Streaming/NonStreaming RHI classification (L73-87) — determines pool budget membership |
| `Engine/Source/Runtime/Engine/Private/Streaming/AsyncTextureStreaming.cpp` | Pool budget calculation (L634-635), NeverStream impact on NonStreamingMips (L1114, L1193) |
| `Engine/Source/Runtime/RenderCore/Private/RenderGraphUtils.cpp` | `AllocatePooledBufferCurrentLLMTag` (L1015-1023) |
| `Engine/Source/Runtime/Engine/Private/UnrealEngine.cpp` | `obj list` implementation, calls `GetResourceSizeEx(Exclusive)` (L9610-9617) |
