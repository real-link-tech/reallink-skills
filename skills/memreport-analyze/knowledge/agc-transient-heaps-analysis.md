# AgcTransientHeaps 原理与构成分析

## 概述

`AgcTransientHeapsLLM` 是 PS5 平台专用的 LLM 标签，追踪 Agc RHI 层中**瞬态资源堆（Transient Resource Heap）**的物理内存占用。瞬态资源是 RDG（Render Dependency Graph）在帧内创建、帧内释放的 GPU 资源，通过内存别名（aliasing）共享同一段堆内存以节省显存。

---

## 1. 瞬态 vs 非瞬态的判定逻辑

判定发生在 RDG 编译阶段，由 `FRDGBuilder::IsTransient()` 决定。

> 源码：`Engine/Source/Runtime/RenderCore/Private/RenderGraphBuilder.cpp`

### 1.1 Buffer 判定（`IsTransient(FRDGBufferRef)`）

```
平台支持瞬态 Buffer？  ──否──→ 非瞬态
        │是
Buffer 有待上传数据（bQueuedForUpload）？ ──是──→ 非瞬态
        │否
IsTransientInternal() 通过？ ──否──→ 非瞬态
        │是
是 DrawIndirect 且 r.RDG.TransientAllocator.IndirectArgumentBuffers=0？ ──是──→ 非瞬态
        │否
有 BUF_UnorderedAccess 标记？ ──否──→ 非瞬态
        │是
        ↓
      瞬态
```

**关键约束：Buffer 必须同时满足 UAV 标记才能成为瞬态。** 纯 Vertex/Index/Uniform buffer 永远不会瞬态。

### 1.2 Texture 判定（`IsTransient(FRDGTextureRef)`）

```
平台支持瞬态 Texture？ ──否──→ 非瞬态
        │是
Texture 有 Shared 标记？ ──是──→ 非瞬态
        │否
IsTransientInternal() 通过？
        │
      结果即最终结果
```

### 1.3 核心内部判定（`IsTransientInternal()`）

```cpp
// 简化后的判定逻辑
bool IsTransientInternal(Resource, bFastVRAM)
{
    if (bFastVRAM && FPlatformMemory::SupportsFastVRAMMemory())
    {
        // FastVRAM + 平台支持 → 直接跳过所有检查，强制瞬态
        return true;  // ← 不检查 bExtracted、bForceNonTransient
    }

    // 以下仅在非 FastVRAM 或平台不支持 FastVRAM 时执行
    if (GRDGTransientAllocator == 2)           return false;  // 模式2：仅 FastVRAM 可瞬态
    if (Resource->bForceNonTransient)           return false;  // 用户显式禁止
    if (Resource->bExtracted)
    {
        // 被 Extract 的资源（需跨帧保留）
        if (GRDGTransientExtractedResources == 0) return false;  // 模式0：Extract 一律非瞬态
        if (GRDGTransientExtractedResources == 1
            && Resource->TransientExtractionHint == Disable) return false;  // 模式1：尊重 Hint
    }
    return true;
}
```

**关键规则总结：**

| 条件 | 结果 |
|------|------|
| FastVRAM 标记 + 平台支持 | **强制瞬态**（无视 Extract、ForceNonTransient） |
| 非 FastVRAM + 未 Extract + 未 ForceNonTransient | 瞬态 |
| 非 FastVRAM + 已 Extract + `GRDGTransientExtractedResources=1`（默认） | 取决于 TransientExtractionHint |
| 非 FastVRAM + bForceNonTransient | 非瞬态 |
| Buffer 无 UAV 标记 | 非瞬态（无论其他条件） |
| Texture 有 Shared 标记 | 非瞬态 |

### 1.4 相关 CVar

| CVar | 默认值 | 作用 |
|------|--------|------|
| `r.RDG.TransientAllocator` | 1 | 0=关闭瞬态分配, 1=启用, 2=仅 FastVRAM |
| `r.RDG.TransientExtractedResources` | 1 | 0=Extract 资源一律非瞬态, 1=尊重 Hint, 2=强制全部瞬态 |
| `r.RDG.TransientAllocator.IndirectArgumentBuffers` | 0 | 0=IndirectArg buffer 不可瞬态（规避 GPU crash UE-115982） |

---

## 2. FastVRAM 配置

> 源码：`Engine/Source/Runtime/Renderer/Private/SceneRendering.h` (FFastVramConfig)
> 源码：`Engine/Source/Runtime/Renderer/Private/SceneRendering.cpp` (FASTVRAM_CVAR 定义)

FastVRAM 标记是资源进入瞬态路径的**主要入口**。在支持 FastVRAM 的平台（PS5），带此标记的资源**强制走瞬态分配**。

### 默认开启 FastVRAM 的纹理（`r.FastVRam.XXX = 1`）

| 纹理 | 备注 |
|------|------|
| GBufferB | GBuffer 中仅 B 默认开启 |
| HZB | Hierarchical Z-Buffer |
| SceneDepth | 场景深度 |
| SceneColor | 场景颜色 |
| Bloom | 泛光 |
| BokehDOF, CircleDOF, DOFSetup, DOFReduce, DOFPostfilter | 景深全系列 |
| CombineLUTs | 颜色查找表合成 |
| Downsample | 降采样 |
| EyeAdaptation, Histogram, HistogramReduce | 自动曝光 |
| VelocityFlat, VelocityMax | 运动矢量 |
| MotionBlur | 运动模糊 |
| Tonemap | 色调映射 |
| Upscale | 上采样 |
| DistanceFieldNormal | DF 法线 |
| DistanceFieldAOHistory | DF AO 历史 |
| DistanceFieldAODownsampledBentNormal | DF AO 降采样弯曲法线 |
| DistanceFieldShadows | DF 阴影 |
| Distortion | 扭曲 |
| ScreenSpaceShadowMask | 屏幕空间阴影遮罩 |
| VolumetricFog | 体积雾 |
| PostProcessMaterial | 后处理材质 |

### 默认关闭 FastVRAM 的纹理（`r.FastVRam.XXX = 0`）

GBufferA, GBufferC, GBufferD, GBufferE, GBufferF, GBufferVelocity,
DistanceFieldAOBentNormal, DistanceFieldIrradiance, DistanceFieldAOConfidence,
SeparateTranslucency, SeparateTranslucencyModulate, ScreenSpaceAO, SSR,
DBufferA/B/C/Mask, CustomDepth, ShadowPointLight, ShadowPerObject, ShadowCSM

### Buffer FastVRAM（全部默认开启 = 1）

- DistanceFieldCulledObjectBuffers
- DistanceFieldTileIntersectionResources
- DistanceFieldAOScreenGridResources
- ForwardLightingCullingResources
- GlobalDistanceFieldCullGridBuffers

**重要：FastVRAM 标记仅决定资源是否走瞬态路径。资源是否实际被创建，取决于当帧的渲染功能是否启用。**

---

## 3. 瞬态 vs Pooled 的关键区别

### 3.1 资源是否出现在 Pooled RT Dump 中？

`r.DumpRenderTargetPoolMemory` 输出的是 **Render Target Pool** 中的资源。一个资源出现在该列表中，意味着它通过 `FRenderTargetPool` 管理。

**关键：一个资源可以同时是"瞬态分配"且出现在"Pooled RT"列表中。** 这发生在资源满足以下条件时：
- 标记为瞬态（通过 IsTransient 判定）
- 同时被 Extract（需跨帧引用）

此时 `AllocateTransientResources()` 中的处理逻辑为：

```cpp
// 分配时：内存来自瞬态堆
FRHITransientTexture* TransientTexture = TransientResourceAllocator->CreateTexture(...);

// 完成时：如果被 Extract，包装为 Pooled Render Target
if (Texture->bExtracted)
{
    SetExternalPooledRenderTargetRHI(Texture,
        GRDGTransientResourceAllocator.AllocateRenderTarget(TransientTexture));
    // ↑ 创建一个 FRDGTransientRenderTarget 包装器
    //   内存在瞬态堆中，但通过 Pooled RT 接口对外暴露
}
else
{
    SetTransientTextureRHI(Texture, TransientTexture);
}
```

> 源码：`RenderGraphBuilder.cpp` AllocateTransientResources(), 约第 3273-3296 行

### 3.2 三类资源的归属

| 类别 | 内存来源 | 出现在 Pooled RT Dump？ | 出现在 `rhi.DumpResourceMemory`？ | 计入 AgcTransientHeapsLLM？ |
|------|---------|----------------------|-------------------------------|--------------------------|
| **纯瞬态**（未 Extract） | 瞬态堆 | 否 | 否（标记为 transient 的资源被排除） | 是 |
| **瞬态 + Extract** | 瞬态堆 | 是（通过包装器） | 可能（取决于实现） | 是 |
| **纯 Pooled**（非瞬态） | 通用 GPU 内存 | 是 | 是 | 否 |

### 3.3 如何确认某个资源的归属

仅凭 memreport 无法确定一个出现在 Pooled RT Dump 中的资源是否实际由瞬态堆分配。需要：

1. 确认该资源是否有 FastVRAM 标记（查 `FFastVramConfig` 及 CVar 覆盖）
2. 确认该资源在 RDG 图中是否被 Extract
3. 如果 FastVRAM + 平台支持 → 即使 Extract 也走瞬态堆
4. 使用 `r.RDG.DumpGraph` 或 Unreal Insights 的 RDG 可视化确认

---

## 4. 瞬态堆内存管理

### 4.1 RHI 层：堆分配器

> 源码：`Engine/Source/Runtime/RHICore/Public/RHICoreTransientResourceAllocator.h`

瞬态堆使用 **First-Fit 分配器**，核心是 **Fence 驱动的内存别名（aliasing）**：

- 每个资源分配时附带 **Acquire Fence**（标记该资源开始使用的 GPU 时间点）
- 每个资源释放时附带 **Discard Fence**（标记最后使用的 GPU 时间点）
- 新分配尝试复用已释放内存时，检查 fence 是否重叠：

```cpp
// 伪代码
if (!FRHITransientAllocationFences::Contains(已释放区域.DiscardFences, 新分配.AcquireFences))
{
    // Fence 不重叠 → GPU 时间线上不冲突 → 可以 alias
    复用此内存区域;
}
```

Fence 系统区分 **Graphics Pipeline** 和 **AsyncCompute Pipeline**，在跨管线场景下使用 Fork/Join 点进行同步判定。

### 4.2 资源缓存

分配器维护已释放资源的缓存（`TRHITransientResourceCache`），避免反复创建/销毁 RHI 对象：

- Buffer 缓存容量：64（`r.RHI.TransientAllocator.BufferCacheSize`）
- Texture 缓存容量：64（`r.RHI.TransientAllocator.TextureCacheSize`）
- GC 延迟：32 帧（超过此帧数未使用的缓存资源被释放）

### 4.3 PS5 虚拟堆机制

> 源码：`Engine/Platforms/PS5/Source/Runtime/AgcRHI/Private/AgcTransientResourceAllocator.h/.cpp`
> 源码：`Engine/Platforms/PS5/Source/Runtime/AgcRHI/Private/AgcSubmission.cpp`

当 `AGC_ENABLE_VIRTUAL_TRANSIENT_HEAPS = 1` 时（PS5 默认）：

**堆创建参数：**
- 保留虚拟地址空间：**4 GB**
- 页大小：**2 MB**（`LargePage`）
- 对齐：`Agc::Alignment::kMaxTiledAlignment`
- 内存类型：GPU 虚拟内存（`EVirtualMemoryPlatformType::GPU`）

**按需 Commit/Decommit（`FAgcTransientHeapMapper`）：**

每帧流程：
1. **Commit 阶段**：统计本帧最大分配需求（`RequiredBytes`），如果 `CommittedBytes < RequiredBytes`，commit 新的 2MB 页
2. **Release 阶段**：记录每帧分配量到历史数组，在多帧窗口中取最大值作为 `RequiredBytes`
3. **Trim 阶段**：如果 `CommittedBytes > RequiredBytes`，decommit 多余页面

**LLM 记账**在 Commit/Decommit 时双向更新：
```cpp
// Commit 时
LLM(FLowLevelMemTracker::Get().OnLowLevelChangeInMemoryUse(
    ELLMTracker::Platform, +BytesToMap, ELLMTagPS5::AgcTransientHeaps));
LLM(FLowLevelMemTracker::Get().OnLowLevelChangeInMemoryUse(
    ELLMTracker::Default, +BytesToMap, ELLMTagPS5::AgcTransientHeaps));

// Decommit 时
LLM(..., -BytesToUnmap, ...);
```

---

## 5. 三个 Stat 的关系

| Stat | 含义 | 来源 |
|------|------|------|
| `STAT_RHITransientMemoryRequested` | 帧内所有瞬态资源的请求总量（alias 前） | `FRHITransientMemoryStats::Submit()` |
| `STAT_RHITransientMemoryAliased` | 通过 alias 节省的内存量 | Requested - Used |
| `STAT_RHITransientMemoryUsed` | 瞬态堆中实际被占用的字节 | 堆分配器的 high-water mark |
| `STAT_AgcTransientHeapsLLM` | LLM 追踪的已 commit 物理页（≈Used + 管理开销） | `FAgcTransientHeapMapper` commit/decommit 差值 |
| `STAT_Agc_TransientHeap` | 虚拟堆中已 commit 的页面总量（含空闲页） | `UpdateStats()` 累计 |

```
STAT_RHITransientMemoryRequested  (帧内资源请求总和)
        │
        │ - STAT_RHITransientMemoryAliased (alias 节省量)
        ↓
STAT_RHITransientMemoryUsed       (堆内实际占用)
        │
        │ ≈ (+ 少量管理开销)
        ↓
STAT_AgcTransientHeapsLLM         (LLM 记账)
        │
        │ (堆按 2MB 页粒度 commit，有未使用的空闲页)
        ↓
STAT_Agc_TransientHeap            (堆 commit 总容量)
```

**已 commit 但未使用的差额**（`STAT_Agc_TransientHeap` - `STAT_AgcTransientHeapsLLM`）来源：
- 2MB 页对齐浪费
- 历史帧高水位导致的延迟 decommit（Trim 基于多帧窗口最大值）
- 堆内碎片

---

## 6. 哪些资源确实是瞬态的

### 6.1 确定走瞬态路径的资源（FastVRAM=1 默认开启）

以下资源**如果在当帧被 RDG 创建**，在 PS5 上一定走瞬态分配（因为 FastVRAM 标记强制瞬态）：

**纹理：** SceneColor, SceneDepth, GBufferB, HZB, Bloom, BokehDOF, CircleDOF, DOFSetup, DOFReduce, DOFPostfilter, CombineLUTs, Downsample, EyeAdaptation, Histogram, HistogramReduce, VelocityFlat, VelocityMax, MotionBlur, Tonemap, Upscale, DistanceFieldNormal, DistanceFieldAOHistory, DistanceFieldAODownsampledBentNormal, DistanceFieldShadows, Distortion, ScreenSpaceShadowMask, VolumetricFog, PostProcessMaterial

**Buffer：** DistanceFieldCulledObjectBuffers, DistanceFieldTileIntersectionResources, DistanceFieldAOScreenGridResources, ForwardLightingCullingResources, GlobalDistanceFieldCullGridBuffers

**注意：** 即使这些资源被 Extract（跨帧），FastVRAM 标记也让它们强制走瞬态堆。此时它们会同时出现在 Pooled RT Dump 中（通过 `FRDGTransientRenderTarget` 包装器），但实际内存在瞬态堆。

### 6.2 可能走瞬态路径的资源（非 FastVRAM，取决于是否被 Extract）

不带 FastVRAM 标记、但在 RDG 图中未被 Extract 且满足条件（Texture 无 Shared、Buffer 有 UAV）的资源也会走瞬态路径。典型例子：

- Nanite compute pipeline 中间 buffer（culling 结果、raster bin 临时数据等）
- Lumen 当帧 trace 中间结果（非 history 部分）
- Virtual Shadow Map 页面管理临时 buffer
- 各类 compute pass 的 scratch buffer/texture

这些资源不带 FastVRAM 标记（FastVRAM 配置中没有它们），但因为未被 Extract 且有 UAV 标记，默认走瞬态路径。

### 6.3 确定不走瞬态路径的资源

- **所有非 UAV 的 buffer**（VB、IB、UB、SRV-only buffer）
- **带 Shared 标记的 texture**
- **标记 bForceNonTransient 的资源**
- **被 Extract 且 TransientExtractionHint=Disable 且非 FastVRAM 的资源**
- **平台不支持瞬态分配时，所有资源**

### 6.4 不出现在 memreport 任何 dump 中的资源

纯瞬态（未 Extract）资源不会出现在以下命令的输出中：
- `r.DumpRenderTargetPoolMemory`（仅列 Pooled RT）
- `rhi.DumpResourceMemory`（输出标注 "total non-transient"，排除瞬态）
- `ListTextures`（列 UTexture 资产，非 RHI 层瞬态资源）

**目前 UE5 没有内置命令列出每个瞬态资源的名称和大小。** 要获取精确清单需要：
- 使用 `r.RDG.DumpGraph` 导出 RDG pass 拓扑和资源列表
- 使用 Unreal Insights 的 RDG 可视化追踪每个资源的生命周期和分配类型
- 或修改引擎在 `AllocateTransientResources()` 中添加 dump 逻辑

---

## 7. 帧内分配生命周期

```
RDG Graph 构建
    ↓
RDG 编译（Compile）
    ├─ 计算每个资源的生命周期（首次使用 pass → 最后使用 pass）
    ├─ 对每个资源调用 IsTransient() 判定
    └─ 生成 FCollectResourceOp 序列（Allocate/Deallocate 交替）
    ↓
AllocateTransientResources(Ops)
    ├─ 第一趟：按序执行 Allocate/Deallocate
    │   ├─ Allocate: TransientResourceAllocator->CreateBuffer/CreateTexture()
    │   │   → 在堆中找到一段与当前 fence 不冲突的内存区域
    │   │   → 如果缓存中有匹配的 RHI 资源则复用，否则新建
    │   └─ Deallocate: TransientResourceAllocator->DeallocateMemory()
    │       → 记录 Discard Fence，标记该内存可被后续分配 alias
    └─ 第二趟：完成 RHI 资源绑定
        ├─ 未 Extract: SetTransientTextureRHI/SetTransientBufferRHI
        └─ 已 Extract: SetExternalPooledRenderTargetRHI (包装为 Pooled RT)
    ↓
RDG 执行（Execute）
    → 各 pass 使用瞬态资源
    ↓
帧结束
    → 纯瞬态资源：内存标记为空闲，RHI 对象回到缓存
    → 瞬态+Extract：Pooled RT 包装器持有引用，内存暂不释放
    ↓
PS5 FAgcTransientHeapMapper
    → Commit: 如需更多内存则 commit 新的 2MB 页
    → Release: 更新历史帧分配记录
    → Trim: 如有多余 commit 页则 decommit
```

---

## 8. 诊断方法

### 获取瞬态资源明细

引擎目前没有直接 dump 瞬态资源清单的命令。可用方法：

1. **Unreal Insights** — 启用 RDG channel，在 Trace 中查看每个 RDG 资源的 `bTransient` 标记和分配/释放时间线
2. **`r.RDG.DumpGraph 1`** — 导出 RDG 图的 GraphViz 文件，资源节点中包含 transient 信息
3. **Stat 对比** — `STAT_RHITransientTextureMemoryRequested` vs `STAT_RHITransientBufferMemoryRequested` 可知纹理/Buffer 各自的请求量
4. **CVar 实验** — 设置 `r.RDG.TransientAllocator=0` 关闭瞬态分配后对比内存（瞬态资源会回退到常规分配，增加的内存量即原瞬态量）

### 关键 Stat 含义速查

| 看到的数值关系 | 说明 |
|-------------|------|
| Used ≈ LLM | 正常，LLM 比 Used 略大是管理开销 |
| Agc_TransientHeap >> LLM | 堆有大量已 commit 但空闲的页，Trim 不够积极 |
| Aliased / Requested 比例低 | 帧内资源生命周期重叠严重，alias 机会少 |
| Requested 增长但 Used 不变 | alias 效率好，新增资源被有效复用 |
